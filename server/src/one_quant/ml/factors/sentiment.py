"""
因子库 — 情绪因子与事件因子
"""

from __future__ import annotations

import math


class SentimentScoreFactor:
    """新闻情绪因子。

    命名：sentiment_score
    计算：基于关键词的简易情绪打分（-1 到 1）
    注意：生产环境应替换为 NLP 模型推理
    """

    # 简易情绪词典
    _POSITIVE_WORDS = {
        "利好",
        "上涨",
        "突破",
        "新高",
        "暴涨",
        "牛市",
        "盈利",
        "增长",
        "bullish",
        "surge",
        "rally",
        "breakout",
        "gain",
        "profit",
        "rise",
    }
    _NEGATIVE_WORDS = {
        "利空",
        "下跌",
        "暴跌",
        "新低",
        "崩盘",
        "熊市",
        "亏损",
        "衰退",
        "bearish",
        "crash",
        "dump",
        "loss",
        "decline",
        "fall",
        "panic",
    }

    def __init__(self) -> None:
        self.name = "sentiment_score"

    def compute(self, news_texts: list[str]) -> float | None:
        """计算情绪分数。

        Args:
            news_texts: 新闻文本列表。

        Returns:
            情绪分数 [-1, 1]，无数据返回 None。
        """
        if not news_texts:
            return None

        total_score = 0.0
        scored_count = 0

        for text in news_texts:
            text_lower = text.lower()
            pos = sum(1 for w in self._POSITIVE_WORDS if w in text_lower)
            neg = sum(1 for w in self._NEGATIVE_WORDS if w in text_lower)
            total = pos + neg
            if total > 0:
                total_score += (pos - neg) / total
                scored_count += 1

        if scored_count == 0:
            return 0.0  # 无情绪词，视为中性

        return round(total_score / scored_count, 4)


class EventCalendarProximityFactor:
    """事件日历临近度因子。

    命名：event_calendar_proximity
    计算：距离事件的天数越近，因子值越大（指数衰减）
    """

    def __init__(self) -> None:
        self.name = "event_calendar_proximity"

    def compute(self, event_date: int, current_date: int) -> float | None:
        """计算事件临近度。

        Args:
            event_date: 事件日期（YYYYMMDD 或 Unix timestamp 天）。
            current_date: 当前日期（同格式）。

        Returns:
            临近度 [0, 1]，1=当天，指数衰减。已过期返回 None。
        """
        diff = event_date - current_date
        if diff < 0:
            return None  # 事件已过

        # 指数衰减：e^(-diff/7)，7 天半衰期
        proximity = math.exp(-diff / 7.0)
        return round(proximity, 4)
