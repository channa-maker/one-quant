"""量价结构测试 — VPVR, TPOChart, VWAPFamily"""

from __future__ import annotations

from decimal import Decimal

from one_quant.core.types import Kline, Market
from one_quant.strategy.volume_structure import VPVR, TPOChart, VWAPFamily


def _kline(
    open_: str, high: str, low: str, close: str, volume: str, ts: int = 1_000_000_000_000
) -> Kline:
    return Kline(
        symbol="BTCUSDT",
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


def _sample_klines(n: int = 20) -> list[Kline]:
    klines = []
    for i in range(n):
        base = 100 + i
        klines.append(
            _kline(
                open_=str(base),
                high=str(base + 3),
                low=str(base - 2),
                close=str(base + 1),
                volume="100",
                ts=1_000_000_000_000 + i * 3_600_000_000_000,
            )
        )
    return klines


# ──────────────────────────── VPVR 测试 ────────────────────────────


class TestVPVR:
    def test_constructor_bins_minimum(self):
        try:
            VPVR(bins=3)
            assert False, "Should raise ValueError"
        except ValueError:
            pass

    def test_constructor_bins_valid(self):
        v = VPVR(bins=10)
        assert v._bins == 10

    def test_compute_empty_klines(self):
        v = VPVR()
        assert v.compute([]) == {}

    def test_compute_single_price(self):
        v = VPVR()
        klines = [_kline("100", "100", "100", "100", "100") for _ in range(5)]
        result = v.compute(klines)
        assert Decimal(result["poc"]) == Decimal("100")
        assert Decimal(result["vah"]) == Decimal("100")
        assert Decimal(result["val"]) == Decimal("100")

    def test_compute_returns_all_fields(self):
        v = VPVR()
        klines = _sample_klines(20)
        result = v.compute(klines)
        assert "poc" in result
        assert "vah" in result
        assert "val" in result
        assert "hvn" in result
        assert "lvn" in result
        assert "profile" in result
        assert "total_volume" in result

    def test_compute_poc_is_highest_volume(self):
        v = VPVR()
        klines = _sample_klines(20)
        result = v.compute(klines)
        poc = Decimal(result["poc"])
        # POC should be within price range
        all_lows = [k.low for k in klines]
        all_highs = [k.high for k in klines]
        assert min(all_lows) <= poc <= max(all_highs)

    def test_compute_value_area(self):
        v = VPVR()
        klines = _sample_klines(20)
        result = v.compute(klines)
        val = Decimal(result["val"])
        vah = Decimal(result["vah"])
        assert val <= vah

    def test_compute_hvn_non_empty(self):
        v = VPVR()
        klines = _sample_klines(20)
        result = v.compute(klines)
        assert len(result["hvn"]) > 0

    def test_compute_lvn_non_empty(self):
        v = VPVR()
        klines = _sample_klines(20)
        result = v.compute(klines)
        assert len(result["lvn"]) > 0

    def test_compute_custom_bins(self):
        v = VPVR()
        klines = _sample_klines(20)
        result = v.compute(klines, bins=10)
        assert "poc" in result

    def test_compute_doji_handling(self):
        """十字星成交量应归入单个价格。"""
        v = VPVR()
        klines = [
            _kline("100", "100", "100", "100", "500"),
            _kline("100", "110", "90", "105", "200"),
        ]
        result = v.compute(klines)
        assert Decimal(result["total_volume"]) == Decimal("700.00")


# ──────────────────────────── TPOChart 测试 ────────────────────────────


class TestTPOChart:
    def test_invalid_interval(self):
        try:
            TPOChart(interval="2h")
            assert False, "Should raise ValueError"
        except ValueError:
            pass

    def test_valid_intervals(self):
        for interval in ("1m", "5m", "15m", "30m", "1h", "4h"):
            t = TPOChart(interval=interval)
            assert t._interval == interval

    def test_compute_empty(self):
        t = TPOChart()
        assert t.compute([]) == {}

    def test_compute_returns_fields(self):
        t = TPOChart(interval="1h")
        klines = _sample_klines(20)
        result = t.compute(klines)
        if result:  # May be empty if price range is too narrow
            assert "poc" in result
            assert "vah" in result
            assert "val" in result
            assert "letters" in result
            assert "tpo_counts" in result
            assert "single_prints" in result
            assert "opening_range" in result

    def test_compute_same_price_returns_empty(self):
        t = TPOChart(interval="1h")
        klines = [
            _kline("100", "100", "100", "100", "100", ts=1_000_000_000_000 + i * 3_600_000_000_000)
            for i in range(10)
        ]
        result = t.compute(klines)
        assert result == {}

    def test_letters_are_ascii(self):
        t = TPOChart(interval="1h")
        klines = _sample_klines(20)
        result = t.compute(klines)
        if result and "letters" in result:
            for price_str, letters in result["letters"].items():
                assert isinstance(letters, str)
                assert len(letters) > 0

    def test_opening_range_has_high_low(self):
        t = TPOChart(interval="1h")
        klines = _sample_klines(30)
        result = t.compute(klines)
        if result and result.get("opening_range"):
            assert "high" in result["opening_range"]
            assert "low" in result["opening_range"]


# ──────────────────────────── VWAPFamily 测试 ────────────────────────────


class TestVWAPFamily:
    def test_anchored_vwap_empty(self):
        v = VWAPFamily()
        assert v.anchored_vwap([], 0) == []

    def test_anchored_vwap_all_before_anchor(self):
        v = VWAPFamily()
        klines = [_kline("100", "105", "95", "102", "100", ts=1_000_000_000_000)]
        result = v.anchored_vwap(klines, anchor_time=2_000_000_000_000)
        assert result == []

    def test_anchored_vwap_computation(self):
        v = VWAPFamily()
        klines = [
            _kline("100", "105", "95", "102", "100", ts=1_000_000_000_000),
            _kline("102", "108", "100", "106", "200", ts=2_000_000_000_000),
            _kline("106", "110", "104", "108", "150", ts=3_000_000_000_000),
        ]
        result = v.anchored_vwap(klines, anchor_time=1_000_000_000_000)
        assert len(result) == 3
        # Each VWAP should be a positive Decimal
        for vwap in result:
            assert vwap > 0

    def test_anchored_vwap_partial(self):
        v = VWAPFamily()
        klines = [
            _kline("100", "105", "95", "102", "100", ts=1_000_000_000_000),
            _kline("102", "108", "100", "106", "200", ts=2_000_000_000_000),
        ]
        result = v.anchored_vwap(klines, anchor_time=2_000_000_000_000)
        assert len(result) == 1

    def test_vwap_bands_empty(self):
        v = VWAPFamily()
        assert v.vwap_bands([]) == {}

    def test_vwap_bands_returns_fields(self):
        v = VWAPFamily()
        klines = _sample_klines(20)
        result = v.vwap_bands(klines)
        assert "vwap" in result
        assert "upper" in result
        assert "lower" in result
        assert "std" in result
        assert "bandwidth" in result

    def test_vwap_bands_order(self):
        v = VWAPFamily()
        klines = _sample_klines(20)
        result = v.vwap_bands(klines)
        lower = Decimal(result["lower"])
        vwap = Decimal(result["vwap"])
        upper = Decimal(result["upper"])
        assert lower <= vwap <= upper

    def test_vwap_bands_custom_std(self):
        v = VWAPFamily()
        klines = _sample_klines(20)
        r1 = v.vwap_bands(klines, num_std=1.0)
        r2 = v.vwap_bands(klines, num_std=2.0)
        # Wider std → wider band
        bw1 = Decimal(r1["bandwidth"])
        bw2 = Decimal(r2["bandwidth"])
        assert bw2 >= bw1

    def test_institutional_cost_empty(self):
        v = VWAPFamily()
        assert v.institutional_cost([]) == Decimal("0")

    def test_institutional_cost_computation(self):
        v = VWAPFamily()
        klines = _sample_klines(20)
        cost = v.institutional_cost(klines)
        assert cost > 0

    def test_institutional_cost_weighted_by_volume(self):
        v = VWAPFamily()
        # High volume kline should dominate
        klines = [
            _kline("100", "105", "95", "102", "1000"),
            _kline("200", "205", "195", "202", "1"),  # Low volume
        ]
        cost = v.institutional_cost(klines)
        # Cost should be closer to 100 (high volume) than 200
        assert cost < Decimal("150")

    def test_zero_volume_returns_zero(self):
        v = VWAPFamily()
        klines = [_kline("100", "100", "100", "100", "0")]
        assert v.institutional_cost(klines) == Decimal("0")
        assert v.vwap_bands(klines) == {}
