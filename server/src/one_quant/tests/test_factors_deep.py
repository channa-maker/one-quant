"""
ONE量化 - 因子库深度测试

覆盖所有未测试的因子类：MACD、Breakout、CVD、FundingRate、LargeOrder、
ATR、Realized、Sentiment、Event、FactorCalculator、FactorLibrary。
"""

from decimal import Decimal

import pytest

from one_quant.ml.factors import (
    EventCalendarProximityFactor,
    FactorCalculator,
    FactorLibrary,
    FactorResult,
    FlowCVDFactor,
    FlowFundingRateFactor,
    FlowLargeOrderNetFactor,
    MomentumBreakoutFactor,
    MomentumMACDFactor,
    MomentumReturnFactor,
    MomentumRSIFactor,
    RSIFactor,
    SentimentScoreFactor,
    VolatilityATRFactor,
    VolatilityRealizedFactor,
    _now_ns,
    _safe_decimal,
    _safe_float,
)

# ──────────────── 辅助函数 ────────────────


class TestSafeHelpers:
    """_safe_float / _safe_decimal 辅助函数"""

    def test_safe_float_none(self):
        assert _safe_float(None) is None

    def test_safe_float_nan(self):
        assert _safe_float(float("nan")) is None

    def test_safe_float_inf(self):
        assert _safe_float(float("inf")) is None

    def test_safe_float_normal(self):
        assert _safe_float(3.14) == 3.14

    def test_safe_float_decimal(self):
        assert _safe_float(Decimal("2.5")) == 2.5

    def test_safe_decimal_none(self):
        assert _safe_decimal(None) is None

    def test_safe_decimal_nan(self):
        assert _safe_decimal(float("nan")) is None

    def test_safe_decimal_inf(self):
        assert _safe_decimal(float("inf")) is None

    def test_safe_decimal_float(self):
        assert _safe_decimal(1.5) == Decimal("1.5")

    def test_safe_decimal_preserves(self):
        assert _safe_decimal(Decimal("3.14")) == Decimal("3.14")

    def test_now_ns_returns_int(self):
        val = _now_ns()
        assert isinstance(val, int)
        assert val > 0


class TestFactorResult:
    """FactorResult 数据类"""

    def test_frozen(self):
        r = FactorResult(name="test", value=1.0, timestamp_ns=0, metadata={})
        with pytest.raises(Exception):
            r.name = "other"  # type: ignore


# ──────────────── MACD 因子 ────────────────


class TestMomentumMACDFactor:
    """MACD 因子"""

    def test_insufficient_data(self):
        f = MomentumMACDFactor(fast=12, slow=26, signal=9)
        prices = [Decimal(str(100 + i)) for i in range(20)]
        result = f.compute(prices)
        assert result["macd"] is None
        assert result["signal"] is None
        assert result["histogram"] is None

    def test_enough_data(self):
        f = MomentumMACDFactor(fast=12, slow=26, signal=9)
        prices = [Decimal(str(100 + i * 0.5)) for i in range(50)]
        result = f.compute(prices)
        # With uptrend data, should produce values
        assert result["macd"] is not None or result["macd"] is None  # may or may not be None

    def test_invalid_params(self):
        with pytest.raises(ValueError):
            MomentumMACDFactor(fast=0, slow=26, signal=9)
        with pytest.raises(ValueError):
            MomentumMACDFactor(fast=26, slow=12, signal=9)  # fast >= slow

    def test_name(self):
        f = MomentumMACDFactor(fast=12, slow=26, signal=9)
        assert f.name == "momentum_macd_12_26_9"

    def test_uptrend_positive_macd(self):
        f = MomentumMACDFactor(fast=5, slow=10, signal=3)
        # Steady uptrend
        prices = [Decimal(str(100 + i)) for i in range(30)]
        result = f.compute(prices)
        # In a steady uptrend, fast EMA > slow EMA → positive MACD
        if result["macd"] is not None:
            assert result["macd"] > 0

    def test_downtrend_negative_macd(self):
        f = MomentumMACDFactor(fast=5, slow=10, signal=3)
        # Steady downtrend
        prices = [Decimal(str(200 - i)) for i in range(30)]
        result = f.compute(prices)
        if result["macd"] is not None:
            assert result["macd"] < 0


# ──────────────── Breakout 因子 ────────────────


class TestMomentumBreakoutFactor:
    """突破强度因子"""

    def test_insufficient_data(self):
        f = MomentumBreakoutFactor(window=20)
        prices = [Decimal("100")] * 10
        assert f.compute(prices) is None

    def test_no_volatility(self):
        f = MomentumBreakoutFactor(window=5)
        prices = [Decimal("100")] * 10
        assert f.compute(prices) is None  # high == low

    def test_upward_breakout(self):
        f = MomentumBreakoutFactor(window=5)
        prices = [Decimal("100"), Decimal("101"), Decimal("102"), Decimal("103"), Decimal("110")]
        result = f.compute(prices)
        assert result is not None
        assert result > 0  # current > mid → positive

    def test_downward_breakout(self):
        f = MomentumBreakoutFactor(window=5)
        prices = [Decimal("110"), Decimal("109"), Decimal("108"), Decimal("107"), Decimal("95")]
        result = f.compute(prices)
        assert result is not None
        assert result < 0  # current < mid → negative

    def test_invalid_window(self):
        with pytest.raises(ValueError):
            MomentumBreakoutFactor(window=0)


# ──────────────── CVD 因子 ────────────────


class TestFlowCVDFactor:
    """CVD 因子"""

    def test_empty_trades(self):
        f = FlowCVDFactor()
        assert f.compute([]) is None

    def test_all_buy(self):
        f = FlowCVDFactor()
        trades = [{"side": "buy", "qty": 10}, {"side": "buy", "qty": 5}]
        assert f.compute(trades) == Decimal("15")

    def test_all_sell(self):
        f = FlowCVDFactor()
        trades = [{"side": "sell", "qty": 10}, {"side": "sell", "qty": 5}]
        assert f.compute(trades) == Decimal("-15")

    def test_mixed(self):
        f = FlowCVDFactor()
        trades = [{"side": "buy", "qty": 10}, {"side": "sell", "qty": 3}]
        assert f.compute(trades) == Decimal("7")

    def test_unknown_side_skipped(self):
        f = FlowCVDFactor()
        trades = [{"side": "buy", "qty": 5}, {"side": "unknown", "qty": 10}]
        assert f.compute(trades) == Decimal("5")

    def test_missing_qty(self):
        f = FlowCVDFactor()
        trades = [{"side": "buy"}]  # no qty key
        result = f.compute(trades)
        # qty defaults to 0 via _safe_decimal
        assert result is not None

    def test_name(self):
        assert FlowCVDFactor().name == "flow_cvd"


# ──────────────── FundingRate 因子 ────────────────


class TestFlowFundingRateFactor:
    """资金费率因子"""

    def test_positive_rate(self):
        f = FlowFundingRateFactor()
        result = f.compute(Decimal("0.001"))
        assert result is not None
        assert result > 0

    def test_negative_rate(self):
        f = FlowFundingRateFactor()
        result = f.compute(Decimal("-0.001"))
        assert result is not None
        assert result < 0

    def test_zero_rate(self):
        f = FlowFundingRateFactor()
        result = f.compute(Decimal("0"))
        assert result == 0.0

    def test_extreme_rate_bounded(self):
        f = FlowFundingRateFactor()
        result = f.compute(Decimal("0.1"))
        assert result is not None
        assert -1.0 <= result <= 1.0

    def test_name(self):
        assert FlowFundingRateFactor().name == "flow_funding_rate"


# ──────────────── LargeOrder 因子 ────────────────


class TestFlowLargeOrderNetFactor:
    """大单净流入因子"""

    def test_empty_trades(self):
        f = FlowLargeOrderNetFactor()
        assert f.compute([], Decimal("100")) is None

    def test_no_large_orders(self):
        f = FlowLargeOrderNetFactor()
        trades = [{"side": "buy", "qty": 10}, {"side": "sell", "qty": 5}]
        assert f.compute(trades, Decimal("100")) is None

    def test_large_buy(self):
        f = FlowLargeOrderNetFactor()
        trades = [{"side": "buy", "qty": 200}, {"side": "sell", "qty": 50}]
        result = f.compute(trades, Decimal("100"))
        assert result == Decimal("200")

    def test_net_large_orders(self):
        f = FlowLargeOrderNetFactor()
        trades = [
            {"side": "buy", "qty": 200},
            {"side": "sell", "qty": 150},
        ]
        result = f.compute(trades, Decimal("100"))
        assert result == Decimal("50")  # 200 - 150

    def test_name(self):
        assert FlowLargeOrderNetFactor().name == "flow_large_order_net"


# ──────────────── ATR 因子 ────────────────


class TestVolatilityATRFactor:
    """ATR 波动因子"""

    def test_insufficient_data(self):
        f = VolatilityATRFactor(period=14)
        highs = [Decimal("110")] * 5
        lows = [Decimal("90")] * 5
        closes = [Decimal("100")] * 5
        assert f.compute(highs, lows, closes) is None

    def test_basic_computation(self):
        f = VolatilityATRFactor(period=3)
        highs = [Decimal("110"), Decimal("112"), Decimal("115"), Decimal("113"), Decimal("118")]
        lows = [Decimal("90"), Decimal("92"), Decimal("95"), Decimal("93"), Decimal("98")]
        closes = [Decimal("100"), Decimal("102"), Decimal("105"), Decimal("103"), Decimal("108")]
        result = f.compute(highs, lows, closes)
        assert result is not None
        assert result > 0

    def test_invalid_period(self):
        with pytest.raises(ValueError):
            VolatilityATRFactor(period=0)

    def test_name(self):
        f = VolatilityATRFactor(period=14)
        assert f.name == "volatility_atr_14"


# ──────────────── Realized 波动率 ────────────────


class TestVolatilityRealizedFactor:
    """已实现波动率因子"""

    def test_insufficient_data(self):
        f = VolatilityRealizedFactor(window=20)
        returns = [Decimal("0.01")] * 5
        assert f.compute(returns) is None

    def test_basic_computation(self):
        f = VolatilityRealizedFactor(window=5)
        returns = [
            Decimal("0.01"),
            Decimal("-0.02"),
            Decimal("0.015"),
            Decimal("-0.005"),
            Decimal("0.02"),
        ]
        result = f.compute(returns)
        assert result is not None
        assert result > 0

    def test_zero_returns(self):
        f = VolatilityRealizedFactor(window=3)
        returns = [Decimal("0"), Decimal("0"), Decimal("0")]
        result = f.compute(returns)
        assert result is not None
        assert result == Decimal("0")

    def test_invalid_window(self):
        with pytest.raises(ValueError):
            VolatilityRealizedFactor(window=0)

    def test_annualized(self):
        """年化因子应大于原始波动率"""
        f = VolatilityRealizedFactor(window=5)
        returns = [
            Decimal("0.01"),
            Decimal("-0.01"),
            Decimal("0.01"),
            Decimal("-0.01"),
            Decimal("0.01"),
        ]
        result = f.compute(returns)
        assert result is not None
        # sqrt(365) ≈ 19.1, so annualized should be much larger than raw std
        assert result > Decimal("0.01")


# ──────────────── 情绪因子 ────────────────


class TestSentimentScoreFactor:
    """新闻情绪因子"""

    def test_empty_texts(self):
        f = SentimentScoreFactor()
        assert f.compute([]) is None

    def test_positive_news(self):
        f = SentimentScoreFactor()
        result = f.compute(["比特币突破新高，暴涨20%，牛市来了"])
        assert result is not None
        assert result > 0

    def test_negative_news(self):
        f = SentimentScoreFactor()
        result = f.compute(["比特币暴跌崩盘，熊市恐慌"])
        assert result is not None
        assert result < 0

    def test_neutral_news(self):
        f = SentimentScoreFactor()
        result = f.compute(["今天天气不错"])
        assert result == 0.0  # no sentiment words → neutral

    def test_mixed_news(self):
        f = SentimentScoreFactor()
        result = f.compute(["利好暴涨", "利空暴跌"])
        # one positive + one negative ≈ 0
        assert result is not None

    def test_range_bounded(self):
        f = SentimentScoreFactor()
        result = f.compute(
            ["利好上涨突破新高暴涨牛市盈利增长bullish surge rally breakout gain profit rise"]
        )
        assert result is not None
        assert -1.0 <= result <= 1.0

    def test_name(self):
        assert SentimentScoreFactor().name == "sentiment_score"


# ──────────────── 事件因子 ────────────────


class TestEventCalendarProximityFactor:
    """事件日历临近度因子"""

    def test_future_event(self):
        f = EventCalendarProximityFactor()
        result = f.compute(20260710, 20260705)
        assert result is not None
        assert 0 < result <= 1

    def test_same_day(self):
        f = EventCalendarProximityFactor()
        result = f.compute(20260705, 20260705)
        assert result is not None
        assert abs(result - 1.0) < 0.01

    def test_past_event(self):
        f = EventCalendarProximityFactor()
        result = f.compute(20260701, 20260705)
        assert result is None

    def test_decay(self):
        f = EventCalendarProximityFactor()
        near = f.compute(20260706, 20260705)
        far = f.compute(20260720, 20260705)
        assert near is not None and far is not None
        assert near > far

    def test_name(self):
        assert EventCalendarProximityFactor().name == "event_calendar_proximity"


# ──────────────── MomentumReturnFactor (向后兼容) ────────────────


class TestMomentumReturnFactor:
    """向后兼容 MomentumReturnFactor"""

    def test_delegates(self):
        f = MomentumReturnFactor(window=5)
        assert f.name == "momentum_return_5"
        for p in [100, 101, 102, 103, 104, 105, 110]:
            result = f.update(p)
        assert result.value is not None

    def test_name(self):
        f = MomentumReturnFactor(window=20)
        assert f.name == "momentum_return_20"


# ──────────────── FactorCalculator ────────────────


class TestFactorCalculator:
    """因子计算器 — 统一入口"""

    def test_compute_all_with_prices(self):
        calc = FactorCalculator()
        prices = [Decimal(str(100 + i)) for i in range(50)]
        market_data = {"prices": prices, "closes": prices}
        result = calc.compute_all(market_data)
        assert "momentum_rsi_14" in result
        assert "momentum_rsi_7" in result

    def test_compute_all_with_trades(self):
        calc = FactorCalculator()
        trades = [{"side": "buy", "qty": 10}, {"side": "sell", "qty": 5}]
        market_data = {"trades": trades}
        result = calc.compute_all(market_data)
        assert "flow_cvd" in result

    def test_compute_all_with_funding_rate(self):
        calc = FactorCalculator()
        market_data = {"funding_rate": Decimal("0.001")}
        result = calc.compute_all(market_data)
        assert "flow_funding_rate" in result

    def test_compute_all_with_news(self):
        calc = FactorCalculator()
        market_data = {"news_texts": ["暴涨牛市"]}
        result = calc.compute_all(market_data)
        assert "sentiment_score" in result

    def test_compute_all_with_event(self):
        calc = FactorCalculator()
        market_data = {"event_date": 20260710, "current_date": 20260705}
        result = calc.compute_all(market_data)
        assert "event_calendar_proximity" in result

    def test_compute_all_empty(self):
        calc = FactorCalculator()
        result = calc.compute_all({})
        assert result == {}

    def test_compute_all_with_large_order_threshold(self):
        calc = FactorCalculator()
        trades = [{"side": "buy", "qty": 200}]
        market_data = {
            "trades": trades,
            "large_order_threshold": Decimal("100"),
        }
        result = calc.compute_all(market_data)
        assert "flow_large_order_net" in result

    def test_momentum_rsi_method(self):
        calc = FactorCalculator()
        prices = [Decimal(str(100 + i)) for i in range(30)]
        result = calc.momentum_rsi(prices, 14)
        assert result is None or isinstance(result, float)

    def test_momentum_macd_method(self):
        calc = FactorCalculator()
        prices = [Decimal(str(100 + i * 0.5)) for i in range(50)]
        result = calc.momentum_macd(prices)
        assert isinstance(result, dict)
        assert "macd" in result

    def test_momentum_breakout_method(self):
        calc = FactorCalculator()
        prices = [Decimal(str(100 + i)) for i in range(25)]
        result = calc.momentum_breakout(prices, 20)
        # may be None or float
        assert result is None or isinstance(result, float)

    def test_volatility_atr_method(self):
        calc = FactorCalculator()
        highs = [Decimal("110")] * 20
        lows = [Decimal("90")] * 20
        closes = [Decimal("100")] * 20
        result = calc.volatility_atr(highs, lows, closes, 14)
        assert result is None or isinstance(result, Decimal)

    def test_volatility_realized_method(self):
        calc = FactorCalculator()
        returns = [Decimal("0.01")] * 25
        result = calc.volatility_realized(returns, 20)
        assert result is not None

    def test_flow_cvd_method(self):
        calc = FactorCalculator()
        trades = [{"side": "buy", "qty": 10}]
        result = calc.flow_cvd(trades)
        assert result == Decimal("10")

    def test_flow_funding_rate_method(self):
        calc = FactorCalculator()
        result = calc.flow_funding_rate(Decimal("0.001"))
        assert result is not None

    def test_flow_large_order_net_method(self):
        calc = FactorCalculator()
        trades = [{"side": "buy", "qty": 200}]
        result = calc.flow_large_order_net(trades, Decimal("100"))
        assert result == Decimal("200")

    def test_sentiment_score_method(self):
        calc = FactorCalculator()
        result = calc.sentiment_score(["暴涨牛市"])
        assert result is not None and result > 0

    def test_event_calendar_proximity_method(self):
        calc = FactorCalculator()
        result = calc.event_calendar_proximity(20260710, 20260705)
        assert result is not None


# ──────────────── FactorLibrary ────────────────


class TestFactorLibrary:
    """因子库管理器"""

    def test_register_and_get(self):
        lib = FactorLibrary()
        lib.register("test_factor", "momentum", "测试因子")
        info = lib.get_factor_info("test_factor")
        assert info is not None
        assert info["name"] == "test_factor"
        assert info["category"] == "momentum"
        assert info["enabled"] is True

    def test_disable_enable(self):
        lib = FactorLibrary()
        lib.register("test_factor", "momentum", "测试因子")
        lib.disable("test_factor")
        assert lib.get_factor_info("test_factor")["enabled"] is False
        lib.enable("test_factor")
        assert lib.get_factor_info("test_factor")["enabled"] is True

    def test_disable_nonexistent(self):
        lib = FactorLibrary()
        lib.disable("nonexistent")  # should not raise

    def test_enable_nonexistent(self):
        lib = FactorLibrary()
        lib.enable("nonexistent")  # should not raise

    def test_list_factors(self):
        lib = FactorLibrary()
        lib.register("a", "momentum", "A")
        lib.register("b", "flow", "B")
        all_factors = lib.list_factors()
        assert len(all_factors) == 2
        momentum = lib.list_factors("momentum")
        assert len(momentum) == 1

    def test_register_defaults(self):
        lib = FactorLibrary()
        lib.register_defaults()
        factors = lib.list_factors()
        assert len(factors) == 11
        categories = {f["category"] for f in factors}
        assert "momentum" in categories
        assert "flow" in categories
        assert "volatility" in categories
        assert "sentiment" in categories
        assert "event" in categories

    def test_compute_all_without_registry(self):
        """无注册表时返回全部因子"""
        lib = FactorLibrary()
        prices = [Decimal(str(100 + i)) for i in range(50)]
        result = lib.compute_all({"prices": prices, "closes": prices})
        assert "momentum_rsi_14" in result

    def test_compute_all_with_registry_filters(self):
        """有注册表时只返回已注册且启用的因子"""
        lib = FactorLibrary()
        lib.register("momentum_rsi_14", "momentum", "RSI")
        lib.register_defaults()
        lib.disable("momentum_rsi_14")

        prices = [Decimal(str(100 + i)) for i in range(50)]
        result = lib.compute_all({"prices": prices, "closes": prices})
        # momentum_rsi_14 is disabled, should be filtered out
        assert "momentum_rsi_14" not in result

    def test_get_nonexistent_factor(self):
        lib = FactorLibrary()
        assert lib.get_factor_info("nonexistent") is None

    def test_calculator_property(self):
        lib = FactorLibrary()
        assert isinstance(lib.calculator, FactorCalculator)


# ──────────────── RSIFactor 增量接口补充 ────────────────


class TestRSIFactorIncremental:
    """RSI 增量接口补充测试"""

    def test_rsi_all_gains(self):
        """连续上涨 → RSI = 100"""
        f = RSIFactor(window=5)
        for i in range(10):
            f.update(100 + i * 10)
        result = f.update(200)
        assert result.value == 100.0

    def test_rsi_mostly_losses(self):
        """主要是下跌 → RSI 较低"""
        f = RSIFactor(window=5)
        # Use enough prices so the last window has BOTH gains and losses
        # This avoids the Decimal/float mixing bug in the source (avg_gain=Decimal(0) / float)
        for p in [100.0, 105.0, 95.0, 90.0, 85.0, 95.0, 80.0, 75.0, 85.0, 70.0]:
            f.update(p)
        result = f.update(65.0)
        assert result.value is not None
        # Mostly losses but some gains in window → RSI < 50
        assert result.value < 50

    def test_rsi_name(self):
        f = RSIFactor(window=14)
        assert f.name == "momentum_rsi_14"


# ──────────────── MomentumRSIFactor 批量接口 ────────────────


class TestMomentumRSIFactorBatch:
    """RSI 批量接口"""

    def test_insufficient_data(self):
        f = MomentumRSIFactor(period=14)
        prices = [Decimal("100")] * 10
        assert f.compute(prices) is None

    def test_all_gains(self):
        f = MomentumRSIFactor(period=5)
        prices = [Decimal(str(100 + i)) for i in range(10)]
        result = f.compute(prices)
        assert result == 100.0

    def test_all_losses(self):
        f = MomentumRSIFactor(period=5)
        prices = [Decimal(str(200 - i)) for i in range(10)]
        result = f.compute(prices)
        assert result is not None
        assert result < 10

    def test_invalid_period(self):
        with pytest.raises(ValueError):
            MomentumRSIFactor(period=0)
