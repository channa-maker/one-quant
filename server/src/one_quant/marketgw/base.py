"""
ONE量化 - 行情网关基类

定义行情网关的标准生命周期和数据发布接口。

与 ``exchange/gateway_base.py`` 的关系:
- ``exchange/gateway_base.MarketDataGateway`` 是通用交易所网关基类（含下单等）
- ``marketgw/base.MarketGateway`` 专注于行情数据采集，接口更精简

所有行情数据通过 ``infra.event_bus.EventBus`` 发布，下游消费者无需了解数据来源。
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from one_quant.infra.event_bus import EventBus

logger = logging.getLogger(__name__)


class MarketGateway(ABC):
    """
    行情网关抽象基类。

    职责:
    1. 连接交易所 WebSocket
    2. 接收原始数据流
    3. 调用 normalizer 归一化为领域类型
    4. 通过 EventBus 发布到对应通道 (market.ticker / market.kline / market.orderbook / market.trade)

    子类必须实现:
    - connect(): 建立 WebSocket 连接
    - disconnect(): 断开连接
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
    async def disconnect(self) -> None:
        """断开 WebSocket 连接"""

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
        """启动网关，标记为运行状态"""
        self._running = True
        self._logger.info("行情网关启动: %s", self.__class__.__name__)

    async def stop(self) -> None:
        """停止网关，断开连接"""
        self._running = False
        await self.disconnect()
        self._logger.info("行情网关停止: %s", self.__class__.__name__)
