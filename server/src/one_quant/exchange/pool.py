"""
ONE量化 - 交易所适配器池

统一管理所有交易所适配器实例，惰性创建、用后释放。
禁止直接 new 适配器，必须通过 BrokerPool 获取。
"""

from __future__ import annotations

import logging
from typing import Any

from one_quant.core.types import Market
from one_quant.exchange.contracts import ExchangeAdapter

logger = logging.getLogger(__name__)


class BrokerPool:
    """交易所适配器池。

    管理所有交易所适配器的生命周期。
    适配器按名称注册，按需获取。

    Example::

        pool = BrokerPool()
        pool.register("binance", BinanceAdapter(...))
        adapter = pool.get("binance")
        await adapter.connect()
    """

    def __init__(self) -> None:
        self._adapters: dict[str, ExchangeAdapter] = {}
        self._connected: set[str] = set()

    def register(self, name: str, adapter: ExchangeAdapter) -> None:
        """注册适配器。

        Args:
            name: 适配器名称。
            adapter: 适配器实例。
        """
        self._adapters[name] = adapter
        logger.info("适配器已注册: %s (支持市场: %s)", name, adapter.supported_markets)

    def get(self, name: str) -> ExchangeAdapter:
        """获取适配器。

        Args:
            name: 适配器名称。

        Returns:
            适配器实例。

        Raises:
            KeyError: 适配器未注册。
        """
        adapter = self._adapters.get(name)
        if adapter is None:
            available = ", ".join(sorted(self._adapters.keys())) or "(无)"
            raise KeyError(f"适配器 '{name}' 未注册。可用: {available}")
        return adapter

    async def connect_all(self) -> None:
        """连接所有已注册的适配器。"""
        for name, adapter in self._adapters.items():
            try:
                await adapter.connect()
                self._connected.add(name)
                logger.info("适配器已连接: %s", name)
            except Exception:
                logger.exception("适配器连接失败: %s", name)

    async def disconnect_all(self) -> None:
        """断开所有适配器。"""
        for name in list(self._connected):
            try:
                await self._adapters[name].disconnect()
                self._connected.discard(name)
                logger.info("适配器已断开: %s", name)
            except Exception:
                logger.exception("适配器断开失败: %s", name)

    def get_by_market(self, market: Market) -> list[ExchangeAdapter]:
        """按市场类型获取适配器列表。

        Args:
            market: 市场类型。

        Returns:
            支持该市场的适配器列表。
        """
        return [a for a in self._adapters.values() if market in a.supported_markets]

    @property
    def stats(self) -> dict[str, Any]:
        """统计信息。"""
        return {
            "total": len(self._adapters),
            "connected": len(self._connected),
            "adapters": list(self._adapters.keys()),
        }
