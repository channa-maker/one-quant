"""
ONE量化 - 行情网关基类 & 事件总线

本模块定义:
1. EventBus: 异步发布-订阅事件总线，用于行情数据的解耦分发
2. MarketGateway: 行情网关抽象基类，所有交易所接入需继承此类

设计原则:
- 所有 I/O 操作均为 async
- 通过 EventBus 发布行情数据，下游消费者无需了解数据来源
- 统一使用 one_quant.core.types 中的领域类型
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from collections import defaultdict
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)


# ──────────────────────────── 事件总线 ────────────────────────────


class EventBus:
    """
    异步发布-订阅事件总线。

    采用 channel（通道）机制，每个 channel 可有多个订阅者。
    订阅者回调签名为 ``async def handler(data: Any) -> None``。

    典型通道命名:
    - ``market.ticker``   实时行情
    - ``market.kline``    K线数据
    - ``market.orderbook`` 盘口快照
    - ``market.trade``    逐笔成交

    示例::

        bus = EventBus()

        async def on_ticker(data):
            print(f"收到行情: {data}")

        bus.subscribe("market.ticker", on_ticker)
        await bus.publish("market.ticker", ticker_obj)
    """

    def __init__(self) -> None:
        # channel -> [handler1, handler2, ...]
        self._handlers: dict[str, list[Callable[[Any], Awaitable[None]]]] = defaultdict(list)

    def subscribe(
        self,
        channel: str,
        handler: Callable[[Any], Awaitable[None]],
    ) -> None:
        """
        订阅指定通道。

        Args:
            channel: 通道名称，如 ``"market.ticker"``
            handler: 异步回调函数，接收一个参数（消息数据）
        """
        self._handlers[channel].append(handler)
        logger.debug("事件总线: 新增订阅 channel=%s handler=%s", channel, handler.__qualname__)

    def unsubscribe(
        self,
        channel: str,
        handler: Callable[[Any], Awaitable[None]],
    ) -> None:
        """
        取消订阅指定通道。

        Args:
            channel: 通道名称
            handler: 之前注册的回调函数
        """
        handlers = self._handlers.get(channel, [])
        if handler in handlers:
            handlers.remove(handler)
            logger.debug("事件总线: 取消订阅 channel=%s handler=%s", channel, handler.__qualname__)

    async def publish(self, channel: str, data: Any) -> None:
        """
        向指定通道发布消息。

        所有订阅者的回调将被并发执行（asyncio.gather）。
        单个回调异常不会影响其他回调，仅记录日志。

        Args:
            channel: 通道名称
            data: 消息数据（通常是领域类型实例）
        """
        handlers = self._handlers.get(channel, [])
        if not handlers:
            return

        # 并发执行所有回调，收集异常但不中断
        results = await asyncio.gather(
            *(self._safe_call(h, data, channel) for h in handlers),
            return_exceptions=True,
        )
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(
                    "事件总线: handler %s 在 channel=%s 上异常: %s",
                    handlers[i].__qualname__,
                    channel,
                    result,
                )

    @staticmethod
    async def _safe_call(
        handler: Callable[[Any], Awaitable[None]],
        data: Any,
        channel: str,
    ) -> None:
        """安全调用单个 handler，异常时记录日志并继续"""
        try:
            await handler(data)
        except Exception as exc:
            logger.error(
                "事件总线: %s 处理 channel=%s 时异常: %s",
                handler.__qualname__,
                channel,
                exc,
            )
            raise  # 让 gather 捕获


# ──────────────────────────── 行情网关基类 ────────────────────────────


class MarketGateway(ABC):
    """
    行情网关抽象基类。

    负责:
    1. 连接交易所 WebSocket
    2. 接收原始数据流
    3. 调用 normalizer 归一化为领域类型
    4. 通过 EventBus 发布到对应通道

    子类必须实现:
    - connect(): 建立 WebSocket 连接
    - subscribe_ticker(): 订阅实时行情
    - subscribe_kline(): 订阅 K 线
    - subscribe_orderbook(): 订阅盘口
    - subscribe_trades(): 订阅逐笔成交
    """

    def __init__(self, event_bus: EventBus) -> None:
        """
        初始化行情网关。

        Args:
            event_bus: 事件总线实例，用于发布归一化后的行情数据
        """
        self._event_bus = event_bus
        self._running = False
        self._logger = logging.getLogger(self.__class__.__name__)

    @property
    def event_bus(self) -> EventBus:
        """获取事件总线实例"""
        return self._event_bus

    @property
    def is_running(self) -> bool:
        """网关是否正在运行"""
        return self._running

    @abstractmethod
    async def connect(self) -> None:
        """建立 WebSocket 连接"""

    @abstractmethod
    async def subscribe_ticker(self, symbols: list[str]) -> None:
        """
        订阅实时行情（Ticker）。

        Args:
            symbols: 标的符号列表，内部统一命名格式（如 ["BTC/USDT", "ETH/USDT"]）
        """

    @abstractmethod
    async def subscribe_kline(self, symbols: list[str], interval: str) -> None:
        """
        订阅 K 线数据。

        Args:
            symbols: 标的符号列表
            interval: K 线周期，如 "1m", "5m", "1h", "1d"
        """

    @abstractmethod
    async def subscribe_orderbook(self, symbols: list[str], depth: int = 20) -> None:
        """
        订阅盘口 L2 数据。

        Args:
            symbols: 标的符号列表
            depth: 盘口深度，如 5, 10, 20
        """

    @abstractmethod
    async def subscribe_trades(self, symbols: list[str]) -> None:
        """
        订阅逐笔成交。

        Args:
            symbols: 标的符号列表
        """

    async def start(self) -> None:
        """启动网关，标记为运行状态并建立连接"""
        self._running = True
        self._logger.info("行情网关启动: %s", self.__class__.__name__)
        await self.connect()

    async def stop(self) -> None:
        """停止网关，标记为非运行状态"""
        self._running = False
        self._logger.info("行情网关停止: %s", self.__class__.__name__)
