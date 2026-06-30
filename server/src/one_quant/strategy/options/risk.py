"""卖方保证金监控 + 展期顾问"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any


class MarginMonitor:
    """卖方保证金监控。"""

    def __init__(
        self,
        margin_ratio: Decimal = Decimal("0.15"),
        exercise_warning_dte: int = 3,
        exercise_warning_delta: Decimal = Decimal("0.85"),
    ):
        self.margin_ratio = margin_ratio
        self.exercise_warning_dte = exercise_warning_dte
        self.exercise_warning_delta = exercise_warning_delta

    def check_margin(self, position: dict[str, Any], spot: Decimal) -> dict[str, Any]:
        """保证金检查。"""
        option_type = position.get("option_type", "call")
        strike = Decimal(str(position.get("strike", 0)))
        quantity = Decimal(str(position.get("quantity", 0)))
        premium = Decimal(str(position.get("premium", 0)))
        available_margin = Decimal(str(position.get("available_margin", 0)))

        abs_qty = abs(quantity)
        if abs_qty == 0:
            return {
                "required_margin": Decimal("0"),
                "available_margin": available_margin,
                "margin_ratio": Decimal("0"),
                "warning": None,
            }

        if option_type == "call":
            otm_amount = max(Decimal("0"), strike - spot)
            base_margin = max(
                spot * self.margin_ratio - otm_amount,
                spot * self.margin_ratio * Decimal("0.5"),
            )
        else:
            otm_amount = max(Decimal("0"), spot - strike)
            base_margin = max(
                strike * self.margin_ratio - otm_amount,
                strike * self.margin_ratio * Decimal("0.5"),
            )

        required_margin = (base_margin + premium) * abs_qty
        margin_ratio = (
            (required_margin / available_margin * 100).quantize(Decimal("0.01"))
            if available_margin > 0
            else Decimal("999")
        )

        warning = None
        if required_margin > available_margin:
            warning = (
                f"⚠️ 保证金不足！需要 {required_margin}，"
                f"可用 {available_margin}，缺口 {required_margin - available_margin}"
            )
        elif margin_ratio > Decimal("80"):
            warning = f"⚠️ 保证金使用率 {margin_ratio}%，接近上限"

        return {
            "required_margin": required_margin.quantize(Decimal("0.01")),
            "available_margin": available_margin,
            "margin_ratio": margin_ratio,
            "warning": warning,
        }

    def exercise_warning(self, position: dict[str, Any], spot: Decimal) -> dict[str, Any] | None:
        """被行权预警。"""
        quantity = Decimal(str(position.get("quantity", 0)))
        if quantity >= 0:
            return None

        expiry = position.get("expiry")
        if isinstance(expiry, str):
            expiry = date.fromisoformat(expiry)
        if expiry is None:
            return None

        dte = (expiry - date.today()).days
        delta = Decimal(str(position.get("delta", 0)))
        abs_delta = abs(delta)

        if dte > self.exercise_warning_dte:
            return None
        if abs_delta < self.exercise_warning_delta:
            return None

        strike = Decimal(str(position.get("strike", 0)))
        option_type = position.get("option_type", "call")

        if option_type == "call":
            itm_amount = max(Decimal("0"), spot - strike)
        else:
            itm_amount = max(Decimal("0"), strike - spot)

        return {
            "level": "critical" if dte <= 1 else "warning",
            "dte": dte,
            "delta": str(delta),
            "itm_amount": str(itm_amount),
            "message": (
                f"🔴 被行权预警：{option_type.upper()} 行权价={strike}，"
                f"剩余 {dte} 天，Delta={delta}，实值金额={itm_amount}。"
                f"建议尽快平仓或展期。"
            ),
        }


class RollAdvisor:
    """展期顾问。"""

    def __init__(
        self,
        roll_dte: int = 7,
        close_dte: int = 3,
        min_credit: Decimal = Decimal("0"),
    ):
        self.roll_dte = roll_dte
        self.close_dte = close_dte
        self.min_credit = min_credit

    def suggest_roll(self, position: dict[str, Any], days_to_expiry: int) -> dict[str, Any] | None:
        """展期/平仓提示。"""
        delta = Decimal(str(position.get("delta", 0)))
        abs_delta = abs(delta)
        strike = Decimal(str(position.get("strike", 0)))
        premium = Decimal(str(position.get("premium", 0)))

        if days_to_expiry <= self.close_dte and abs_delta >= Decimal("0.8"):
            return {
                "action": "close",
                "urgency": "high",
                "reason": (
                    f"临近到期（{days_to_expiry}天）且深度实值（Delta={delta}），"
                    f"建议立即平仓避免被行权"
                ),
                "details": {
                    "current_premium": str(premium),
                    "delta": str(delta),
                    "dte": days_to_expiry,
                },
            }

        if days_to_expiry <= self.roll_dte and abs_delta < Decimal("0.5"):
            return {
                "action": "roll",
                "urgency": "medium",
                "reason": (
                    f"临近到期（{days_to_expiry}天）且虚值（Delta={delta}），"
                    f"建议展期到下一到期日以保持仓位"
                ),
                "details": {
                    "current_strike": str(strike),
                    "current_dte": days_to_expiry,
                    "delta": str(delta),
                    "suggested_new_dte": "30-60天",
                },
            }

        if self.close_dte < days_to_expiry <= self.roll_dte:
            return {
                "action": "consider_roll",
                "urgency": "low",
                "reason": (
                    f"进入时间价值衰减加速期（{days_to_expiry}天），"
                    f"Delta={delta}，可考虑展期以锁定收益"
                ),
                "details": {
                    "current_strike": str(strike),
                    "current_dte": days_to_expiry,
                    "delta": str(delta),
                },
            }

        return None
