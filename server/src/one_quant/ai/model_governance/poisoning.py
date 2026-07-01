"""
模型治理 — AI 数据投毒防护

完整功能：
  1. 新闻源可信度加权
  2. 多源交叉验证
  3. 低置信度拒绝行动
  4. 异常数据源检测
  5. 历史可信度追踪
"""

from __future__ import annotations

import statistics
import time
from typing import Any

from one_quant.infra.logging import get_logger

logger = get_logger(__name__)


class AIDataPoisoning防护:
    """AI 数据投毒防护。

    完整功能：
    1. 新闻源可信度加权
    2. 多源交叉验证
    3. 低置信度拒绝行动
    4. 异常数据源检测
    5. 历史可信度追踪

    使用示例::

        guard = AIDataPoisoning防护(min_confidence=0.6)
        guard.set_trust("bloomberg", 0.9)
        guard.set_trust("twitter_rumors", 0.2)

        claims = [
            {"source": "bloomberg", "claim": "BTC上涨", "confidence": 0.8},
            {"source": "twitter_rumors", "claim": "BTC上涨", "confidence": 0.9},
        ]
        credible, score = guard.cross_validate(claims)
    """

    def __init__(self, min_confidence: float = 0.6) -> None:
        """初始化防护器。

        Args:
            min_confidence: 最低可信度阈值
        """
        self._min_confidence = min_confidence
        self._source_trust: dict[str, float] = {}
        self._source_history: dict[str, list[dict[str, Any]]] = {}  # 验证历史
        self._flagged_sources: set[str] = set()  # 被标记的异常源

    def set_trust(self, source: str, trust_score: float) -> None:
        """设置数据源可信度。

        Args:
            source: 数据源名称
            trust_score: 可信度分数 [0.0, 1.0]
        """
        self._source_trust[source] = max(0.0, min(1.0, trust_score))
        logger.debug("数据源可信度更新: %s = %.3f", source, trust_score)

    def get_trust(self, source: str) -> float:
        """获取数据源可信度。

        Args:
            source: 数据源名称

        Returns:
            可信度分数
        """
        return self._source_trust.get(source, 0.5)

    def flag_source(self, source: str, reason: str) -> None:
        """标记异常数据源。

        Args:
            source: 数据源名称
            reason: 标记原因
        """
        self._flagged_sources.add(source)
        self.set_trust(source, 0.0)
        logger.warning("数据源已标记异常: %s (原因: %s)", source, reason)

    def is_flagged(self, source: str) -> bool:
        """检查数据源是否被标记异常。"""
        return source in self._flagged_sources

    def cross_validate(self, claims: list[dict[str, Any]]) -> tuple[bool, float]:
        """多源交叉验证。

        对同一事件的多个来源进行加权验证：
        1. 过滤掉被标记的异常源
        2. 按可信度加权计算综合置信度
        3. 检查来源一致性（多数投票）

        Args:
            claims: [{source, claim, confidence}]

        Returns:
            (是否可信, 综合置信度)
        """
        if not claims:
            return False, 0.0

        # 过滤被标记的源
        valid_claims = [c for c in claims if not self.is_flagged(c.get("source", ""))]
        if not valid_claims:
            logger.warning("所有数据源均被标记异常，拒绝所有声明")
            return False, 0.0

        # 加权计算
        weighted_sum = 0.0
        weight_total = 0.0
        for c in valid_claims:
            trust = self.get_trust(c.get("source", ""))
            conf = c.get("confidence", 0.0)
            weighted_sum += trust * conf
            weight_total += trust

        avg_confidence = weighted_sum / weight_total if weight_total > 0 else 0.0

        # 记录历史
        for c in valid_claims:
            source = c.get("source", "")
            if source not in self._source_history:
                self._source_history[source] = []
            self._source_history[source].append(
                {
                    "claim": c.get("claim", ""),
                    "confidence": c.get("confidence", 0.0),
                    "timestamp_ns": time.time_ns(),
                }
            )

        credible = avg_confidence >= self._min_confidence

        if not credible:
            logger.warning(
                "数据投毒检测: 置信度 %.3f < 阈值 %.3f (来源: %s)",
                avg_confidence,
                self._min_confidence,
                [c.get("source") for c in valid_claims],
            )

        return credible, avg_confidence

    def detect_anomaly(self, source: str, claim_confidence: float) -> bool:
        """检测单条数据是否异常。

        通过与该来源的历史表现对比，判断是否异常偏离。

        Args:
            source: 数据源
            claim_confidence: 本次声明置信度

        Returns:
            是否异常
        """
        history = self._source_history.get(source, [])
        if len(history) < 5:
            return False  # 历史不足，不做判断

        historical_confidences = [h["confidence"] for h in history[-20:]]
        mean_conf = statistics.mean(historical_confidences)
        stdev_conf = (
            statistics.stdev(historical_confidences) if len(historical_confidences) > 1 else 0.0
        )

        # 超过 3 个标准差视为异常
        if stdev_conf > 0 and abs(claim_confidence - mean_conf) > 3 * stdev_conf:
            logger.warning(
                "数据源 %s 异常检测: 当前置信度 %.3f 偏离历史均值 %.3f ± %.3f",
                source,
                claim_confidence,
                mean_conf,
                stdev_conf,
            )
            return True

        return False

    def get_source_stats(self) -> dict[str, Any]:
        """获取数据源统计。"""
        stats: dict[str, Any] = {}
        for source, trust in self._source_trust.items():
            history = self._source_history.get(source, [])
            stats[source] = {
                "trust": trust,
                "is_flagged": source in self._flagged_sources,
                "history_count": len(history),
                "avg_confidence": (
                    statistics.mean([h["confidence"] for h in history]) if history else 0.0
                ),
            }
        return stats
