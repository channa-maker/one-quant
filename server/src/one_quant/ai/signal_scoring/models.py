"""信号评分 — 协议与数据结构"""

from __future__ import annotations

import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class EvidenceSource(Protocol):
    """证据源协议"""

    name: str

    def compute(self, symbol: str, market_data: dict[str, Any]) -> tuple[float, float]:
        """计算证据强度和方向"""
        ...


@dataclass(frozen=True)
class SignalCard:
    """信号卡（多维）"""

    signal_id: str
    symbol: str
    direction: str
    score: float
    confidence_interval: tuple[float, float]
    level: str
    time_horizon: str
    risk_note: str
    suggested_stop: Decimal
    risk_reward_ratio: float
    reason: str
    evidence_details: dict[str, float]
    historical_win_rate: float
    timestamp_ns: int


@dataclass
class ScoreRecord:
    """评分记录"""

    raw_score: float
    calibrated_score: float
    outcome: bool | None = None
    symbol: str = ""
    timestamp_ns: int = 0

    def __post_init__(self) -> None:
        if self.timestamp_ns == 0:
            self.timestamp_ns = time.time_ns()


def classify_signal(score: float) -> str:
    """信号分级"""
    if score >= 85:
        return "S"
    if score >= 70:
        return "A"
    if score >= 55:
        return "B"
    return "C"


def classify_time_horizon(avg_holding_periods: list[float]) -> str:
    """根据平均持仓周期判定时间维度"""
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
