"""期权链建模 — 链构建、Greeks 计算、IV 曲面拟合（SVI/SABR）"""

from __future__ import annotations

import math
from datetime import date
from decimal import Decimal
from typing import Literal

from one_quant.core.types import OptionQuote
from one_quant.strategy.options.constants import (
    DAYS_PER_YEAR,
    DEFAULT_RISK_FREE_RATE,
    black_scholes_greeks,
)


class OptionChainModel:
    """期权链建模。"""

    def build_chain(
        self, quotes: list[OptionQuote]
    ) -> dict[date, dict[Decimal, dict[str, OptionQuote | None]]]:
        """构建期权链：按到期日 × 行权价组织。"""
        chain: dict[date, dict[Decimal, dict[str, OptionQuote | None]]] = {}

        for q in quotes:
            expiry = q.expiry
            strike = q.strike

            if expiry not in chain:
                chain[expiry] = {}
            if strike not in chain[expiry]:
                chain[expiry][strike] = {"call": None, "put": None}

            chain[expiry][strike][q.option_type] = q

        return dict(sorted(chain.items(), key=lambda x: x[0]))

    def compute_greeks(
        self,
        spot: Decimal,
        strike: Decimal,
        expiry: date,
        iv: float,
        option_type: Literal["call", "put"],
        risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
    ) -> dict[str, Decimal]:
        """计算单个期权的 Greeks。"""
        return black_scholes_greeks(spot, strike, expiry, iv, option_type, risk_free_rate)

    def fit_iv_surface(
        self, chain: dict[date, dict[Decimal, dict[str, OptionQuote | None]]]
    ) -> dict[date, dict[Decimal, float]]:
        """IV 曲面拟合（SVI 模型）。"""
        surface: dict[date, dict[Decimal, float]] = {}

        for expiry, strikes_map in chain.items():
            data_points: list[tuple[float, float]] = []
            for strike, opt_map in strikes_map.items():
                quote = opt_map.get("call") or opt_map.get("put")
                if quote is not None and float(quote.iv) > 0:
                    data_points.append((float(strike), float(quote.iv)))

            if not data_points:
                continue

            data_points.sort(key=lambda x: x[0])

            if len(data_points) >= 5:
                fitted = self._fit_svi(data_points)
                surface[expiry] = {Decimal(str(k)): v for k, v in fitted.items()}
            else:
                surface[expiry] = {Decimal(str(k)): v for k, v in data_points}

        return surface

    def _fit_svi(self, data_points: list[tuple[float, float]]) -> dict[float, float]:
        """SVI 参数拟合。"""
        if len(data_points) < 2:
            return {k: v for k, v in data_points}

        strikes = [p[0] for p in data_points]
        ivs = [p[1] for p in data_points]

        mid_strike = (strikes[0] + strikes[-1]) / 2.0
        atm_iv = ivs[len(ivs) // 2]

        a = atm_iv**2
        b = 0.1
        rho = -0.3
        m = 0.0
        sigma = 0.2

        best_params = {"a": a, "b": b, "rho": rho, "m": m, "sigma": sigma}

        result: dict[float, float] = {}
        for k_val in strikes:
            k = math.log(k_val / mid_strike) if mid_strike > 0 else 0.0
            w = best_params["a"] + best_params["b"] * (
                best_params["rho"] * (k - best_params["m"])
                + math.sqrt((k - best_params["m"]) ** 2 + best_params["sigma"] ** 2)
            )
            iv_fitted = math.sqrt(max(w, 0.0001))
            result[k_val] = iv_fitted

        return result

    def fit_sabr(
        self,
        data_points: list[tuple[float, float]],
        spot: float,
        expiry: date,
        beta: float = 0.5,
    ) -> dict[float, float]:
        """SABR 模型拟合。"""
        if len(data_points) < 2:
            return {k: v for k, v in data_points}

        T = max((expiry - date.today()).days / float(DAYS_PER_YEAR), 0.001)  # noqa: N806
        F = spot  # noqa: N806

        strikes = [p[0] for p in data_points]
        ivs = [p[1] for p in data_points]
        atm_idx = min(range(len(strikes)), key=lambda i: abs(strikes[i] - F))
        atm_iv = ivs[atm_idx]

        alpha = atm_iv * (F ** (1 - beta)) if F > 0 else 0.3
        rho = -0.3

        result: dict[float, float] = {}
        for K in strikes:  # noqa: N806
            iv_sabr = self._sabr_hagan_iv(F, K, T, alpha, beta, rho)
            result[K] = iv_sabr

        return result

    @staticmethod
    def _sabr_hagan_iv(
        F: float,  # noqa: N803
        K: float,  # noqa: N803
        T: float,  # noqa: N803
        alpha: float,
        beta: float,
        rho: float,  # noqa: N803
    ) -> float:
        """Hagan et al. (2002) SABR 隐含波动率近似公式。"""
        eps = 1e-10

        fk_geom = (F * K) ** ((1 - beta) / 2.0)

        if abs(F - K) < eps:
            vol_correction = (
                ((1 - beta) ** 2 / 24.0) * (alpha**2 / (fk_geom**2))
                + (rho * beta * alpha / (4.0 * fk_geom))
                + (2 - 3 * rho**2) / 24.0 * (alpha**2)
            ) * T
            iv = (alpha / fk_geom) * (1.0 + vol_correction)
            return max(iv, 0.001)

        log_fk = math.log(F / K)

        if abs(beta - 1.0) < eps:
            z = alpha * log_fk
        else:
            z = (alpha / (1 - beta)) * (F ** (1 - beta) - K ** (1 - beta))

        if abs(z) < eps:
            xz = 1.0
        else:
            discriminant = 1.0 - 2.0 * rho * z + z * z
            if discriminant < eps:
                discriminant = eps
            numerator_inner = math.sqrt(discriminant) + z - rho
            denominator_inner = 1.0 - rho
            if abs(denominator_inner) < eps:
                denominator_inner = eps
            xz = math.log(max(numerator_inner / denominator_inner, eps)) / z

        p1 = ((1 - beta) ** 2 / 24.0) * (alpha**2 / (fk_geom**2))
        p2 = rho * beta * alpha / (4.0 * fk_geom)
        p3 = (2.0 - 3.0 * rho**2) / 24.0
        correction = 1.0 + (p1 + p2 + p3) * T

        denominator = fk_geom * xz if abs(xz) > eps else fk_geom
        if abs(denominator) < eps:
            return 0.3

        iv = (
            (alpha * z / log_fk) * correction / xz
            if abs(log_fk) > eps
            else (alpha / fk_geom) * correction
        )

        if abs(z) < eps:
            iv = (alpha / fk_geom) * correction

        return max(iv, 0.001)
