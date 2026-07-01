"""
模型治理 — 数据类定义
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from one_quant.ai.model_governance.enums import (
    AlertSeverity,
    ApprovalAction,
    DriftType,
    ModelStatus,
)


@dataclass
class ModelCard:
    """模型卡 — 模型元信息与治理记录。

    每个模型版本对应一张模型卡，包含：
    - 基本信息（ID、名称、版本、描述、负责人）
    - 生命周期状态
    - 验证结果
    - 审批链
    - 血缘信息
    - 监控配置
    """

    model_id: str
    name: str
    version: str
    description: str
    status: ModelStatus = ModelStatus.DRAFT
    owner: str = ""
    tags: list[str] = field(default_factory=list)
    validation_results: dict[str, Any] = field(default_factory=dict)
    approval_chain: list[dict[str, Any]] = field(default_factory=list)
    lineage: dict[str, Any] = field(default_factory=dict)
    monitoring_config: dict[str, Any] = field(default_factory=dict)
    created_at: int = 0
    approved_at: int = 0
    retired_at: int = 0
    last_monitored_at: int = 0

    def __post_init__(self) -> None:
        if self.created_at == 0:
            self.created_at = time.time_ns()

    @property
    def is_active(self) -> bool:
        """模型是否处于活跃状态（approved 或 live）"""
        return self.status in (ModelStatus.APPROVED, ModelStatus.LIVE)

    @property
    def approval_count(self) -> int:
        """通过审批次数"""
        return len(
            [a for a in self.approval_chain if a.get("action") == ApprovalAction.APPROVE.value]
        )

    @property
    def rejection_count(self) -> int:
        """被拒绝次数"""
        return len(
            [a for a in self.approval_chain if a.get("action") == ApprovalAction.REJECT.value]
        )


@dataclass
class LineageRecord:
    """血缘记录 — 追踪模型的上下游依赖。

    记录模型从哪里来（训练数据、特征工程）和到哪里去（被谁使用）。
    """

    model_id: str
    upstream_datasets: list[str] = field(default_factory=list)  # 训练数据集
    upstream_features: list[str] = field(default_factory=list)  # 使用的特征
    upstream_models: list[str] = field(default_factory=list)  # 上游模型（如基座模型）
    downstream_consumers: list[str] = field(default_factory=list)  # 下游消费者
    training_config: dict[str, Any] = field(default_factory=dict)  # 训练配置
    training_metrics: dict[str, float] = field(default_factory=dict)  # 训练指标
    created_at: int = 0

    def __post_init__(self) -> None:
        if self.created_at == 0:
            self.created_at = time.time_ns()


@dataclass
class ValidationReport:
    """验证报告 — 独立验证的结果记录。"""

    model_id: str
    validator: str  # 验证人/系统
    passed: bool  # 是否通过
    metrics: dict[str, float] = field(default_factory=dict)  # 验证指标
    backtest_results: dict[str, Any] = field(default_factory=dict)  # 回测结果
    risk_assessment: dict[str, Any] = field(default_factory=dict)  # 风险评估
    notes: str = ""
    timestamp_ns: int = 0

    def __post_init__(self) -> None:
        if self.timestamp_ns == 0:
            self.timestamp_ns = time.time_ns()


@dataclass
class DriftAlert:
    """漂移告警 — 检测到模型漂移时触发。"""

    model_id: str
    drift_type: DriftType
    severity: AlertSeverity
    metric_name: str
    current_value: float
    baseline_value: float
    threshold: float
    message: str
    timestamp_ns: int = 0

    def __post_init__(self) -> None:
        if self.timestamp_ns == 0:
            self.timestamp_ns = time.time_ns()

    @property
    def deviation_pct(self) -> float:
        """偏差百分比"""
        if self.baseline_value == 0:
            return 0.0
        return abs(self.current_value - self.baseline_value) / abs(self.baseline_value) * 100


@dataclass
class MonitoringSnapshot:
    """监控快照 — 模型运行时的指标快照。"""

    model_id: str
    metrics: dict[str, float]
    prediction_count: int = 0
    error_count: int = 0
    avg_latency_ms: float = 0.0
    timestamp_ns: int = 0

    def __post_init__(self) -> None:
        if self.timestamp_ns == 0:
            self.timestamp_ns = time.time_ns()

    @property
    def error_rate(self) -> float:
        """错误率"""
        if self.prediction_count == 0:
            return 0.0
        return self.error_count / self.prediction_count
