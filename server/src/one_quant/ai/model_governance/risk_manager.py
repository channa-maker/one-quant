"""
模型治理 — 模型风险管理器 (MRM)

完整功能：
  1. 模型清单管理（注册/查询/版本管理）
  2. 模型卡元信息与治理记录
  3. 审批链（多级审批、拒绝、回退）
  4. 模型验证流程
  5. 模型血缘追踪
  6. 运行时监控（漂移检测、性能退化）
  7. 模型退役机制
"""

from __future__ import annotations

import statistics
import time
from collections.abc import Callable
from typing import Any

from one_quant.ai.model_governance.enums import (
    AlertSeverity,
    ApprovalAction,
    DriftType,
    ModelStatus,
)
from one_quant.ai.model_governance.models import (
    DriftAlert,
    LineageRecord,
    ModelCard,
    MonitoringSnapshot,
    ValidationReport,
)
from one_quant.infra.logging import get_logger

logger = get_logger(__name__)


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
