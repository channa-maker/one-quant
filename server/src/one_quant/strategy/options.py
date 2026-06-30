"""期权链建模 + 实时 Greeks + IV 曲面"""

from __future__ import annotations

import math
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from one_quant.core.types import OptionQuote
from one_quant.infra.logging import get_logger

logger = get_logger(__name__)


def black_scholes_greeks(
    spot: Decimal,
    strike: Decimal,
    expiry: date,
    volatility: float,
    option_type: str = "call",
    risk_free_rate: float = 0.05,
) -> dict[str, float]:
    """Black-Scholes Greeks 计算。

    Args:
        spot: 标的价格
        strike: 行权价
        expiry: 到期日
        volatility: 波动率
        option_type: call/put
        risk_free_rate: 无风险利率

    Returns:
        Greeks 字典 {delta, gamma, theta, vega, rho}
    """
    S = float(spot)
    K = float(strike)
    T = max((expiry - date.today()).days / 365.0, 0.001)
    r = risk_free_rate
    sigma = volatility

    d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)

    nd1 = _norm_cdf(d1)
    nd2 = _norm_cdf(d2)
    npd1 = _norm_pdf(d1)

    if option_type == "call":
        delta = nd1
        theta = (-S * npd1 * sigma / (2 * math.sqrt(T)) - r * K * math.exp(-r * T) * nd2) / 365
    else:
        delta = nd1 - 1
        theta = (-S * npd1 * sigma / (2 * math.sqrt(T)) + r * K * math.exp(-r * T) * (1 - nd2)) / 365

    gamma = npd1 / (S * sigma * math.sqrt(T))
    vega = S * npd1 * math.sqrt(T) / 100
    rho = K * T * math.exp(-r * T) * (nd2 if option_type == "call" else -_norm_cdf(-d2)) / 100

    return {"delta": delta, "gamma": gamma, "theta": theta, "vega": vega, "rho": rho}


def _norm_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)


class IVSurface:
    """隐含波动率曲面。

    存储和查询不同行权价/到期日的 IV。
    支持 SVI/SABR 拟合（骨架）。
    """

    def __init__(self) -> None:
        self._iv_data: dict[str, dict[str, float]] = {}  # {expiry_strike: iv}

    def update(self, expiry: date, strike: float, iv: float) -> None:
        key = f"{expiry.isoformat()}_{strike}"
        self._iv_data[key] = {"iv": iv, "strike": strike, "expiry": expiry.isoformat()}

    def get_iv(self, expiry: date, strike: float) -> float | None:
        key = f"{expiry.isoformat()}_{strike}"
        data = self._iv_data.get(key)
        return data["iv"] if data else None

    def get_smile(self, expiry: date) -> list[dict[str, Any]]:
        """获取指定到期日的波动率微笑"""
        prefix = expiry.isoformat()
        smile = []
        for key, data in self._iv_data.items():
            if key.startswith(prefix):
                smile.append({"strike": data["strike"], "iv": data["iv"]})
        return sorted(smile, key=lambda x: x["strike"])

    def fit_svi(self, expiry: date) -> dict[str, float]:
        """SVI 拟合（骨架）"""
        # TODO: 实现 SVI 参数拟合
        return {"a": 0, "b": 0, "rho": 0, "m": 0, "sigma": 0}
