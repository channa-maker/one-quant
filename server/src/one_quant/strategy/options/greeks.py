"""组合层 Greeks 聚合与风控"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from one_quant.strategy.options.constants import (
    DEFAULT_DELTA_LIMIT,
    DEFAULT_GAMMA_LIMIT,
    DEFAULT_THETA_LIMIT,
    DEFAULT_VEGA_LIMIT,
    RiskCheckResult,
)


class OptionGreeksAggregator:
    """组合层 Greeks 聚合与风控。"""

    def __init__(
        self,
        delta_limit: Decimal = DEFAULT_DELTA_LIMIT,
        gamma_limit: Decimal = DEFAULT_GAMMA_LIMIT,
        vega_limit: Decimal = DEFAULT_VEGA_LIMIT,
        theta_limit: Decimal = DEFAULT_THETA_LIMIT,
    ):
        self.delta_limit = delta_limit
        self.gamma_limit = gamma_limit
        self.vega_limit = vega_limit
        self.theta_limit = theta_limit

    def portfolio_greeks(self, positions: list[dict[str, Any]]) -> dict[str, Decimal]:
        """计算组合总 Greeks。"""
        total_delta = Decimal("0")
        total_gamma = Decimal("0")
        total_theta = Decimal("0")
        total_vega = Decimal("0")

        for pos in positions:
            qty = Decimal(str(pos.get("quantity", 0)))
            total_delta += qty * Decimal(str(pos.get("delta", 0)))
            total_gamma += qty * Decimal(str(pos.get("gamma", 0)))
            total_theta += qty * Decimal(str(pos.get("theta", 0)))
            total_vega += qty * Decimal(str(pos.get("vega", 0)))

        return {
            "delta": total_delta.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            "gamma": total_gamma.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            "theta": total_theta.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            "vega": total_vega.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
        }

    def check_greeks_limits(self, portfolio: dict[str, Decimal]) -> RiskCheckResult:
        """Greeks 限额检查。"""
        violations: list[tuple[str, Decimal, Decimal]] = []

        checks = [
            ("delta", portfolio.get("delta", Decimal("0")), self.delta_limit),
            ("gamma", portfolio.get("gamma", Decimal("0")), self.gamma_limit),
            ("vega", portfolio.get("vega", Decimal("0")), self.vega_limit),
            ("theta", portfolio.get("theta", Decimal("0")), self.theta_limit),
        ]

        for name, current, limit in checks:
            if abs(current) > limit:
                violations.append((name, current, limit))

        return RiskCheckResult(passed=len(violations) == 0, violations=violations)
