"""AI 信号推荐与评分系统 — 共振融合 + 评分引擎"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Protocol

from one_quant.core.types import Signal
from one_quant.infra.logging import get_logger

logger = get_logger(__name__)


class SignalSource(Protocol):
    """信号源协议（插件化）"""
    name: str
    weight: float  # 权重 0-1
    max_contribution: float  # 单源最大贡献（封顶）

    async def extract(self, symbol: str, data: dict[str, Any]) -> float:
        """提取子信号分数 (0-1)"""
        ...


@dataclass
class SignalCard:
    """信号卡 — AI 推荐的完整信息"""
    symbol: str
    score: float  # 综合评分 0-1
    direction: str  # buy / sell / hold
    confidence: float  # 置信度
    sources: dict[str, float] = field(default_factory=dict)  # 各源分数
    reason_zh: str = ""
    timestamp_ns: int = 0

    def __post_init__(self) -> None:
        if self.timestamp_ns == 0:
            self.timestamp_ns = time.time_ns()


class SignalScoringEngine:
    """信号评分引擎。

    多源共振融合：
    1. 各信号源独立打分
    2. 加权融合（单源封顶防止单点主导）
    3. 冲突衰减（多空分歧时降低置信度）
    4. 评分校准（Isotonic/Platt）
    """

    def __init__(self) -> None:
        self._sources: dict[str, SignalSource] = {}
        self._calibrator: Any = None

    def register_source(self, source: SignalSource) -> None:
        """注册信号源"""
        self._sources[source.name] = source
        logger.info("信号源注册: %s (权重=%.2f)", source.name, source.weight)

    async def score(self, symbol: str, data: dict[str, Any]) -> SignalCard:
        """计算综合评分

        Args:
            symbol: 标的符号
            data: 输入数据

        Returns:
            信号卡
        """
        scores: dict[str, float] = {}

        for name, source in self._sources.items():
            try:
                raw_score = await source.extract(symbol, data)
                # 单源封顶
                capped = min(raw_score, source.max_contribution)
                scores[name] = capped * source.weight
            except Exception:
                logger.exception("信号源 %s 提取失败", name)
                scores[name] = 0.0

        # 加权融合
        if scores:
            total_weight = sum(s.weight for s in self._sources.values())
            combined = sum(scores.values()) / total_weight if total_weight > 0 else 0.0
        else:
            combined = 0.0

        # 冲突衰减
        values = list(scores.values())
        if len(values) > 1:
            max_val = max(values)
            min_val = min(values)
            if max_val > 0:
                conflict = min_val / max_val
                if conflict > 0.3:
                    combined *= (1 - conflict * 0.5)

        # 方向判定
        if combined > 0.6:
            direction = "buy"
        elif combined < 0.4:
            direction = "sell"
        else:
            direction = "hold"

        return SignalCard(
            symbol=symbol,
            score=combined,
            direction=direction,
            confidence=abs(combined - 0.5) * 2,
            sources=scores,
            reason_zh=f"多源共振评分: {combined:.3f}",
        )
