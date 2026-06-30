"""
ONE量化 - 交易所适配器合约

交易所适配器负责与具体交易所 API 交互，将交易所私有格式
转换为统一领域类型（core.types）。

规范：
  - 所有方法为异步（async），适配 IO 密集的网络调用
  - connect / disconnect 管理连接生命周期
  - submit_order 返回交易所分配的订单ID
  - 异常处理由适配器内部完成，向上抛出统一异常（自定义）
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from one_quant.core.types import (
    Market,
    Order,
    PositionState,
    Ticker,
)


class ExchangeAdapter(ABC):
    """交易所适配器基类。

    每个交易所（Binance、OKX、Alpaca 等）实现一个子类。
    适配器负责：
      1. 连接管理（WebSocket / REST）
      2. 订单生命周期（下单、撤单、状态查询）
      3. 行情订阅（Ticker、K线、盘口等由上层管理）
      4. 数据格式转换（交易所格式 → 统一领域类型）

    Attributes:
        name: 交易所名称（如 "binance", "okx"）
        supported_markets: 支持的市场类型集合

    Example::

        class BinanceAdapter(ExchangeAdapter):
            name = "binance"
            supported_markets = {Market.SPOT, Market.FUTURES}

            async def connect(self) -> None:
                # 建立 WebSocket 连接
                ...

            async def submit_order(self, order: Order) -> str:
                # 调用 Binance REST API 下单
                return "binance_order_id_123"
    """

    name: str
    supported_markets: set[Market]

    @abstractmethod
    async def connect(self) -> None:
        """建立与交易所的连接。

        包括 WebSocket 订阅连接和 REST API 鉴权。
        连接失败应抛出异常。
        """
        raise NotImplementedError

    @abstractmethod
    async def disconnect(self) -> None:
        """断开与交易所的连接。

        优雅关闭所有连接，释放资源。
        """
        raise NotImplementedError

    @abstractmethod
    async def submit_order(self, order: Order) -> str:
        """提交订单到交易所。

        Args:
            order: 统一订单对象

        Returns:
            交易所分配的订单ID（字符串）

        Raises:
            ExchangeError: 下单失败（余额不足、参数错误等）
        """
        raise NotImplementedError

    @abstractmethod
    async def cancel_order(self, order_id: str, symbol: str) -> bool:
        """撤销订单。

        Args:
            order_id: 交易所订单ID
            symbol: 标的符号

        Returns:
            是否成功撤销。订单已成交或不存在时返回 False。
        """
        raise NotImplementedError

    @abstractmethod
    async def get_positions(self) -> list[PositionState]:
        """查询当前所有持仓。

        Returns:
            持仓状态列表。无持仓时返回空列表。
        """
        raise NotImplementedError

    @abstractmethod
    async def get_ticker(self, symbol: str) -> Ticker:
        """查询指定标的最新行情。

        Args:
            symbol: 标的符号

        Returns:
            最新行情快照
        """
        raise NotImplementedError
