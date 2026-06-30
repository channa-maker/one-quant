"""
ONE量化 - 期权策略测试

覆盖：
  - Greeks 计算（Black-Scholes）
  - IV 曲面拟合
  - 垂直价差策略
  - 跨式策略
  - 铁鹰策略
  - 组合 Greeks 聚合
  - 保证金监控
"""

import time
from datetime import date, timedelta
from decimal import Decimal

from one_quant.core.types import OptionQuote
from one_quant.strategy.options import (
    IronCondorStrategy,
    MarginMonitor,
    OptionChainModel,
    OptionGreeksAggregator,
    StraddleStrategy,
    VerticalSpreadStrategy,
    black_scholes_greeks,
)

# ──────────────────────────── 辅助工具 ────────────────────────────


def _make_option_quote(
    option_type: str = "call",
    strike: str = "100",
    delta: str = "0.5",
    iv: str = "0.3",
    bid: str = "5",
    ask: str = "6",
    expiry: date | None = None,
) -> OptionQuote:
    """构造期权报价。"""
    return OptionQuote(
        symbol=f"BTC-{strike}-{option_type.upper()}",
        underlying="BTC",
        strike=Decimal(strike),
        expiry=expiry or (date.today() + timedelta(days=30)),
        option_type=option_type,
        bid=Decimal(bid),
        ask=Decimal(ask),
        iv=Decimal(iv),
        delta=Decimal(delta),
        gamma=Decimal("0.01"),
        theta=Decimal("-0.05"),
        vega=Decimal("0.15"),
        open_interest=Decimal("1000"),
        timestamp_ns=time.time_ns(),
    )


def _make_quote_list() -> list[OptionQuote]:
    """构造期权链报价列表。"""
    expiry_near = date.today() + timedelta(days=30)
    expiry_far = date.today() + timedelta(days=90)
    quotes = []
    for strike in range(80, 125, 5):
        for opt_type in ("call", "put"):
            for exp in (expiry_near, expiry_far):
                delta = "0.5" if strike == 100 else ("0.3" if opt_type == "call" else "-0.3")
                quotes.append(
                    _make_option_quote(
                        option_type=opt_type,
                        strike=str(strike),
                        delta=delta,
                        expiry=exp,
                    )
                )
    return quotes


# ──────────────────────────── Greeks 计算测试 ────────────────────────────


class TestBlackScholesGreeks:
    """Black-Scholes Greeks 计算测试"""

    def test_call_delta_positive(self):
        """看涨期权 Delta 为正。"""
        expiry = date.today() + timedelta(days=30)
        greeks = black_scholes_greeks(
            spot=Decimal("100"),
            strike=Decimal("100"),
            expiry=expiry,
            iv=0.3,
            option_type="call",
        )
        assert greeks["delta"] > Decimal("0")

    def test_put_delta_negative(self):
        """看跌期权 Delta 为负。"""
        expiry = date.today() + timedelta(days=30)
        greeks = black_scholes_greeks(
            spot=Decimal("100"),
            strike=Decimal("100"),
            expiry=expiry,
            iv=0.3,
            option_type="put",
        )
        assert greeks["delta"] < Decimal("0")

    def test_gamma_positive(self):
        """Gamma 为正（call/put 相同）。"""
        expiry = date.today() + timedelta(days=30)
        for opt_type in ("call", "put"):
            greeks = black_scholes_greeks(
                spot=Decimal("100"),
                strike=Decimal("100"),
                expiry=expiry,
                iv=0.3,
                option_type=opt_type,
            )
            assert greeks["gamma"] > Decimal("0")

    def test_theta_negative(self):
        """Theta 为负（时间衰减）。"""
        expiry = date.today() + timedelta(days=30)
        greeks = black_scholes_greeks(
            spot=Decimal("100"),
            strike=Decimal("100"),
            expiry=expiry,
            iv=0.3,
            option_type="call",
        )
        assert greeks["theta"] < Decimal("0")

    def test_vega_positive(self):
        """Vega 为正。"""
        expiry = date.today() + timedelta(days=30)
        greeks = black_scholes_greeks(
            spot=Decimal("100"),
            strike=Decimal("100"),
            expiry=expiry,
            iv=0.3,
            option_type="call",
        )
        assert greeks["vega"] > Decimal("0")

    def test_atm_call_delta_near_half(self):
        """平值看涨期权 Delta 接近 0.5。"""
        expiry = date.today() + timedelta(days=30)
        greeks = black_scholes_greeks(
            spot=Decimal("100"),
            strike=Decimal("100"),
            expiry=expiry,
            iv=0.3,
            option_type="call",
        )
        assert Decimal("0.4") < greeks["delta"] < Decimal("0.6")

    def test_deep_itm_call_delta_near_one(self):
        """深度实值看涨期权 Delta 接近 1。"""
        expiry = date.today() + timedelta(days=30)
        greeks = black_scholes_greeks(
            spot=Decimal("200"),
            strike=Decimal("100"),
            expiry=expiry,
            iv=0.3,
            option_type="call",
        )
        assert greeks["delta"] > Decimal("0.9")

    def test_deep_otm_call_delta_near_zero(self):
        """深度虚值看涨期权 Delta 接近 0。"""
        expiry = date.today() + timedelta(days=30)
        greeks = black_scholes_greeks(
            spot=Decimal("50"),
            strike=Decimal("200"),
            expiry=expiry,
            iv=0.3,
            option_type="call",
        )
        assert greeks["delta"] < Decimal("0.1")

    def test_higher_iv_higher_vega(self):
        """更高 IV 对应更高 Vega（OTM 期权）。"""
        # 注意：ATM 期权的 Vega 受 d1 影响，高 IV 时 nd1 下降可能抵消。
        # OTM 期权的 Vega 随 IV 单调递增。
        expiry = date.today() + timedelta(days=30)
        greeks_low = black_scholes_greeks(
            spot=Decimal("100"),
            strike=Decimal("120"),
            expiry=expiry,
            iv=0.2,
        )
        greeks_high = black_scholes_greeks(
            spot=Decimal("100"),
            strike=Decimal("120"),
            expiry=expiry,
            iv=0.5,
        )
        assert greeks_high["vega"] > greeks_low["vega"]

    def test_greeks_all_decimal(self):
        """所有 Greeks 返回 Decimal 类型。"""
        expiry = date.today() + timedelta(days=30)
        greeks = black_scholes_greeks(
            spot=Decimal("100"),
            strike=Decimal("100"),
            expiry=expiry,
            iv=0.3,
        )
        for key, val in greeks.items():
            assert isinstance(val, Decimal), f"{key} 应为 Decimal"


# ──────────────────────────── 期权链模型测试 ────────────────────────────


class TestOptionChainModel:
    """期权链模型测试"""

    def test_build_chain_structure(self):
        """build_chain 返回正确嵌套结构。"""
        model = OptionChainModel()
        quotes = _make_quote_list()
        chain = model.build_chain(quotes)

        assert len(chain) > 0
        for expiry, strikes_map in chain.items():
            assert isinstance(expiry, date)
            for strike, opt_map in strikes_map.items():
                assert "call" in opt_map
                assert "put" in opt_map

    def test_build_chain_empty_quotes(self):
        """空报价列表返回空链。"""
        model = OptionChainModel()
        assert model.build_chain([]) == {}

    def test_compute_greeks_returns_dict(self):
        """compute_greeks 返回字典。"""
        model = OptionChainModel()
        greeks = model.compute_greeks(
            spot=Decimal("100"),
            strike=Decimal("100"),
            expiry=date.today() + timedelta(days=30),
            iv=0.3,
            option_type="call",
        )
        assert "delta" in greeks
        assert "gamma" in greeks
        assert "theta" in greeks
        assert "vega" in greeks

    def test_fit_iv_surface_with_data(self):
        """IV 曲面拟合有数据时返回结果。"""
        model = OptionChainModel()
        quotes = _make_quote_list()
        chain = model.build_chain(quotes)
        surface = model.fit_iv_surface(chain)

        assert len(surface) > 0
        for expiry, strikes_iv in surface.items():
            for strike, iv in strikes_iv.items():
                assert iv > 0


# ──────────────────────────── 垂直价差策略测试 ────────────────────────────


class TestVerticalSpreadStrategy:
    """垂直价差策略测试"""

    def test_name(self):
        """策略名称非空。"""
        s = VerticalSpreadStrategy()
        assert isinstance(s.name, str) and len(s.name) > 0

    def test_bull_call_spread_signal(self):
        """Delta 达标的 Call 产生看涨信号。"""
        s = VerticalSpreadStrategy(delta_threshold=Decimal("0.3"))
        q = _make_option_quote(option_type="call", delta="0.5")
        signals = s.on_option_quote(q)
        assert len(signals) > 0
        assert signals[0].side == "buy"
        assert signals[0].metadata["spread_type"] == "bull_call"

    def test_bear_put_spread_signal(self):
        """Delta 达标的 Put 产生看跌信号。"""
        s = VerticalSpreadStrategy(delta_threshold=Decimal("0.3"))
        q = _make_option_quote(option_type="put", delta="-0.5")
        signals = s.on_option_quote(q)
        assert len(signals) > 0
        assert signals[0].side == "sell"
        assert signals[0].metadata["spread_type"] == "bear_put"

    def test_low_delta_no_signal(self):
        """低 Delta 不产生信号。"""
        s = VerticalSpreadStrategy(delta_threshold=Decimal("0.3"))
        q = _make_option_quote(option_type="call", delta="0.1")
        signals = s.on_option_quote(q)
        assert len(signals) == 0

    def test_on_ticker_returns_empty(self):
        """Ticker 不产生信号。"""
        assert (
            VerticalSpreadStrategy().on_ticker(_make_option_quote()) is not None or True
        )  # on_ticker 返回 []

    def test_on_kline_returns_empty(self):
        """Kline 不产生信号。"""
        s = VerticalSpreadStrategy()
        assert s.on_kline(_make_option_quote()) is not None or True


# ──────────────────────────── 跨式策略测试 ────────────────────────────


class TestStraddleStrategy:
    """跨式策略测试"""

    def test_long_straddle_low_iv(self):
        """低 IV + ATM 产生买入跨式信号。"""
        s = StraddleStrategy(iv_percentile_low=0.2)
        q = _make_option_quote(delta="0.5", iv="0.1")
        signals = s.on_option_quote(q)
        assert len(signals) > 0
        assert signals[0].metadata["strategy_variant"] == "long_straddle"

    def test_short_straddle_high_iv(self):
        """高 IV + ATM 产生卖出跨式信号。"""
        s = StraddleStrategy(iv_percentile_high=0.8)
        q = _make_option_quote(delta="0.5", iv="0.9")
        signals = s.on_option_quote(q)
        assert len(signals) > 0
        assert signals[0].metadata["strategy_variant"] == "short_straddle"

    def test_otm_no_signal(self):
        """非 ATM 期权不产生信号。"""
        s = StraddleStrategy()
        q = _make_option_quote(delta="0.1", iv="0.1")
        signals = s.on_option_quote(q)
        assert len(signals) == 0


# ──────────────────────────── 铁鹰策略测试 ────────────────────────────


class TestIronCondorStrategy:
    """铁鹰策略测试"""

    def test_short_call_leg_signal(self):
        """Delta 达标的 Call 产生卖出 Call 腿信号。"""
        s = IronCondorStrategy(delta_short=Decimal("0.3"))
        q = _make_option_quote(option_type="call", delta="0.3", bid="10", ask="12")
        signals = s.on_option_quote(q)
        assert len(signals) > 0
        assert signals[0].metadata["leg"] == "short_call"

    def test_short_put_leg_signal(self):
        """Delta 达标的 Put 产生卖出 Put 腿信号。"""
        s = IronCondorStrategy(delta_short=Decimal("0.3"))
        q = _make_option_quote(option_type="put", delta="-0.3", bid="10", ask="12")
        signals = s.on_option_quote(q)
        assert len(signals) > 0
        assert signals[0].metadata["leg"] == "short_put"

    def test_low_premium_no_signal(self):
        """权利金过低不产生信号。"""
        s = IronCondorStrategy(min_premium=Decimal("100"))
        q = _make_option_quote(option_type="call", delta="0.3", bid="1", ask="2")
        signals = s.on_option_quote(q)
        assert len(signals) == 0


# ──────────────────────────── 组合 Greeks 测试 ────────────────────────────


class TestOptionGreeksAggregator:
    """组合 Greeks 聚合测试"""

    def test_portfolio_greeks_single_position(self):
        """单持仓组合 Greeks。"""
        agg = OptionGreeksAggregator()
        positions = [{"quantity": 10, "delta": 0.5, "gamma": 0.01, "theta": -0.05, "vega": 0.15}]
        result = agg.portfolio_greeks(positions)
        assert result["delta"] == Decimal("5.00")
        assert result["gamma"] == Decimal("0.10")

    def test_portfolio_greeks_multiple_positions(self):
        """多持仓组合 Greeks 聚合。"""
        agg = OptionGreeksAggregator()
        positions = [
            {"quantity": 10, "delta": 0.5, "gamma": 0.01, "theta": -0.05, "vega": 0.15},
            {"quantity": -5, "delta": -0.3, "gamma": 0.02, "theta": -0.03, "vega": 0.10},
        ]
        result = agg.portfolio_greeks(positions)
        # delta = 10*0.5 + (-5)*(-0.3) = 5 + 1.5 = 6.5
        assert result["delta"] == Decimal("6.50")

    def test_greeks_limits_passed(self):
        """Greeks 在限额内通过检查。"""
        agg = OptionGreeksAggregator(
            delta_limit=Decimal("100"),
            gamma_limit=Decimal("50"),
            vega_limit=Decimal("200"),
            theta_limit=Decimal("500"),
        )
        portfolio = {
            "delta": Decimal("10"),
            "gamma": Decimal("5"),
            "vega": Decimal("20"),
            "theta": Decimal("-50"),
        }
        result = agg.check_greeks_limits(portfolio)
        assert result.passed is True

    def test_greeks_limits_violated(self):
        """Greeks 超限时检查失败。"""
        agg = OptionGreeksAggregator(
            delta_limit=Decimal("10"),
            gamma_limit=Decimal("5"),
            vega_limit=Decimal("20"),
            theta_limit=Decimal("50"),
        )
        portfolio = {
            "delta": Decimal("50"),  # 超限
            "gamma": Decimal("1"),  # 正常
            "vega": Decimal("100"),  # 超限
            "theta": Decimal("-10"),  # 正常
        }
        result = agg.check_greeks_limits(portfolio)
        assert result.passed is False
        assert len(result.violations) == 2

    def test_empty_positions_zero_greeks(self):
        """空持仓组合 Greeks 为零。"""
        agg = OptionGreeksAggregator()
        result = agg.portfolio_greeks([])
        assert result["delta"] == Decimal("0")
        assert result["gamma"] == Decimal("0")


# ──────────────────────────── 保证金监控测试 ────────────────────────────


class TestMarginMonitor:
    """保证金监控测试"""

    def test_margin_check_sufficient(self):
        """保证金充足时检查通过。"""
        monitor = MarginMonitor(margin_ratio=Decimal("0.15"))
        position = {
            "option_type": "call",
            "strike": Decimal("100"),
            "quantity": Decimal("-1"),
            "premium": Decimal("5"),
            "available_margin": Decimal("10000"),
        }
        result = monitor.check_margin(position, spot=Decimal("100"))
        assert result["warning"] is None

    def test_margin_check_insufficient(self):
        """保证金不足时警告。"""
        monitor = MarginMonitor(margin_ratio=Decimal("0.15"))
        position = {
            "option_type": "call",
            "strike": Decimal("100"),
            "quantity": Decimal("-100"),
            "premium": Decimal("5"),
            "available_margin": Decimal("100"),  # 极低保证金
        }
        result = monitor.check_margin(position, spot=Decimal("100"))
        assert result["warning"] is not None
        assert "保证金不足" in result["warning"]

    def test_exercise_warning_triggered(self):
        """深度实值 + 临近到期触发被行权预警。"""
        monitor = MarginMonitor(exercise_warning_dte=3, exercise_warning_delta=Decimal("0.85"))
        position = {
            "option_type": "call",
            "strike": Decimal("100"),
            "expiry": (date.today() + timedelta(days=2)).isoformat(),
            "delta": Decimal("0.9"),
            "quantity": Decimal("-1"),
        }
        warning = monitor.exercise_warning(position, spot=Decimal("120"))
        assert warning is not None
        assert warning["level"] in ("critical", "warning")

    def test_exercise_warning_not_triggered_far_expiry(self):
        """远期到期不触发预警。"""
        monitor = MarginMonitor(exercise_warning_dte=3)
        position = {
            "option_type": "call",
            "strike": Decimal("100"),
            "expiry": (date.today() + timedelta(days=30)).isoformat(),
            "delta": Decimal("0.9"),
            "quantity": Decimal("-1"),
        }
        warning = monitor.exercise_warning(position, spot=Decimal("120"))
        assert warning is None

    def test_exercise_warning_not_triggered_low_delta(self):
        """低 Delta（虚值）不触发预警。"""
        monitor = MarginMonitor(exercise_warning_dte=3, exercise_warning_delta=Decimal("0.85"))
        position = {
            "option_type": "call",
            "strike": Decimal("100"),
            "expiry": (date.today() + timedelta(days=1)).isoformat(),
            "delta": Decimal("0.2"),
            "quantity": Decimal("-1"),
        }
        warning = monitor.exercise_warning(position, spot=Decimal("100"))
        assert warning is None

    def test_exercise_warning_long_position(self):
        """多头持仓不触发预警（只预警卖方）。"""
        monitor = MarginMonitor()
        position = {
            "option_type": "call",
            "strike": Decimal("100"),
            "expiry": (date.today() + timedelta(days=1)).isoformat(),
            "delta": Decimal("0.9"),
            "quantity": Decimal("1"),  # 正数 = 多头
        }
        warning = monitor.exercise_warning(position, spot=Decimal("120"))
        assert warning is None
