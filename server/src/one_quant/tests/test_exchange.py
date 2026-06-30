"""
ONE量化 - 交易所适配器测试

验证 BrokerPool、适配器注册/获取、限流器集成。
"""

from unittest.mock import MagicMock

import pytest

from one_quant.core.types import Market
from one_quant.exchange.contracts import ExchangeAdapter
from one_quant.exchange.pool import BrokerPool


class DummyAdapter(ExchangeAdapter):
    """测试用适配器。"""

    name = "dummy"
    supported_markets = {Market.SPOT}

    async def connect(self) -> None:
        pass

    async def disconnect(self) -> None:
        pass

    async def submit_order(self, order):
        return "order-123"

    async def cancel_order(self, order_id, symbol):
        return True

    async def get_positions(self):
        return []

    async def get_ticker(self, symbol):
        import time
        from decimal import Decimal

        from one_quant.core.types import Ticker

        return Ticker(
            symbol=symbol,
            market=Market.SPOT,
            exchange="dummy",
            last_price=Decimal("100"),
            bid=Decimal("99"),
            ask=Decimal("101"),
            volume_24h=Decimal("1000"),
            timestamp_ns=time.time_ns(),
        )


class TestBrokerPool:
    """BrokerPool 测试"""

    def test_register_and_get(self):
        pool = BrokerPool()
        adapter = DummyAdapter()
        pool.register("dummy", adapter)
        assert pool.get("dummy") is adapter

    def test_get_unknown_raises(self):
        pool = BrokerPool()
        with pytest.raises(KeyError, match="未注册"):
            pool.get("unknown")

    def test_get_by_market(self):
        pool = BrokerPool()
        pool.register("dummy", DummyAdapter())
        adapters = pool.get_by_market(Market.SPOT)
        assert len(adapters) == 1

    def test_get_by_market_empty(self):
        pool = BrokerPool()
        pool.register("dummy", DummyAdapter())
        adapters = pool.get_by_market(Market.FUTURES)
        assert len(adapters) == 0

    @pytest.mark.asyncio
    async def test_connect_all(self):
        pool = BrokerPool()
        pool.register("dummy", DummyAdapter())
        await pool.connect_all()
        assert "dummy" in pool.stats["adapters"]

    def test_stats(self):
        pool = BrokerPool()
        pool.register("d1", DummyAdapter())
        pool.register("d2", DummyAdapter())
        stats = pool.stats
        assert stats["total"] == 2


class TestDummyAdapter:
    """适配器基本测试"""

    @pytest.mark.asyncio
    async def test_connect_disconnect(self):
        adapter = DummyAdapter()
        await adapter.connect()
        await adapter.disconnect()

    @pytest.mark.asyncio
    async def test_submit_order(self):
        adapter = DummyAdapter()
        await adapter.connect()
        result = await adapter.submit_order(MagicMock())
        assert result == "order-123"

    @pytest.mark.asyncio
    async def test_cancel_order(self):
        adapter = DummyAdapter()
        result = await adapter.cancel_order("order-123", "BTCUSDT")
        assert result is True

    @pytest.mark.asyncio
    async def test_get_ticker(self):
        adapter = DummyAdapter()
        ticker = await adapter.get_ticker("BTCUSDT")
        assert ticker.symbol == "BTCUSDT"
