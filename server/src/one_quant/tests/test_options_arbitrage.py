"""IV 套利模型测试 — IVArbitrageModel"""

from __future__ import annotations

import time
from datetime import date, timedelta
from decimal import Decimal

from one_quant.core.types import OptionQuote
from one_quant.strategy.options.arbitrage import IVArbitrageModel


def _q(
    iv: str, strike: str = "100", option_type: str = "call", expiry: date | None = None
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


class TestFindMispricing:
    def test_put_call_parity_violation(self):
        m = IVArbitrageModel(iv_threshold=0.05)
        expiry = date.today() + timedelta(days=30)
        chain = {
            expiry: {
                Decimal("100"): {
                    "call": _q("0.30", "100", "call", expiry),
                    "put": _q("0.50", "100", "put", expiry),
                }
            }
        }
        result = m.find_mispricing(chain)
        assert len(result) > 0
        assert result[0]["type"] == "put_call_parity"
        assert result[0]["iv_diff"] > 0.05

    def test_no_mispricing_when_close(self):
        m = IVArbitrageModel(iv_threshold=0.10)
        expiry = date.today() + timedelta(days=30)
        chain = {
            expiry: {
                Decimal("100"): {
                    "call": _q("0.30", "100", "call", expiry),
                    "put": _q("0.32", "100", "put", expiry),
                }
            }
        }
        result = m.find_mispricing(chain)
        assert len(result) == 0

    def test_smile_discontinuity(self):
        m = IVArbitrageModel(iv_threshold=0.05)
        expiry = date.today() + timedelta(days=30)
        chain = {
            expiry: {
                Decimal("90"): {"call": _q("0.20", "90", "call", expiry)},
                Decimal("100"): {"call": _q("0.60", "100", "call", expiry)},
                Decimal("110"): {"call": _q("0.25", "110", "call", expiry)},
            }
        }
        result = m.find_mispricing(chain)
        smiles = [r for r in result if r["type"] == "smile_discontinuity"]
        assert len(smiles) > 0

    def test_empty_chain(self):
        m = IVArbitrageModel()
        assert m.find_mispricing({}) == []

    def test_severity_field(self):
        m = IVArbitrageModel(iv_threshold=0.05)
        expiry = date.today() + timedelta(days=30)
        chain = {
            expiry: {
                Decimal("100"): {
                    "call": _q("0.20", "100", "call", expiry),
                    "put": _q("0.50", "100", "put", expiry),
                }
            }
        }
        result = m.find_mispricing(chain)
        for r in result:
            assert "severity" in r
            assert r["severity"] > 0


class TestSurfaceArbitrage:
    def test_calendar_spread_opportunity(self):
        m = IVArbitrageModel(iv_threshold=0.05)
        near = date.today() + timedelta(days=30)
        far = date.today() + timedelta(days=90)
        surface = {
            near: {Decimal("100"): 0.40},
            far: {Decimal("100"): 0.20},
        }
        result = m.surface_arbitrage(surface)
        cals = [r for r in result if r["type"] == "calendar_spread"]
        assert len(cals) > 0

    def test_butterfly_opportunity(self):
        m = IVArbitrageModel(iv_threshold=0.05)
        expiry = date.today() + timedelta(days=30)
        surface = {
            expiry: {
                Decimal("90"): 0.20,
                Decimal("100"): 0.60,  # Excess in middle
                Decimal("110"): 0.20,
            }
        }
        result = m.surface_arbitrage(surface)
        butterflies = [r for r in result if r["type"] == "butterfly"]
        assert len(butterflies) > 0

    def test_no_opportunity_normal_surface(self):
        m = IVArbitrageModel(iv_threshold=0.05)
        expiry = date.today() + timedelta(days=30)
        surface = {
            expiry: {
                Decimal("90"): 0.30,
                Decimal("100"): 0.30,
                Decimal("110"): 0.30,
            }
        }
        result = m.surface_arbitrage(surface)
        assert len(result) == 0

    def test_empty_surface(self):
        m = IVArbitrageModel()
        assert m.surface_arbitrage({}) == []

    def test_single_expiry(self):
        m = IVArbitrageModel(iv_threshold=0.05)
        expiry = date.today() + timedelta(days=30)
        surface = {expiry: {Decimal("100"): 0.30}}
        result = m.surface_arbitrage(surface)
        # No calendar spread possible with single expiry
        assert len([r for r in result if r["type"] == "calendar_spread"]) == 0
