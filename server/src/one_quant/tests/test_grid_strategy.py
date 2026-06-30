"""网格策略测试 — GridStrategy"""

from __future__ import annotations

import time
from decimal import Decimal

from one_quant.core.types import Fill, Kline, Market, PositionState, Ticker
from one_quant.strategy.grid import GridStrategy


def _ticker(price: str = "50000") -> Ticker:
    return Ticker(
        symbol="BTCUSDT",
        market=Market.SPOT,
        exchange="binance",
        last_price=Decimal(price),
        bid=Decimal(price),
        ask=Decimal(price),
        volume_24h=Decimal("1000"),
        timestamp_ns=time.time_ns(),
    )


def _kline(close: str = "50000") -> Kline:
    return Kline(
        symbol="BTCUSDT",
        market=Market.SPOT,
        exchange="binance",
        interval="1m",
        open=Decimal("50000"),
        high=Decimal("51000"),
        low=Decimal("49000"),
        close=Decimal(close),
        volume=Decimal("100"),
        timestamp_ns=time.time_ns(),
    )


def _fill(side: str = "buy", price: str = "49500", qty: str = "0.01") -> Fill:
    return Fill(
        order_id="test-order",
        symbol="BTCUSDT",
        side=side,
        price=Decimal(price),
        quantity=Decimal(qty),
        fee=Decimal("0"),
        fee_currency="USDT",
        exchange="binance",
        timestamp_ns=time.time_ns(),
    )


class TestGridStrategyBasics:
    def test_name(self):
        s = GridStrategy()
        assert s.name == "grid"

    def test_enabled_default_false(self):
        s = GridStrategy()
        assert s.enabled is False

    def test_factor_name(self):
        s = GridStrategy(grid_count=10, grid_spacing_pct=Decimal("0.01"))
        assert "grid" in s.factor_name

    def test_invalid_grid_count(self):
        try:
            GridStrategy(grid_count=0)
            assert False
        except ValueError:
            pass

    def test_invalid_spacing(self):
        try:
            GridStrategy(grid_spacing_pct=Decimal("0"))
            assert False
        except ValueError:
            pass

    def test_invalid_position_per_grid(self):
        try:
            GridStrategy(position_per_grid=Decimal("0"))
            assert False
        except ValueError:
            pass

    def test_position_per_grid_upper_bound(self):
        try:
            GridStrategy(position_per_grid=Decimal("1.1"))
            assert False
        except ValueError:
            pass


class TestGridStrategyOnTicker:
    def test_first_ticker_builds_grid(self):
        s = GridStrategy()
        signals = s.on_ticker(_ticker("50000"))
        assert signals == []  # First tick just builds grid
        assert "BTCUSDT" in s._states

    def test_second_ticker_may_signal(self):
        s = GridStrategy(grid_count=10, grid_spacing_pct=Decimal("0.01"))
        s.on_ticker(_ticker("50000"))
        # Price drop to trigger buy grid
        signals = s.on_ticker(_ticker("49000"))
        # May or may not signal depending on grid layout
        assert isinstance(signals, list)

    def test_ticker_returns_list(self):
        s = GridStrategy()
        result = s.on_ticker(_ticker())
        assert isinstance(result, list)


class TestGridStrategyOnKline:
    def test_first_kline_builds_grid(self):
        s = GridStrategy()
        signals = s.on_kline(_kline("50000"))
        assert signals == []

    def test_kline_returns_list(self):
        s = GridStrategy()
        result = s.on_kline(_kline())
        assert isinstance(result, list)


class TestGridStrategyOnFill:
    def test_buy_fill_updates_position(self):
        s = GridStrategy()
        s.on_ticker(_ticker("50000"))
        s.on_fill(_fill(side="buy", price="49500", qty="0.01"))
        state = s._states["BTCUSDT"]
        assert state.position_qty > 0

    def test_sell_fill_reduces_position(self):
        s = GridStrategy()
        s.on_ticker(_ticker("50000"))
        s.on_fill(_fill(side="buy", price="49500", qty="0.1"))
        s.on_fill(_fill(side="sell", price="50500", qty="0.05"))
        state = s._states["BTCUSDT"]
        assert state.position_qty < Decimal("0.1")

    def test_fill_unknown_symbol_ignored(self):
        s = GridStrategy()
        s.on_fill(_fill())  # No grid built yet
        assert "BTCUSDT" not in s._states


class TestGridStrategyOnRecover:
    def test_recover_sets_position(self):
        s = GridStrategy()
        state = PositionState(
            symbol="BTCUSDT",
            market=Market.SPOT,
            side="long",
            quantity=Decimal("0.1"),
            entry_price=Decimal("50000"),
            unrealized_pnl=Decimal("100"),
            realized_pnl=Decimal("0"),
            timestamp_ns=time.time_ns(),
        )
        s.on_recover(state)
        assert "BTCUSDT" in s._states
        assert s._states["BTCUSDT"].position_qty == Decimal("0.1")

    def test_recover_with_zero_price_ignored(self):
        s = GridStrategy()
        state = PositionState(
            symbol="BTCUSDT",
            market=Market.SPOT,
            side="flat",
            quantity=Decimal("0"),
            entry_price=Decimal("0"),
            unrealized_pnl=Decimal("0"),
            realized_pnl=Decimal("0"),
            timestamp_ns=time.time_ns(),
        )
        s.on_recover(state)
        # Should not create grid for zero price
        assert "BTCUSDT" not in s._states


class TestGridStrategyComputeStrength:
    def test_strength_at_center(self):
        s = GridStrategy()
        strength = s._compute_strength(Decimal("50000"), Decimal("50000"))
        assert strength >= 0.1

    def test_strength_at_edge(self):
        s = GridStrategy(grid_count=10, grid_spacing_pct=Decimal("0.01"))
        strength = s._compute_strength(Decimal("45000"), Decimal("50000"))
        assert 0.1 <= strength <= 1.0

    def test_strength_zero_center(self):
        s = GridStrategy()
        strength = s._compute_strength(Decimal("100"), Decimal("0"))
        assert strength == 0.5
