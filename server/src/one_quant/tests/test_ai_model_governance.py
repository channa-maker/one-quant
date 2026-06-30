"""AI 模型治理测试 — 模型清单/验证/审批/退役状态机

覆盖模块: one_quant.ai.model_governance
目标: ≥80% 覆盖率
"""

from __future__ import annotations

from unittest.mock import MagicMock

from one_quant.ai.model_governance import (
    AIDataPoisoning防护,
    AlertSeverity,
    ApprovalAction,
    DriftAlert,
    DriftType,
    LineageRecord,
    ModelCard,
    ModelRiskManager,
    ModelStatus,
    MonitoringSnapshot,
    ValidationReport,
)

# ──────────────────── 辅助工厂 ────────────────────


def _make_card(
    model_id: str = "m1",
    name: str = "test_model",
    version: str = "1.0",
    status: ModelStatus = ModelStatus.DRAFT,
) -> ModelCard:
    return ModelCard(
        model_id=model_id, name=name, version=version, description="测试模型", status=status
    )


def _make_snapshot(
    model_id: str = "m1", accuracy: float = 0.85, pred_count: int = 100, err_count: int = 5
) -> MonitoringSnapshot:
    return MonitoringSnapshot(
        model_id=model_id,
        metrics={"accuracy": accuracy, "sharpe": 1.5},
        prediction_count=pred_count,
        error_count=err_count,
    )


# ──────────────────── ModelCard 测试 ────────────────────


class TestModelCard:
    """模型卡测试"""

    def test_auto_timestamp(self):
        card = _make_card()
        assert card.created_at > 0

    def test_is_active(self):
        card = _make_card(status=ModelStatus.APPROVED)
        assert card.is_active is True
        card.status = ModelStatus.LIVE
        assert card.is_active is True
        card.status = ModelStatus.DRAFT
        assert card.is_active is False

    def test_approval_count(self):
        card = _make_card()
        card.approval_chain = [
            {"action": ApprovalAction.APPROVE.value},
            {"action": ApprovalAction.REJECT.value},
            {"action": ApprovalAction.APPROVE.value},
        ]
        assert card.approval_count == 2
        assert card.rejection_count == 1


# ──────────────────── MonitoringSnapshot 测试 ────────────────────


class TestMonitoringSnapshot:
    """监控快照测试"""

    def test_error_rate(self):
        snap = _make_snapshot(pred_count=100, err_count=10)
        assert snap.error_rate == 0.1

    def test_error_rate_zero_predictions(self):
        snap = _make_snapshot(pred_count=0, err_count=0)
        assert snap.error_rate == 0.0

    def test_auto_timestamp(self):
        snap = _make_snapshot()
        assert snap.timestamp_ns > 0


# ──────────────────── DriftAlert 测试 ────────────────────


class TestDriftAlert:
    """漂移告警测试"""

    def test_deviation_pct(self):
        alert = DriftAlert(
            model_id="m1",
            drift_type=DriftType.PERFORMANCE_DRIFT,
            severity=AlertSeverity.WARNING,
            metric_name="accuracy",
            current_value=0.75,
            baseline_value=0.85,
            threshold=0.05,
            message="test",
        )
        assert abs(alert.deviation_pct - 11.76) < 1.0

    def test_deviation_pct_zero_baseline(self):
        alert = DriftAlert(
            model_id="m1",
            drift_type=DriftType.PERFORMANCE_DRIFT,
            severity=AlertSeverity.WARNING,
            metric_name="accuracy",
            current_value=0.75,
            baseline_value=0.0,
            threshold=0.05,
            message="test",
        )
        assert alert.deviation_pct == 0.0

    def test_auto_timestamp(self):
        alert = DriftAlert(
            model_id="m1",
            drift_type=DriftType.DATA_DRIFT,
            severity=AlertSeverity.INFO,
            metric_name="x",
            current_value=0.0,
            baseline_value=0.0,
            threshold=0.1,
            message="test",
        )
        assert alert.timestamp_ns > 0


# ──────────────────── ModelRiskManager 测试 ────────────────────


class TestModelRiskManager:
    """模型风险管理器测试"""

    # ── 注册/查询 ──

    def test_register_and_get(self):
        mrm = ModelRiskManager()
        card = _make_card()
        mrm.register(card)
        assert mrm.get_model("m1") is card

    def test_get_nonexistent(self):
        mrm = ModelRiskManager()
        assert mrm.get_model("nonexistent") is None

    def test_list_models(self):
        mrm = ModelRiskManager()
        mrm.register(_make_card("m1", status=ModelStatus.DRAFT))
        mrm.register(_make_card("m2", status=ModelStatus.LIVE))
        assert len(mrm.list_models()) == 2
        assert len(mrm.list_models(ModelStatus.DRAFT)) == 1

    def test_list_active_models(self):
        mrm = ModelRiskManager()
        mrm.register(_make_card("m1", status=ModelStatus.DRAFT))
        mrm.register(_make_card("m2", status=ModelStatus.APPROVED))
        mrm.register(_make_card("m3", status=ModelStatus.LIVE))
        active = mrm.list_active_models()
        assert len(active) == 2

    def test_update_tags(self):
        mrm = ModelRiskManager()
        mrm.register(_make_card())
        assert mrm.update_tags("m1", ["v1", "prod"]) is True
        assert mrm.get_model("m1").tags == ["v1", "prod"]

    def test_update_tags_nonexistent(self):
        mrm = ModelRiskManager()
        assert mrm.update_tags("nonexistent", ["tag"]) is False

    # ── 验证流程 ──

    def test_submit_validation(self):
        mrm = ModelRiskManager()
        mrm.register(_make_card())
        assert mrm.submit_validation("m1", {"sharpe": 1.5}) is True
        assert mrm.get_model("m1").status == ModelStatus.VALIDATION

    def test_submit_validation_nonexistent(self):
        mrm = ModelRiskManager()
        assert mrm.submit_validation("nonexistent", {}) is False

    def test_submit_validation_wrong_status(self):
        mrm = ModelRiskManager()
        mrm.register(_make_card(status=ModelStatus.LIVE))
        assert mrm.submit_validation("m1", {}) is False

    def test_submit_validation_report_passed(self):
        mrm = ModelRiskManager()
        mrm.register(_make_card())
        report = ValidationReport(
            model_id="m1", validator="test", passed=True, metrics={"sharpe": 1.5}
        )
        assert mrm.submit_validation_report(report) is True
        assert mrm.get_model("m1").status == ModelStatus.VALIDATION

    def test_submit_validation_report_failed(self):
        mrm = ModelRiskManager()
        mrm.register(_make_card())
        report = ValidationReport(model_id="m1", validator="test", passed=False)
        assert mrm.submit_validation_report(report) is True
        assert mrm.get_model("m1").status == ModelStatus.DRAFT

    def test_submit_validation_report_nonexistent(self):
        mrm = ModelRiskManager()
        report = ValidationReport(model_id="x", validator="test", passed=True)
        assert mrm.submit_validation_report(report) is False

    def test_get_validation_reports(self):
        mrm = ModelRiskManager()
        mrm.register(_make_card())
        report = ValidationReport(model_id="m1", validator="test", passed=True)
        mrm.submit_validation_report(report)
        reports = mrm.get_validation_reports("m1")
        assert len(reports) == 1

    # ── 审批链 ──

    def test_approve(self):
        mrm = ModelRiskManager()
        mrm.register(_make_card(status=ModelStatus.VALIDATION))
        assert mrm.approve("m1", "risk_team", "LGTM") is True
        card = mrm.get_model("m1")
        assert card.status == ModelStatus.APPROVED
        assert card.approved_at > 0

    def test_approve_wrong_status(self):
        mrm = ModelRiskManager()
        mrm.register(_make_card(status=ModelStatus.DRAFT))
        assert mrm.approve("m1", "risk_team") is False

    def test_approve_nonexistent(self):
        mrm = ModelRiskManager()
        assert mrm.approve("x", "risk_team") is False

    def test_reject(self):
        mrm = ModelRiskManager()
        mrm.register(_make_card(status=ModelStatus.VALIDATION))
        assert mrm.reject("m1", "risk_team", "回撤太大") is True
        assert mrm.get_model("m1").status == ModelStatus.DRAFT

    def test_reject_nonexistent(self):
        mrm = ModelRiskManager()
        assert mrm.reject("x", "risk_team") is False

    def test_request_changes(self):
        mrm = ModelRiskManager()
        mrm.register(_make_card(status=ModelStatus.VALIDATION))
        assert mrm.request_changes("m1", "reviewer", "需要更多回测") is True
        assert mrm.get_model("m1").status == ModelStatus.DRAFT

    def test_request_changes_nonexistent(self):
        mrm = ModelRiskManager()
        assert mrm.request_changes("x", "reviewer") is False

    def test_get_approval_history(self):
        mrm = ModelRiskManager()
        mrm.register(_make_card(status=ModelStatus.VALIDATION))
        mrm.approve("m1", "risk_team")
        history = mrm.get_approval_history("m1")
        assert len(history) == 1

    def test_get_approval_history_nonexistent(self):
        mrm = ModelRiskManager()
        assert mrm.get_approval_history("x") == []

    # ── 生命周期 ──

    def test_promote_to_live(self):
        mrm = ModelRiskManager()
        mrm.register(_make_card(status=ModelStatus.APPROVED))
        assert mrm.promote_to_live("m1") is True
        assert mrm.get_model("m1").status == ModelStatus.LIVE

    def test_promote_to_live_wrong_status(self):
        mrm = ModelRiskManager()
        mrm.register(_make_card(status=ModelStatus.DRAFT))
        assert mrm.promote_to_live("m1") is False

    def test_promote_to_live_nonexistent(self):
        mrm = ModelRiskManager()
        assert mrm.promote_to_live("x") is False

    def test_retire(self):
        mrm = ModelRiskManager()
        mrm.register(_make_card(status=ModelStatus.LIVE))
        assert mrm.retire("m1", "过期") is True
        card = mrm.get_model("m1")
        assert card.status == ModelStatus.RETIRED
        assert card.retired_at > 0

    def test_retire_nonexistent(self):
        mrm = ModelRiskManager()
        assert mrm.retire("x", "reason") is False

    def test_rollback(self):
        mrm = ModelRiskManager()
        mrm.register(_make_card(status=ModelStatus.LIVE))
        assert mrm.rollback("m1", ModelStatus.DRAFT, "回退") is True
        assert mrm.get_model("m1").status == ModelStatus.DRAFT

    def test_rollback_nonexistent(self):
        mrm = ModelRiskManager()
        assert mrm.rollback("x", ModelStatus.DRAFT, "reason") is False

    # ── 血缘追踪 ──

    def test_record_lineage(self):
        mrm = ModelRiskManager()
        mrm.register(_make_card())
        record = LineageRecord(
            model_id="m1",
            upstream_datasets=["btc_1m"],
            upstream_features=["ema_12", "ema_26"],
        )
        mrm.record_lineage(record)
        lineage = mrm.get_lineage("m1")
        assert lineage is not None
        assert "btc_1m" in lineage.upstream_datasets

    def test_record_lineage_updates_card(self):
        mrm = ModelRiskManager()
        mrm.register(_make_card())
        record = LineageRecord(model_id="m1", upstream_datasets=["ds1"])
        mrm.record_lineage(record)
        assert "upstream_datasets" in mrm.get_model("m1").lineage

    def test_get_lineage_nonexistent(self):
        mrm = ModelRiskManager()
        assert mrm.get_lineage("x") is None

    def test_get_downstream_models(self):
        mrm = ModelRiskManager()
        mrm.register(_make_card("m1"))
        mrm.register(_make_card("m2"))
        mrm.record_lineage(LineageRecord(model_id="m2", upstream_models=["m1"]))
        downstream = mrm.get_downstream_models("m1")
        assert "m2" in downstream

    def test_get_upstream_chain(self):
        mrm = ModelRiskManager()
        mrm.register(_make_card("m1"))
        mrm.register(_make_card("m2"))
        mrm.record_lineage(
            LineageRecord(model_id="m2", upstream_models=["m1"], upstream_datasets=["ds1"])
        )
        chain = mrm.get_upstream_chain("m2")
        assert chain["model_id"] == "m2"
        assert len(chain["upstream_models"]) == 1

    def test_get_upstream_chain_cycle(self):
        """循环依赖检测"""
        mrm = ModelRiskManager()
        mrm.register(_make_card("m1"))
        mrm.register(_make_card("m2"))
        mrm.record_lineage(LineageRecord(model_id="m1", upstream_models=["m2"]))
        mrm.record_lineage(LineageRecord(model_id="m2", upstream_models=["m1"]))
        chain = mrm.get_upstream_chain("m1")
        # 递归访问 m1→m2→m1 应检测到循环
        assert chain.get("model_id") == "m1"

    def test_impact_analysis(self):
        mrm = ModelRiskManager()
        mrm.register(_make_card("m1"))
        mrm.register(_make_card("m2"))
        mrm.register(_make_card("m3"))
        mrm.record_lineage(LineageRecord(model_id="m2", upstream_models=["m1"]))
        mrm.record_lineage(LineageRecord(model_id="m3", upstream_models=["m2"]))
        impact = mrm.impact_analysis("m1")
        assert impact["total_impacted"] == 2
        assert "m2" in impact["all_downstream"]
        assert "m3" in impact["all_downstream"]

    # ── 监控 ──

    def test_record_snapshot(self):
        mrm = ModelRiskManager()
        mrm.register(_make_card())
        snap = _make_snapshot()
        alerts = mrm.record_snapshot(snap)
        assert isinstance(alerts, list)
        assert mrm.get_model("m1").last_monitored_at > 0

    def test_drift_detection_performance(self):
        """性能漂移检测"""
        mrm = ModelRiskManager()
        mrm.register(_make_card())
        # 建立基线
        for _ in range(15):
            mrm.record_snapshot(
                MonitoringSnapshot(
                    model_id="m1",
                    metrics={"accuracy": 0.9},
                    prediction_count=100,
                )
            )
        # 触发漂移
        alerts = mrm.record_snapshot(
            MonitoringSnapshot(
                model_id="m1",
                metrics={"accuracy": 0.5},
                prediction_count=100,
            )
        )
        assert len(alerts) > 0

    def test_error_rate_alert(self):
        """高错误率告警"""
        mrm = ModelRiskManager()
        mrm.register(_make_card())
        # 需要先建立足够的历史快照（至少10个）
        for i in range(12):
            mrm.record_snapshot(
                MonitoringSnapshot(
                    model_id="m1",
                    metrics={"accuracy": 0.9},
                    prediction_count=100,
                    error_count=1,
                )
            )
        snap = MonitoringSnapshot(
            model_id="m1",
            metrics={"accuracy": 0.9},
            prediction_count=100,
            error_count=10,  # 10% 错误率
        )
        alerts = mrm.record_snapshot(snap)
        error_alerts = [a for a in alerts if a.metric_name == "error_rate"]
        assert len(error_alerts) == 1

    def test_error_rate_critical(self):
        """严重错误率"""
        mrm = ModelRiskManager()
        mrm.register(_make_card())
        for i in range(12):
            mrm.record_snapshot(
                MonitoringSnapshot(
                    model_id="m1",
                    metrics={"accuracy": 0.9},
                    prediction_count=100,
                    error_count=1,
                )
            )
        snap = MonitoringSnapshot(
            model_id="m1",
            metrics={"accuracy": 0.9},
            prediction_count=100,
            error_count=15,  # 15%
        )
        alerts = mrm.record_snapshot(snap)
        error_alerts = [a for a in alerts if a.metric_name == "error_rate"]
        assert any(a.severity == AlertSeverity.CRITICAL for a in error_alerts)

    def test_on_drift_callback(self):
        """漂移回调"""
        mrm = ModelRiskManager()
        callback = MagicMock()
        mrm.on_drift(callback)
        mrm.register(_make_card())
        # 建立基线
        for _ in range(15):
            mrm.record_snapshot(
                MonitoringSnapshot(
                    model_id="m1",
                    metrics={"accuracy": 0.9},
                    prediction_count=100,
                )
            )
        # 触发漂移
        mrm.record_snapshot(
            MonitoringSnapshot(
                model_id="m1",
                metrics={"accuracy": 0.3},
                prediction_count=100,
            )
        )
        assert callback.called

    def test_get_monitoring_history(self):
        mrm = ModelRiskManager()
        mrm.register(_make_card())
        for i in range(5):
            mrm.record_snapshot(
                MonitoringSnapshot(
                    model_id="m1",
                    metrics={"accuracy": 0.9 - i * 0.01},
                    prediction_count=100,
                )
            )
        history = mrm.get_monitoring_history("m1", limit=3)
        assert len(history) == 3

    def test_get_drift_alerts(self):
        mrm = ModelRiskManager()
        mrm.register(_make_card())
        # 建立基线
        for _ in range(15):
            mrm.record_snapshot(
                MonitoringSnapshot(
                    model_id="m1",
                    metrics={"accuracy": 0.9},
                    prediction_count=100,
                )
            )
        # 触发漂移
        mrm.record_snapshot(
            MonitoringSnapshot(
                model_id="m1",
                metrics={"accuracy": 0.3},
                prediction_count=100,
            )
        )
        alerts = mrm.get_drift_alerts(model_id="m1")
        assert len(alerts) > 0

    def test_configure_drift_threshold(self):
        mrm = ModelRiskManager()
        mrm.configure_drift_threshold(DriftType.PERFORMANCE_DRIFT, "custom_metric", 0.5)
        assert mrm._drift_thresholds["performance_drift"]["custom_metric"] == 0.5

    def test_drift_insufficient_history(self):
        """历史快照不足时不检测"""
        mrm = ModelRiskManager()
        mrm.register(_make_card())
        snap = MonitoringSnapshot(
            model_id="m1",
            metrics={"accuracy": 0.5},
            prediction_count=100,
        )
        alerts = mrm.record_snapshot(snap)
        assert len(alerts) == 0

    # ── 治理报告 ──

    def test_generate_governance_report(self):
        mrm = ModelRiskManager()
        mrm.register(_make_card("m1", status=ModelStatus.DRAFT))
        mrm.register(_make_card("m2", status=ModelStatus.LIVE))
        report = mrm.generate_governance_report()
        assert report["total_models"] == 2
        assert report["status_distribution"]["draft"] == 1
        assert report["status_distribution"]["live"] == 1
        assert report["active_models"] == 1


# ──────────────────── AIDataPoisoning防护 测试 ────────────────────


class TestAIDataPoisoning防护:
    """AI 数据投毒防护测试"""

    def test_set_and_get_trust(self):
        guard = AIDataPoisoning防护()
        guard.set_trust("bloomberg", 0.9)
        assert guard.get_trust("bloomberg") == 0.9

    def test_default_trust(self):
        guard = AIDataPoisoning防护()
        assert guard.get_trust("unknown") == 0.5

    def test_trust_clamp(self):
        guard = AIDataPoisoning防护()
        guard.set_trust("src", 1.5)
        assert guard.get_trust("src") == 1.0
        guard.set_trust("src2", -0.5)
        assert guard.get_trust("src2") == 0.0

    def test_flag_source(self):
        guard = AIDataPoisoning防护()
        guard.flag_source("bad_src", "投毒")
        assert guard.is_flagged("bad_src")
        assert guard.get_trust("bad_src") == 0.0

    def test_is_flagged(self):
        guard = AIDataPoisoning防护()
        assert guard.is_flagged("clean") is False

    def test_cross_validate_empty(self):
        guard = AIDataPoisoning防护()
        credible, score = guard.cross_validate([])
        assert credible is False and score == 0.0

    def test_cross_validate_all_flagged(self):
        guard = AIDataPoisoning防护()
        guard.flag_source("bad", "reason")
        credible, score = guard.cross_validate([{"source": "bad", "claim": "x", "confidence": 0.9}])
        assert credible is False

    def test_cross_validate_credible(self):
        guard = AIDataPoisoning防护(min_confidence=0.5)
        guard.set_trust("reliable", 0.9)
        claims = [{"source": "reliable", "claim": "BTC涨", "confidence": 0.8}]
        credible, score = guard.cross_validate(claims)
        assert credible is True
        assert score > 0

    def test_cross_validate_not_credible(self):
        guard = AIDataPoisoning防护(min_confidence=0.9)
        guard.set_trust("low", 0.3)
        claims = [{"source": "low", "claim": "BTC涨", "confidence": 0.5}]
        credible, score = guard.cross_validate(claims)
        assert credible is False

    def test_cross_validate_weighted(self):
        """多源加权验证"""
        guard = AIDataPoisoning防护(min_confidence=0.5)
        guard.set_trust("high", 0.9)
        guard.set_trust("low", 0.3)
        claims = [
            {"source": "high", "claim": "BTC涨", "confidence": 0.8},
            {"source": "low", "claim": "BTC涨", "confidence": 0.9},
        ]
        credible, score = guard.cross_validate(claims)
        # 加权: (0.9*0.8 + 0.3*0.9) / (0.9+0.3) = (0.72+0.27)/1.2 = 0.825
        assert score > 0.7

    def test_detect_anomaly_insufficient_history(self):
        guard = AIDataPoisoning防护()
        assert guard.detect_anomaly("src", 0.5) is False

    def test_detect_anomaly(self):
        guard = AIDataPoisoning防护()
        # 建立历史，使用不同置信度使stdev>0
        for i in range(10):
            guard.cross_validate(
                [{"source": "src", "claim": "x", "confidence": 0.5 + (i % 3) * 0.1}]
            )
        # 异常值：远超历史均值
        assert guard.detect_anomaly("src", 0.99) is True

    def test_detect_anomaly_normal(self):
        guard = AIDataPoisoning防护()
        for i in range(10):
            guard.cross_validate(
                [{"source": "src", "claim": "x", "confidence": 0.5 + (i % 3) * 0.1}]
            )
        assert guard.detect_anomaly("src", 0.55) is False

    def test_get_source_stats(self):
        guard = AIDataPoisoning防护()
        guard.set_trust("src1", 0.8)
        guard.set_trust("src2", 0.6)
        guard.flag_source("src2", "bad")
        stats = guard.get_source_stats()
        assert stats["src1"]["trust"] == 0.8
        assert stats["src1"]["is_flagged"] is False
        assert stats["src2"]["is_flagged"] is True

    def test_cross_validate_records_history(self):
        guard = AIDataPoisoning防护()
        guard.set_trust("src", 0.8)
        guard.cross_validate([{"source": "src", "claim": "x", "confidence": 0.7}])
        stats = guard.get_source_stats()
        assert stats["src"]["history_count"] == 1
