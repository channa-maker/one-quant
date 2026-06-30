"""期权风控补充测试 — MarginMonitor, RollAdvisor (risk.py)"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from one_quant.strategy.options.risk import MarginMonitor, RollAdvisor

# ──────────────────────────── MarginMonitor 补充测试 ────────────────────────────


class TestMarginMonitorExtended:
    def test_put_option_margin(self):
        m = MarginMonitor(margin_ratio=Decimal("0.15"))
        pos = {
            "option_type": "put",
            "strike": Decimal("100"),
            "quantity": Decimal("-1"),
            "premium": Decimal("5"),
            "available_margin": Decimal("10000"),
        }
        result = m.check_margin(pos, spot=Decimal("100"))
        assert result["required_margin"] > 0
        assert result["warning"] is None

    def test_zero_quantity(self):
        m = MarginMonitor()
        pos = {
            "option_type": "call",
            "strike": Decimal("100"),
            "quantity": Decimal("0"),
            "premium": Decimal("5"),
            "available_margin": Decimal("10000"),
        }
        result = m.check_margin(pos, spot=Decimal("100"))
        assert result["required_margin"] == Decimal("0")

    def test_margin_ratio_high_warning(self):
        m = MarginMonitor(margin_ratio=Decimal("0.15"))
        pos = {
            "option_type": "call",
            "strike": Decimal("100"),
            "quantity": Decimal("-50"),
            "premium": Decimal("5"),
            "available_margin": Decimal("1000"),
        }
        result = m.check_margin(pos, spot=Decimal("100"))
        # Either insufficient or high usage warning
        assert result["warning"] is not None

    def test_otm_call_lower_margin(self):
        m = MarginMonitor(margin_ratio=Decimal("0.15"))
        # OTM call: spot < strike
        pos = {
            "option_type": "call",
            "strike": Decimal("120"),
            "quantity": Decimal("-1"),
            "premium": Decimal("2"),
            "available_margin": Decimal("10000"),
        }
        result = m.check_margin(pos, spot=Decimal("100"))
        assert result["warning"] is None

    def test_otm_put_lower_margin(self):
        m = MarginMonitor(margin_ratio=Decimal("0.15"))
        # OTM put: spot > strike
        pos = {
            "option_type": "put",
            "strike": Decimal("80"),
            "quantity": Decimal("-1"),
            "premium": Decimal("2"),
            "available_margin": Decimal("10000"),
        }
        result = m.check_margin(pos, spot=Decimal("100"))
        assert result["warning"] is None

    def test_exercise_warning_put(self):
        m = MarginMonitor(exercise_warning_dte=3, exercise_warning_delta=Decimal("0.85"))
        pos = {
            "option_type": "put",
            "strike": Decimal("100"),
            "expiry": (date.today() + timedelta(days=1)).isoformat(),
            "delta": Decimal("-0.90"),
            "quantity": Decimal("-1"),
        }
        result = m.exercise_warning(pos, spot=Decimal("80"))
        assert result is not None
        assert "PUT" in result["message"]

    def test_exercise_warning_at_boundary_dte(self):
        m = MarginMonitor(exercise_warning_dte=3, exercise_warning_delta=Decimal("0.85"))
        pos = {
            "option_type": "call",
            "strike": Decimal("100"),
            "expiry": (date.today() + timedelta(days=3)).isoformat(),
            "delta": Decimal("0.86"),
            "quantity": Decimal("-1"),
        }
        result = m.exercise_warning(pos, spot=Decimal("110"))
        assert result is not None
        assert result["level"] == "warning"

    def test_exercise_warning_critical_dte(self):
        m = MarginMonitor(exercise_warning_dte=3, exercise_warning_delta=Decimal("0.85"))
        pos = {
            "option_type": "call",
            "strike": Decimal("100"),
            "expiry": (date.today() + timedelta(days=1)).isoformat(),
            "delta": Decimal("0.90"),
            "quantity": Decimal("-1"),
        }
        result = m.exercise_warning(pos, spot=Decimal("110"))
        assert result["level"] == "critical"

    def test_exercise_warning_no_expiry(self):
        m = MarginMonitor()
        pos = {"option_type": "call", "delta": Decimal("0.9"), "quantity": Decimal("-1")}
        result = m.exercise_warning(pos, spot=Decimal("100"))
        assert result is None

    def test_margin_ratio_zero_available(self):
        m = MarginMonitor()
        pos = {
            "option_type": "call",
            "strike": Decimal("100"),
            "quantity": Decimal("-1"),
            "premium": Decimal("5"),
            "available_margin": Decimal("0"),
        }
        result = m.check_margin(pos, spot=Decimal("100"))
        assert result["margin_ratio"] == Decimal("999")


# ──────────────────────────── RollAdvisor 测试 ────────────────────────────


class TestRollAdvisor:
    def test_close_deep_itm_near_expiry(self):
        r = RollAdvisor(roll_dte=7, close_dte=3)
        pos = {"delta": Decimal("0.9"), "strike": Decimal("100"), "premium": Decimal("15")}
        result = r.suggest_roll(pos, days_to_expiry=2)
        assert result is not None
        assert result["action"] == "close"
        assert result["urgency"] == "high"

    def test_roll_otm_near_expiry(self):
        r = RollAdvisor(roll_dte=7, close_dte=3)
        pos = {"delta": Decimal("0.2"), "strike": Decimal("100"), "premium": Decimal("1")}
        result = r.suggest_roll(pos, days_to_expiry=5)
        assert result is not None
        assert result["action"] == "roll"
        assert result["urgency"] == "medium"

    def test_consider_roll_middle_zone(self):
        r = RollAdvisor(roll_dte=7, close_dte=3)
        pos = {"delta": Decimal("0.4"), "strike": Decimal("100"), "premium": Decimal("5")}
        result = r.suggest_roll(pos, days_to_expiry=5)
        assert result is not None
        # dte=5 <= roll_dte=7 and abs_delta=0.4 < 0.5 → "roll"
        assert result["action"] in ("roll", "consider_roll")
        assert result["urgency"] in ("medium", "low")

    def test_no_suggestion_far_expiry(self):
        r = RollAdvisor(roll_dte=7, close_dte=3)
        pos = {"delta": Decimal("0.5"), "strike": Decimal("100"), "premium": Decimal("5")}
        result = r.suggest_roll(pos, days_to_expiry=30)
        assert result is None

    def test_no_suggestion_at_close_dte_low_delta(self):
        r = RollAdvisor(roll_dte=7, close_dte=3)
        pos = {"delta": Decimal("0.1"), "strike": Decimal("100"), "premium": Decimal("1")}
        result = r.suggest_roll(pos, days_to_expiry=3)
        # close_dte <= days_to_expiry <= roll_dte with low delta → roll
        assert result is not None

    def test_negative_delta_put(self):
        r = RollAdvisor(roll_dte=7, close_dte=3)
        pos = {"delta": Decimal("-0.9"), "strike": Decimal("100"), "premium": Decimal("15")}
        result = r.suggest_roll(pos, days_to_expiry=2)
        assert result is not None
        assert result["action"] == "close"
