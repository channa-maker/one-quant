"""
SMC — 结构分析器
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from one_quant.core.types import Kline


class SMCAnalyzer:
    """SMC 结构分析器。

    提供以下结构因子：
    - BOS: Break of Structure（市场结构破坏）
    - CHoCH: Change of Character（趋势转换信号）
    - Order Block: 订单块（机构挂单区域）
    - Fair Value Gap (FVG): 公允价值缺口
    - 流动性池: 等高/等低点止损聚集区
    - 流动性猎杀: 假突破扫止损后反转
    - 溢价/折价区: 基于近期波段的价格位置判断
    """

    SWING_LOOKBACK = 5
    OB_LOOKBACK = 20
    FVG_MIN_GAP_RATIO = 0.001
    LIQUIDITY_TOLERANCE = Decimal("0.002")

    def __init__(self) -> None:
        self._trend: dict[str, str] = {}
        self._last_bos: dict[str, dict[str, Any] | None] = {}
        self._last_choch: dict[str, dict[str, Any] | None] = {}

    # ──────────────── Swing 高低点识别 ────────────────

    def _find_swing_highs(
        self, highs: list[Decimal], lookback: int = SWING_LOOKBACK
    ) -> list[dict[str, Any]]:
        """识别 Swing 高点（局部极值）。"""
        swings: list[dict[str, Any]] = []
        for i in range(lookback, len(highs) - lookback):
            is_highest = all(
                highs[i] >= highs[j] for j in range(i - lookback, i + lookback + 1) if j != i
            )
            if is_highest:
                swings.append({"index": i, "price": highs[i]})
        return swings

    def _find_swing_lows(
        self, lows: list[Decimal], lookback: int = SWING_LOOKBACK
    ) -> list[dict[str, Any]]:
        """识别 Swing 低点（局部极值）。"""
        swings: list[dict[str, Any]] = []
        for i in range(lookback, len(lows) - lookback):
            is_lowest = all(
                lows[i] <= lows[j] for j in range(i - lookback, i + lookback + 1) if j != i
            )
            if is_lowest:
                swings.append({"index": i, "price": lows[i]})
        return swings

    # ──────────────── BOS 市场结构破坏 ────────────────

    def detect_bos(self, highs: list[Decimal], lows: list[Decimal]) -> dict[str, Any] | None:
        """BOS（Break of Structure）— 市场结构破坏。"""
        if len(highs) < 15 or len(lows) < 15:
            return None

        swing_highs = self._find_swing_highs(highs)
        swing_lows = self._find_swing_lows(lows)

        if len(swing_highs) < 2 or len(swing_lows) < 2:
            return None

        current_high = highs[-1]
        current_low = lows[-1]

        prev_sh = swing_highs[-2]
        if current_high > prev_sh["price"]:
            return {
                "type": "bullish_bos",
                "price": str(current_high),
                "swing_price": str(prev_sh["price"]),
                "index": len(highs) - 1,
                "swing_index": prev_sh["index"],
            }

        prev_sl = swing_lows[-2]
        if current_low < prev_sl["price"]:
            return {
                "type": "bearish_bos",
                "price": str(current_low),
                "swing_price": str(prev_sl["price"]),
                "index": len(lows) - 1,
                "swing_index": prev_sl["index"],
            }

        return None

    # ──────────────── CHoCH 趋势转换 ────────────────

    def detect_choch(
        self, highs: list[Decimal], lows: list[Decimal], trend: str
    ) -> dict[str, Any] | None:
        """CHoCH（Change of Character）— 趋势转换信号。"""
        if len(highs) < 15 or len(lows) < 15:
            return None

        swing_highs = self._find_swing_highs(highs)
        swing_lows = self._find_swing_lows(lows)

        current_high = highs[-1]
        current_low = lows[-1]

        if trend == "bullish" and swing_lows:
            last_sl = swing_lows[-1]
            if current_low < last_sl["price"]:
                return {
                    "type": "bearish_choch",
                    "price": str(current_low),
                    "swing_price": str(last_sl["price"]),
                    "index": len(lows) - 1,
                    "swing_index": last_sl["index"],
                    "prev_trend": trend,
                }

        elif trend == "bearish" and swing_highs:
            last_sh = swing_highs[-1]
            if current_high > last_sh["price"]:
                return {
                    "type": "bullish_choch",
                    "price": str(current_high),
                    "swing_price": str(last_sh["price"]),
                    "index": len(highs) - 1,
                    "swing_index": last_sh["index"],
                    "prev_trend": trend,
                }

        return None

    # ──────────────── Order Block 订单块 ────────────────

    def find_order_blocks(self, klines: list[Kline]) -> list[dict[str, Any]]:
        """Order Block 订单块识别。"""
        if len(klines) < 5:
            return []

        order_blocks: list[dict[str, Any]] = []

        for i in range(2, len(klines) - 1):
            k = klines[i]
            k_prev = klines[i - 1]
            k_next = klines[i + 1]

            body_prev = k_prev.close - k_prev.open
            body_next = k_next.close - k_next.open

            if body_prev < 0 and body_next > 0:
                if k_next.close > k.open and k_next.open < k.close:
                    ob_top = max(k.open, k.close)
                    ob_bottom = min(k.open, k.close)
                    strength = float(abs(body_next) / k_next.close) if k_next.close > 0 else 0
                    order_blocks.append(
                        {
                            "type": "bullish_ob",
                            "top": str(ob_top),
                            "bottom": str(ob_bottom),
                            "index": i,
                            "strength": min(strength * 100, 1.0),
                            "volume": str(k.volume),
                        }
                    )

            elif body_prev > 0 and body_next < 0:
                if k_next.close < k.open and k_next.open > k.close:
                    ob_top = max(k.open, k.close)
                    ob_bottom = min(k.open, k.close)
                    strength = float(abs(body_next) / k_next.close) if k_next.close > 0 else 0
                    order_blocks.append(
                        {
                            "type": "bearish_ob",
                            "top": str(ob_top),
                            "bottom": str(ob_bottom),
                            "index": i,
                            "strength": min(strength * 100, 1.0),
                            "volume": str(k.volume),
                        }
                    )

        return order_blocks[-10:]

    # ──────────────── Fair Value Gap (FVG) ────────────────

    def find_fvg(self, klines: list[Kline]) -> list[dict[str, Any]]:
        """Fair Value Gap 公允价值缺口识别。"""
        if len(klines) < 3:
            return []

        fvgs: list[dict[str, Any]] = []

        for i in range(2, len(klines)):
            k1 = klines[i - 2]
            k3 = klines[i]

            if k3.low > k1.high:
                gap = k3.low - k1.high
                gap_ratio = float(gap / k1.high) if k1.high > 0 else 0
                if gap_ratio >= self.FVG_MIN_GAP_RATIO:
                    fvgs.append(
                        {
                            "type": "bullish_fvg",
                            "top": str(k3.low),
                            "bottom": str(k1.high),
                            "index": i,
                            "gap_size": str(gap),
                            "gap_ratio": round(gap_ratio, 6),
                        }
                    )

            elif k3.high < k1.low:
                gap = k1.low - k3.high
                gap_ratio = float(gap / k1.low) if k1.low > 0 else 0
                if gap_ratio >= self.FVG_MIN_GAP_RATIO:
                    fvgs.append(
                        {
                            "type": "bearish_fvg",
                            "top": str(k1.low),
                            "bottom": str(k3.high),
                            "index": i,
                            "gap_size": str(gap),
                            "gap_ratio": round(gap_ratio, 6),
                        }
                    )

        return fvgs[-10:]

    # ──────────────── 流动性池 ────────────────

    def find_liquidity_pools(
        self, highs: list[Decimal], lows: list[Decimal]
    ) -> list[dict[str, Any]]:
        """流动性池识别：等高/等低点止损聚集区。"""
        swing_highs = self._find_swing_highs(highs)
        swing_lows = self._find_swing_lows(lows)

        pools: list[dict[str, Any]] = []

        used_highs: set[int] = set()
        for i, sh in enumerate(swing_highs):
            if i in used_highs:
                continue
            cluster = [sh]
            used_highs.add(i)
            for j in range(i + 1, len(swing_highs)):
                if j in used_highs:
                    continue
                if (
                    abs(swing_highs[j]["price"] - sh["price"]) / sh["price"]
                    < self.LIQUIDITY_TOLERANCE
                ):
                    cluster.append(swing_highs[j])
                    used_highs.add(j)

            if len(cluster) >= 2:
                avg_price = sum(c["price"] for c in cluster) / Decimal(len(cluster))
                pools.append(
                    {
                        "type": "sell_side_liquidity",
                        "price": str(avg_price),
                        "touch_count": len(cluster),
                        "indices": [c["index"] for c in cluster],
                    }
                )

        used_lows: set[int] = set()
        for i, sl in enumerate(swing_lows):
            if i in used_lows:
                continue
            cluster = [sl]
            used_lows.add(i)
            for j in range(i + 1, len(swing_lows)):
                if j in used_lows:
                    continue
                if (
                    abs(swing_lows[j]["price"] - sl["price"]) / sl["price"]
                    < self.LIQUIDITY_TOLERANCE
                ):
                    cluster.append(swing_lows[j])
                    used_lows.add(j)

            if len(cluster) >= 2:
                avg_price = sum(c["price"] for c in cluster) / Decimal(len(cluster))
                pools.append(
                    {
                        "type": "buy_side_liquidity",
                        "price": str(avg_price),
                        "touch_count": len(cluster),
                        "indices": [c["index"] for c in cluster],
                    }
                )

        return pools

    # ──────────────── 流动性猎杀 ────────────────

    def detect_liquidity_grab(
        self, klines: list[Kline], pools: list[dict[str, Any]]
    ) -> dict[str, Any] | None:
        """流动性猎杀检测：假突破扫止损后反转。"""
        if len(klines) < 3 or not pools:
            return None

        k_current = klines[-1]
        k_prev = klines[-2]

        for pool in pools:
            pool_price = Decimal(pool["price"])

            if pool["type"] == "sell_side_liquidity":
                if k_prev.high > pool_price and k_current.close < pool_price:
                    upper_wick = k_prev.high - max(k_prev.open, k_prev.close)
                    body = abs(k_prev.close - k_prev.open)
                    if body == 0 or upper_wick > body:
                        return {
                            "type": "sell_side_grab",
                            "pool_price": str(pool_price),
                            "grab_high": str(k_prev.high),
                            "close": str(k_current.close),
                            "reversal_strength": float(
                                (k_prev.high - k_current.close) / k_current.close
                            )
                            if k_current.close > 0
                            else 0,
                            "signal": "bullish",
                        }

            elif pool["type"] == "buy_side_liquidity":
                if k_prev.low < pool_price and k_current.close > pool_price:
                    lower_wick = min(k_prev.open, k_prev.close) - k_prev.low
                    body = abs(k_prev.close - k_prev.open)
                    if body == 0 or lower_wick > body:
                        return {
                            "type": "buy_side_grab",
                            "pool_price": str(pool_price),
                            "grab_low": str(k_prev.low),
                            "close": str(k_current.close),
                            "reversal_strength": float(
                                (k_current.close - k_prev.low) / k_current.close
                            )
                            if k_current.close > 0
                            else 0,
                            "signal": "bearish",
                        }

        return None

    # ──────────────── 溢价/折价区 ────────────────

    def premium_discount(self, klines: list[Kline]) -> str:
        """溢价/折价区判断。"""
        if len(klines) < 20:
            return "equilibrium"

        recent = klines[-20:]
        highest = max(k.high for k in recent)
        lowest = min(k.low for k in recent)

        if highest == lowest:
            return "equilibrium"

        current = klines[-1].close
        position = (current - lowest) / (highest - lowest)

        if position > Decimal("0.6"):
            return "premium"
        elif position < Decimal("0.4"):
            return "discount"
        else:
            return "equilibrium"

    # ──────────────── 趋势管理 ────────────────

    def update_trend(self, symbol: str, highs: list[Decimal], lows: list[Decimal]) -> str:
        """更新并返回当前趋势。"""
        if len(highs) < 10 or len(lows) < 10:
            return self._trend.get(symbol, "bullish")

        swing_highs = self._find_swing_highs(highs)
        swing_lows = self._find_swing_lows(lows)

        if len(swing_highs) < 2 or len(swing_lows) < 2:
            return self._trend.get(symbol, "bullish")

        higher_high = swing_highs[-1]["price"] > swing_highs[-2]["price"]
        higher_low = swing_lows[-1]["price"] > swing_lows[-2]["price"]
        lower_high = swing_highs[-1]["price"] < swing_highs[-2]["price"]
        lower_low = swing_lows[-1]["price"] < swing_lows[-2]["price"]

        if higher_high and higher_low:
            self._trend[symbol] = "bullish"
        elif lower_high and lower_low:
            self._trend[symbol] = "bearish"

        return self._trend.get(symbol, "bullish")
