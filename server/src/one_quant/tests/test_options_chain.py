"""期权链模型测试 — OptionChainModel (chain.py) 补充覆盖"""

from __future__ import annotations

import time
from datetime import date, timedelta
from decimal import Decimal

from one_quant.core.types import OptionQuote
from one_quant.strategy.options.chain import OptionChainModel


def _q(
    strike: str = "100",
    option_type: str = "call",
    iv: str = "0.30",
    expiry: date | None = None,
) -> OptionQuote:
    return OptionQuote(
        symbol=f"BTC-{strike}-{option_type.upper()}",
        underlying="BTC",
        strike=Decimal(strike),
        expiry=expiry or (date.today() + timedelta(days=30)),
        option_type=option_type,
        bid=Decimal("5"),
        ask=Decimal("6"),
        iv=Decimal(iv),
        delta=Decimal("0.5"),
        gamma=Decimal("0.01"),
        theta=Decimal("-0.05"),
        vega=Decimal("0.15"),
        open_interest=Decimal("1000"),
        timestamp_ns=time.time_ns(),
    )


class TestOptionChainModelBuildChain:
    def test_single_quote(self):
        m = OptionChainModel()
        chain = m.build_chain([_q("100", "call")])
        exp = date.today() + timedelta(days=30)
        assert exp in chain
        assert Decimal("100") in chain[exp]
        assert chain[exp][Decimal("100")]["call"] is not None
        assert chain[exp][Decimal("100")]["put"] is None

    def test_call_and_put_same_strike(self):
        m = OptionChainModel()
        quotes = [_q("100", "call"), _q("100", "put")]
        chain = m.build_chain(quotes)
        exp = date.today() + timedelta(days=30)
        assert chain[exp][Decimal("100")]["call"] is not None
        assert chain[exp][Decimal("100")]["put"] is not None

    def test_multiple_strikes_sorted(self):
        m = OptionChainModel()
        quotes = [_q("110", "call"), _q("90", "call"), _q("100", "call")]
        chain = m.build_chain(quotes)
        exp = date.today() + timedelta(days=30)
        strikes = list(chain[exp].keys())
        # build_chain sorts by expiry but not by strike within expiry
        assert Decimal("110") in strikes
        assert Decimal("90") in strikes
        assert Decimal("100") in strikes

    def test_multiple_expiries_sorted(self):
        m = OptionChainModel()
        near = date.today() + timedelta(days=10)
        far = date.today() + timedelta(days=60)
        quotes = [_q("100", "call", expiry=near), _q("100", "call", expiry=far)]
        chain = m.build_chain(quotes)
        expiries = list(chain.keys())
        assert expiries == sorted(expiries)


class TestOptionChainModelGreeks:
    def test_compute_greeks_returns_five_keys(self):
        m = OptionChainModel()
        greeks = m.compute_greeks(
            spot=Decimal("100"),
            strike=Decimal("100"),
            expiry=date.today() + timedelta(days=30),
            iv=0.3,
            option_type="call",
        )
        assert set(greeks.keys()) == {"delta", "gamma", "theta", "vega", "rho"}

    def test_compute_greeks_put(self):
        m = OptionChainModel()
        greeks = m.compute_greeks(
            spot=Decimal("100"),
            strike=Decimal("100"),
            expiry=date.today() + timedelta(days=30),
            iv=0.3,
            option_type="put",
        )
        assert greeks["delta"] < 0


class TestOptionChainModelFitIVSurface:
    def test_fit_with_few_points(self):
        m = OptionChainModel()
        exp = date.today() + timedelta(days=30)
        chain = {
            exp: {
                Decimal("100"): {"call": _q("100", "call", "0.30", exp), "put": None},
                Decimal("110"): {"call": _q("110", "call", "0.35", exp), "put": None},
            }
        }
        surface = m.fit_iv_surface(chain)
        assert exp in surface
        assert len(surface[exp]) == 2

    def test_fit_with_many_points_uses_svi(self):
        m = OptionChainModel()
        exp = date.today() + timedelta(days=30)
        strikes_map = {}
        for s in range(80, 125, 5):
            strikes_map[Decimal(str(s))] = {
                "call": _q(str(s), "call", f"0.{20 + s - 80}", exp),
                "put": None,
            }
        chain = {exp: strikes_map}
        surface = m.fit_iv_surface(chain)
        assert exp in surface
        assert len(surface[exp]) >= 5

    def test_fit_empty_chain(self):
        m = OptionChainModel()
        assert m.fit_iv_surface({}) == {}


class TestOptionChainModelSVI:
    def test_fit_svi_short_data(self):
        m = OptionChainModel()
        result = m._fit_svi([(100.0, 0.3)])
        assert 100.0 in result

    def test_fit_svi_two_points(self):
        m = OptionChainModel()
        result = m._fit_svi([(90.0, 0.25), (110.0, 0.35)])
        assert len(result) == 2
        for k, v in result.items():
            assert v > 0


class TestOptionChainModelSABR:
    def test_fit_sabr_basic(self):
        m = OptionChainModel()
        data = [(90.0, 0.25), (100.0, 0.30), (110.0, 0.35)]
        result = m.fit_sabr(data, spot=100.0, expiry=date.today() + timedelta(days=30))
        assert len(result) == 3
        for k, v in result.items():
            assert v > 0

    def test_fit_sabr_short_data(self):
        m = OptionChainModel()
        result = m.fit_sabr([(100.0, 0.3)], spot=100.0, expiry=date.today() + timedelta(days=30))
        assert len(result) == 1

    def test_sabr_hagan_atm(self):
        """ATM (F=K) 应走特殊分支。"""
        iv = OptionChainModel._sabr_hagan_iv(F=100.0, K=100.0, T=0.1, alpha=0.3, beta=0.5, rho=-0.3)
        assert iv > 0

    def test_sabr_hagan_otm(self):
        iv = OptionChainModel._sabr_hagan_iv(F=100.0, K=120.0, T=0.1, alpha=0.3, beta=0.5, rho=-0.3)
        assert iv > 0

    def test_sabr_hagan_itm(self):
        iv = OptionChainModel._sabr_hagan_iv(F=100.0, K=80.0, T=0.1, alpha=0.3, beta=0.5, rho=-0.3)
        assert iv > 0

    def test_sabr_hagan_beta_one(self):
        """beta=1.0 应走 log(F/K) 分支。"""
        iv = OptionChainModel._sabr_hagan_iv(F=100.0, K=110.0, T=0.1, alpha=0.3, beta=1.0, rho=-0.3)
        assert iv > 0

    def test_sabr_hagan_near_zero_spread(self):
        """F≈K 且 z≈0 应安全处理。"""
        iv = OptionChainModel._sabr_hagan_iv(
            F=100.0, K=100.001, T=0.1, alpha=0.3, beta=0.5, rho=-0.3
        )
        assert iv > 0
