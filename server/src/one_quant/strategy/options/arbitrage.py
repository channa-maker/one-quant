"""IV 套利模型 — 定价错误检测 + 曲面套利"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any


class IVArbitrageModel:
    """IV 套利模型。"""

    def __init__(
        self,
        iv_threshold: float = 0.05,
        min_spread: Decimal = Decimal("0.01"),
    ):
        self.iv_threshold = iv_threshold
        self.min_spread = min_spread

    def find_mispricing(
        self, chain: dict[date, dict[Decimal, dict[str, Any]]]
    ) -> list[dict[str, Any]]:
        """寻找 IV 定价错误。"""
        mispricings: list[dict[str, Any]] = []

        for expiry, strikes_map in chain.items():
            for strike, opt_map in strikes_map.items():
                call_q = opt_map.get("call")
                put_q = opt_map.get("put")

                if call_q is not None and put_q is not None:
                    call_iv = float(call_q.iv)
                    put_iv = float(put_q.iv)
                    iv_diff = abs(call_iv - put_iv)

                    if iv_diff > self.iv_threshold:
                        mispricings.append(
                            {
                                "type": "put_call_parity",
                                "expiry": expiry.isoformat(),
                                "strike": str(strike),
                                "call_iv": call_iv,
                                "put_iv": put_iv,
                                "iv_diff": iv_diff,
                                "severity": iv_diff / self.iv_threshold,
                                "detail": (
                                    f"Put-Call IV 偏差 {iv_diff:.1%}"
                                    f"（阈值 {self.iv_threshold:.1%}），"
                                    f"行权价={strike}，到期={expiry}"
                                ),
                            }
                        )

            sorted_strikes = sorted(strikes_map.keys())
            for i in range(1, len(sorted_strikes)):
                prev_strike = sorted_strikes[i - 1]
                curr_strike = sorted_strikes[i]

                for opt_type in ("call", "put"):
                    prev_q = strikes_map[prev_strike].get(opt_type)
                    curr_q = strikes_map[curr_strike].get(opt_type)

                    if prev_q is not None and curr_q is not None:
                        iv_change = abs(float(curr_q.iv) - float(prev_q.iv))
                        strike_gap = float(curr_strike - prev_strike)

                        if iv_change > self.iv_threshold * 3 and strike_gap > 0:
                            mispricings.append(
                                {
                                    "type": "smile_discontinuity",
                                    "expiry": expiry.isoformat(),
                                    "strikes": [str(prev_strike), str(curr_strike)],
                                    "iv_change": iv_change,
                                    "severity": iv_change / (self.iv_threshold * 3),
                                    "detail": (
                                        f"IV 微笑突变：{prev_strike}→{curr_strike}，"
                                        f"IV 变化 {iv_change:.1%}"
                                    ),
                                }
                            )

        return mispricings

    def surface_arbitrage(self, surface: dict[date, dict[Decimal, float]]) -> list[dict[str, Any]]:
        """曲面套利检查。"""
        opportunities: list[dict[str, Any]] = []
        sorted_expiries = sorted(surface.keys())

        for i in range(1, len(sorted_expiries)):
            near_expiry = sorted_expiries[i - 1]
            far_expiry = sorted_expiries[i]

            near_strikes = surface[near_expiry]
            far_strikes = surface[far_expiry]

            common_strikes = set(near_strikes.keys()) & set(far_strikes.keys())
            for strike in common_strikes:
                near_iv = near_strikes[strike]
                far_iv = far_strikes[strike]

                if far_iv < near_iv - self.iv_threshold:
                    opportunities.append(
                        {
                            "type": "calendar_spread",
                            "near_expiry": near_expiry.isoformat(),
                            "far_expiry": far_expiry.isoformat(),
                            "strike": str(strike),
                            "near_iv": near_iv,
                            "far_iv": far_iv,
                            "iv_diff": near_iv - far_iv,
                            "detail": (
                                f"日历价差套利：近月IV={near_iv:.1%} >"
                                f" 远月IV={far_iv:.1%}，行权价={strike}"
                            ),
                        }
                    )

        for expiry, strikes_map in surface.items():
            sorted_strikes = sorted(strikes_map.keys())
            for i in range(1, len(sorted_strikes) - 1):
                k1, k2, k3 = sorted_strikes[i - 1], sorted_strikes[i], sorted_strikes[i + 1]
                iv1, iv2, iv3 = strikes_map[k1], strikes_map[k2], strikes_map[k3]

                if k3 != k1:
                    weight = float(k2 - k1) / float(k3 - k1)
                    iv_interp = iv1 + (iv3 - iv1) * weight
                    excess = iv2 - iv_interp

                    if excess > self.iv_threshold:
                        opportunities.append(
                            {
                                "type": "butterfly",
                                "expiry": expiry.isoformat(),
                                "strikes": [str(k1), str(k2), str(k3)],
                                "ivs": [iv1, iv2, iv3],
                                "excess": excess,
                                "detail": (
                                    f"蝶式价差套利：K={k1}/{k2}/{k3}，"
                                    f"中间IV={iv2:.1%}，插值={iv_interp:.1%}"
                                ),
                            }
                        )

        return opportunities
