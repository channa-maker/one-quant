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

import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol, runtime_checkable

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
    direction: str  # "long" / "short" / "neutral"
    score: float  # 0-100 校准后综合评分
    confidence_interval: tuple[float, float]  # 置信区间
    level: str  # "S" / "A" / "B" / "C"
    time_horizon: str  # "短炒" / "日内" / "波段" / "中线"
    risk_note: str  # 风险提示
    suggested_stop: Decimal  # 建议止损价
    risk_reward_ratio: float  # 风险回报比
    reason: str  # 中文理由
    evidence_details: dict[str, float]  # 各源贡献 {源名: 贡献分}
    historical_win_rate: float  # 历史同类胜率
    timestamp_ns: int  # 纳秒时间戳


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
