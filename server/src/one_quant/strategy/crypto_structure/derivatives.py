"""
加密专属结构分析 — 衍生品结构
"""

from __future__ import annotations

from decimal import Decimal


class DerivativesStructure:
    """衍生品结构分析。

    分析合约市场的结构性指标：
    - 资金费率极值
    - OI 变化
    - 清算热力图
    """

    FUNDING_EXTREME_HIGH = Decimal("0.001")
    FUNDING_EXTREME_LOW = Decimal("-0.001")

    def funding_rate_extreme(self, rate: Decimal) -> dict:
        """资金费率极值分析。"""
        annualized = rate * Decimal("3") * Decimal("365")

        if rate >= self.FUNDING_EXTREME_HIGH:
            level = "extreme_high"
            signal = "bearish"
            intensity = min(float(rate / self.FUNDING_EXTREME_HIGH), 1.0)
        elif rate >= self.FUNDING_EXTREME_HIGH / 2:
            level = "high"
            signal = "bearish"
            intensity = float(rate / self.FUNDING_EXTREME_HIGH) * 0.5
        elif rate <= self.FUNDING_EXTREME_LOW:
            level = "extreme_low"
            signal = "bullish"
            intensity = min(float(abs(rate) / abs(self.FUNDING_EXTREME_LOW)), 1.0)
        elif rate <= self.FUNDING_EXTREME_LOW / 2:
            level = "low"
            signal = "bullish"
            intensity = float(abs(rate) / abs(self.FUNDING_EXTREME_LOW)) * 0.5
        else:
            level = "normal"
            signal = "neutral"
            intensity = 0.0

        return {
            "level": level,
            "signal": signal,
            "intensity": round(intensity, 4),
            "annualized": str(annualized.quantize(Decimal("0.0001"))),
        }

    def oi_change(self, oi_data: list[dict]) -> dict:
        """OI（Open Interest）变化分析。"""
        if len(oi_data) < 2:
            return {
                "current_oi": "0",
                "change": "0",
                "change_pct": "0",
                "price_direction": "flat",
                "signal": "neutral",
                "interpretation": "数据不足",
            }

        current = oi_data[-1]
        prev = oi_data[-2]

        current_oi = Decimal(str(current["oi"]))
        prev_oi = Decimal(str(prev["oi"]))
        current_price = Decimal(str(current["price"]))
        prev_price = Decimal(str(prev["price"]))

        oi_change_val = current_oi - prev_oi
        oi_change_pct = (oi_change_val / prev_oi * 100) if prev_oi > 0 else Decimal("0")

        price_change = current_price - prev_price
        if price_change > 0:
            price_dir = "up"
        elif price_change < 0:
            price_dir = "down"
        else:
            price_dir = "flat"

        if oi_change_val > 0 and price_dir == "up":
            signal = "bullish"
            interpretation = "OI增+价涨：新多头入场，上涨趋势延续"
        elif oi_change_val > 0 and price_dir == "down":
            signal = "bearish"
            interpretation = "OI增+价跌：新空头入场，下跌趋势延续"
        elif oi_change_val < 0 and price_dir == "up":
            signal = "bullish_weak"
            interpretation = "OI减+价涨：空头平仓反弹，非趋势性上涨"
        elif oi_change_val < 0 and price_dir == "down":
            signal = "bearish_weak"
            interpretation = "OI减+价跌：多头平仓回调，非趋势性下跌"
        else:
            signal = "neutral"
            interpretation = "OI和价格无明显方向"

        return {
            "current_oi": str(current_oi.quantize(Decimal("0.01"))),
            "change": str(oi_change_val.quantize(Decimal("0.01"))),
            "change_pct": str(oi_change_pct.quantize(Decimal("0.01"))),
            "price_direction": price_dir,
            "signal": signal,
            "interpretation": interpretation,
        }

    def liquidation_heatmap(
        self,
        positions: list[dict],
        price_bins: int = 50,
    ) -> dict:
        """清算热力图。"""
        if not positions:
            return {"heatmap": {}, "high_density_zones": [], "signal": "neutral"}

        liq_prices = [Decimal(str(p["liquidation_price"])) for p in positions]
        min_price = min(liq_prices)
        max_price = max(liq_prices)

        if min_price == max_price:
            total_size = sum(Decimal(str(p["size"])) for p in positions)
            return {
                "heatmap": {str(min_price): str(total_size)},
                "high_density_zones": [
                    {
                        "price": str(min_price),
                        "volume": str(total_size),
                        "side": positions[0]["side"],
                    }
                ],
                "signal": "neutral",
            }

        bin_size = (max_price - min_price) / Decimal(price_bins)

        heatmap: dict[Decimal, Decimal] = {}
        side_map: dict[Decimal, str] = {}

        for p in positions:
            liq = Decimal(str(p["liquidation_price"]))
            size = Decimal(str(p["size"]))
            bin_idx = min(
                int((liq - min_price) / bin_size),
                price_bins - 1,
            )
            bin_price = min_price + bin_size * Decimal(bin_idx) + bin_size / 2
            heatmap[bin_price] = heatmap.get(bin_price, Decimal("0")) + size
            if bin_price not in side_map:
                side_map[bin_price] = p["side"]

        if not heatmap:
            return {"heatmap": {}, "high_density_zones": [], "signal": "neutral"}

        sorted_zones = sorted(heatmap.items(), key=lambda x: x[1], reverse=True)
        top_count = max(1, len(sorted_zones) // 10)
        high_density = [
            {
                "price": str(p.quantize(Decimal("0.01"))),
                "volume": str(v.quantize(Decimal("0.01"))),
                "side": side_map.get(p, "unknown"),
            }
            for p, v in sorted_zones[:top_count]
        ]

        long_zones = [z for z in high_density if z["side"] == "long"]
        short_zones = [z for z in high_density if z["side"] == "short"]

        if len(long_zones) > len(short_zones):
            signal = "bearish"
        elif len(short_zones) > len(long_zones):
            signal = "bullish"
        else:
            signal = "neutral"

        return {
            "heatmap": {
                str(p.quantize(Decimal("0.01"))): str(v.quantize(Decimal("0.01")))
                for p, v in sorted(heatmap.items())
            },
            "high_density_zones": high_density,
            "signal": signal,
        }
