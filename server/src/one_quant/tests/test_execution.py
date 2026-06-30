"""
ONE量化 - 执行引擎综合测试

验证 OMS + EMS + 限流器 + 净额轧差。
"""

import time
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from one_quant.core.types import Fill, Market, Order, Signal
from one_quant.execution.ems import ExecutionManager, TWAPAlgo, _round_to_lot
from one_quant.execution.oms import OrderManager
from one_quant.execution.rate_limiter import RateLimiter
from one_quant.infra.event_bus import InMemoryEventBus


def _make_order(price: str = "50000", qty: str = "0.1") -> Order:
    return Order(
        client_order_id="test-uuid",
        symbol="BTCUSDT",
        market=Market.SPOT,
        side="buy",
        order_type="limit",
        quantity=Decimal(qty),
        price=Decimal(price),
        stop_price=None,
        status="pending",
        exchange="binance",
        timestamp_ns=time.time_ns(),
    )


class TestOMSIntegration:
    """OMS 集成测试"""

    def test_full_lifecycle(self):
        """订单完整生命周期：创建→提交→成交。"""
        bus = InMemoryEventBus()
        oms = OrderManager(bus)

        # 创建信号
        signal = Signal(
            symbol="BTCUSDT",
            market=Market.SPOT,
            side="buy",
            strength=0.8,
            strategy_name="test",
            reason="测试",
            timestamp_ns=time.time_ns(),
        )

        # 创建订单
        order = oms.create_order_from_signal(
            signal, price=Decimal("50000"), quantity=Decimal("0.1"), exchange="binance"
        )
        assert order.status == "pending"

        # 提交
        oms.update_order_status(order.client_order_id, "submitted")
        assert oms.get_order(order.client_order_id).status == "submitted"

        # 成交
        fill = Fill(
            order_id=order.client_order_id,
            symbol="BTCUSDT",
            side="buy",
            price=Decimal("50000"),
            quantity=Decimal("0.1"),
            fee=Decimal("5"),
            fee_currency="USDT",
            exchange="binance",
            timestamp_ns=time.time_ns(),
        )
        oms.process_fill(fill)
        assert oms.get_order(order.client_order_id).status == "filled"
        assert oms.stats["fills"] == 1


class TestEMSIntegration:
    """EMS 集成测试"""

    @pytest.mark.asyncio
    async def test_twap_execution(self):
        """TWAP 拆单执行。"""
        adapter = AsyncMock()
        adapter.submit_order = AsyncMock(return_value="ex-order-1")

        algo = TWAPAlgo(duration_sec=1, slice_count=3)
        order = _make_order(qty="0.3")

        fills = await algo.execute(order, adapter)
        assert adapter.submit_order.call_count == 3
        assert len(fills) == 3

    @pytest.mark.asyncio
    async def test_ems_auto_select(self):
        """EMS 自动选择算法。"""
        adapter = AsyncMock()
        adapter.submit_order = AsyncMock(return_value="ex-order-1")

        ems = ExecutionManager(adapter)
        order = _make_order(price="100", qty="0.001")  # 小单

        fills = await ems.execute(order)
        assert len(fills) == 1  # 即时执行

    def test_round_to_lot(self):
        """取整测试。"""
        assert _round_to_lot(Decimal("1.234"), Decimal("0.01")) == Decimal("1.23")
        assert _round_to_lot(Decimal("2.0"), Decimal("0.5")) == Decimal("2.0")


class TestRateLimiterIntegration:
    """限流器集成测试"""

    @pytest.mark.asyncio
    async def test_burst_then_throttle(self):
        """突发请求后限流。"""
        limiter = RateLimiter("test", max_tokens=3, refill_rate=10.0)

        # 快速消耗 3 个令牌
        await limiter.acquire()
        await limiter.acquire()
        await limiter.acquire()

        # 第 4 个需要等待
        assert limiter.available_tokens < 0.5
