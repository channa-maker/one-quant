"""信号评分器 — 综合分 = Calibrate(Σ wᵢ · sᵢ · dᵢ)"""

from __future__ import annotations

import time
from decimal import Decimal
from typing import Any

from one_quant.ai.signal_scoring.calibrator import ScoreCalibrator
from one_quant.ai.signal_scoring.models import (
    EvidenceSource,
    ScoreRecord,
    SignalCard,
    classify_signal,
    classify_time_horizon,
)
from one_quant.infra.logging import get_logger

logger = get_logger(__name__)


class SignalScorer:
    """信号评分器 — 综合分 = Calibrate(Σ wᵢ · sᵢ · dᵢ)

    评分流程：
    1. 各证据源独立计算 (strength, direction)
    2. 加权融合：score = Σ wᵢ · sᵢ · |dᵢ|
    3. 共振加成：≥3 独立源同向 → bonus
    4. 单源封顶：防止单源主导
    5. 冲突衰减：矛盾时向中性收敛
    6. 校准：raw_score → calibrated_score（85分≈85%胜率）
    """

    # 默认权重
    DEFAULT_WEIGHTS: dict[str, float] = {
        "order_flow": 0.20,  # 订单流
        "smc": 0.15,  # SMC（Smart Money Concepts）
        "volume_price": 0.15,  # 量价
        "ml_model": 0.15,  # ML 模型
        "llm_analysis": 0.10,  # LLM 分析
        "crypto_structure": 0.15,  # 加密结构
        "onchain": 0.10,  # 链上数据
    }

    # 单源封顶（最大贡献比例）
    SINGLE_SOURCE_CAP: float = 0.35

    # 共振加成参数
    RESONANCE_MIN_SOURCES: int = 3  # 最少同向源数
    RESONANCE_BONUS: float = 0.15  # 共振加成比例

    # 冲突衰减参数
    CONFLICT_THRESHOLD: float = 0.3  # 冲突检测阈值

    def __init__(self, calibrator: ScoreCalibrator | None = None) -> None:
        self._calibrator = calibrator or ScoreCalibrator()
        self._evidence_sources: dict[str, EvidenceSource] = {}
        self._weights: dict[str, float] = dict(self.DEFAULT_WEIGHTS)
        self._score_history: list[ScoreRecord] = []

    def register_source(
        self,
        source: EvidenceSource,
        weight: float | None = None,
    ) -> None:
        """注册证据源

        Args:
            source: 证据源实例
            weight: 自定义权重（None 使用默认值）
        """
        self._evidence_sources[source.name] = source
        if weight is not None:
            self._weights[source.name] = weight

        logger.info("证据源注册: %s (权重=%.2f)", source.name, self._weights.get(source.name, 0))

    def score(self, symbol: str, market_data: dict[str, Any]) -> SignalCard:
        """计算综合评分

        评分流程：
        1. 各源独立计算 → (strength, direction)
        2. 加权融合 + 单源封顶
        3. 共振加成（≥3 源同向）
        4. 冲突衰减
        5. 校准映射
        6. 生成信号卡

        Args:
            symbol: 标的符号
            market_data: 市场数据

        Returns:
            信号卡（多维信息）
        """
        # ① 各源独立计算
        raw_scores: dict[str, tuple[float, float]] = {}  # name → (strength, direction)
        for name, source in self._evidence_sources.items():
            try:
                strength, direction = source.compute(symbol, market_data)
                raw_scores[name] = (
                    max(0.0, min(1.0, strength)),
                    direction,
                )
            except Exception:
                logger.exception("证据源 %s 计算失败", name)
                raw_scores[name] = (0.0, 0.0)

        # ② 加权融合 + 单源封顶
        contributions: dict[str, float] = {}
        weighted_sum = 0.0
        total_weight = 0.0

        for name, (strength, direction) in raw_scores.items():
            weight = self._weights.get(name, 0.0)
            if weight <= 0:
                continue

            # 方向加权：strength × |direction| × weight
            contribution = strength * abs(direction) * weight

            # 单源封顶
            max_contribution = self.SINGLE_SOURCE_CAP
            contribution = min(contribution, max_contribution)

            contributions[name] = contribution
            weighted_sum += contribution
            total_weight += weight

        # 归一化到 0-100
        if total_weight > 0:
            raw_score = (weighted_sum / total_weight) * 100.0
        else:
            raw_score = 0.0

        # ③ 共振加成
        bullish_sources = [name for name, (s, d) in raw_scores.items() if d > 0 and s > 0.3]
        bearish_sources = [name for name, (s, d) in raw_scores.items() if d < 0 and s > 0.3]

        resonance_bonus = 0.0
        if len(bullish_sources) >= self.RESONANCE_MIN_SOURCES:
            resonance_bonus = self.RESONANCE_BONUS * 100
            logger.debug("多头共振: %d 源同向 → +%.1f 加成", len(bullish_sources), resonance_bonus)
        elif len(bearish_sources) >= self.RESONANCE_MIN_SOURCES:
            resonance_bonus = self.RESONANCE_BONUS * 100
            logger.debug("空头共振: %d 源同向 → +%.1f 加成", len(bearish_sources), resonance_bonus)

        raw_score += resonance_bonus

        # ④ 冲突衰减
        if bullish_sources and bearish_sources:
            conflict_ratio = min(len(bullish_sources), len(bearish_sources)) / max(
                len(bullish_sources), len(bearish_sources)
            )
            if conflict_ratio > self.CONFLICT_THRESHOLD:
                # 矛盾时向中性（50分）收敛
                decay = conflict_ratio * 0.5
                raw_score = raw_score * (1 - decay) + 50 * decay
                logger.debug(
                    "冲突衰减: 多头%d源 vs 空头%d源 → 衰减%.1f%%",
                    len(bullish_sources),
                    len(bearish_sources),
                    decay * 100,
                )

        # 限制范围
        raw_score = max(0.0, min(100.0, raw_score))

        # ⑤ 校准映射
        calibrated_score = self._calibrator.calibrate(raw_score)
        calibrated_score = max(0.0, min(100.0, calibrated_score))

        # ⑥ 方向判定
        net_direction = sum(d * s for s, d in raw_scores.values())
        if net_direction > 0.1:
            signal_direction = "long"
        elif net_direction < -0.1:
            signal_direction = "short"
        else:
            signal_direction = "neutral"

        # ⑦ 信号分级
        level = classify_signal(calibrated_score)

        # ⑧ 置信区间（基于源一致性）
        source_directions = [d for _, d in raw_scores.values() if d != 0]
        if source_directions:
            consistency = abs(sum(source_directions)) / len(source_directions)
        else:
            consistency = 0.0
        ci_half_width = (1 - consistency) * 15  # 不确定性越大，区间越宽
        confidence_interval = (
            max(0.0, calibrated_score - ci_half_width),
            min(100.0, calibrated_score + ci_half_width),
        )

        # ⑨ 风险回报比（基于评分等级）
        rr_ratio = self._estimate_risk_reward(calibrated_score, level)

        # ⑩ 构建信号卡
        signal_id = f"sig_{symbol}_{time.time_ns()}"

        card = SignalCard(
            signal_id=signal_id,
            symbol=symbol,
            direction=signal_direction,
            score=round(calibrated_score, 2),
            confidence_interval=(
                round(confidence_interval[0], 2),
                round(confidence_interval[1], 2),
            ),
            level=level,
            time_horizon=classify_time_horizon([]),
            risk_note=self._generate_risk_note(level, calibrated_score, consistency),
            suggested_stop=Decimal("0"),  # 需要具体价格数据才能计算
            risk_reward_ratio=rr_ratio,
            reason=self._generate_reason(
                symbol, signal_direction, calibrated_score, level, contributions
            ),
            evidence_details=contributions,
            historical_win_rate=calibrated_score / 100.0,  # 校准后分数 ≈ 胜率
            timestamp_ns=time.time_ns(),
        )

        # 记录评分历史
        self._score_history.append(
            ScoreRecord(
                raw_score=raw_score,
                calibrated_score=calibrated_score,
                symbol=symbol,
            )
        )

        logger.info(
            "信号评分: %s → %.1f分 (%s级, %s, %d源共振)",
            symbol,
            calibrated_score,
            level,
            signal_direction,
            max(len(bullish_sources), len(bearish_sources)),
        )

        return card

    def _estimate_risk_reward(self, score: float, level: str) -> float:
        """估算风险回报比

        高分信号 → 更高风险回报比要求
        """
        base_rr = {
            "S": 3.0,
            "A": 2.5,
            "B": 2.0,
            "C": 1.5,
        }
        return base_rr.get(level, 1.5)

    def _generate_risk_note(self, level: str, score: float, consistency: float) -> str:
        """生成风险提示（中文）"""
        notes: list[str] = []

        if level == "S":
            notes.append("极强信号，多源高度共振")
        elif level == "A":
            notes.append("强信号，建议关注")
        elif level == "B":
            notes.append("中等信号，注意分歧")
        else:
            notes.append("弱信号，建议观望")

        if consistency < 0.5:
            notes.append("多空分歧较大，控制仓位")

        if score > 90:
            notes.append("极端信号，注意过热风险")

        return "；".join(notes)

    def _generate_reason(
        self,
        symbol: str,
        direction: str,
        score: float,
        level: str,
        contributions: dict[str, float],
    ) -> str:
        """生成中文信号理由"""
        dir_zh = {"long": "看多", "short": "看空", "neutral": "中性"}.get(direction, "中性")

        # 找出贡献最大的源
        top_sources = sorted(contributions.items(), key=lambda x: x[1], reverse=True)[:3]
        source_names = {
            "order_flow": "订单流",
            "smc": "SMC结构",
            "volume_price": "量价关系",
            "ml_model": "ML模型",
            "llm_analysis": "AI分析",
            "crypto_structure": "加密结构",
            "onchain": "链上数据",
        }

        top_desc = "、".join(source_names.get(name, name) for name, _ in top_sources if _ > 0)

        return f"{symbol} {dir_zh}信号（{level}级，{score:.0f}分），主要依据：{top_desc}"

    def get_score_history(self, symbol: str | None = None, limit: int = 100) -> list[ScoreRecord]:
        """获取评分历史

        Args:
            symbol: 筛选标的（None 表示全部）
            limit: 返回数量上限

        Returns:
            评分记录列表
        """
        records = self._score_history
        if symbol:
            records = [r for r in records if r.symbol == symbol]
        return records[-limit:]

    def update_outcome(self, signal_id: str, outcome: bool) -> None:
        """更新信号结果（用于校准器滚动更新）

        Args:
            signal_id: 信号ID
            outcome: True=盈利, False=亏损
        """
        # 找到对应记录并更新（通过 signal_id 前缀匹配时间戳）
        target_ts_str = signal_id.split("_")[-1] if "_" in signal_id else ""
        for record in self._score_history:
            # 通过时间戳匹配信号
            if str(record.timestamp_ns) == target_ts_str:
                record.outcome = outcome
                break

        # 触发再校准
        if len(self._score_history) >= 50:
            predictions = [r.raw_score for r in self._score_history if r.outcome is not None]
            outcomes = [r.outcome for r in self._score_history if r.outcome is not None]
            if len(predictions) >= 20:
                self._calibrator.recalibrate(predictions, outcomes)


# ──────────────────────────── 反噪音系统 ────────────────────────────
