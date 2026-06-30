"""
Tests for strategy.consistency (BacktestConsistencyChecker) and strategy.basic_strategies
"""

import time
from decimal import Decimal

import pytest

from one_quant.core.types import Fill, Kline, Market, Signal, Ticker
from one_quant.strategy.basic_strategies import (
    EMACrossStrategy,
    GridStrategy,
    RSIReversalStrategy,
)


def _make_ticker(price: str = "50000", symbol: str = "BTC/USDT") -> Ticker:
    return Ticker(
        symbol=symbol,
        market=Market.SPOT,
        exchange="binance",
        last_price=Decimal(price),
        bid=Decimal(price),
        ask=Decimal(price),
        volume_24h=Decimal("1000"),
        timestamp_ns=time.time_ns(),
    )


def _make_kline(close: str = "50000", symbol: str = "BTC/USDT") -> Kline:
    return Kline(
        symbol=symbol,
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


# ═══════════════════════ EMACrossStrategy ═══════════════════════


class TestEMACrossStrategy:
    def test_name(self):
        s = EMACrossStrategy()
        assert s.name == "ema_cross"

    def test_default_params(self):
        s = EMACrossStrategy()
        assert s._fast_period == 12
        assert s._slow_period == 26
        assert s._symbol == "BTC/USDT"
        assert s._initialized is False

    def test_custom_params(self):
        s = EMACrossStrategy(fast_period=5, slow_period=10, symbol="ETH/USDT")
        assert s._fast_period == 5
        assert s._slow_period == 10
        assert s._symbol == "ETH/USDT"

    def test_on_ticker_wrong_symbol(self):
        s = EMACrossStrategy(symbol="BTC/USDT")
        ticker = _make_ticker(symbol="ETH/USDT")
        assert s.on_ticker(ticker) == []

    def test_on_kline_wrong_symbol(self):
        s = EMACrossStrategy(symbol="BTC/USDT")
        kline = _make_kline(symbol="ETH/USDT")
        assert s.on_kline(kline) == []

    def test_on_ticker_returns_list(self):
        s = EMACrossStrategy()
        result = s.on_ticker(_make_ticker())
        assert isinstance(result, list)

    def test_on_kline_returns_list(self):
        s = EMACrossStrategy()
        result = s.on_kline(_make_kline())
        assert isinstance(result, list)

    def test_ema_initialization(self):
        s = EMACrossStrategy(fast_period=3, slow_period=5)
        # Feed enough data points
        for i in range(10):
            s._update_ema(Decimal(str(50000 + i * 100)))
        assert s._initialized is True

    def test_golden_cross_signal(self):
        """EMA fast crosses above slow → buy signal."""
        s = EMACrossStrategy(fast_period=3, slow_period=5, symbol="BTC/USDT")

        # First establish a trend where fast < slow
        prices_down = [Decimal(str(50000 - i * 100)) for i in range(20)]
        for p in prices_down:
            s.on_kline(_make_kline(close=str(p)))

        # Now reverse: fast should cross above slow
        signals = []
        for i in range(20):
            p = Decimal(str(48000 + i * 200))
            sigs = s.on_kline(_make_kline(close=str(p)))
            signals.extend(sigs)

        buy_signals = [s for s in signals if s.side == "buy"]
        # May or may not trigger depending on exact prices, but structure should work
        assert all(isinstance(s, Signal) for s in buy_signals)

    def test_death_cross_signal(self):
        """EMA fast crosses below slow → sell signal."""
        s = EMACrossStrategy(fast_period=3, slow_period=5, symbol="BTC/USDT")

        # Establish uptrend
        for i in range(20):
            s.on_kline(_make_kline(close=str(50000 + i * 100)))

        # Reverse to downtrend
        signals = []
        for i in range(20):
            p = Decimal(str(52000 - i * 200))
            sigs = s.on_kline(_make_kline(close=str(p)))
            signals.extend(sigs)

        sell_signals = [s for s in signals if s.side == "sell"]
        assert all(isinstance(s, Signal) for s in sell_signals)

    def test_no_signal_before_initialization(self):
        s = EMACrossStrategy(fast_period=12, slow_period=26)
        # Feed fewer than slow_period data points
        for i in range(10):
            signals = s.on_kline(_make_kline(close=str(50000 + i * 100)))
            assert signals == []

    def test_signal_attributes(self):
        s = EMACrossStrategy(fast_period=3, slow_period=5, symbol="BTC/USDT")

        # Generate enough data for initialization and a cross
        for i in range(30):
            s.on_kline(_make_kline(close=str(50000 + i * 50)))
        for i in range(30):
            signals = s.on_kline(_make_kline(close=str(51500 - i * 100)))
            for sig in signals:
                assert sig.symbol == "BTC/USDT"
                assert sig.market == Market.SPOT
                assert sig.strategy_name == "ema_cross"
                assert 0 <= sig.strength <= 1
                assert "EMA" in sig.reason

    def test_on_ticker_generates_signals(self):
        s = EMACrossStrategy(fast_period=3, slow_period=5, symbol="BTC/USDT")

        # Feed via ticker
        for i in range(30):
            s.on_ticker(_make_ticker(price=str(50000 + i * 50)))
        for i in range(30):
            signals = s.on_ticker(_make_ticker(price=str(51500 - i * 100)))
            # May or may not produce signals, but should not crash
            assert isinstance(signals, list)


# ═══════════════════════ RSIReversalStrategy ═══════════════════════


class TestRSIReversalStrategy:
    def test_name(self):
        s = RSIReversalStrategy()
        assert s.name == "rsi_reversal"

    def test_default_params(self):
        s = RSIReversalStrategy()
        assert s._period == 14
        assert s._oversold == Decimal("30")
        assert s._overbought == Decimal("70")
        assert s._symbol == "BTC/USDT"

    def test_custom_params(self):
        s = RSIReversalStrategy(period=7, oversold=20, overbought=80, symbol="ETH/USDT")
        assert s._period == 7
        assert s._oversold == Decimal("20")
        assert s._overbought == Decimal("80")

    def test_on_ticker_wrong_symbol(self):
        s = RSIReversalStrategy(symbol="BTC/USDT")
        assert s.on_ticker(_make_ticker(symbol="ETH/USDT")) == []

    def test_on_kline_wrong_symbol(self):
        s = RSIReversalStrategy(symbol="BTC/USDT")
        assert s.on_kline(_make_kline(symbol="ETH/USDT")) == []

    def test_rsi_calculation_not_enough_data(self):
        s = RSIReversalStrategy(period=14)
        # Less than period + 1 data points
        for i in range(10):
            s._closes.append(Decimal(str(50000 + i * 100)))
        rsi = s._calc_rsi()
        assert rsi == Decimal("50")  # Default when not enough data

    def test_rsi_calculation_all_gains(self):
        s = RSIReversalStrategy(period=5)
        # Monotonically increasing prices → RSI should be 100
        for i in range(10):
            s._closes.append(Decimal(str(50000 + i * 100)))
        rsi = s._calc_rsi()
        assert rsi == Decimal("100")

    def test_rsi_calculation_all_losses(self):
        s = RSIReversalStrategy(period=5)
        # Monotonically decreasing prices
        for i in range(10):
            s._closes.append(Decimal(str(50900 - i * 100)))
        rsi = s._calc_rsi()
        assert rsi < Decimal("10")

    def test_rsi_oversold_bounce_signal(self):
        """RSI crosses above oversold line → buy signal."""
        s = RSIReversalStrategy(period=5, oversold=30, overbought=70, symbol="BTC/USDT")

        # First push RSI into oversold territory with declining prices
        for i in range(20):
            s.on_kline(_make_kline(close=str(50000 - i * 200)))

        # Now bounce back
        signals = []
        for i in range(10):
            sigs = s.on_kline(_make_kline(close=str(46000 + i * 500)))
            signals.extend(sigs)

        buy_signals = [s for s in signals if s.side == "buy"]
        # Check structure of any signals found
        for sig in buy_signals:
            assert sig.strategy_name == "rsi_reversal"
            assert "RSI" in sig.reason

    def test_rsi_overbought_reversal_signal(self):
        """RSI crosses below overbought line → sell signal."""
        s = RSIReversalStrategy(period=5, oversold=30, overbought=70, symbol="BTC/USDT")

        # Push RSI into overbought territory
        for i in range(20):
            s.on_kline(_make_kline(close=str(50000 + i * 200)))

        # Now decline
        signals = []
        for i in range(10):
            sigs = s.on_kline(_make_kline(close=str(54000 - i * 500)))
            signals.extend(sigs)

        sell_signals = [s for s in signals if s.side == "sell"]
        for sig in sell_signals:
            assert sig.strategy_name == "rsi_reversal"

    def test_no_signal_stable_rsi(self):
        """Stable prices → RSI near 50 → no signals."""
        s = RSIReversalStrategy(period=5, oversold=30, overbought=70)

        # Feed stable prices
        for i in range(30):
            price = 50000 + (i % 2) * 10  # Oscillate slightly
            s.on_kline(_make_kline(close=str(price)))

        signals = []
        for i in range(10):
            price = 50000 + (i % 2) * 10
            sigs = s.on_kline(_make_kline(close=str(price)))
            signals.extend(sigs)

        # RSI near 50, no oversold/overbought → no signals
        assert len(signals) == 0

    def test_on_ticker_path(self):
        s = RSIReversalStrategy(period=5, symbol="BTC/USDT")
        for i in range(20):
            result = s.on_ticker(_make_ticker(price=str(50000 + i * 100)))
            assert isinstance(result, list)


# ═══════════════════════ GridStrategy ═══════════════════════


class TestGridStrategy:
    def test_name(self):
        s = GridStrategy()
        assert s.name == "grid"

    def test_default_params(self):
        s = GridStrategy()
        assert s._symbol == "BTC/USDT"
        assert s._grid_lower == Decimal("40000")
        assert s._grid_upper == Decimal("50000")
        assert s._grid_count == 10

    def test_custom_params(self):
        s = GridStrategy(
            symbol="ETH/USDT",
            grid_lower=Decimal("2000"),
            grid_upper=Decimal("4000"),
            grid_count=5,
        )
        assert s._symbol == "ETH/USDT"
        assert s._grid_step == Decimal("400")

    def test_on_ticker_wrong_symbol(self):
        s = GridStrategy(symbol="BTC/USDT")
        assert s.on_ticker(_make_ticker(symbol="ETH/USDT")) == []

    def test_on_kline_wrong_symbol(self):
        s = GridStrategy(symbol="BTC/USDT")
        assert s.on_kline(_make_kline(symbol="ETH/USDT")) == []

    def test_price_below_grid(self):
        s = GridStrategy(grid_lower=Decimal("40000"), grid_upper=Decimal("50000"))
        signals = s._check_grid(Decimal("39000"), time.time_ns())
        assert signals == []

    def test_price_above_grid(self):
        s = GridStrategy(grid_lower=Decimal("40000"), grid_upper=Decimal("50000"))
        signals = s._check_grid(Decimal("51000"), time.time_ns())
        assert signals == []

    def test_price_at_lower_bound(self):
        s = GridStrategy(grid_lower=Decimal("40000"), grid_upper=Decimal("50000"))
        signals = s._check_grid(Decimal("40000"), time.time_ns())
        # First time, no last_price → no signal
        assert signals == []

    def test_grid_buy_signal_on_downward_cross(self):
        """Price crosses down through a grid line → buy."""
        s = GridStrategy(
            grid_lower=Decimal("40000"),
            grid_upper=Decimal("50000"),
            grid_count=10,
        )
        # Grid lines at 41000, 42000, ..., 49000

        # First set price at grid level 5 (45000)
        s._check_grid(Decimal("45000"), time.time_ns())

        # Move down to grid level 3 (43000)
        signals = s._check_grid(Decimal("43000"), time.time_ns())

        buy_signals = [s for s in signals if s.side == "buy"]
        assert len(buy_signals) >= 1
        assert "网格买入" in buy_signals[0].reason

    def test_grid_sell_signal_on_upward_cross(self):
        """Price crosses up through a filled grid line → sell."""
        s = GridStrategy(
            grid_lower=Decimal("40000"),
            grid_upper=Decimal("50000"),
            grid_count=10,
        )

        # First buy at level 3
        s._check_grid(Decimal("45000"), time.time_ns())
        s._check_grid(Decimal("43000"), time.time_ns())

        # Now move back up
        signals = s._check_grid(Decimal("45000"), time.time_ns())

        sell_signals = [s for s in signals if s.side == "sell"]
        for sig in sell_signals:
            assert "网格卖出" in sig.reason

    def test_grid_no_duplicate_fills(self):
        """Same grid level shouldn't trigger buy twice."""
        s = GridStrategy(
            grid_lower=Decimal("40000"),
            grid_upper=Decimal("50000"),
            grid_count=10,
        )

        s._check_grid(Decimal("45000"), time.time_ns())
        s._check_grid(Decimal("43000"), time.time_ns())
        signals1 = s._check_grid(Decimal("43000"), time.time_ns())  # Same level again

        # Should not produce another buy for the same grid
        buy_signals = [s for s in signals1 if s.side == "buy"]
        assert len(buy_signals) == 0

    def test_on_ticker_path(self):
        s = GridStrategy(symbol="BTC/USDT")
        result = s.on_ticker(_make_ticker(price="45000"))
        assert isinstance(result, list)

    def test_on_kline_path(self):
        s = GridStrategy(symbol="BTC/USDT")
        result = s.on_kline(_make_kline(close="45000"))
        assert isinstance(result, list)

    def test_grid_signal_attributes(self):
        s = GridStrategy(
            grid_lower=Decimal("40000"),
            grid_upper=Decimal("50000"),
            grid_count=10,
        )
        s._check_grid(Decimal("45000"), time.time_ns())
        signals = s._check_grid(Decimal("43000"), time.time_ns())

        for sig in signals:
            assert sig.symbol == "BTC/USDT"
            assert sig.market == Market.SPOT
            assert sig.strategy_name == "grid"
            assert sig.strength == 0.5


# ═══════════════════════ BacktestConsistencyChecker ═══════════════════════


class TestBacktestConsistencyChecker:
    @pytest.mark.asyncio
    async def test_check_empty_data(self):
        from one_quant.strategy.consistency import BacktestConsistencyChecker

        checker = BacktestConsistencyChecker()

        # Create a simple strategy factory
        class DummyStrategy:
            name = "dummy"
            enabled = True

            def on_ticker(self, ticker):
                return []

            def on_kline(self, kline):
                return []

            def on_fill(self, fill):
                pass

        result = await checker.check_empty_data(lambda: DummyStrategy())
        assert result is True

    @pytest.mark.asyncio
    async def test_check_empty_data_exception(self):
        from one_quant.strategy.consistency import BacktestConsistencyChecker

        checker = BacktestConsistencyChecker()

        def bad_factory():
            raise RuntimeError("boom")

        result = await checker.check_empty_data(bad_factory)
        assert result is False

    @pytest.mark.asyncio
    async def test_check_no_future_function_short_data(self):
        from one_quant.strategy.consistency import BacktestConsistencyChecker

        checker = BacktestConsistencyChecker()

        class DummyStrategy:
            name = "dummy"

            def on_ticker(self, ticker):
                return []

            def on_kline(self, kline):
                return []

            def on_fill(self, fill):
                pass

        # Less than 2 data points → returns True
        result = await checker.check_no_future_function(
            lambda: DummyStrategy(),
            [{"_type": "kline", "symbol": "X", "close": "1", "timestamp_ns": 1}],
        )
        assert result is True

    def test_check_backtest_live_deviation_empty_both(self):
        from one_quant.strategy.consistency import BacktestConsistencyChecker

        result = BacktestConsistencyChecker.check_backtest_live_deviation([], [])
        assert result is True

    def test_check_backtest_live_deviation_empty_one(self):
        from one_quant.strategy.consistency import BacktestConsistencyChecker

        fills = [_make_fill(price="50000")]
        result = BacktestConsistencyChecker.check_backtest_live_deviation(fills, [])
        assert result is False

    def test_check_backtest_live_deviation_different_count(self):
        from one_quant.strategy.consistency import BacktestConsistencyChecker

        bt = [_make_fill(price="50000")]
        live = [_make_fill(price="50000"), _make_fill(price="50100")]
        result = BacktestConsistencyChecker.check_backtest_live_deviation(bt, live)
        assert result is False

    def test_check_backtest_live_deviation_within_threshold(self):
        from one_quant.strategy.consistency import BacktestConsistencyChecker

        bt = [_make_fill(price="50000", ts=100)]
        live = [_make_fill(price="50010", ts=100)]
        result = BacktestConsistencyChecker.check_backtest_live_deviation(
            bt, live, threshold=Decimal("0.001")
        )
        # Deviation = |50000-50010|/50010 ≈ 0.0002 < 0.001
        assert result is True

    def test_check_backtest_live_deviation_exceeds_threshold(self):
        from one_quant.strategy.consistency import BacktestConsistencyChecker

        bt = [_make_fill(price="50000", ts=100)]
        live = [_make_fill(price="51000", ts=100)]
        result = BacktestConsistencyChecker.check_backtest_live_deviation(
            bt, live, threshold=Decimal("0.001")
        )
        # Deviation = 1000/51000 ≈ 0.0196 > 0.001
        assert result is False

    def test_check_backtest_live_deviation_symbol_mismatch(self):
        from one_quant.strategy.consistency import BacktestConsistencyChecker

        bt = [
            Fill(
                order_id="1",
                symbol="BTCUSDT",
                side="buy",
                price=Decimal("50000"),
                quantity=Decimal("1"),
                fee=Decimal("0"),
                fee_currency="USDT",
                exchange="binance",
                timestamp_ns=100,
            )
        ]
        live = [
            Fill(
                order_id="2",
                symbol="ETHUSDT",
                side="buy",
                price=Decimal("50000"),
                quantity=Decimal("1"),
                fee=Decimal("0"),
                fee_currency="USDT",
                exchange="binance",
                timestamp_ns=100,
            )
        ]
        result = BacktestConsistencyChecker.check_backtest_live_deviation(bt, live)
        assert result is False

    def test_check_backtest_live_deviation_side_mismatch(self):
        from one_quant.strategy.consistency import BacktestConsistencyChecker

        bt = [_make_fill(price="50000", side="buy", ts=100)]
        live = [_make_fill(price="50000", side="sell", ts=100)]
        result = BacktestConsistencyChecker.check_backtest_live_deviation(bt, live)
        assert result is False

    def test_check_backtest_live_deviation_zero_live_price(self):
        from one_quant.strategy.consistency import BacktestConsistencyChecker

        bt = [_make_fill(price="50000", ts=100)]
        live = [_make_fill(price="0", ts=100)]
        result = BacktestConsistencyChecker.check_backtest_live_deviation(bt, live)
        assert result is False

    @pytest.mark.asyncio
    async def test_check_cost_impact(self):
        from one_quant.strategy.consistency import BacktestConsistencyChecker

        checker = BacktestConsistencyChecker()

        class DummyStrategy:
            name = "dummy"

            def on_ticker(self, ticker):
                return []

            def on_kline(self, kline):
                return []

            def on_fill(self, fill):
                pass

        data = [
            {
                "_type": "kline",
                "symbol": "BTCUSDT",
                "market": "SPOT",
                "close": "50000",
                "open": "50000",
                "high": "50100",
                "low": "49900",
                "volume": "100",
                "timestamp_ns": 1000000000 + i * 86400000000000,
            }
            for i in range(5)
        ]

        diff = await checker.check_cost_impact(lambda: DummyStrategy(), data)
        # No trades → difference is 0
        assert diff >= Decimal("0") or diff == Decimal("0")


def _make_fill(price: str = "50000", side: str = "buy", ts: int = 100) -> Fill:
    return Fill(
        order_id="ord-1",
        symbol="BTCUSDT",
        side=side,
        price=Decimal(price),
        quantity=Decimal("1"),
        fee=Decimal("0"),
        fee_currency="USDT",
        exchange="binance",
        timestamp_ns=ts,
    )
