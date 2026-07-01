"""
加密专属结构分析 — 期权结构
"""

from __future__ import annotations

from decimal import Decimal


class OptionStructure:
    """期权结构分析。

    分析期权市场的结构性指标：
    - Max Pain: 期权到期时让最多期权作废的价格
    - GEX: Gamma 暴露
    - PCR: Put/Call Ratio
    - IV Skew: 隐含波动率偏斜
    """

    def max_pain(self, chain: list[dict]) -> Decimal:
        """Max Pain（最大痛苦价）计算。"""
        if not chain:
            return Decimal("0")

        strikes = sorted(set(Decimal(str(c["strike"])) for c in chain))

        if len(strikes) < 2:
            return strikes[0] if strikes else Decimal("0")

        min_pain = Decimal("infinity")
        max_pain_price = strikes[0]

        for test_price in strikes:
            total_pain = Decimal("0")

            for c in chain:
                strike = Decimal(str(c["strike"]))
                oi = Decimal(str(c.get("open_interest", 0)))
                option_type = c.get("type", "call")

                if option_type == "call":
                    intrinsic = max(Decimal("0"), test_price - strike)
                else:
                    intrinsic = max(Decimal("0"), strike - test_price)

                total_pain += intrinsic * oi

            if total_pain < min_pain:
                min_pain = total_pain
                max_pain_price = test_price

        return max_pain_price

    def gex_exposure(self, chain: list[dict], spot_price: Decimal) -> dict:
        """GEX（Gamma Exposure）计算。"""
        if not chain:
            return {
                "total_gex": "0",
                "positive_gex": "0",
                "negative_gex": "0",
                "net_gex": "0",
                "regime": "neutral",
                "call_wall": "0",
                "put_wall": "0",
            }

        total_gex = Decimal("0")
        pos_gex = Decimal("0")
        neg_gex = Decimal("0")
        call_gamma_map: dict[Decimal, Decimal] = {}
        put_gamma_map: dict[Decimal, Decimal] = {}

        for c in chain:
            strike = Decimal(str(c["strike"]))
            oi = Decimal(str(c.get("open_interest", 0)))
            gamma = Decimal(str(c.get("gamma", 0)))
            option_type = c.get("type", "call")

            gex = gamma * oi * spot_price * spot_price / Decimal("100")

            if option_type == "call":
                total_gex += gex
                pos_gex += gex
                call_gamma_map[strike] = call_gamma_map.get(strike, Decimal("0")) + gex
            else:
                total_gex -= gex
                neg_gex += gex
                put_gamma_map[strike] = put_gamma_map.get(strike, Decimal("0")) + gex

        net_gex = pos_gex - neg_gex
        if net_gex > 0:
            regime = "stabilizing"
        elif net_gex < 0:
            regime = "amplifying"
        else:
            regime = "neutral"

        call_wall = (
            max(call_gamma_map.keys(), key=lambda k: call_gamma_map[k])
            if call_gamma_map
            else Decimal("0")
        )
        put_wall = (
            max(put_gamma_map.keys(), key=lambda k: put_gamma_map[k])
            if put_gamma_map
            else Decimal("0")
        )

        return {
            "total_gex": str(total_gex.quantize(Decimal("0.01"))),
            "positive_gex": str(pos_gex.quantize(Decimal("0.01"))),
            "negative_gex": str(neg_gex.quantize(Decimal("0.01"))),
            "net_gex": str(net_gex.quantize(Decimal("0.01"))),
            "regime": regime,
            "call_wall": str(call_wall),
            "put_wall": str(put_wall),
        }

    def put_call_ratio(self, chain: list[dict]) -> dict:
        """Put/Call Ratio（PCR）。"""
        call_oi = sum(
            Decimal(str(c.get("open_interest", 0))) for c in chain if c.get("type") == "call"
        )
        put_oi = sum(
            Decimal(str(c.get("open_interest", 0))) for c in chain if c.get("type") == "put"
        )
        call_vol = sum(Decimal(str(c.get("volume", 0))) for c in chain if c.get("type") == "call")
        put_vol = sum(Decimal(str(c.get("volume", 0))) for c in chain if c.get("type") == "put")

        oi_ratio = float(put_oi / call_oi) if call_oi > 0 else 0.0
        vol_ratio = float(put_vol / call_vol) if call_vol > 0 else 0.0

        if oi_ratio > 1.5:
            sentiment = "fear"
            extreme = True
        elif oi_ratio > 1.0:
            sentiment = "fear"
            extreme = False
        elif oi_ratio < 0.5:
            sentiment = "greed"
            extreme = True
        elif oi_ratio < 1.0:
            sentiment = "greed"
            extreme = False
        else:
            sentiment = "neutral"
            extreme = False

        return {
            "oi_ratio": round(oi_ratio, 4),
            "volume_ratio": round(vol_ratio, 4),
            "sentiment": sentiment,
            "extreme": extreme,
        }

    def iv_skew(self, chain: list[dict]) -> dict:
        """IV 偏斜（隐含波动率偏斜）。"""
        if not chain:
            return {
                "skew": 0.0,
                "put_wing_iv": "0",
                "call_wing_iv": "0",
                "atm_iv": "0",
                "interpretation": "数据不足",
            }

        strikes = sorted(set(Decimal(str(c["strike"])) for c in chain))
        if not strikes:
            return {
                "skew": 0.0,
                "put_wing_iv": "0",
                "call_wing_iv": "0",
                "atm_iv": "0",
                "interpretation": "无有效行权价",
            }

        atm_price = strikes[len(strikes) // 2]

        otm_puts = [c for c in chain if Decimal(str(c["strike"])) < atm_price * Decimal("0.95")]
        otm_calls = [c for c in chain if Decimal(str(c["strike"])) > atm_price * Decimal("1.05")]
        atm_options = [
            c
            for c in chain
            if (
                atm_price * Decimal("0.95")
                <= Decimal(str(c["strike"]))
                <= atm_price * Decimal("1.05")
            )
        ]

        def avg_iv(options: list[dict]) -> Decimal:
            if not options:
                return Decimal("0")
            ivs = [Decimal(str(c.get("iv", 0))) for c in options]
            return sum(ivs) / Decimal(len(ivs))

        put_wing_iv = avg_iv(otm_puts)
        call_wing_iv = avg_iv(otm_calls)
        atm_iv = avg_iv(atm_options)

        skew = float(put_wing_iv - call_wing_iv)

        if skew > 0.05:
            interpretation = "正偏斜：市场恐慌，下行保护溢价高"
        elif skew < -0.05:
            interpretation = "负偏斜：市场贪婪，上行押注溢价高"
        else:
            interpretation = "偏斜中性：市场情绪平稳"

        return {
            "skew": round(skew, 4),
            "put_wing_iv": str(put_wing_iv.quantize(Decimal("0.0001"))),
            "call_wing_iv": str(call_wing_iv.quantize(Decimal("0.0001"))),
            "atm_iv": str(atm_iv.quantize(Decimal("0.0001"))),
            "interpretation": interpretation,
        }
