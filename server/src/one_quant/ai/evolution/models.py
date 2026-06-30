"""自进化平台 — 数据模型与枚举"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class StrategyLifecycle(StrEnum):
    """策略生命周期阶段"""

    DRAFT = "draft"
    BACKTESTING = "backtesting"
    SHADOW = "shadow"
    GRAYSCALE = "grayscale"
    LIVE = "live"
    CHALLENGER = "challenger"
    DECAYING = "decaying"
    RETIRED = "retired"


class FactorSource(StrEnum):
    """因子来源"""

    LLM = "llm"
    GENETIC = "genetic"
    MANUAL = "manual"
    LIBRARY = "library"


@dataclass
class Strategy:
    """策略实体"""

    strategy_id: str
    name: str
    version: str
    lifecycle: StrategyLifecycle
    factors: list[str] = field(default_factory=list)
    params: dict[str, Any] = field(default_factory=dict)
    config: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    backtest_result: dict[str, Any] = field(default_factory=dict)
    risk_assessment: dict[str, Any] = field(default_factory=dict)
    slot: str = ""
    created_at: int = 0
    updated_at: int = 0

    def __post_init__(self) -> None:
        now = time.time_ns()
        if self.created_at == 0:
            self.created_at = now
        if self.updated_at == 0:
            self.updated_at = now


@dataclass
class Factor:
    """候选因子"""

    factor_id: str
    name: str
    expression: str
    source: FactorSource
    ic: float = 0.0
    icir: float = 0.0
    turnover: float = 0.0
    created_at: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.created_at == 0:
            self.created_at = time.time_ns()


@dataclass
class BacktestResult:
    """回测结果"""

    strategy_id: str
    total_return: float = 0.0
    annual_return: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    max_drawdown: float = 0.0
    calmar_ratio: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    total_trades: int = 0
    avg_holding_period: float = 0.0
    oos_return: float = 0.0
    oos_sharpe: float = 0.0
    multi_period_stable: bool = False
    period_results: dict[str, float] = field(default_factory=dict)
    ic_decay_rate: float = 0.0
    overfit_score: float = 0.0
    train_test_gap: float = 0.0
    passed: bool = False
    reject_reasons: list[str] = field(default_factory=list)
    timestamp_ns: int = 0

    def __post_init__(self) -> None:
        if self.timestamp_ns == 0:
            self.timestamp_ns = time.time_ns()


@dataclass
class ShadowResult:
    """影子运行结果"""

    strategy_id: str
    shadow_days: int = 0
    total_signals: int = 0
    correct_signals: int = 0
    signal_accuracy: float = 0.0
    simulated_return: float = 0.0
    champion_return: float = 0.0
    outperformance: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    passed: bool = False
    timestamp_ns: int = 0

    def __post_init__(self) -> None:
        if self.timestamp_ns == 0:
            self.timestamp_ns = time.time_ns()


@dataclass
class ChampionRecord:
    """冠军策略记录"""

    strategy: Strategy
    promoted_at: int = 0
    metrics_at_promotion: dict[str, Any] = field(default_factory=dict)
    audit_trail: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ChallengerRecord:
    """挑战者记录"""

    strategy: Strategy
    submitted_at: int = 0
    comparison_results: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ComparisonResult:
    """冠军-挑战者对比结果"""

    slot: str
    champion_id: str
    challenger_id: str
    champion_sharpe: float = 0.0
    challenger_sharpe: float = 0.0
    champion_max_dd: float = 0.0
    challenger_max_dd: float = 0.0
    champion_win_rate: float = 0.0
    challenger_win_rate: float = 0.0
    outperformance: float = 0.0
    stability_score: float = 0.0
    promoted: bool = False
    reason: str = ""
    timestamp_ns: int = 0

    def __post_init__(self) -> None:
        if self.timestamp_ns == 0:
            self.timestamp_ns = time.time_ns()


@dataclass
class EvolutionAuditRecord:
    """进化审计记录"""

    event: str
    strategy_id: str
    stage: str
    data_used: dict[str, Any] = field(default_factory=dict)
    comparison: dict[str, Any] = field(default_factory=dict)
    decision: str = ""
    reason: str = ""
    metrics_snapshot: dict[str, Any] = field(default_factory=dict)
    timestamp_ns: int = 0

    def __post_init__(self) -> None:
        if self.timestamp_ns == 0:
            self.timestamp_ns = time.time_ns()
