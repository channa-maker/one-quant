"""
ONE量化 - OMS 订单管理测试

验证订单创建、状态更新、成交处理。
"""

import time
from decimal import Decimal

from one_quant.core.types import Fill, Market, Signal
from one_quant.execution.oms import OrderManager
from one_quant.infra.event_bus import InMemoryEventBus


class TestOrderManager:
    """OMS 测试"""

    def _make_signal(self) -> Signal:
        return Signal(
            symbol="BTCUSDT",
            market=Market.SPOT,
            side="buy",
            strength=0.8,
            strategy_name="test",
            reason="测试",
            timestamp_ns=time.time_ns(),
        )

    def test_create_order_from_signal(self) -> None:
        bus = InMemoryEventBus()
        oms = OrderManager(bus)
        signal = self._make_signal()

        order = oms.create_order_from_signal(
            signal,
            order_type="limit",
            price=Decimal("50000"),
            quantity=Decimal("0.1"),
            exchange="binance",
        )

        assert order.symbol == "BTCUSDT"
        assert order.side == "buy"
        assert order.status == "pending"
        assert order.client_order_id  # UUID 不为空

    def test_update_order_status(self) -> None:
        bus = InMemoryEventBus()
        oms = OrderManager(bus)
        signal = self._make_signal()

        order = oms.create_order_from_signal(
            signal, price=Decimal("50000"), quantity=Decimal("0.1"), exchange="binance"
        )
        updated = oms.update_order_status(order.client_order_id, "submitted")
        assert updated is not None
        assert updated.status == "submitted"

    def test_update_nonexistent_order(self) -> None:
        bus = InMemoryEventBus()
        oms = OrderManager(bus)
        result = oms.update_order_status("nonexistent", "filled")
        assert result is None

    def test_process_fill(self) -> None:
        bus = InMemoryEventBus()
        oms = OrderManager(bus)
        signal = self._make_signal()

        order = oms.create_order_from_signal(
            signal, price=Decimal("50000"), quantity=Decimal("0.1"), exchange="binance"
        )

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

        # 订单应变为 filled
        updated = oms.get_order(order.client_order_id)
        assert updated is not None
        assert updated.status == "filled"

    def test_stats(self) -> None:
        bus = InMemoryEventBus()
        oms = OrderManager(bus)
        assert oms.stats["orders"] == 0
        assert oms.stats["fills"] == 0
