"""
加密专属结构分析 — 策略融合层
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any


class StrategyFusion:
    """策略融合层 — 四层共振。

    将四个维度的信号融合为最终交易决策：
    1. 订单流（微观）
    2. SMC（中观）
    3. 因子/ML（统计）
    4. LLM（消息面）
    """

    WEIGHTS = {
        "order_flow": 0.30,
        "smc": 0.30,
        "ml": 0.25,
        "llm": 0.15,
    }

    def fuse(
        self,
        order_flow: dict[str, Any],
        smc: dict[str, Any],
        ml_score: float,
        llm_signal: dict[str, Any],
    ) -> dict[str, Any]:
        """四层信号融合。"""
        layers: dict[str, dict[str, Any]] = {
            "order_flow": {
                "side": order_flow.get("side", "neutral"),
                "strength": order_flow.get("strength", 0.0),
            },
            "smc": {
                "side": smc.get("side", "neutral"),
                "strength": smc.get("strength", 0.0),
            },
            "ml": {
                "side": "buy" if ml_score > 0.1 else ("sell" if ml_score < -0.1 else "neutral"),
                "strength": abs(ml_score),
            },
            "llm": {
                "side": llm_signal.get("side", "neutral"),
                "strength": llm_signal.get("confidence", 0.0),
            },
        }

        buy_score = Decimal("0")
        sell_score = Decimal("0")

        for name, layer in layers.items():
            weight = Decimal(str(self.WEIGHTS.get(name, 0.25)))
            if layer["side"] == "buy":
                buy_score += weight * Decimal(str(layer["strength"]))
            elif layer["side"] == "sell":
                sell_score += weight * Decimal(str(layer["strength"]))

        if buy_score > sell_score and buy_score > Decimal("0.1"):
            final_side = "buy"
            final_strength = float(buy_score)
        elif sell_score > buy_score and sell_score > Decimal("0.1"):
            final_side = "sell"
            final_strength = float(sell_score)
        else:
            final_side = "neutral"
            final_strength = 0.0

        agreeing = sum(
            1
            for layer in layers.values()
            if layer["side"] == final_side and layer["side"] != "neutral"
        )

        llm_veto = False
        llm_side = layers["llm"]["side"]
        llm_conf = layers["llm"]["strength"]

        if final_side != "neutral" and llm_side != "neutral" and llm_side != final_side:
            if llm_conf > 0.8 and agreeing <= 2:
                llm_veto = True
                final_side = "neutral"
                final_strength = 0.0

        if agreeing >= 3:
            confidence = "high"
        elif agreeing >= 2:
            confidence = "medium"
        else:
            confidence = "low"

        return {
            "side": final_side,
            "strength": round(min(final_strength, 1.0), 4),
            "confidence": confidence,
            "layers_agreed": agreeing,
            "llm_veto": llm_veto,
            "detail": {
                "buy_score": str(buy_score.quantize(Decimal("0.0001"))),
                "sell_score": str(sell_score.quantize(Decimal("0.0001"))),
                "layers": {
                    name: {"side": layer["side"], "strength": round(layer["strength"], 4)}
                    for name, layer in layers.items()
                },
            },
        }
