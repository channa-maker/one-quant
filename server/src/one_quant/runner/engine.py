"""
ONE量化 - 策略运行引擎

单 asyncio 事件循环，订阅 EventBus 行情通道，
分发给所有已启用策略，收集信号后送入风控→执行链路。

支持策略热插拔：
  - 运行时注册/注销策略（不中断引擎）
  - 运行时启用/禁用策略
  - 运行时替换策略（原子操作：移除旧 + 添加新）
  - 策略状态查询
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from one_quant.core.types import (
    Fill,
    Kline,
    OptionQuote,
    OrderBook,
    PositionState,
    Signal,
    Ticker,
)
from one_quant.infra.event_bus import EventBus
from one_quant.strategy.contracts import Strategy

logger = logging.getLogger(__name__)


class StrategyRunner:
    """策略运行引擎。

    职责：
    1. 从 EventBus 订阅行情数据。
    2. 将行情分发给所有已启用策略。
    3. 收集策略产生的信号。
    4. 将信号发布到 EventBus（供风控引擎消费）。
    5. 支持策略热插拔（运行时注册/注销/替换）。

    热插拔特性：
    - register_strategy / unregister_strategy：运行时增删策略
    - enable_strategy / disable_strategy：运行时启用/禁用
    - replace_strategy：原子替换（移除旧策略 + 注册新策略）
    - 所有操作线程安全，不中断行情分发

    Attributes:
        event_bus: 事件总线实例。
        strategies: 已注册策略列表（只读视图）。
    """

    def __init__(self, event_bus: EventBus) -> None:
        """初始化策略运行引擎。

        Args:
            event_bus: 事件总线实例。
        """
        self._event_bus = event_bus
        self._strategies: list[Strategy] = []
        self._strategy_lock = asyncio.Lock()  # 保护策略列表的并发访问
        self._running = False
        self._signal_count = 0
        self._tick_count = 0

        # 策略生命周期事件记录
        self._lifecycle_events: list[dict[str, Any]] = []

    @property
    def strategies(self) -> list[Strategy]:
        """已注册策略列表（只读副本）。"""
        return list(self._strategies)

    def register_strategy(self, strategy: Strategy) -> None:
        """注册策略。

        如果引擎正在运行，此方法是线程安全的，
        新策略会在下一个 tick 开始接收数据。

        Args:
            strategy: 策略实例。
        """
        # 检查是否已注册同名策略
        existing = [s for s in self._strategies if s.name == strategy.name]
        if existing:
            logger.warning(
                "策略名称 '%s' 已存在，将被替换",
                strategy.name,
            )
            for s in existing:
                self._strategies.remove(s)

        self._strategies.append(strategy)
        self._record_lifecycle("register", strategy.name, strategy.enabled)
        logger.info("策略已注册: %s (enabled=%s)", strategy.name, strategy.enabled)

    async def unregister_strategy(self, name: str) -> bool:
        """注销策略（运行时安全移除）。

        Args:
            name: 策略名称。

        Returns:
            是否成功注销。
        """
        async with self._strategy_lock:
            target = next((s for s in self._strategies if s.name == name), None)
            if target is None:
                logger.warning("策略不存在: %s", name)
                return False

            self._strategies.remove(target)
            self._record_lifecycle("unregister", name, False)
            logger.info("策略已注销: %s", name)
            return True

    async def enable_strategy(self, name: str) -> bool:
        """启用策略。

        Args:
            name: 策略名称。

        Returns:
            是否成功启用。
        """
        async with self._strategy_lock:
            target = next((s for s in self._strategies if s.name == name), None)
            if target is None:
                logger.warning("策略不存在: %s", name)
                return False

            if target.enabled:
                logger.debug("策略已处于启用状态: %s", name)
                return True

            target.enabled = True
            self._record_lifecycle("enable", name, True)
            logger.info("策略已启用: %s", name)
            return True

    async def disable_strategy(self, name: str) -> bool:
        """禁用策略。

        禁用后策略不再接收行情数据，但保留在注册列表中，
        可随时重新启用。

        Args:
            name: 策略名称。

        Returns:
            是否成功禁用。
        """
        async with self._strategy_lock:
            target = next((s for s in self._strategies if s.name == name), None)
            if target is None:
                logger.warning("策略不存在: %s", name)
                return False

            if not target.enabled:
                logger.debug("策略已处于禁用状态: %s", name)
                return True

            target.enabled = False
            self._record_lifecycle("disable", name, False)
            logger.info("策略已禁用: %s", name)
            return True

    async def replace_strategy(self, old_name: str, new_strategy: Strategy) -> bool:
        """原子替换策略（热更新）。

        移除旧策略并注册新策略，保证同一时刻不会有两个同名策略
        同时处理行情数据。

        Args:
            old_name: 要移除的策略名称。
            new_strategy: 新策略实例。

        Returns:
            是否成功替换。
        """
        async with self._strategy_lock:
            # 查找旧策略
            old = next((s for s in self._strategies if s.name == old_name), None)
            if old is None:
                logger.warning("要替换的策略不存在: %s", old_name)
                return False

            # 原子操作：先移除旧的，再添加新的
            self._strategies.remove(old)
            self._strategies.append(new_strategy)

            self._record_lifecycle("replace", old_name, new_strategy.enabled)
            logger.info(
                "策略已替换: %s → %s (enabled=%s)",
                old_name,
                new_strategy.name,
                new_strategy.enabled,
            )
            return True

    def get_strategy(self, name: str) -> Strategy | None:
        """按名称获取策略。

        Args:
            name: 策略名称。

        Returns:
            策略实例或 None。
        """
        return next((s for s in self._strategies if s.name == name), None)

    def get_strategy_status(self) -> list[dict[str, Any]]:
        """获取所有策略的状态信息。

        Returns:
            策略状态列表。
        """
        return [
            {
                "name": s.name,
                "enabled": s.enabled,
                "type": type(s).__name__,
            }
            for s in self._strategies
        ]

    async def start(self) -> None:
        """启动策略引擎。

        订阅 EventBus 行情通道，开始分发。
        """
        self._running = True

        # 订阅行情通道
        self._event_bus.subscribe("market.ticker", self._on_ticker)
        self._event_bus.subscribe("market.kline", self._on_kline)
        self._event_bus.subscribe("market.orderbook", self._on_orderbook)
        self._event_bus.subscribe("market.option_quote", self._on_option_quote)
        self._event_bus.subscribe("execution.fill", self._on_fill)
        self._event_bus.subscribe("position.recover", self._on_recover)

        logger.info(
            "策略引擎已启动，注册 %d 个策略，%d 个已启用",
            len(self._strategies),
            sum(1 for s in self._strategies if s.enabled),
        )

    async def stop(self) -> None:
        """停止策略引擎。"""
        self._running = False
        logger.info(
            "策略引擎已停止，共处理 %d 个 tick，产生 %d 个信号",
            self._tick_count,
            self._signal_count,
        )

    # ──────────── 行情分发（带锁保护） ────────────

    async def _on_ticker(self, data: dict[str, Any]) -> None:
        """处理实时行情。"""
        ticker = Ticker(**data)
        self._tick_count += 1

        # 获取当前策略快照（避免在迭代时列表被修改）
        async with self._strategy_lock:
            strategies_snapshot = list(self._strategies)

        for strategy in strategies_snapshot:
            if not strategy.enabled:
                continue
            try:
                signals = strategy.on_ticker(ticker)
                await self._emit_signals(signals)
            except Exception:
                logger.exception("策略 %s 处理 ticker 异常", strategy.name)

    async def _on_kline(self, data: dict[str, Any]) -> None:
        """处理K线更新。"""
        kline = Kline(**data)

        async with self._strategy_lock:
            strategies_snapshot = list(self._strategies)

        for strategy in strategies_snapshot:
            if not strategy.enabled:
                continue
            try:
                signals = strategy.on_kline(kline)
                await self._emit_signals(signals)
            except Exception:
                logger.exception("策略 %s 处理 kline 异常", strategy.name)

    async def _on_orderbook(self, data: dict[str, Any]) -> None:
        """处理盘口更新。"""
        orderbook = OrderBook(**data)

        async with self._strategy_lock:
            strategies_snapshot = list(self._strategies)

        for strategy in strategies_snapshot:
            if not strategy.enabled:
                continue
            try:
                signals = strategy.on_orderbook(orderbook)
                await self._emit_signals(signals)
            except Exception:
                logger.exception("策略 %s 处理 orderbook 异常", strategy.name)

    async def _on_option_quote(self, data: dict[str, Any]) -> None:
        """处理期权报价。"""
        quote = OptionQuote(**data)

        async with self._strategy_lock:
            strategies_snapshot = list(self._strategies)

        for strategy in strategies_snapshot:
            if not strategy.enabled:
                continue
            try:
                signals = strategy.on_option_quote(quote)
                await self._emit_signals(signals)
            except Exception:
                logger.exception("策略 %s 处理 option_quote 异常", strategy.name)

    async def _on_fill(self, data: dict[str, Any]) -> None:
        """处理成交回报。"""
        fill = Fill(**data)

        async with self._strategy_lock:
            strategies_snapshot = list(self._strategies)

        for strategy in strategies_snapshot:
            if not strategy.enabled:
                continue
            try:
                strategy.on_fill(fill)
            except Exception:
                logger.exception("策略 %s 处理 fill 异常", strategy.name)

    async def _on_recover(self, data: dict[str, Any]) -> None:
        """处理持仓恢复。"""
        state = PositionState(**data)

        async with self._strategy_lock:
            strategies_snapshot = list(self._strategies)

        for strategy in strategies_snapshot:
            if not strategy.enabled:
                continue
            try:
                strategy.on_recover(state)
            except Exception:
                logger.exception("策略 %s 处理 recover 异常", strategy.name)

    # ──────────── 信号发射 ────────────

    async def _emit_signals(self, signals: list[Signal]) -> None:
        """将信号发布到 EventBus。

        Args:
            signals: 信号列表。
        """
        for signal in signals:
            self._signal_count += 1
            await self._event_bus.publish(
                "strategy.signal",
                signal.model_dump(mode="json"),
            )
            logger.info(
                "信号产生: %s %s %s strength=%.2f reason=%s",
                signal.strategy_name,
                signal.side,
                signal.symbol,
                signal.strength,
                signal.reason,
            )

    # ──────────── 生命周期记录 ────────────

    def _record_lifecycle(self, action: str, name: str, enabled: bool) -> None:
        """记录策略生命周期事件。"""
        self._lifecycle_events.append({
            "action": action,
            "strategy_name": name,
            "enabled": enabled,
            "timestamp_ns": time.time_ns(),
        })

    def get_lifecycle_events(self, limit: int = 50) -> list[dict[str, Any]]:
        """获取策略生命周期事件记录。

        Args:
            limit: 最大返回数。

        Returns:
            事件列表（最新在前）。
        """
        return list(reversed(self._lifecycle_events[-limit:]))

    @property
    def stats(self) -> dict[str, Any]:
        """运行统计。"""
        return {
            "strategies": len(self._strategies),
            "enabled": sum(1 for s in self._strategies if s.enabled),
            "ticks": self._tick_count,
            "signals": self._signal_count,
            "lifecycle_events": len(self._lifecycle_events),
        }
