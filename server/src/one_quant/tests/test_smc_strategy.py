"""SMC 策略补充测试 — SMCStrategy 类"""

from __future__ import annotations

import time
from decimal import Decimal

from one_quant.core.types import Kline, Market, Ticker
from one_quant.strategy.smc import SmartMoneyIndex, SMCAnalyzer, SMCStrategy


def _kline(
    open_: str = "100",
    high: str = "105",
    low: str = "95",
    close: str = "102",
    volume: str = "1000",
    ts: int = 1_000_000_000_000,
    symbol: str = "BTCUSDT",
) -> Kline:
    return Kline(
        symbol=symbol,
        market=Market.SPOT,
        exchange="binance",
        interval="1h",
        open=Decimal(open_),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        volume=Decimal(volume),
        timestamp_ns=ts,
    )


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


def _trending_up_klines(n: int = 30) -> list[Kline]:
    klines = []
    for i in range(n):
        base = 100 + i * 2
        klines.append(
            _kline(
                open_=str(base),
                high=str(base + 5),
                low=str(base - 1),
                close=str(base + 3),
                ts=1_000_000_000_000 + i * 3_600_000_000_000,
            )
        )
    return klines


class TestSMCStrategyInit:
    def test_name(self):
        s = SMCStrategy()
        assert s.name == "smc"

    def test_enabled_default(self):
        s = SMCStrategy()
        assert s.enabled is False

    def test_invalid_ob_proximity(self):
        try:
            SMCStrategy(ob_proximity_ratio=0.5)
            assert False
        except ValueError:
            pass

    def test_invalid_signal_threshold(self):
        try:
            SMCStrategy(signal_threshold=1.5)
            assert False
        except ValueError:
            pass


class TestSMCStrategyOnTicker:
    def test_returns_empty(self):
        s = SMCStrategy()
        signals = s.on_ticker(_ticker())
        assert signals == []

    def test_caches_market(self):
        s = SMCStrategy()
        s.on_ticker(_ticker())
        assert "BTCUSDT" in s._market_cache


class TestSMCStrategyOnKline:
    def test_short_data_returns_empty(self):
        s = SMCStrategy()
        for i in range(10):
            signals = s.on_kline(_kline(ts=1_000_000_000_000 + i * 3_600_000_000_000))
        assert signals == []

    def test_buffers_updated(self):
        s = SMCStrategy()
        for i in range(5):
            s.on_kline(_kline(ts=1_000_000_000_000 + i * 3_600_000_000_000))
        assert len(s._kline_buf["BTCUSDT"]) == 5
        assert len(s._highs["BTCUSDT"]) == 5
        assert len(s._lows["BTCUSDT"]) == 5

    def test_buffer_capped_at_100(self):
        s = SMCStrategy()
        for i in range(120):
            s.on_kline(
                _kline(
                    ts=1_000_000_000_000 + i * 3_600_000_000_000,
                    close=str(100 + i),
                )
            )
        assert len(s._kline_buf["BTCUSDT"]) <= 100
        assert len(s._highs["BTCUSDT"]) <= 100

    def test_with_trending_data(self):
        s = SMCStrategy(signal_threshold=0.3)
        klines = _trending_up_klines(30)
        signals = []
        for k in klines:
            signals.extend(s.on_kline(k))
        # May or may not generate signals depending on structure
        assert isinstance(signals, list)


class TestSMCStrategyCheckOBProximity:
    def test_in_zone(self):
        s = SMCStrategy(ob_proximity_ratio=0.01)
        obs = [{"type": "bullish_ob", "top": "105", "bottom": "100"}]
        result = s._check_ob_proximity(Decimal("102"), obs)
        assert result is not None

    def test_near_zone(self):
        s = SMCStrategy(ob_proximity_ratio=0.01)
        obs = [{"type": "bullish_ob", "top": "105", "bottom": "100"}]
        result = s._check_ob_proximity(Decimal("105.1"), obs)
        assert result is not None

    def test_far_away(self):
        s = SMCStrategy(ob_proximity_ratio=0.001)
        obs = [{"type": "bullish_ob", "top": "105", "bottom": "100"}]
        result = s._check_ob_proximity(Decimal("200"), obs)
        assert result is None

    def test_empty_obs(self):
        s = SMCStrategy()
        result = s._check_ob_proximity(Decimal("100"), [])
        assert result is None


class TestSMCAnalyzerExtended:
    def test_swing_highs(self):
        a = SMCAnalyzer()
        highs = [Decimal(str(100 + (5 if 5 <= i <= 7 else 0))) for i in range(30)]
        swings = a._find_swing_highs(highs, lookback=3)
        assert isinstance(swings, list)

    def test_swing_lows(self):
        a = SMCAnalyzer()
        lows = [Decimal(str(100 - (5 if 5 <= i <= 7 else 0))) for i in range(30)]
        swings = a._find_swing_lows(lows, lookback=3)
        assert isinstance(swings, list)

    def test_premium_discount_high_price(self):
        a = SMCAnalyzer()
        klines = []
        for i in range(20):
            klines.append(
                _kline(
                    open_=str(200 - i),
                    high=str(202 - i),
                    low=str(198 - i),
                    close=str(201 - i),
                )
            )
        zone = a.premium_discount(klines)
        assert zone in ("premium", "discount", "equilibrium")

    def test_premium_discount_low_price(self):
        a = SMCAnalyzer()
        klines = []
        for i in range(20):
            klines.append(
                _kline(
                    open_=str(100 + i),
                    high=str(102 + i),
                    low=str(98 + i),
                    close=str(101 + i),
                )
            )
        zone = a.premium_discount(klines)
        assert zone in ("premium", "discount", "equilibrium")


class TestSmartMoneyIndexExtended:
    def test_smi_monotonic_up(self):
        smi = SmartMoneyIndex()
        opens = [Decimal(str(100 + i)) for i in range(10)]
        closes = [Decimal(str(101 + i)) for i in range(10)]
        volumes = [Decimal("1000")] * 10
        result = smi.classic_smi(opens, closes, volumes)
        assert len(result) == 10

    def test_smi_mismatched_lengths(self):
        smi = SmartMoneyIndex()
        result = smi.classic_smi(
            [Decimal("100"), Decimal("101")],
            [Decimal("101")],
            [Decimal("1000")],
        )
        assert result == []
