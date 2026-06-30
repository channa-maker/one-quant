"""UnifiedBroker 统一券商抽象层 — 跨市场统一接口"""

from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Any

from one_quant.core.types import Fill, Market, Order, PositionState, Ticker
from one_quant.infra.logging import get_logger

logger = get_logger(__name__)


class UnifiedBroker(ABC):
    """统一券商抽象层。

    桥接 IBKR(美股/美期权) + 币安/OKX(加密) + Deribit(加密期权)。
    提供统一的下单/撤单/持仓/资金查询接口。

    子类实现：
    - CryptoBroker: 加密货币
    - StockBroker: 美股
    - OptionBroker: 期权
    """

    name: str
    supported_markets: set[Market]

    @abstractmethod
    async def connect(self) -> None: ...

    @abstractmethod
    async def disconnect(self) -> None: ...

    @abstractmethod
    async def submit_order(self, order: Order) -> str: ...

    @abstractmethod
    async def cancel_order(self, order_id: str, symbol: str) -> bool: ...

    @abstractmethod
    async def get_positions(self) -> list[PositionState]: ...

    @abstractmethod
    async def get_balance(self) -> dict[str, Decimal]: ...

    @abstractmethod
    async def get_ticker(self, symbol: str) -> Ticker: ...


class CryptoBroker(UnifiedBroker):
    """加密货币券商（封装币安/OKX 适配器）"""
    name = "crypto"
    supported_markets = {Market.SPOT, Market.FUTURES}

    def __init__(self) -> None:
        self._adapters: dict[str, Any] = {}

    def register_adapter(self, exchange: str, adapter: Any) -> None:
        self._adapters[exchange] = adapter

    async def connect(self) -> None:
        for name, adapter in self._adapters.items():
            await adapter.connect()
            logger.info("加密券商已连接: %s", name)

    async def disconnect(self) -> None:
        for adapter in self._adapters.values():
            await adapter.disconnect()

    async def submit_order(self, order: Order) -> str:
        adapter = self._adapters.get(order.exchange)
        if not adapter:
            raise ValueError(f"未注册的交易所: {order.exchange}")
        return await adapter.submit_order(order)

    async def cancel_order(self, order_id: str, symbol: str) -> bool:
        for adapter in self._adapters.values():
            try:
                return await adapter.cancel_order(order_id, symbol)
            except Exception:
                continue
        return False

    async def get_positions(self) -> list[PositionState]:
        all_positions = []
        for adapter in self._adapters.values():
            all_positions.extend(await adapter.get_positions())
        return all_positions

    async def get_balance(self) -> dict[str, Decimal]:
        return {}

    async def get_ticker(self, symbol: str) -> Ticker:
        for adapter in self._adapters.values():
            try:
                return await adapter.get_ticker(symbol)
            except Exception:
                continue
        raise ValueError(f"无法获取行情: {symbol}")


class StockBroker(UnifiedBroker):
    """美股券商（IBKR 适配器骨架）"""
    name = "stock"
    supported_markets = {Market.STOCK}

    async def connect(self) -> None:
        logger.info("IBKR 适配器待实现")

    async def disconnect(self) -> None:
        pass

    async def submit_order(self, order: Order) -> str:
        raise NotImplementedError("IBKR 适配器待实现")

    async def cancel_order(self, order_id: str, symbol: str) -> bool:
        raise NotImplementedError

    async def get_positions(self) -> list[PositionState]:
        return []

    async def get_balance(self) -> dict[str, Decimal]:
        return {}

    async def get_ticker(self, symbol: str) -> Ticker:
        raise NotImplementedError
