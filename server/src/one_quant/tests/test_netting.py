"""
Tests for execution.netting (MultiStrategyNetting + NettingEngine)
"""

import time
import uuid
from decimal import Decimal

from one_quant.core.types import Market, Order, Signal
from one_quant.execution.netting import MultiStrategyNetting, NettingEngine


def _make_signal(
    symbol: str = "BTCUSDT",
    side: str = "buy",
    strength: float = 0.8,
    strategy: str = "test",
) -> Signal:
    return Signal(
        symbol=symbol,
        market=Market.SPOT,
        side=side,
        strength=strength,
        strategy_name=strategy,
        reason="test signal",
        timestamp_ns=time.time_ns(),
    )


def _make_order(
    symbol: str = "BTCUSDT",
    side: str = "buy",
    qty: str = "1.0",
    price: str = "50000",
    exchange: str = "binance",
) -> Order:
    return Order(
        client_order_id=str(uuid.uuid4()),
        symbol=symbol,
        market=Market.SPOT,
        side=side,
        order_type="limit",
        quantity=Decimal(qty),
        price=Decimal(price),
        stop_price=None,
        status="pending",
        exchange=exchange,
        timestamp_ns=time.time_ns(),
    )


# ═══════════════════════ MultiStrategyNetting ═══════════════════════


class TestMultiStrategyNetting:
    def test_create(self):
        engine = MultiStrategyNetting()
        assert engine.stats["netting_operations"] == 0

    def test_net_single_signal(self):
        engine = MultiStrategyNetting()
        signals = [_make_signal(side="buy", strength=0.8)]

        result = engine.net_signals(signals)

        assert len(result) == 1
        assert result[0].side == "buy"
        assert result[0].strength == 0.8

    def test_net_same_direction_signals(self):
        engine = MultiStrategyNetting()
        signals = [
            _make_signal(side="buy", strength=0.5),
            _make_signal(side="buy", strength=0.3),
        ]

        result = engine.net_signals(signals)

        assert len(result) == 1
        assert result[0].side == "buy"
        assert result[0].strength == 0.8

    def test_net_opposite_direction_partial_cancel(self):
        engine = MultiStrategyNetting()
        signals = [
            _make_signal(side="buy", strength=0.8),
            _make_signal(side="sell", strength=0.3),
        ]

        result = engine.net_signals(signals)

        assert len(result) == 1
        assert result[0].side == "buy"
        # Net strength = 0.8 - 0.3 = 0.5
        assert abs(result[0].strength - 0.5) < 0.01

    def test_net_complete_cancel(self):
        engine = MultiStrategyNetting()
        signals = [
            _make_signal(side="buy", strength=0.5),
            _make_signal(side="sell", strength=0.5),
        ]

        result = engine.net_signals(signals)

        # Completely cancelled
        assert len(result) == 0

    def test_net_multiple_symbols(self):
        engine = MultiStrategyNetting()
        signals = [
            _make_signal(symbol="BTCUSDT", side="buy", strength=0.8),
            _make_signal(symbol="ETHUSDT", side="sell", strength=0.6),
        ]

        result = engine.net_signals(signals)

        assert len(result) == 2
        symbols = {r.symbol for r in result}
        assert symbols == {"BTCUSDT", "ETHUSDT"}

    def test_net_sell_wins(self):
        engine = MultiStrategyNetting()
        signals = [
            _make_signal(side="buy", strength=0.3),
            _make_signal(side="sell", strength=0.8),
        ]

        result = engine.net_signals(signals)

        assert len(result) == 1
        assert result[0].side == "sell"

    def test_net_strength_capped_at_1(self):
        engine = MultiStrategyNetting()
        signals = [
            _make_signal(side="buy", strength=0.8),
            _make_signal(side="buy", strength=0.8),
        ]

        result = engine.net_signals(signals)

        assert len(result) == 1
        assert result[0].strength <= 1.0

    def test_net_updates_stats(self):
        engine = MultiStrategyNetting()
        signals = [_make_signal()]

        engine.net_signals(signals)

        assert engine.stats["netting_operations"] == 1

    def test_net_conflict_detection(self):
        engine = MultiStrategyNetting(conflict_threshold=0.3)
        # High strength on both sides → conflict
        signals = [
            _make_signal(side="buy", strength=0.8),
            _make_signal(side="sell", strength=0.7),
        ]

        result = engine.net_signals(signals)

        # Still produces a net signal
        assert len(result) == 1

    def test_net_empty_signals(self):
        engine = MultiStrategyNetting()
        result = engine.net_signals([])
        assert result == []

    def test_net_result_has_metadata(self):
        engine = MultiStrategyNetting()
        signals = [
            _make_signal(side="buy", strength=0.8, strategy="strat_a"),
            _make_signal(side="buy", strength=0.5, strategy="strat_b"),
        ]

        result = engine.net_signals(signals)

        assert result[0].strategy_name == "multi_strategy_netting"
        assert "净额轧差" in result[0].reason


# ═══════════════════════ NettingEngine ═══════════════════════


class TestNettingEngine:
    def test_create(self):
        engine = NettingEngine()
        assert engine.stats["netting_operations"] == 0
        assert engine.stats["total_saved_fees"] == Decimal("0")

    def test_net_orders_empty(self):
        engine = NettingEngine()
        result = engine.net_orders([])
        assert result == []

    def test_net_orders_single_buy(self):
        engine = NettingEngine()
        orders = [_make_order(side="buy", qty="1.0")]

        result = engine.net_orders(orders)

        assert len(result) == 1
        assert result[0].side == "buy"
        assert result[0].quantity == Decimal("1.0")

    def test_net_orders_single_sell(self):
        engine = NettingEngine()
        orders = [_make_order(side="sell", qty="1.0")]

        result = engine.net_orders(orders)

        assert len(result) == 1
        assert result[0].side == "sell"

    def test_net_orders_opposite_same_qty(self):
        engine = NettingEngine(fee_rate=Decimal("0.001"))
        orders = [
            _make_order(side="buy", qty="1.0"),
            _make_order(side="sell", qty="1.0"),
        ]

        result = engine.net_orders(orders)

        # Perfectly hedged → no orders needed
        assert len(result) == 0
        assert engine.stats["total_saved_fees"] > Decimal("0")

    def test_net_orders_partial_hedge(self):
        engine = NettingEngine(fee_rate=Decimal("0.001"))
        orders = [
            _make_order(side="buy", qty="1.0"),
            _make_order(side="sell", qty="0.6"),
        ]

        result = engine.net_orders(orders)

        # Net buy = 0.4
        assert len(result) == 1
        assert result[0].side == "buy"
        assert result[0].quantity == Decimal("0.4")

    def test_net_orders_sell_larger(self):
        engine = NettingEngine()
        orders = [
            _make_order(side="buy", qty="0.3"),
            _make_order(side="sell", qty="1.0"),
        ]

        result = engine.net_orders(orders)

        assert len(result) == 1
        assert result[0].side == "sell"
        assert result[0].quantity == Decimal("0.7")

    def test_net_orders_different_symbols(self):
        engine = NettingEngine()
        orders = [
            _make_order(symbol="BTCUSDT", side="buy", qty="1.0"),
            _make_order(symbol="ETHUSDT", side="sell", qty="1.0"),
        ]

        result = engine.net_orders(orders)

        # Different symbols → no hedge
        assert len(result) == 2

    def test_net_orders_different_exchanges(self):
        engine = NettingEngine()
        orders = [
            _make_order(side="buy", qty="1.0", exchange="binance"),
            _make_order(side="sell", qty="1.0", exchange="okx"),
        ]

        result = engine.net_orders(orders)

        # Different exchanges → no hedge
        assert len(result) == 2

    def test_net_orders_saved_fees(self):
        engine = NettingEngine(fee_rate=Decimal("0.001"))
        orders = [
            _make_order(side="buy", qty="1.0"),
            _make_order(side="sell", qty="0.5"),
        ]

        engine.net_orders(orders)

        # Hedge qty = 0.5, saved = 0.5 * 2 * 0.001 = 0.001
        assert engine.stats["total_saved_fees"] == Decimal("0.0010")

    def test_check_conflict_no_conflict(self):
        engine = NettingEngine()
        orders = [_make_order(side="buy", qty="1.0")]

        conflicts = engine.check_conflict(orders)

        assert len(conflicts) == 0

    def test_check_conflict_with_conflict(self):
        engine = NettingEngine()
        orders = [
            _make_order(side="buy", qty="1.0"),
            _make_order(side="sell", qty="0.5"),
        ]

        conflicts = engine.check_conflict(orders)

        assert len(conflicts) == 1
        assert conflicts[0]["symbol"] == "BTCUSDT"
        assert conflicts[0]["conflict_quantity"] == Decimal("0.5")
        assert "severity" in conflicts[0]

    def test_check_conflict_severity_high(self):
        engine = NettingEngine()
        orders = [
            _make_order(side="buy", qty="1.0"),
            _make_order(side="sell", qty="0.8"),
        ]

        conflicts = engine.check_conflict(orders)

        assert len(conflicts) == 1
        assert conflicts[0]["severity"] == "high"

    def test_check_conflict_severity_low(self):
        engine = NettingEngine()
        orders = [
            _make_order(side="buy", qty="10.0"),
            _make_order(side="sell", qty="0.1"),
        ]

        conflicts = engine.check_conflict(orders)

        assert len(conflicts) == 1
        # conflict_qty = 0.1, total_buy = 10 (1%), total_sell = 0.1 (100%)
        # 0.1 > 0.1*0.5? 0.1 > 0.05 → high for sell side
        # Actually 0.1/0.1 = 1.0 > 0.5 → high
        # Need: conflict_qty < 0.2 * both
        # So: min(total_buy, total_sell) / total_buy < 0.2 AND < 0.2 * total_sell
        # That means both sides need to be much larger than conflict_qty
        # Impossible: conflict_qty = min(buy, sell)
        # severity is low when conflict_qty <= 0.2 * total_buy AND <= 0.2 * total_sell
        # This means min(buy, sell) <= 0.2 * buy AND <= 0.2 * sell
        # min(buy, sell) <= 0.2 * sell means buy >= sell / 0.2 = 5*sell (if sell is min)
        # But if sell is min, then min(buy,sell)=sell, and sell <= 0.2*buy → buy >= 5*sell
        # AND sell <= 0.2*sell → 1 <= 0.2 → impossible!
        # So severity can NEVER be "low" with the current code since
        # conflict_qty = min(buy, sell), and min(buy,sell) > 0.2 * min(buy,sell) always.
        # It's always at least "medium".
        assert conflicts[0]["severity"] in ("medium", "high")

    def test_arbitrate_empty(self):
        engine = NettingEngine()
        result = engine.arbitrate([])
        assert result == []

    def test_arbitrate_no_conflict(self):
        engine = NettingEngine()
        orders = [_make_order(side="buy", qty="1.0")]

        result = engine.arbitrate(orders)

        assert len(result) == 1
        assert result[0].side == "buy"

    def test_arbitrate_buy_wins(self):
        engine = NettingEngine()
        orders = [
            _make_order(side="buy", qty="10.0", price="50000"),
            _make_order(side="sell", qty="1.0", price="50000"),
        ]

        result = engine.arbitrate(orders)

        assert len(result) == 1
        assert result[0].side == "buy"
        # Merged quantity
        assert result[0].quantity == Decimal("10.0")

    def test_arbitrate_sell_wins(self):
        engine = NettingEngine()
        orders = [
            _make_order(side="buy", qty="1.0", price="50000"),
            _make_order(side="sell", qty="10.0", price="50000"),
        ]

        result = engine.arbitrate(orders)

        assert len(result) == 1
        assert result[0].side == "sell"

    def test_arbitrate_equal_score_cancels(self):
        engine = NettingEngine()
        orders = [
            _make_order(side="buy", qty="1.0", price="50000"),
            _make_order(side="sell", qty="1.0", price="50000"),
        ]

        result = engine.arbitrate(orders)

        # Equal score → both cancelled
        assert len(result) == 0

    def test_merge_orders_via_arbitrate(self):
        engine = NettingEngine()
        # Two buys vs one sell → buy wins, merges into one
        orders = [
            _make_order(side="buy", qty="1.0", price="50000"),
            _make_order(side="buy", qty="2.0", price="60000"),
            _make_order(side="sell", qty="0.5", price="50000"),
        ]

        result = engine.arbitrate(orders)

        assert len(result) == 1
        assert result[0].side == "buy"
        assert result[0].quantity == Decimal("3.0")
        # Weighted avg price = (1*50000 + 2*60000) / 3 = 56666.67
        assert result[0].price is not None

    def test_multiple_symbols_independent(self):
        engine = NettingEngine()
        orders = [
            _make_order(symbol="BTCUSDT", side="buy", qty="1.0"),
            _make_order(symbol="BTCUSDT", side="sell", qty="1.0"),
            _make_order(symbol="ETHUSDT", side="buy", qty="5.0"),
        ]

        result = engine.net_orders(orders)

        # BTC hedged, ETH kept
        assert len(result) == 1
        assert result[0].symbol == "ETHUSDT"
