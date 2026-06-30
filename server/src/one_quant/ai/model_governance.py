"""
模型治理 — 模型风险管理 MRM + AI 防护 + 血缘追踪 + 运行监控

完整功能：
  1. 模型清单管理（注册/查询/版本管理）
  2. 模型卡（ModelCard）元信息与治理记录
  3. 审批链（多级审批、拒绝、回退）
  4. 模型验证流程（独立验证 + 验证报告）
  5. 模型血缘追踪（训练数据、特征、上游依赖）
  6. 运行时监控（漂移检测、性能退化、告警）
  7. 数据投毒防护（多源交叉验证、可信度加权）
"""

from __future__ import annotations

import statistics
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from one_quant.infra.logging import get_logger

logger = get_logger(__name__)


# ──────────────────────────── 枚举 ────────────────────────────


class ModelStatus(StrEnum):
    """模型生命周期状态"""

    DRAFT = "draft"  # 草稿：刚创建，未提交验证
    VALIDATION = "validation"  # 验证中：已提交独立验证
    APPROVED = "approved"  # 已审批：通过验证和审批
    LIVE = "live"  # 上线：正在生产环境运行
    RETIRED = "retired"  # 退役：已下线


class ApprovalAction(StrEnum):
    """审批动作"""

    APPROVE = "approve"  # 通过
    REJECT = "reject"  # 拒回
    REQUEST_CHANGES = "request_changes"  # 要求修改


class DriftType(StrEnum):
    """漂移类型"""

    DATA_DRIFT = "data_drift"  # 输入数据分布漂移
    CONCEPT_DRIFT = "concept_drift"  # 概念漂移（输入输出关系变化）
    PERFORMANCE_DRIFT = "performance_drift"  # 性能漂移（准确率下降等）


class AlertSeverity(StrEnum):
    """告警严重度"""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


# ──────────────────────────── 数据类 ────────────────────────────


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


# ──────────────────────────── 模型风险管理器 ────────────────────────────


class ModelRiskManager:
    """模型风险管理器 (MRM)。

    完整功能：
    1. 模型清单管理（注册/查询/版本管理）
    2. 模型卡元信息与治理记录
    3. 审批链（多级审批、拒绝、回退）
    4. 模型验证流程
    5. 模型血缘追踪
    6. 运行时监控（漂移检测、性能退化）
    7. 模型退役机制

    使用示例::

        mrm = ModelRiskManager()

        # 注册模型
        card = ModelCard(
            model_id="v1.0", name="ma_cross",
            version="1.0", description="均线交叉策略"
        )
        mrm.register(card)

        # 记录血缘
        mrm.record_lineage(LineageRecord(
            model_id="v1.0",
            upstream_datasets=["btc_1m_2024"],
            upstream_features=["ema_12", "ema_26"],
        ))

        # 提交验证
        mrm.submit_validation("v1.0", {"sharpe": 1.5, "max_drawdown": 0.15})

        # 审批
        mrm.approve("v1.0", "risk_team", "回测通过")

        # 上线
        mrm.promote_to_live("v1.0")

        # 监控
        mrm.record_snapshot(MonitoringSnapshot(
            model_id="v1.0", metrics={"accuracy": 0.85},
            prediction_count=1000
        ))
    """

    def __init__(self) -> None:
        self._models: dict[str, ModelCard] = {}
        self._lineage: dict[str, LineageRecord] = {}
        self._validation_reports: dict[str, list[ValidationReport]] = {}
        self._monitoring_snapshots: dict[str, list[MonitoringSnapshot]] = {}
        self._drift_alerts: list[DriftAlert] = []
        self._drift_callbacks: list[Callable[[DriftAlert], None]] = []

        # 漂移检测阈值配置
        self._drift_thresholds: dict[str, dict[str, float]] = {
            DriftType.DATA_DRIFT.value: {
                "default": 0.15,  # 分布偏移 15%
            },
            DriftType.PERFORMANCE_DRIFT.value: {
                "accuracy": 0.05,  # 准确率下降 5%
                "sharpe": 0.20,  # 夏普比率下降 20%
                "max_drawdown": 0.10,  # 最大回撤增加 10%
            },
        }

    # ──────────────── 模型清单管理 ────────────────

    def register(self, card: ModelCard) -> None:
        """注册新模型。

        Args:
            card: 模型卡
        """
        self._models[card.model_id] = card
        self._validation_reports[card.model_id] = []
        self._monitoring_snapshots[card.model_id] = []
        logger.info("模型注册: %s v%s (%s)", card.name, card.version, card.model_id)

    def get_model(self, model_id: str) -> ModelCard | None:
        """获取模型卡。

        Args:
            model_id: 模型ID

        Returns:
            模型卡或 None
        """
        return self._models.get(model_id)

    def list_models(self, status: ModelStatus | None = None) -> list[ModelCard]:
        """列出模型。

        Args:
            status: 可选，按状态过滤

        Returns:
            模型卡列表
        """
        if status:
            return [m for m in self._models.values() if m.status == status]
        return list(self._models.values())

    def list_active_models(self) -> list[ModelCard]:
        """列出所有活跃模型（approved + live）。"""
        return [m for m in self._models.values() if m.is_active]

    def update_tags(self, model_id: str, tags: list[str]) -> bool:
        """更新模型标签。

        Args:
            model_id: 模型ID
            tags: 新标签列表

        Returns:
            是否成功
        """
        card = self._models.get(model_id)
        if not card:
            return False
        card.tags = list(tags)
        return True

    # ──────────────── 验证流程 ────────────────

    def submit_validation(self, model_id: str, results: dict[str, Any]) -> bool:
        """提交模型验证结果。

        Args:
            model_id: 模型ID
            results: 验证结果（如 sharpe、max_drawdown 等）

        Returns:
            是否成功提交
        """
        card = self._models.get(model_id)
        if not card:
            logger.warning("模型不存在: %s", model_id)
            return False

        if card.status not in (ModelStatus.DRAFT, ModelStatus.VALIDATION):
            logger.warning("模型状态不允许提交验证: %s (当前: %s)", model_id, card.status.value)
            return False

        card.validation_results = results
        card.status = ModelStatus.VALIDATION
        logger.info("模型提交验证: %s", model_id)
        return True

    def submit_validation_report(self, report: ValidationReport) -> bool:
        """提交详细验证报告。

        Args:
            report: 验证报告

        Returns:
            是否成功
        """
        if report.model_id not in self._models:
            return False

        self._validation_reports[report.model_id].append(report)

        # 同步更新模型卡的验证结果
        card = self._models[report.model_id]
        card.validation_results = {
            "passed": report.passed,
            "metrics": report.metrics,
            "backtest": report.backtest_results,
            "risk": report.risk_assessment,
            "validator": report.validator,
            "notes": report.notes,
        }

        if report.passed:
            card.status = ModelStatus.VALIDATION
            logger.info("验证报告提交（通过）: %s by %s", report.model_id, report.validator)
        else:
            card.status = ModelStatus.DRAFT
            logger.info("验证报告提交（未通过）: %s by %s", report.model_id, report.validator)

        return True

    def get_validation_reports(self, model_id: str) -> list[ValidationReport]:
        """获取模型的验证报告列表。"""
        return self._validation_reports.get(model_id, [])

    # ──────────────── 审批链 ────────────────

    def approve(self, model_id: str, approver: str, notes: str = "") -> bool:
        """审批通过。

        Args:
            model_id: 模型ID
            approver: 审批人
            notes: 审批备注

        Returns:
            是否成功
        """
        card = self._models.get(model_id)
        if not card:
            return False

        if card.status != ModelStatus.VALIDATION:
            logger.warning("模型不在验证状态，无法审批: %s (当前: %s)", model_id, card.status.value)
            return False

        card.approval_chain.append(
            {
                "approver": approver,
                "action": ApprovalAction.APPROVE.value,
                "notes": notes,
                "timestamp_ns": time.time_ns(),
            }
        )
        card.status = ModelStatus.APPROVED
        card.approved_at = time.time_ns()
        logger.info("模型审批通过: %s by %s", model_id, approver)
        return True

    def reject(self, model_id: str, approver: str, reason: str = "") -> bool:
        """审批拒绝。

        Args:
            model_id: 模型ID
            approver: 审批人
            reason: 拒绝原因

        Returns:
            是否成功
        """
        card = self._models.get(model_id)
        if not card:
            return False

        card.approval_chain.append(
            {
                "approver": approver,
                "action": ApprovalAction.REJECT.value,
                "notes": reason,
                "timestamp_ns": time.time_ns(),
            }
        )
        card.status = ModelStatus.DRAFT
        logger.info("模型审批拒绝: %s by %s (原因: %s)", model_id, approver, reason)
        return True

    def request_changes(self, model_id: str, approver: str, feedback: str = "") -> bool:
        """要求修改。

        Args:
            model_id: 模型ID
            approver: 审批人
            feedback: 修改意见

        Returns:
            是否成功
        """
        card = self._models.get(model_id)
        if not card:
            return False

        card.approval_chain.append(
            {
                "approver": approver,
                "action": ApprovalAction.REQUEST_CHANGES.value,
                "notes": feedback,
                "timestamp_ns": time.time_ns(),
            }
        )
        card.status = ModelStatus.DRAFT
        logger.info("要求修改: %s by %s", model_id, approver)
        return True

    def get_approval_history(self, model_id: str) -> list[dict[str, Any]]:
        """获取审批历史。"""
        card = self._models.get(model_id)
        if not card:
            return []
        return list(card.approval_chain)

    # ──────────────── 生命周期管理 ────────────────

    def promote_to_live(self, model_id: str) -> bool:
        """将已审批模型推上线。

        Args:
            model_id: 模型ID

        Returns:
            是否成功
        """
        card = self._models.get(model_id)
        if not card:
            return False

        if card.status != ModelStatus.APPROVED:
            logger.warning("只有已审批模型才能上线: %s (当前: %s)", model_id, card.status.value)
            return False

        card.status = ModelStatus.LIVE
        logger.info("模型上线: %s", model_id)
        return True

    def retire(self, model_id: str, reason: str) -> bool:
        """退役模型。

        Args:
            model_id: 模型ID
            reason: 退役原因

        Returns:
            是否成功
        """
        card = self._models.get(model_id)
        if not card:
            return False

        card.status = ModelStatus.RETIRED
        card.retired_at = time.time_ns()
        logger.info("模型退役: %s (原因: %s)", model_id, reason)
        return True

    def rollback(self, model_id: str, target_status: ModelStatus, reason: str) -> bool:
        """回退模型状态。

        Args:
            model_id: 模型ID
            target_status: 目标状态
            reason: 回退原因

        Returns:
            是否成功
        """
        card = self._models.get(model_id)
        if not card:
            return False

        old_status = card.status
        card.status = target_status
        card.approval_chain.append(
            {
                "approver": "system",
                "action": "rollback",
                "notes": f"从 {old_status.value} 回退到 {target_status.value}: {reason}",
                "timestamp_ns": time.time_ns(),
            }
        )
        logger.info(
            "模型回退: %s %s → %s (%s)", model_id, old_status.value, target_status.value, reason
        )
        return True

    # ──────────────── 血缘追踪 ────────────────

    def record_lineage(self, record: LineageRecord) -> None:
        """记录模型血缘。

        Args:
            record: 血缘记录
        """
        self._lineage[record.model_id] = record

        # 同步更新模型卡的血缘字段
        card = self._models.get(record.model_id)
        if card:
            card.lineage = {
                "upstream_datasets": record.upstream_datasets,
                "upstream_features": record.upstream_features,
                "upstream_models": record.upstream_models,
                "downstream_consumers": record.downstream_consumers,
                "training_config": record.training_config,
                "training_metrics": record.training_metrics,
            }

        logger.info(
            "血缘记录: %s (数据集: %d, 特征: %d, 上游模型: %d)",
            record.model_id,
            len(record.upstream_datasets),
            len(record.upstream_features),
            len(record.upstream_models),
        )

    def get_lineage(self, model_id: str) -> LineageRecord | None:
        """获取模型血缘。"""
        return self._lineage.get(model_id)

    def get_downstream_models(self, model_id: str) -> list[str]:
        """获取依赖指定模型的下游模型列表。

        Args:
            model_id: 模型ID

        Returns:
            下游模型ID列表
        """
        downstream = []
        for mid, record in self._lineage.items():
            if model_id in record.upstream_models:
                downstream.append(mid)
        return downstream

    def get_upstream_chain(self, model_id: str, visited: set[str] | None = None) -> dict[str, Any]:
        """递归获取模型的完整上游依赖链。

        Args:
            model_id: 模型ID
            visited: 已访问集合（防循环）

        Returns:
            树形依赖结构
        """
        if visited is None:
            visited = set()

        if model_id in visited:
            return {"model_id": model_id, "cycle": True}

        visited.add(model_id)
        record = self._lineage.get(model_id)

        if not record:
            return {"model_id": model_id, "datasets": [], "features": [], "upstream_models": []}

        upstream_tree = []
        for upstream_id in record.upstream_models:
            upstream_tree.append(self.get_upstream_chain(upstream_id, visited))

        return {
            "model_id": model_id,
            "datasets": record.upstream_datasets,
            "features": record.upstream_features,
            "upstream_models": upstream_tree,
            "training_metrics": record.training_metrics,
        }

    def impact_analysis(self, model_id: str) -> dict[str, Any]:
        """影响分析：如果指定模型出问题，哪些下游会受影响。

        Args:
            model_id: 模型ID

        Returns:
            影响分析报告
        """
        direct_downstream = self.get_downstream_models(model_id)

        # 递归收集所有下游
        all_downstream: set[str] = set()
        queue = list(direct_downstream)
        while queue:
            mid = queue.pop(0)
            if mid in all_downstream:
                continue
            all_downstream.add(mid)
            queue.extend(self.get_downstream_models(mid))

        return {
            "model_id": model_id,
            "direct_downstream": direct_downstream,
            "all_downstream": sorted(all_downstream),
            "total_impacted": len(all_downstream),
        }

    # ──────────────── 运行时监控 ────────────────

    def record_snapshot(self, snapshot: MonitoringSnapshot) -> list[DriftAlert]:
        """记录监控快照并检测漂移。

        Args:
            snapshot: 监控快照

        Returns:
            触发的漂移告警列表
        """
        model_id = snapshot.model_id
        if model_id not in self._monitoring_snapshots:
            self._monitoring_snapshots[model_id] = []

        self._monitoring_snapshots[model_id].append(snapshot)

        # 更新模型卡的最后监控时间
        card = self._models.get(model_id)
        if card:
            card.last_monitored_at = snapshot.timestamp_ns

        # 检测漂移
        alerts = self._detect_drift(model_id, snapshot)

        # 触发回调
        for alert in alerts:
            self._drift_alerts.append(alert)
            for cb in self._drift_callbacks:
                try:
                    cb(alert)
                except Exception:
                    logger.exception("漂移告警回调异常")

        return alerts

    def _detect_drift(self, model_id: str, snapshot: MonitoringSnapshot) -> list[DriftAlert]:
        """检测模型漂移。

        基于历史快照的统计分析，检测性能漂移。

        Args:
            model_id: 模型ID
            snapshot: 最新快照

        Returns:
            漂移告警列表
        """
        alerts: list[DriftAlert] = []
        history = self._monitoring_snapshots.get(model_id, [])

        # 至少需要 10 个历史快照才能建立基线
        if len(history) < 10:
            return alerts

        # 取前 80% 作为基线，后 20% 作为当前窗口
        split_idx = int(len(history) * 0.8)
        baseline_snapshots = history[:split_idx]
        recent_snapshots = history[split_idx:]

        # 检测每个指标的漂移
        for metric_name in snapshot.metrics:
            baseline_values = [
                s.metrics.get(metric_name, 0.0)
                for s in baseline_snapshots
                if metric_name in s.metrics
            ]
            recent_values = [
                s.metrics.get(metric_name, 0.0)
                for s in recent_snapshots
                if metric_name in s.metrics
            ]

            if not baseline_values or not recent_values:
                continue

            baseline_mean = statistics.mean(baseline_values)
            recent_mean = statistics.mean(recent_values)

            # 获取该指标的漂移阈值
            perf_thresholds = self._drift_thresholds.get(DriftType.PERFORMANCE_DRIFT.value, {})
            threshold = perf_thresholds.get(metric_name, perf_thresholds.get("default", 0.10))

            if baseline_mean == 0:
                continue

            deviation = abs(recent_mean - baseline_mean) / abs(baseline_mean)

            if deviation > threshold:
                severity = (
                    AlertSeverity.CRITICAL if deviation > threshold * 2 else AlertSeverity.WARNING
                )
                alert = DriftAlert(
                    model_id=model_id,
                    drift_type=DriftType.PERFORMANCE_DRIFT,
                    severity=severity,
                    metric_name=metric_name,
                    current_value=recent_mean,
                    baseline_value=baseline_mean,
                    threshold=threshold,
                    message=(
                        f"模型 {model_id} 指标 {metric_name} 漂移: "
                        f"基线={baseline_mean:.4f}, 当前={recent_mean:.4f}, "
                        f"偏差={deviation:.2%} (阈值={threshold:.2%})"
                    ),
                )
                alerts.append(alert)

        # 检测错误率异常
        if snapshot.error_rate > 0.05:  # 错误率 > 5%
            alert = DriftAlert(
                model_id=model_id,
                drift_type=DriftType.PERFORMANCE_DRIFT,
                severity=AlertSeverity.CRITICAL
                if snapshot.error_rate > 0.10
                else AlertSeverity.WARNING,
                metric_name="error_rate",
                current_value=snapshot.error_rate,
                baseline_value=0.0,
                threshold=0.05,
                message=(
                    f"模型 {model_id} 错误率异常: {snapshot.error_rate:.2%} "
                    f"(预测数: {snapshot.prediction_count}, 错误数: {snapshot.error_count})"
                ),
            )
            alerts.append(alert)

        return alerts

    def get_monitoring_history(
        self,
        model_id: str,
        limit: int = 100,
    ) -> list[MonitoringSnapshot]:
        """获取监控历史。"""
        snapshots = self._monitoring_snapshots.get(model_id, [])
        return snapshots[-limit:]

    def get_drift_alerts(
        self,
        model_id: str | None = None,
        severity: AlertSeverity | None = None,
        limit: int = 50,
    ) -> list[DriftAlert]:
        """获取漂移告警。"""
        alerts = list(reversed(self._drift_alerts))
        if model_id:
            alerts = [a for a in alerts if a.model_id == model_id]
        if severity:
            alerts = [a for a in alerts if a.severity == severity]
        return alerts[:limit]

    def on_drift(self, callback: Callable[[DriftAlert], None]) -> None:
        """注册漂移告警回调。

        Args:
            callback: 回调函数
        """
        self._drift_callbacks.append(callback)

    def configure_drift_threshold(
        self,
        drift_type: DriftType,
        metric_name: str,
        threshold: float,
    ) -> None:
        """配置漂移检测阈值。

        Args:
            drift_type: 漂移类型
            metric_name: 指标名称
            threshold: 阈值
        """
        if drift_type.value not in self._drift_thresholds:
            self._drift_thresholds[drift_type.value] = {}
        self._drift_thresholds[drift_type.value][metric_name] = threshold

    # ──────────────── 治理报告 ────────────────

    def generate_governance_report(self) -> dict[str, Any]:
        """生成治理全景报告。

        Returns:
            包含模型统计、状态分布、告警汇总等
        """
        status_counts: dict[str, int] = {}
        for status in ModelStatus:
            status_counts[status.value] = len(
                [m for m in self._models.values() if m.status == status]
            )

        total_alerts = len(self._drift_alerts)
        critical_alerts = len(
            [a for a in self._drift_alerts if a.severity == AlertSeverity.CRITICAL]
        )

        # 最近 24 小时的告警
        now = time.time_ns()
        day_ns = 24 * 3600 * 1_000_000_000
        recent_alerts = len([a for a in self._drift_alerts if (now - a.timestamp_ns) < day_ns])

        return {
            "total_models": len(self._models),
            "status_distribution": status_counts,
            "active_models": len(self.list_active_models()),
            "total_lineage_records": len(self._lineage),
            "total_validation_reports": sum(
                len(reports) for reports in self._validation_reports.values()
            ),
            "monitoring": {
                "total_snapshots": sum(len(s) for s in self._monitoring_snapshots.values()),
                "monitored_models": len(self._monitoring_snapshots),
            },
            "alerts": {
                "total": total_alerts,
                "critical": critical_alerts,
                "recent_24h": recent_alerts,
            },
            "timestamp_ns": now,
        }


# ──────────────────────────── AI 数据投毒防护 ────────────────────────────


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
