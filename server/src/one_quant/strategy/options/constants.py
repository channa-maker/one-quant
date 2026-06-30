"""期权策略 — 常量、辅助函数、Black-Scholes Greeks 计算"""

from __future__ import annotations

import math
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

# 默认无风险利率
DEFAULT_RISK_FREE_RATE: float = 0.05

# 默认年化天数
DAYS_PER_YEAR: int = 365

# Greeks 限额默认值
DEFAULT_DELTA_LIMIT = Decimal("1000")
DEFAULT_GAMMA_LIMIT = Decimal("500")
DEFAULT_VEGA_LIMIT = Decimal("2000")
DEFAULT_THETA_LIMIT = Decimal("5000")


def _norm_cdf(x: float) -> float:
    """标准正态分布累积分布函数。"""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    """标准正态分布概率密度函数。"""
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def _dec(v: float, prec: str = "0.000001") -> Decimal:
    """float → Decimal，截断精度。"""
    return Decimal(str(v)).quantize(Decimal(prec), rounding=ROUND_HALF_UP)


class RiskCheckResult:
    """风控检查结果。"""

    def __init__(self, passed: bool, violations: list[tuple[str, Decimal, Decimal]] | None = None):
        self.passed = passed
        self.violations = violations or []

    def __repr__(self) -> str:
        if self.passed:
            return "RiskCheckResult(passed=True)"
        return f"RiskCheckResult(passed=False, violations={self.violations})"


def black_scholes_greeks(
    spot: Decimal,
    strike: Decimal,
    expiry: date,
    iv: float,
    option_type: Literal["call", "put"] = "call",
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
) -> dict[str, Decimal]:
    """Black-Scholes 模型计算期权 Greeks。

    Args:
        spot: 标的当前价格
        strike: 行权价
        expiry: 到期日
        iv: 隐含波动率（年化）
        option_type: 期权类型，call 或 put
        risk_free_rate: 无风险利率

    Returns:
        Greeks 字典，键为 delta/gamma/theta/vega/rho，值为 Decimal。
    """
    S = float(spot)  # noqa: N806
    K = float(strike)  # noqa: N806
    T = max((expiry - date.today()).days / float(DAYS_PER_YEAR), 0.001)  # noqa: N806
    r = risk_free_rate
    sigma = max(iv, 0.001)

    d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)

    nd1 = _norm_cdf(d1)
    npd1 = _norm_pdf(d1)

    if option_type == "call":
        delta = nd1
    else:
        delta = nd1 - 1.0

    gamma = npd1 / (S * sigma * math.sqrt(T))

    if option_type == "call":
        theta = (
            -S * npd1 * sigma / (2.0 * math.sqrt(T)) - r * K * math.exp(-r * T) * _norm_cdf(d2)
        ) / float(DAYS_PER_YEAR)
    else:
        theta = (
            -S * npd1 * sigma / (2.0 * math.sqrt(T)) + r * K * math.exp(-r * T) * _norm_cdf(-d2)
        ) / float(DAYS_PER_YEAR)

    vega = S * npd1 * math.sqrt(T) / 100.0

    if option_type == "call":
        rho = K * T * math.exp(-r * T) * _norm_cdf(d2) / 100.0
    else:
        rho = -K * T * math.exp(-r * T) * _norm_cdf(-d2) / 100.0

    return {
        "delta": _dec(delta),
        "gamma": _dec(gamma),
        "theta": _dec(theta),
        "vega": _dec(vega),
        "rho": _dec(rho),
    }
