"""
ONE量化 - 策略运行引擎

单 asyncio 事件循环，订阅 EventBus 行情通道，
分发给所有已启用策略，收集信号后送入风控→执行链路。
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

    Attributes:
        event_bus: 事件总线实例。
        strategies: 已注册策略列表。
    """

    def __init__(self, event_bus: EventBus) -> None:
        """初始化策略运行引擎。

        Args:
            event_bus: 事件总线实例。
        """
        self._event_bus = event_bus
        self._strategies: list[Strategy] = []
        self._running = False
        self._signal_count = 0
        self._tick_count = 0

    def register_strategy(self, strategy: Strategy) -> None:
        """注册策略。

        Args:
            strategy: 策略实例。
        """
        self._strategies.append(strategy)
        logger.info("策略已注册: %s (enabled=%s)", strategy.name, strategy.enabled)

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

    # ──────────── 行情分发 ────────────

    async def _on_ticker(self, data: dict[str, Any]) -> None:
        """处理实时行情。"""
        ticker = Ticker(**data)
        self._tick_count += 1

        for strategy in self._strategies:
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

        for strategy in self._strategies:
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

        for strategy in self._strategies:
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

        for strategy in self._strategies:
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

        for strategy in self._strategies:
            if not strategy.enabled:
                continue
            try:
                strategy.on_fill(fill)
            except Exception:
                logger.exception("策略 %s 处理 fill 异常", strategy.name)

    async def _on_recover(self, data: dict[str, Any]) -> None:
        """处理持仓恢复。"""
        state = PositionState(**data)

        for strategy in self._strategies:
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

    @property
    def stats(self) -> dict[str, int]:
        """运行统计。"""
        return {
            "strategies": len(self._strategies),
            "enabled": sum(1 for s in self._strategies if s.enabled),
            "ticks": self._tick_count,
            "signals": self._signal_count,
        }
