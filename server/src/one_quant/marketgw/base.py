"""
ONE量化 - 行情网关基类

所有交易所行情网关继承此基类，实现 connect/disconnect/subscribe。
网关职责：接收原始行情 → 归一化为领域类型 → 发布到 EventBus。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from one_quant.infra.event_bus import EventBus


class MarketGateway(ABC):
    """行情网关基类。

    Attributes:
        name: 网关名称（如 "binance", "okx"）
        event_bus: 事件总线实例，用于发布归一化后的行情数据
    """

    name: str

    def __init__(self, event_bus: EventBus) -> None:
        """初始化行情网关。

        Args:
            event_bus: 事件总线实例。
        """
        self._event_bus = event_bus
        self._running = False
        self._subscribed_symbols: set[str] = set()

    @abstractmethod
    async def connect(self) -> None:
        """建立与交易所的 WebSocket 连接。"""
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """断开连接，释放资源。"""
        ...

    @abstractmethod
    async def subscribe_ticker(self, symbol: str) -> None:
        """订阅实时行情。

        Args:
            symbol: 交易所原始符号（如 "BTCUSDT"）。
        """
        ...

    @abstractmethod
    async def subscribe_kline(self, symbol: str, interval: str) -> None:
        """订阅K线数据。

        Args:
            symbol: 交易所原始符号。
            interval: K线周期（如 "1m", "5m", "1h"）。
        """
        ...

    @abstractmethod
    async def subscribe_orderbook(self, symbol: str, depth: int = 20) -> None:
        """订阅盘口深度。

        Args:
            symbol: 交易所原始符号。
            depth: 深度档位数。
        """
        ...

    @abstractmethod
    async def subscribe_trades(self, symbol: str) -> None:
        """订阅逐笔成交。

        Args:
            symbol: 交易所原始符号。
        """
        ...

    async def start(self) -> None:
        """启动网关（连接 + 开始接收）。"""
        await self.connect()
        self._running = True

    async def stop(self) -> None:
        """停止网关。"""
        self._running = False
        await self.disconnect()

    @property
    def is_running(self) -> bool:
        """网关是否运行中。"""
        return self._running
