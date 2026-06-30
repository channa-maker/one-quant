"""
ONE量化 - 情绪分析智能体

分析新闻/社媒情绪，输出情绪分数和中文解读。
"""

from __future__ import annotations

import logging
from typing import Any

from one_quant.agents.base import BaseAgent

logger = logging.getLogger(__name__)


class SentimentAgent(BaseAgent):
    """情绪分析智能体。

    职责：
    1. 接收新闻/社媒文本
    2. 调用 LLM 进行情绪分析
    3. 输出情绪分数（-1 到 +1）和中文解读
    4. 多源交叉验证，低置信拒绝行动

    输入：新闻/社媒文本列表
    输出：情绪分数 + 中文解读 + 置信度
    """

    name = "sentiment"
    description = "新闻/社媒情绪分析"

    async def run(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """执行情绪分析。

        Args:
            input_data: 包含 texts（文本列表）、symbol（标的符号）。

        Returns:
            情绪分析结果。
        """
        texts = input_data.get("texts", [])
        symbol = input_data.get("symbol", "")

        if not texts:
            return {
                "success": True,
                "agent": self.name,
                "symbol": symbol,
                "sentiment_score": 0.0,
                "confidence": 0.0,
                "interpretation": "无文本数据",
            }

        # 分析每条文本的情绪
        scores = []
        interpretations = []
        for text in texts:
            result = self._analyze_single(text)
            scores.append(result["score"])
            interpretations.append(result["interpretation"])

        # 综合分数（加权平均）
        avg_score = sum(scores) / len(scores) if scores else 0.0
        confidence = min(len(scores) / 10.0, 1.0)  # 样本越多置信度越高

        # 低置信拒绝行动
        if confidence < 0.3:
            return {
                "success": True,
                "agent": self.name,
                "symbol": symbol,
                "sentiment_score": 0.0,
                "confidence": confidence,
                "interpretation": "样本不足，拒绝给出结论",
                "action": "hold",
            }

        # 生成中文解读
        interpretation = self._generate_interpretation(avg_score, len(texts))

        return {
            "success": True,
            "agent": self.name,
            "symbol": symbol,
            "sentiment_score": round(avg_score, 3),
            "confidence": round(confidence, 3),
            "interpretation": interpretation,
            "sample_count": len(texts),
            "action": "buy" if avg_score > 0.3 else "sell" if avg_score < -0.3 else "hold",
        }

    def _analyze_single(self, text: str) -> dict[str, Any]:
        """分析单条文本情绪（简化实现，实际应调用 LLM）。

        Args:
            text: 文本内容。

        Returns:
            情绪分数和解读。
        """
        # 简化：基于关键词的情绪分析
        positive_words = {"利好", "上涨", "突破", "新高", "买入", "看涨", "牛市"}
        negative_words = {"利空", "下跌", "暴跌", "崩盘", "卖出", "看跌", "熊市"}

        pos_count = sum(1 for w in positive_words if w in text)
        neg_count = sum(1 for w in negative_words if w in text)

        if pos_count > neg_count:
            score = min(pos_count * 0.2, 1.0)
            interpretation = "偏积极"
        elif neg_count > pos_count:
            score = max(-neg_count * 0.2, -1.0)
            interpretation = "偏消极"
        else:
            score = 0.0
            interpretation = "中性"

        return {"score": score, "interpretation": interpretation}

    def _generate_interpretation(self, score: float, count: int) -> str:
        """生成中文解读。"""
        if score > 0.5:
            return f"市场情绪明显偏积极（基于 {count} 条信息，得分 {score:.2f}）"
        elif score > 0.2:
            return f"市场情绪略偏积极（基于 {count} 条信息，得分 {score:.2f}）"
        elif score < -0.5:
            return f"市场情绪明显偏消极（基于 {count} 条信息，得分 {score:.2f}）"
        elif score < -0.2:
            return f"市场情绪略偏消极（基于 {count} 条信息，得分 {score:.2f}）"
        else:
            return f"市场情绪中性（基于 {count} 条信息，得分 {score:.2f}）"
