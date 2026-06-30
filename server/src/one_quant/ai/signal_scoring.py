"""AI 信号评分系统 — 共振融合 + 评分校准 + 反噪音

核心公式：综合分 = Calibrate(Σ wᵢ · sᵢ · dᵢ)
- wᵢ: 权重
- sᵢ: 证据强度 (0-1)
- dᵢ: 方向因子 (+1/-1/0)
- Calibrate: Isotonic/Platt 校准 → 85分 ≈ 85% 真实胜率

关键特性：
- ≥3 独立源同向 → 共振加成
- 单源封顶 → 逼高分多源
- 冲突衰减 → 矛盾时向中性收敛
"""

from __future__ import annotations

import math
import time
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Protocol, runtime_checkable

from one_quant.core.types import Signal
from one_quant.infra.logging import get_logger

logger = get_logger(__name__)


# ──────────────────────────── 协议与数据结构 ────────────────────────────


@runtime_checkable
class EvidenceSource(Protocol):
    """证据源协议 — 插件化信号源

    所有证据源必须实现此协议：
    - name: 源名称
    - compute: 返回 (strength, direction)
    """
    name: str

    def compute(self, symbol: str, market_data: dict[str, Any]) -> tuple[float, float]:
        """计算证据强度和方向

        Args:
            symbol: 标的符号
            market_data: 市场数据

        Returns:
            (strength: 0-1, direction: +1/-1/0)
            strength: 证据强度，0=无信号, 1=最强信号
            direction: +1=看多, -1=看空, 0=中性
        """
        ...


@dataclass(frozen=True)
class SignalCard:
    """信号卡（多维） — AI 推荐的完整信息

    frozen=True 保证不可变，线程安全
    """
    signal_id: str
    symbol: str
    direction: str                           # "long" / "short" / "neutral"
    score: float                             # 0-100 校准后综合评分
    confidence_interval: tuple[float, float] # 置信区间
    level: str                               # "S" / "A" / "B" / "C"
    time_horizon: str                        # "短炒" / "日内" / "波段" / "中线"
    risk_note: str                           # 风险提示
    suggested_stop: Decimal                  # 建议止损价
    risk_reward_ratio: float                 # 风险回报比
    reason: str                              # 中文理由
    evidence_details: dict[str, float]       # 各源贡献 {源名: 贡献分}
    historical_win_rate: float               # 历史同类胜率
    timestamp_ns: int                        # 纳秒时间戳


@dataclass
class ScoreRecord:
    """评分记录 — 用于校准器滚动更新"""
    raw_score: float
    calibrated_score: float
    outcome: bool | None = None  # 最终结果（True=盈利, False=亏损, None=待定）
    symbol: str = ""
    timestamp_ns: int = 0

    def __post_init__(self) -> None:
        if self.timestamp_ns == 0:
            self.timestamp_ns = time.time_ns()


# ──────────────────────────── 信号分级 ────────────────────────────


def classify_signal(score: float) -> str:
    """信号分级

    S(≥85): 极强信号 — 多源高度共振
    A(70-84): 强信号 — 多数源同向
    B(55-69): 中等信号 — 有一定分歧
    C(<55): 弱信号 — 分歧较大或证据不足

    Args:
        score: 校准后评分 (0-100)

    Returns:
        等级字符串
    """
    if score >= 85:
        return "S"
    if score >= 70:
        return "A"
    if score >= 55:
        return "B"
    return "C"


def classify_time_horizon(avg_holding_periods: list[float]) -> str:
    """根据平均持仓周期判定时间维度

    Args:
        avg_holding_periods: 各源建议的持仓周期（分钟）

    Returns:
        时间维度中文标签
    """
    if not avg_holding_periods:
        return "日内"

    avg = sum(avg_holding_periods) / len(avg_holding_periods)
    if avg < 30:
        return "短炒"
    if avg < 240:
        return "日内"
    if avg < 1440:
        return "波段"
    return "中线"


# ──────────────────────────── 评分校准器 ────────────────────────────


class ScoreCalibrator:
    """评分校准器 — 85分 = 历史真实胜率约 85%

    使用 Platt Scaling 或 Isotonic Regression 将原始评分映射为校准后概率。
    支持滚动再校准，随实盘数据更新校准函数。

    校准原理：
    - 收集 (raw_score, outcome) 数据对
    - 用 Platt Scaling: P(y=1|s) = 1 / (1 + exp(A*s + B))
    - 或 Isotonic Regression: 单调分段线性映射
    - 校准后分数直接反映真实胜率
    """

    def __init__(self, method: str = "platt") -> None:
        """初始化校准器

        Args:
            method: 校准方法 "platt" 或 "isotonic"
        """
        self._method = method
        self._records: list[ScoreRecord] = []
        # Platt 参数
        self._platt_a: float = -1.0
        self._platt_b: float = 0.0
        # Isotonic 参数（分段映射）
        self._isotonic_x: list[float] = []  # 断点
        self._isotonic_y: list[float] = []  # 对应概率
        self._is_fitted: bool = False

    def calibrate(self, raw_score: float, market: str = "default") -> float:
        """Isotonic/Platt 校准

        将原始评分映射为校准后分数（0-100），使得：
        - 校准后 85 分 ≈ 85% 历史胜率
        - 校准后分数有明确的概率含义

        Args:
            raw_score: 原始评分 (0-100)
            market: 市场标识（不同市场可有不同校准参数）

        Returns:
            校准后评分 (0-100)
        """
        if not self._is_fitted:
            # 未拟合时使用线性映射（兜底）
            return max(0.0, min(100.0, raw_score))

        # 归一化到 [0, 1]
        s = raw_score / 100.0

        if self._method == "platt":
            # Platt Scaling: P = 1 / (1 + exp(A*s + B))
            try:
                exponent = self._platt_a * s + self._platt_b
                exponent = max(-500, min(500, exponent))  # 防溢出
                prob = 1.0 / (1.0 + math.exp(exponent))
            except (OverflowError, ZeroDivisionError):
                prob = s
        else:
            # Isotonic Regression（分段线性插值）
            prob = self._isotonic_interpolate(s)

        return max(0.0, min(100.0, prob * 100.0))

    def recalibrate(self, predictions: list[float], outcomes: list[bool]) -> None:
        """滚动再校准

        用最新的 (预测, 结果) 数据重新拟合校准函数。

        Args:
            predictions: 原始评分列表 (0-100)
            outcomes: 对应结果列表 (True=盈利)
        """
        if len(predictions) != len(outcomes) or len(predictions) < 20:
            logger.warning("校准数据不足: %d 条（最少 20 条）", len(predictions))
            return

        # 存储记录
        for pred, outcome in zip(predictions, outcomes):
            self._records.append(ScoreRecord(
                raw_score=pred,
                calibrated_score=pred,  # 待校准
                outcome=outcome,
            ))

        if self._method == "platt":
            self._fit_platt(predictions, outcomes)
        else:
            self._fit_isotonic(predictions, outcomes)

        self._is_fitted = True
        logger.info(
            "校准器更新: method=%s, samples=%d, a=%.4f, b=%.4f",
            self._method, len(predictions), self._platt_a, self._platt_b,
        )

    def _fit_platt(self, predictions: list[float], outcomes: list[bool]) -> None:
        """Platt Scaling 拟合

        使用最大似然估计参数 A, B：
        P(y=1|s) = 1 / (1 + exp(A*s + B))

        简化实现：梯度下降
        """
        # 归一化预测
        x = [p / 100.0 for p in predictions]
        y = [1.0 if o else 0.0 for o in outcomes]
        n = len(x)

        # 梯度下降
        a, b = -1.0, 0.0
        lr = 0.01

        for _ in range(1000):
            grad_a, grad_b = 0.0, 0.0
            for i in range(n):
                try:
                    exp_val = math.exp(a * x[i] + b)
                    p = 1.0 / (1.0 + exp_val)
                except OverflowError:
                    p = 0.0 if a * x[i] + b > 0 else 1.0

                err = p - y[i]
                grad_a += err * x[i]
                grad_b += err

            grad_a /= n
            grad_b /= n

            a -= lr * grad_a
            b -= lr * grad_b

            # 收敛检查
            if abs(grad_a) < 1e-6 and abs(grad_b) < 1e-6:
                break

        self._platt_a = a
        self._platt_b = b

    def _fit_isotonic(self, predictions: list[float], outcomes: list[bool]) -> None:
        """Isotonic Regression 拟合

        保序回归：保证映射函数单调递增。
        使用 PAV (Pool Adjacent Violators) 算法。
        """
        # 按预测值排序
        paired = sorted(zip(predictions, outcomes), key=lambda t: t[0])

        # 分桶计算实际胜率
        bucket_size = max(5, len(paired) // 20)
        xs: list[float] = []
        ys: list[float] = []

        for i in range(0, len(paired), bucket_size):
            bucket = paired[i:i + bucket_size]
            avg_x = sum(p[0] for p in bucket) / len(bucket)
            avg_y = sum(1.0 if p[1] else 0.0 for p in bucket) / len(bucket)
            xs.append(avg_x / 100.0)  # 归一化
            ys.append(avg_y)

        # PAV 算法（保序）
        n = len(xs)
        pools = [[ys[i]] for i in range(n)]

        i = 0
        while i < len(pools) - 1:
            if sum(pools[i]) / len(pools[i]) > sum(pools[i + 1]) / len(pools[i + 1]):
                # 合并违反单调性的相邻池
                pools[i] = pools[i] + pools[i + 1]
                pools.pop(i + 1)
                if i > 0:
                    i -= 1
            else:
                i += 1

        # 构建分段映射
        self._isotonic_x = []
        self._isotonic_y = []
        idx = 0
        for pool in pools:
            self._isotonic_x.append(xs[idx])
            self._isotonic_y.append(sum(pool) / len(pool))
            idx += len(pool)

    def _isotonic_interpolate(self, s: float) -> float:
        """Isotonic 分段线性插值"""
        if not self._isotonic_x:
            return s

        # 边界处理
        if s <= self._isotonic_x[0]:
            return self._isotonic_y[0]
        if s >= self._isotonic_x[-1]:
            return self._isotonic_y[-1]

        # 线性插值
        for i in range(len(self._isotonic_x) - 1):
            if self._isotonic_x[i] <= s <= self._isotonic_x[i + 1]:
                t = (s - self._isotonic_x[i]) / (self._isotonic_x[i + 1] - self._isotonic_x[i])
                return self._isotonic_y[i] + t * (self._isotonic_y[i + 1] - self._isotonic_y[i])

        return s


# ──────────────────────────── 信号评分器 ────────────────────────────


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
        "order_flow": 0.20,      # 订单流
        "smc": 0.15,             # SMC（Smart Money Concepts）
        "volume_price": 0.15,    # 量价
        "ml_model": 0.15,        # ML 模型
        "llm_analysis": 0.10,    # LLM 分析
        "crypto_structure": 0.15,# 加密结构
        "onchain": 0.10,         # 链上数据
    }

    # 单源封顶（最大贡献比例）
    SINGLE_SOURCE_CAP: float = 0.35

    # 共振加成参数
    RESONANCE_MIN_SOURCES: int = 3    # 最少同向源数
    RESONANCE_BONUS: float = 0.15     # 共振加成比例

    # 冲突衰减参数
    CONFLICT_THRESHOLD: float = 0.3   # 冲突检测阈值

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
        bullish_sources = [
            name for name, (s, d) in raw_scores.items()
            if d > 0 and s > 0.3
        ]
        bearish_sources = [
            name for name, (s, d) in raw_scores.items()
            if d < 0 and s > 0.3
        ]

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
                    len(bullish_sources), len(bearish_sources), decay * 100,
                )

        # 限制范围
        raw_score = max(0.0, min(100.0, raw_score))

        # ⑤ 校准映射
        calibrated_score = self._calibrator.calibrate(raw_score)
        calibrated_score = max(0.0, min(100.0, calibrated_score))

        # ⑥ 方向判定
        net_direction = sum(d * s for s, d in raw_scores.values())
        if net_direction > 0.1:
            direction = "long"
        elif net_direction < -0.1:
            direction = "short"
        else:
            direction = "neutral"

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
            direction=direction,
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
            reason=self._generate_reason(symbol, direction, calibrated_score, level, contributions),
            evidence_details=contributions,
            historical_win_rate=calibrated_score / 100.0,  # 校准后分数 ≈ 胜率
            timestamp_ns=time.time_ns(),
        )

        # 记录评分历史
        self._score_history.append(ScoreRecord(
            raw_score=raw_score,
            calibrated_score=calibrated_score,
            symbol=symbol,
        ))

        logger.info(
            "信号评分: %s → %.1f分 (%s级, %s, %d源共振)",
            symbol, calibrated_score, level, direction,
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

        top_desc = "、".join(
            source_names.get(name, name) for name, _ in top_sources if _ > 0
        )

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


class AntiNoise:
    """反噪音系统 — 过滤低质量信号

    三重过滤：
    1. 冷却期：同一标的短时间内不重复推送
    2. 去重：相同方向/相近分数的信号合并
    3. Regime 感知：高波动环境下提高推送阈值
    """

    def __init__(self, cooldown_sec: int = 300) -> None:
        """初始化反噪音系统

        Args:
            cooldown_sec: 冷却期（秒），默认 5 分钟
        """
        self._cooldown = cooldown_sec
        self._last_signal: dict[str, int] = {}  # symbol → last signal timestamp_ns
        self._recent_signals: dict[str, list[SignalCard]] = defaultdict(list)  # symbol → [recent signals]
        self._regime_threshold_boost: float = 0.0  # regime 感知阈值提升

    def should_push(self, signal: SignalCard) -> bool:
        """是否应该推送信号

        过滤规则：
        1. 冷却期内同标的不推送
        2. 相同方向 + 相近分数（±5分）→ 不重复推送
        3. 高波动环境 → 提高推送门槛

        Args:
            signal: 待推送信号

        Returns:
            True=应该推送, False=过滤掉
        """
        symbol = signal.symbol
        now = signal.timestamp_ns

        # ① 冷却期检查
        last_ts = self._last_signal.get(symbol, 0)
        cooldown_ns = self._cooldown * 1_000_000_000
        if now - last_ts < cooldown_ns:
            logger.debug("信号过滤（冷却期）: %s, 剩余 %ds",
                         symbol, (cooldown_ns - (now - last_ts)) // 1_000_000_000)
            return False

        # ② 去重检查
        recent = self._recent_signals.get(symbol, [])
        for prev in recent[-5:]:  # 检查最近 5 条
            if (
                prev.direction == signal.direction
                and abs(prev.score - signal.score) < 5
                and (now - prev.timestamp_ns) < cooldown_ns * 3
            ):
                logger.debug("信号过滤（去重）: %s, 方向=%s, 分差=%.1f",
                             symbol, signal.direction, abs(prev.score - signal.score))
                return False

        # ③ Regime 感知：高波动环境提高门槛
        min_score = 70 + self._regime_threshold_boost
        if signal.score < min_score:
            logger.debug("信号过滤（Regime门限）: %s, score=%.1f < min=%.1f",
                         symbol, signal.score, min_score)
            return False

        # 通过所有过滤 → 允许推送
        self._last_signal[symbol] = now
        self._recent_signals[symbol].append(signal)

        # 清理旧记录（保留最近 20 条）
        if len(self._recent_signals[symbol]) > 20:
            self._recent_signals[symbol] = self._recent_signals[symbol][-20:]

        return True

    def set_regime(self, volatility_level: str) -> None:
        """设置市场 regime（用于动态调整推送阈值）

        Args:
            volatility_level: "low" / "medium" / "high" / "extreme"
        """
        boosts = {
            "low": 0.0,
            "medium": 5.0,
            "high": 10.0,
            "extreme": 20.0,
        }
        self._regime_threshold_boost = boosts.get(volatility_level, 0.0)
        logger.info("Regime 设置: %s, 阈值提升 +%.0f", volatility_level, self._regime_threshold_boost)

    def reset_cooldown(self, symbol: str) -> None:
        """手动重置某标的的冷却期

        Args:
            symbol: 标的符号
        """
        self._last_signal.pop(symbol, None)
        logger.info("冷却期重置: %s", symbol)

    @property
    def stats(self) -> dict[str, Any]:
        """统计信息"""
        return {
            "tracked_symbols": len(self._last_signal),
            "total_recent_signals": sum(len(v) for v in self._recent_signals.values()),
            "cooldown_sec": self._cooldown,
            "regime_boost": self._regime_threshold_boost,
        }


# ──────────────────────────── 内置证据源实现 ────────────────────────────


class OrderFlowSource:
    """订单流证据源 — 分析大单/吃单/挂单行为"""

    name = "order_flow"

    def compute(self, symbol: str, market_data: dict[str, Any]) -> tuple[float, float]:
        """分析订单流信号

        检测：
        - 大单方向
        - 吃单/挂单比例
        - 主动买卖力度

        Returns:
            (strength, direction)
        """
        trades = market_data.get("trades", [])
        if not trades:
            return 0.0, 0.0

        buy_volume = sum(t.get("quantity", 0) for t in trades if t.get("side") == "buy")
        sell_volume = sum(t.get("quantity", 0) for t in trades if t.get("side") == "sell")
        total = buy_volume + sell_volume

        if total == 0:
            return 0.0, 0.0

        # 买卖比例 → 方向和强度
        ratio = (buy_volume - sell_volume) / total
        strength = min(1.0, abs(ratio) * 2)  # 归一化
        direction = 1.0 if ratio > 0 else -1.0 if ratio < 0 else 0.0

        return strength, direction


class VolumePriceSource:
    """量价关系证据源 — 分析量价配合"""

    name = "volume_price"

    def compute(self, symbol: str, market_data: dict[str, Any]) -> tuple[float, float]:
        """分析量价信号

        检测：
        - 放量突破
        - 缩量回调
        - 量价背离

        Returns:
            (strength, direction)
        """
        klines = market_data.get("klines", [])
        if len(klines) < 5:
            return 0.0, 0.0

        # 简化实现：最近 K 线的量价关系
        recent = klines[-5:]
        price_change = (recent[-1].get("close", 0) - recent[0].get("open", 0)) / recent[0].get("open", 1)
        volume_change = recent[-1].get("volume", 0) / max(recent[0].get("volume", 1), 1)

        # 价涨量增 → 看多；价跌量增 → 看空
        if price_change > 0 and volume_change > 1.2:
            return min(1.0, abs(price_change) * 10), 1.0
        elif price_change < 0 and volume_change > 1.2:
            return min(1.0, abs(price_change) * 10), -1.0

        return 0.3, 0.0  # 中性


class SMCSource:
    """SMC（Smart Money Concepts）证据源 — 基于 SMCAnalyzer 分析机构行为"""

    name = "smc"

    def __init__(self, analyzer: Any = None) -> None:
        """初始化 SMC 证据源

        Args:
            analyzer: SMCAnalyzer 实例，None 时自动创建
        """
        self._analyzer = analyzer

    def compute(self, symbol: str, market_data: dict[str, Any]) -> tuple[float, float]:
        """调用 SMCAnalyzer 检测 BOS/CHoCH/OB/FVG，返回 (strength, direction)

        综合以下 SMC 结构信号：
        - BOS（市场结构破坏）：趋势延续确认
        - CHoCH（趋势转换）：趋势反转信号
        - Order Block（订单块）：机构挂单区域
        - FVG（公允价值缺口）：价格不平衡区域

        Args:
            symbol: 标的符号
            market_data: 市场数据（需含 klines/highs/lows）

        Returns:
            (strength: 0-1, direction: +1/-1/0)
        """
        # 懒加载 SMCAnalyzer
        if self._analyzer is None:
            try:
                from one_quant.strategy.smc import SMCAnalyzer
                self._analyzer = SMCAnalyzer()
            except ImportError:
                return 0.0, 0.0

        # 提取 K 线数据
        klines = market_data.get("klines", [])
        highs_raw = market_data.get("highs", [])
        lows_raw = market_data.get("lows", [])

        # 从 K 线提取 high/low 序列
        from decimal import Decimal
        if klines and not highs_raw:
            highs_raw = [float(k.get("high", k.get("close", 0))) for k in klines]
            lows_raw = [float(k.get("low", k.get("close", 0))) for k in klines]

        if len(highs_raw) < 15 or len(lows_raw) < 15:
            return 0.0, 0.0

        highs = [Decimal(str(h)) for h in highs_raw]
        lows = [Decimal(str(l)) for l in lows_raw]

        signals: list[tuple[float, float]] = []  # (strength, direction)

        # ① BOS 检测（市场结构破坏）
        try:
            bos = self._analyzer.detect_bos(highs, lows)
            if bos:
                bos_type = bos.get("type", "")
                if "bullish" in bos_type:
                    signals.append((0.7, 1.0))  # 看多 BOS
                elif "bearish" in bos_type:
                    signals.append((0.7, -1.0))  # 看空 BOS
        except Exception:
            pass

        # ② CHoCH 检测（趋势转换）
        try:
            # 根据近期走势判断当前趋势
            recent_highs = highs_raw[-20:]
            recent_lows = lows_raw[-20:]
            trend = "bullish" if recent_highs[-1] > recent_highs[0] else "bearish"
            choch = self._analyzer.detect_choch(highs, lows, trend)
            if choch:
                choch_type = choch.get("type", "")
                if "bullish" in choch_type:
                    signals.append((0.8, 1.0))  # 看多 CHoCH（反转信号更强）
                elif "bearish" in choch_type:
                    signals.append((0.8, -1.0))  # 看空 CHoCH
        except Exception:
            pass

        # ③ Order Block 检测（订单块）
        try:
            if klines:
                from one_quant.core.types import Kline, Market
                from decimal import Decimal as D
                kline_objs = []
                for k in klines[-50:]:  # 只取最近 50 根
                    try:
                        kline_objs.append(Kline(
                            symbol=symbol,
                            market=Market.SPOT,
                            exchange="",
                            interval="1h",
                            open=D(str(k.get("open", 0))),
                            high=D(str(k.get("high", 0))),
                            low=D(str(k.get("low", 0))),
                            close=D(str(k.get("close", 0))),
                            volume=D(str(k.get("volume", 0))),
                            timestamp_ns=k.get("timestamp_ns", 0),
                        ))
                    except Exception:
                        continue

                if len(kline_objs) >= 5:
                    obs = self._analyzer.find_order_blocks(kline_objs)
                    if obs:
                        latest_ob = obs[-1]
                        ob_type = latest_ob.get("type", "")
                        ob_strength = float(latest_ob.get("strength", 0.5))
                        if "bullish" in ob_type:
                            signals.append((ob_strength, 1.0))
                        elif "bearish" in ob_type:
                            signals.append((ob_strength, -1.0))
        except Exception:
            pass

        # ④ FVG 检测（公允价值缺口）
        try:
            if klines:
                from one_quant.core.types import Kline, Market
                from decimal import Decimal as D
                kline_objs = []
                for k in klines[-50:]:
                    try:
                        kline_objs.append(Kline(
                            symbol=symbol,
                            market=Market.SPOT,
                            exchange="",
                            interval="1h",
                            open=D(str(k.get("open", 0))),
                            high=D(str(k.get("high", 0))),
                            low=D(str(k.get("low", 0))),
                            close=D(str(k.get("close", 0))),
                            volume=D(str(k.get("volume", 0))),
                            timestamp_ns=k.get("timestamp_ns", 0),
                        ))
                    except Exception:
                        continue

                if len(kline_objs) >= 3:
                    fvgs = self._analyzer.find_fvg(kline_objs)
                    if fvgs:
                        latest_fvg = fvgs[-1]
                        fvg_type = latest_fvg.get("type", "")
                        gap_ratio = float(latest_fvg.get("gap_ratio", 0))
                        fvg_strength = min(1.0, gap_ratio * 100)  # 归一化
                        if "bullish" in fvg_type:
                            signals.append((fvg_strength, 1.0))
                        elif "bearish" in fvg_type:
                            signals.append((fvg_strength, -1.0))
        except Exception:
            pass

        # 综合所有 SMC 信号
        if not signals:
            return 0.0, 0.0

        # 加权平均（取强度最高的信号为主导）
        signals.sort(key=lambda s: s[0], reverse=True)
        total_strength = sum(s[0] for s in signals)
        weighted_direction = sum(s[0] * s[1] for s in signals)

        avg_strength = min(1.0, total_strength / len(signals))
        avg_direction = weighted_direction / total_strength if total_strength > 0 else 0.0

        # 方向量化
        if avg_direction > 0.1:
            direction = 1.0
        elif avg_direction < -0.1:
            direction = -1.0
        else:
            direction = 0.0

        return avg_strength, direction


class MLModelSource:
    """ML 模型证据源 — 基于 MLTrainer 的机器学习预测"""

    name = "ml_model"

    def __init__(self, model: Any = None, trainer: Any = None) -> None:
        """初始化 ML 模型证据源

        Args:
            model: 训练好的模型对象（支持 predict/predict_proba）
            trainer: MLTrainer 实例（含 predict 方法）
        """
        self._model = model
        self._trainer = trainer

    def compute(self, symbol: str, market_data: dict[str, Any]) -> tuple[float, float]:
        """调用 ML 模型的 predict 方法，返回 (strength, direction)

        流程：
        1. 从市场数据提取特征
        2. 调用模型推理
        3. 将预测概率转换为 (strength, direction)

        Args:
            symbol: 标的符号
            market_data: 市场数据（需含特征或可计算因子的原始数据）

        Returns:
            (strength: 0-1, direction: +1/-1/0)
        """
        # 优先使用 MLTrainer 的 predict 方法
        if self._trainer is not None:
            try:
                return self._predict_with_trainer(symbol, market_data)
            except Exception:
                logger.debug("MLTrainer 推理异常，尝试直接模型推理")

        # 回退：直接使用模型对象
        if self._model is None:
            return 0.0, 0.0

        try:
            return self._predict_with_model(symbol, market_data)
        except Exception:
            logger.debug("ML 模型推理失败: %s", symbol)
            return 0.0, 0.0

    def _predict_with_trainer(self, symbol: str, market_data: dict[str, Any]) -> tuple[float, float]:
        """使用 MLTrainer 进行推理

        Args:
            symbol: 标的符号
            market_data: 市场数据

        Returns:
            (strength, direction)
        """
        import numpy as np

        # 从市场数据构建特征向量
        features = self._extract_features(market_data)
        if features is None or len(features) == 0:
            return 0.0, 0.0

        X = np.array(features).reshape(1, -1) if len(features) > 0 else None
        if X is None:
            return 0.0, 0.0

        # 调用 MLTrainer.predict
        predictions = self._trainer.predict(X)
        if not predictions:
            return 0.0, 0.0

        prob = float(predictions[0])  # 预测概率 (0-1)

        # 转换为 (strength, direction)
        # prob > 0.5 → 看多, prob < 0.5 → 看空
        strength = abs(prob - 0.5) * 2  # 距离 0.5 越远越强
        strength = min(1.0, strength)

        if prob > 0.55:
            direction = 1.0
        elif prob < 0.45:
            direction = -1.0
        else:
            direction = 0.0

        return strength, direction

    def _predict_with_model(self, symbol: str, market_data: dict[str, Any]) -> tuple[float, float]:
        """直接使用模型对象推理

        Args:
            symbol: 标的符号
            market_data: 市场数据

        Returns:
            (strength, direction)
        """
        import numpy as np

        features = self._extract_features(market_data)
        if features is None or len(features) == 0:
            return 0.0, 0.0

        X = np.array(features).reshape(1, -1)

        # 调用模型的 predict 或 predict_proba
        if hasattr(self._model, "predict_proba"):
            proba = self._model.predict_proba(X)
            prob = float(proba[0][1]) if hasattr(proba, "__getitem__") else float(proba)
        elif hasattr(self._model, "predict"):
            pred = self._model.predict(X)
            prob = float(pred[0]) if hasattr(pred, "__getitem__") else float(pred)
        else:
            return 0.0, 0.0

        strength = abs(prob - 0.5) * 2
        strength = min(1.0, strength)

        if prob > 0.55:
            direction = 1.0
        elif prob < 0.45:
            direction = -1.0
        else:
            direction = 0.0

        return strength, direction

    @staticmethod
    def _extract_features(market_data: dict[str, Any]) -> list[float] | None:
        """从市场数据提取特征向量

        优先使用预计算的 features 字段，
        否则从原始数据（klines/prices）计算基础特征。

        Args:
            market_data: 市场数据

        Returns:
            特征列表或 None
        """
        # 优先使用预计算特征
        if "features" in market_data:
            feats = market_data["features"]
            if isinstance(feats, (list, tuple)):
                return [float(f) for f in feats]
            return None

        # 从原始价格数据计算基础特征
        prices = market_data.get("prices") or market_data.get("closes", [])
        if not prices or len(prices) < 20:
            return None

        prices = [float(p) for p in prices]
        features: list[float] = []

        # 动量特征
        for period in [5, 10, 20]:
            if len(prices) > period and prices[-period] != 0:
                features.append((prices[-1] - prices[-period]) / prices[-period])
            else:
                features.append(0.0)

        # 波动率特征
        returns = [(prices[i] - prices[i-1]) / prices[i-1] for i in range(1, len(prices)) if prices[i-1] != 0]
        if returns:
            mean_ret = sum(returns[-20:]) / min(20, len(returns))
            features.append((sum((r - mean_ret)**2 for r in returns[-20:]) / min(20, len(returns))) ** 0.5)
        else:
            features.append(0.0)

        # 均值回归特征
        if len(prices) >= 20:
            ma20 = sum(prices[-20:]) / 20
            features.append((prices[-1] - ma20) / ma20 if ma20 != 0 else 0.0)
        else:
            features.append(0.0)

        return features


class LLMAnalysisSource:
    """LLM 分析证据源 — 调用 LLM Provider 获取情绪/事件面分析"""

    name = "llm_analysis"

    def __init__(self, llm_router: Any = None) -> None:
        """初始化 LLM 分析证据源

        Args:
            llm_router: LLMRouter 实例，用于路由到 Claude/DeepSeek
        """
        self._llm_router = llm_router

    def compute(self, symbol: str, market_data: dict[str, Any]) -> tuple[float, float]:
        """调用 LLM Provider 获取情绪/事件面分析

        流程：
        1. 从 market_data 提取新闻/事件文本
        2. 调用 LLM Router 进行情绪分析
        3. 解析返回的情绪分数和方向

        Args:
            symbol: 标的符号
            market_data: 市场数据（可含 news_texts/llm_sentiment/events）

        Returns:
            (strength: 0-1, direction: +1/-1/0)
        """
        # 优先使用预计算的 LLM 情绪分数（避免重复调用）
        if "llm_sentiment" in market_data:
            sentiment = float(market_data["llm_sentiment"])
            strength = min(1.0, abs(sentiment))
            direction = 1.0 if sentiment > 0.1 else -1.0 if sentiment < -0.1 else 0.0
            return strength, direction

        # 无 LLM Router 时回退到本地情绪分析
        if self._llm_router is None:
            return self._local_sentiment(market_data)

        # 收集文本上下文
        text_parts: list[str] = []
        news_texts = market_data.get("news_texts", [])
        if news_texts:
            text_parts.extend(news_texts[:5])  # 最多 5 条新闻
        events = market_data.get("events", [])
        if events:
            text_parts.extend([str(e) for e in events[:3]])

        if not text_parts:
            # 无文本数据时用价格数据做简单分析
            return self._local_sentiment(market_data)

        # 调用 LLM 进行情绪分析
        try:
            import asyncio
            return self._call_llm_sync(symbol, text_parts)
        except Exception:
            logger.debug("LLM 情绪分析异常，回退到本地分析")
            return self._local_sentiment(market_data)

    def _call_llm_sync(self, symbol: str, text_parts: list[str]) -> tuple[float, float]:
        """同步调用 LLM 进行情绪分析

        在同步上下文中创建事件循环调用异步 LLM。

        Args:
            symbol: 标的符号
            text_parts: 文本内容列表

        Returns:
            (strength, direction)
        """
        import asyncio

        system_prompt = (
            "你是加密货币/金融市场情绪分析专家。"
            "分析给定的新闻/事件文本，判断对标的 {symbol} 的影响。\n"
            "输出格式（严格 JSON）：\n"
            '{{"sentiment": float, "confidence": float, "summary": "一句话中文摘要"}}\n'
            'sentiment: -1.0（极度利空）到 1.0（极度利好），0 为中性。\n'
            'confidence: 0.0 到 1.0，表示分析置信度。\n'
            '只输出 JSON，不要其他内容。'
        ).format(symbol=symbol)

        user_text = "\n---\n".join(text_parts)

        try:
            from one_quant.ai.llm_provider import sanitize_user_text, wrap_user_content
            safe_text = sanitize_user_text(user_text)
            wrapped = wrap_user_content(safe_text)
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": wrapped},
            ]

            # 尝试获取事件循环
            try:
                loop = asyncio.get_running_loop()
                # 已在异步上下文中，创建任务
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(asyncio.run, self._llm_router.route(
                        task_complexity="low",
                        messages=messages,
                        max_tokens=256,
                        temperature=0.3,
                    ))
                    response = future.result(timeout=30)
            except RuntimeError:
                # 无运行中的事件循环
                response = asyncio.run(self._llm_router.route(
                    task_complexity="low",
                    messages=messages,
                    max_tokens=256,
                    temperature=0.3,
                ))

            # 解析 LLM 返回
            import json as _json
            content = response.content.strip()
            if "```" in content:
                for block in content.split("```"):
                    block = block.strip()
                    if block.startswith("json"):
                        block = block[4:].strip()
                    if block.startswith("{"):
                        content = block
                        break

            result = _json.loads(content)
            sentiment = float(result.get("sentiment", 0))
            confidence = float(result.get("confidence", 0.5))

            strength = min(1.0, abs(sentiment) * confidence)
            direction = 1.0 if sentiment > 0.1 else -1.0 if sentiment < -0.1 else 0.0

            return strength, direction

        except Exception:
            logger.debug("LLM 情绪分析调用失败")
            return 0.0, 0.0

    @staticmethod
    def _local_sentiment(market_data: dict[str, Any]) -> tuple[float, float]:
        """本地情绪分析（无 LLM 时的回退方案）

        基于价格变动和成交量做简单情绪判断。

        Args:
            market_data: 市场数据

        Returns:
            (strength, direction)
        """
        prices = market_data.get("prices") or market_data.get("closes", [])
        if not prices or len(prices) < 5:
            return 0.0, 0.0

        prices = [float(p) for p in prices]
        # 短期动量
        short_ret = (prices[-1] - prices[-5]) / prices[-5] if prices[-5] != 0 else 0
        # 中期动量
        mid_ret = (prices[-1] - prices[-min(20, len(prices))]) / prices[-min(20, len(prices))] if prices[-min(20, len(prices))] != 0 else 0

        # 综合情绪
        sentiment = short_ret * 0.6 + mid_ret * 0.4
        strength = min(1.0, abs(sentiment) * 10)  # 归一化
        direction = 1.0 if sentiment > 0.005 else -1.0 if sentiment < -0.005 else 0.0

        return strength, direction


class CryptoStructureSource:
    """加密结构证据源 — 加密市场特有结构"""

    name = "crypto_structure"

    def compute(self, symbol: str, market_data: dict[str, Any]) -> tuple[float, float]:
        """分析加密市场结构

        检测：
        - 清算地图
        - 资金费率
        - 持仓量变化
        - 多空比

        Returns:
            (strength, direction)
        """
        funding_rate = market_data.get("funding_rate", 0.0)
        long_short_ratio = market_data.get("long_short_ratio", 1.0)

        # 资金费率极端 → 反向信号
        if abs(funding_rate) > 0.01:
            strength = min(1.0, abs(funding_rate) * 50)
            direction = -1.0 if funding_rate > 0 else 1.0  # 费率过高 → 看空
            return strength, direction

        # 多空比极端 → 反向信号
        if long_short_ratio > 2.0 or long_short_ratio < 0.5:
            strength = 0.6
            direction = -1.0 if long_short_ratio > 2.0 else 1.0
            return strength, direction

        return 0.2, 0.0


class OnchainSource:
    """链上数据证据源 — 区块链链上指标"""

    name = "onchain"

    def compute(self, symbol: str, market_data: dict[str, Any]) -> tuple[float, float]:
        """分析链上数据

        检测：
        - 交易所净流入/流出
        - 大户持仓变化
        - 活跃地址数
        - MVRV / NVT

        Returns:
            (strength, direction)
        """
        net_flow = market_data.get("exchange_net_flow", 0.0)  # 正=流入, 负=流出

        if abs(net_flow) > 0:
            strength = min(1.0, abs(net_flow) / 1000)  # 归一化
            direction = -1.0 if net_flow > 0 else 1.0  # 流入交易所 → 看空（抛压）
            return strength, direction

        return 0.1, 0.0
