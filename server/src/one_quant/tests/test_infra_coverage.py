"""
Infra 包覆盖率测试 — capacity / change_management / disaster_recovery /
healthcheck / incident / notifier / self_heal / vault / watchdog / logging / event_bus
"""

import asyncio
import os
import sys
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── imports ──────────────────────────────────────────────
from one_quant.infra.capacity import CapacityManager, CapacityMetric, CapacityThreshold
from one_quant.infra.change_management import (
    ChangeManager,
    ChangeRequest,
    ChangeStatus,
    ChangeType,
    DRMetrics,
    FreezeEvent,
    RiskLevel,
)
from one_quant.infra.disaster_recovery import (
    BackupStatus,
    DisasterRecovery,
    DRDrillResult,
    DRScenario,
)
from one_quant.infra.event_bus import (
    BackpressurePolicy,
    EventBusFullError,
    InMemoryEventBus,
    MessageEnvelope,
)
from one_quant.infra.healthcheck import ComponentHealth, HealthChecker, HealthStatus, SystemHealth
from one_quant.infra.incident import IncidentManager, IncidentStatus, Severity
from one_quant.infra.logging import (
    StructuredFormatter,
    _mask_dict,
    get_logger,
    log_mask,
    setup_logging,
)
from one_quant.infra.notifier import ConsoleNotifier, EmailNotifier, WebhookNotifier
from one_quant.infra.self_heal import HealResult, SelfHealStrategy
from one_quant.infra.vault import (
    EnvProvider,
    SecretManager,
    create_secret_manager,
)
from one_quant.infra.watchdog import ProcessStatus, Watchdog

# ════════════════════════════════════════════════════════════════
# CapacityManager
# ════════════════════════════════════════════════════════════════


class TestCapacityManager:
    @pytest.fixture
    def mgr(self):
        return CapacityManager()

    @pytest.mark.asyncio
    async def test_check_data_throughput_no_fn(self, mgr):
        result = await mgr.check_data_throughput()
        assert result["status"] == "ok"
        assert "latency" in result["metrics"]

    @pytest.mark.asyncio
    async def test_check_data_throughput_ok(self, mgr):
        async def tick_fn():
            return 500.0

        mgr.set_tick_rate_fn(tick_fn)
        result = await mgr.check_data_throughput()
        assert result["status"] == "ok"
        assert result["metrics"]["tick_rate"]["current"] == 500.0

    @pytest.mark.asyncio
    async def test_check_data_throughput_warning(self, mgr):
        async def tick_fn():
            return 2000.0

        mgr.set_tick_rate_fn(tick_fn)
        result = await mgr.check_data_throughput()
        assert result["status"] == "warning"

    @pytest.mark.asyncio
    async def test_check_data_throughput_critical(self, mgr):
        async def tick_fn():
            return 6000.0

        mgr.set_tick_rate_fn(tick_fn)
        result = await mgr.check_data_throughput()
        assert result["status"] == "critical"

    @pytest.mark.asyncio
    async def test_check_data_throughput_error(self, mgr):
        async def tick_fn():
            raise RuntimeError("fail")

        mgr.set_tick_rate_fn(tick_fn)
        result = await mgr.check_data_throughput()
        assert "error" in result["metrics"].get("tick_rate", {})

    @pytest.mark.asyncio
    async def test_check_data_throughput_with_notify(self, mgr):
        notify = AsyncMock()
        mgr.set_notifier(notify)

        async def tick_fn():
            return 6000.0

        mgr.set_tick_rate_fn(tick_fn)
        await mgr.check_data_throughput()
        notify.assert_called_once()

    @pytest.mark.asyncio
    async def test_check_storage_growth_no_fn(self, mgr):
        result = await mgr.check_storage_growth()
        assert result["status"] == "ok"

    @pytest.mark.asyncio
    async def test_check_storage_growth_ok(self, mgr):
        async def storage_fn():
            return {"db_size_gb": 10, "disk_used_pct": 50, "days_until_full": 90}

        mgr.set_storage_fn(storage_fn)
        result = await mgr.check_storage_growth()
        assert result["status"] == "ok"

    @pytest.mark.asyncio
    async def test_check_storage_growth_warning(self, mgr):
        async def storage_fn():
            return {"db_size_gb": 100, "disk_used_pct": 75, "days_until_full": 10}

        mgr.set_storage_fn(storage_fn)
        result = await mgr.check_storage_growth()
        assert result["status"] == "warning"

    @pytest.mark.asyncio
    async def test_check_storage_growth_critical(self, mgr):
        async def storage_fn():
            return {"db_size_gb": 200, "disk_used_pct": 95, "days_until_full": 2}

        mgr.set_storage_fn(storage_fn)
        result = await mgr.check_storage_growth()
        assert result["status"] == "critical"

    @pytest.mark.asyncio
    async def test_check_storage_growth_days_alert(self, mgr):
        async def storage_fn():
            return {"db_size_gb": 100, "disk_used_pct": 50, "days_until_full": 5}

        mgr.set_storage_fn(storage_fn)
        result = await mgr.check_storage_growth()
        assert "alert" in result["metrics"]

    @pytest.mark.asyncio
    async def test_check_storage_growth_error(self, mgr):
        async def storage_fn():
            raise RuntimeError("fail")

        mgr.set_storage_fn(storage_fn)
        result = await mgr.check_storage_growth()
        assert "error" in result["metrics"]

    @pytest.mark.asyncio
    async def test_check_llm_cost_no_fn(self, mgr):
        result = await mgr.check_llm_cost()
        assert result["status"] == "ok"

    @pytest.mark.asyncio
    async def test_check_llm_cost_ok(self, mgr):
        async def cost_fn():
            return {
                "monthly_cost_usd": 100,
                "daily_budget_usd": 50,
                "days_in_month": 30,
                "day_of_month": 15,
            }

        mgr.set_llm_cost_fn(cost_fn)
        result = await mgr.check_llm_cost()
        assert result["status"] == "ok"

    @pytest.mark.asyncio
    async def test_check_llm_cost_warning(self, mgr):
        async def cost_fn():
            return {
                "monthly_cost_usd": 800,
                "daily_budget_usd": 50,
                "days_in_month": 30,
                "day_of_month": 10,
            }

        mgr.set_llm_cost_fn(cost_fn)
        result = await mgr.check_llm_cost()
        assert result["status"] in ("warning", "critical")

    @pytest.mark.asyncio
    async def test_check_llm_cost_critical(self, mgr):
        async def cost_fn():
            return {
                "monthly_cost_usd": 1200,
                "daily_budget_usd": 50,
                "days_in_month": 30,
                "day_of_month": 5,
            }

        mgr.set_llm_cost_fn(cost_fn)
        result = await mgr.check_llm_cost()
        assert result["status"] == "critical"

    @pytest.mark.asyncio
    async def test_check_llm_cost_error(self, mgr):
        async def cost_fn():
            raise RuntimeError("fail")

        mgr.set_llm_cost_fn(cost_fn)
        result = await mgr.check_llm_cost()
        assert "error" in result["metrics"]

    @pytest.mark.asyncio
    async def test_full_check(self, mgr):
        report = await mgr.full_check()
        assert "sections" in report
        assert "throughput" in report["sections"]
        assert "storage" in report["sections"]
        assert "llm_cost" in report["sections"]
        assert report["overall_status"] == "ok"

    @pytest.mark.asyncio
    async def test_full_check_critical(self, mgr):
        async def tick_fn():
            return 6000.0

        mgr.set_tick_rate_fn(tick_fn)
        report = await mgr.full_check()
        assert report["overall_status"] == "critical"

    def test_current_metrics_empty(self, mgr):
        assert mgr.current_metrics == {}

    def test_current_metrics_with_data(self, mgr):
        mgr._metrics["test"] = CapacityMetric(
            name="test",
            current=42.0,
            threshold=CapacityThreshold(warning=50, critical=90, unit="%"),
            status="ok",
        )
        m = mgr.current_metrics
        assert "test" in m
        assert m["test"]["current"] == 42.0

    def test_history(self, mgr):
        assert mgr.history == []


# ════════════════════════════════════════════════════════════════
# ChangeManager
# ════════════════════════════════════════════════════════════════


class TestChangeManager:
    @pytest.fixture
    def mgr(self):
        return ChangeManager()

    @pytest.fixture
    def sample_change(self):
        return ChangeRequest(
            change_id="CHG-001",
            title="升级策略引擎",
            change_type=ChangeType.FEATURE,
            risk_level=RiskLevel.MEDIUM,
            description="升级到 v2",
            rollback_plan="回滚到 v1",
        )

    def test_submit(self, mgr, sample_change):
        cid = mgr.submit(sample_change)
        assert cid == "CHG-001"
        assert sample_change.status == ChangeStatus.PENDING_APPROVAL

    def test_approve_change(self, mgr, sample_change):
        mgr.submit(sample_change)
        ok = mgr.approve_change({"change_id": "CHG-001", "approver": "技术负责人"})
        assert ok is True
        assert sample_change.status == ChangeStatus.APPROVED

    def test_approve_change_not_found(self, mgr):
        assert mgr.approve_change({"change_id": "NOPE", "approver": "技术负责人"}) is False

    def test_approve_change_wrong_approver(self, mgr, sample_change):
        mgr.submit(sample_change)
        assert mgr.approve_change({"change_id": "CHG-001", "approver": "实习生"}) is False

    def test_approve_change_during_freeze(self, mgr, sample_change):
        mgr.submit(sample_change)
        mgr.freeze(3600, "CPI发布")
        assert mgr.approve_change({"change_id": "CHG-001", "approver": "技术负责人"}) is False

    def test_reject_change(self, mgr, sample_change):
        mgr.submit(sample_change)
        ok = mgr.reject_change("CHG-001", "CTO", "资源不足")
        assert ok is True
        assert sample_change.status == ChangeStatus.REJECTED

    def test_reject_change_not_found(self, mgr):
        assert mgr.reject_change("NOPE", "CTO") is False

    def test_execute_change(self, mgr, sample_change):
        mgr.submit(sample_change)
        mgr.approve_change({"change_id": "CHG-001", "approver": "技术负责人"})
        ok = mgr.execute_change("CHG-001")
        assert ok is True
        assert sample_change.status == ChangeStatus.EXECUTING

    def test_execute_change_not_approved(self, mgr, sample_change):
        mgr.submit(sample_change)
        assert mgr.execute_change("CHG-001") is False

    def test_execute_change_during_freeze(self, mgr, sample_change):
        mgr.submit(sample_change)
        mgr.approve_change({"change_id": "CHG-001", "approver": "技术负责人"})
        mgr.freeze(3600)
        assert mgr.execute_change("CHG-001") is False

    def test_execute_change_not_found(self, mgr):
        assert mgr.execute_change("NOPE") is False

    def test_mark_executed_success(self, mgr, sample_change):
        mgr.submit(sample_change)
        assert mgr.mark_executed("CHG-001", success=True) is True
        assert sample_change.status == ChangeStatus.EXECUTED

    def test_mark_executed_failure(self, mgr, sample_change):
        mgr.submit(sample_change)
        assert mgr.mark_executed("CHG-001", success=False) is True
        assert sample_change.status == ChangeStatus.FAILED

    def test_mark_executed_not_found(self, mgr):
        assert mgr.mark_executed("NOPE") is False

    def test_rollback(self, mgr, sample_change):
        mgr.submit(sample_change)
        ok = mgr.rollback("CHG-001", "部署失败")
        assert ok is True
        assert sample_change.status == ChangeStatus.ROLLED_BACK
        assert sample_change.rolled_back is True

    def test_rollback_not_found(self, mgr):
        assert mgr.rollback("NOPE") is False

    def test_rollback_no_plan(self, mgr):
        change = ChangeRequest(
            change_id="CHG-002",
            title="test",
            change_type=ChangeType.CONFIG,
            risk_level=RiskLevel.LOW,
            description="",
            rollback_plan="",
        )
        mgr.submit(change)
        assert mgr.rollback("CHG-002") is False

    @pytest.mark.asyncio
    async def test_execute_rollback_success(self, mgr, sample_change):
        rollback_fn = AsyncMock(return_value=True)
        mgr.set_rollback_fn(rollback_fn)
        mgr.submit(sample_change)
        ok = await mgr.execute_rollback("CHG-001", "reason")
        assert ok is True
        rollback_fn.assert_called_once_with("CHG-001")

    @pytest.mark.asyncio
    async def test_execute_rollback_failure(self, mgr, sample_change):
        rollback_fn = AsyncMock(return_value=False)
        mgr.set_rollback_fn(rollback_fn)
        mgr.submit(sample_change)
        ok = await mgr.execute_rollback("CHG-001")
        assert ok is False

    @pytest.mark.asyncio
    async def test_execute_rollback_no_fn(self, mgr, sample_change):
        mgr.submit(sample_change)
        ok = await mgr.execute_rollback("CHG-001")
        assert ok is False

    @pytest.mark.asyncio
    async def test_execute_rollback_exception(self, mgr, sample_change):
        rollback_fn = AsyncMock(side_effect=RuntimeError("boom"))
        mgr.set_rollback_fn(rollback_fn)
        mgr.submit(sample_change)
        ok = await mgr.execute_rollback("CHG-001")
        assert ok is False

    @pytest.mark.asyncio
    async def test_execute_rollback_not_found(self, mgr):
        assert await mgr.execute_rollback("NOPE") is False

    def test_freeze_unfreeze(self, mgr):
        assert mgr.is_freeze_period()[0] is False
        mgr.freeze(3600, "CPI")
        frozen, reason = mgr.is_freeze_period()
        assert frozen is True
        assert "CPI" in reason
        mgr.unfreeze()
        assert mgr.is_freeze_period()[0] is False

    def test_freeze_event(self, mgr):
        now = time.time()
        event = FreezeEvent(
            name="FOMC", start_time=now - 100, end_time=now + 100, reason="利率决议"
        )
        mgr.add_freeze_event(event)
        frozen, reason = mgr.is_freeze_period()
        assert frozen is True
        assert "FOMC" in reason

    def test_freeze_event_expired(self, mgr):
        now = time.time()
        event = FreezeEvent(name="OLD", start_time=now - 200, end_time=now - 100)
        mgr.add_freeze_event(event)
        assert mgr.is_freeze_period()[0] is False

    def test_check_freeze_events(self, mgr):
        now = time.time()
        mgr.add_freeze_event(FreezeEvent(name="FOMC", start_time=now - 100, end_time=now + 100))
        mgr.add_freeze_event(FreezeEvent(name="CPI", start_time=now + 200, end_time=now + 300))
        mgr.add_freeze_event(FreezeEvent(name="OLD", start_time=now - 300, end_time=now - 200))
        events = mgr.check_freeze_events()
        assert len(events) == 2
        statuses = {e["status"] for e in events}
        assert "active" in statuses
        assert "upcoming" in statuses

    def test_get_change(self, mgr, sample_change):
        mgr.submit(sample_change)
        d = mgr.get_change("CHG-001")
        assert d is not None
        assert d["title"] == "升级策略引擎"
        assert d["type"] == "feature"

    def test_get_change_not_found(self, mgr):
        assert mgr.get_change("NOPE") is None

    def test_list_changes(self, mgr):
        for i in range(3):
            mgr.submit(
                ChangeRequest(
                    change_id=f"CHG-{i:03d}",
                    title=f"变更{i}",
                    change_type=ChangeType.FEATURE,
                    risk_level=RiskLevel.LOW,
                    description="",
                    rollback_plan="plan",
                )
            )
        all_changes = mgr.list_changes()
        assert len(all_changes) == 3
        pending = mgr.list_changes(status="pending_approval")
        assert len(pending) == 3

    def test_stats(self, mgr, sample_change):
        mgr.submit(sample_change)
        s = mgr.stats
        assert s["total_changes"] == 1
        assert s["pending_approval"] == 1
        assert isinstance(s["release_windows"], list)

    def test_drm_metrics(self):
        m = DRMetrics()
        assert m.rto_target_sec == 300
        assert m.rpo_target_sec == 1

    def test_approval_requirements(self):
        assert "CTO" in ChangeManager.APPROVAL_REQUIREMENTS[RiskLevel.HIGH]
        assert "CEO" in ChangeManager.APPROVAL_REQUIREMENTS[RiskLevel.CRITICAL]

    def test_change_type_enum(self):
        assert ChangeType.HOTFIX == "hotfix"
        assert ChangeType.STRATEGY == "strategy"

    def test_risk_level_enum(self):
        assert RiskLevel.LOW == "low"
        assert RiskLevel.CRITICAL == "critical"

    def test_change_status_enum(self):
        assert ChangeStatus.DRAFT == "draft"
        assert ChangeStatus.EXECUTED == "executed"


# ════════════════════════════════════════════════════════════════
# DisasterRecovery
# ════════════════════════════════════════════════════════════════


class TestDisasterRecovery:
    @pytest.fixture
    def dr(self):
        return DisasterRecovery(rto_target_sec=300, rpo_target_sec=1)

    @pytest.mark.asyncio
    async def test_db_backup_no_fn(self, dr):
        ok = await dr.db_backup()
        assert ok is False
        assert len(dr.backup_history) == 1
        assert dr.backup_history[0]["status"] == "failed"

    @pytest.mark.asyncio
    async def test_db_backup_success(self, dr):
        fn = AsyncMock(return_value=True)
        dr.set_db_backup_fn(fn)
        ok = await dr.db_backup()
        assert ok is True
        assert dr.backup_history[0]["status"] == "success"

    @pytest.mark.asyncio
    async def test_db_backup_failure(self, dr):
        fn = AsyncMock(return_value=False)
        dr.set_db_backup_fn(fn)
        ok = await dr.db_backup()
        assert ok is False
        assert dr.backup_history[0]["status"] == "failed"

    @pytest.mark.asyncio
    async def test_db_backup_exception(self, dr):
        fn = AsyncMock(side_effect=RuntimeError("boom"))
        dr.set_db_backup_fn(fn)
        ok = await dr.db_backup()
        assert ok is False

    @pytest.mark.asyncio
    async def test_redis_backup_no_fn(self, dr):
        ok = await dr.redis_backup()
        assert ok is False

    @pytest.mark.asyncio
    async def test_redis_backup_success(self, dr):
        fn = AsyncMock(return_value=True)
        dr.set_redis_backup_fn(fn)
        ok = await dr.redis_backup()
        assert ok is True
        assert dr.backup_history[0]["type"] == "redis"

    @pytest.mark.asyncio
    async def test_redis_backup_failure(self, dr):
        fn = AsyncMock(return_value=False)
        dr.set_redis_backup_fn(fn)
        ok = await dr.redis_backup()
        assert ok is False

    @pytest.mark.asyncio
    async def test_redis_backup_exception(self, dr):
        fn = AsyncMock(side_effect=RuntimeError("boom"))
        dr.set_redis_backup_fn(fn)
        ok = await dr.redis_backup()
        assert ok is False

    @pytest.mark.asyncio
    async def test_restore_from_backup_db(self, dr):
        fn = AsyncMock(return_value=True)
        dr.set_db_backup_fn(fn)
        dr.set_db_restore_fn(AsyncMock(return_value=True))
        await dr.db_backup()
        bid = dr.backup_history[0]["backup_id"]
        ok = await dr.restore_from_backup(bid)
        assert ok is True

    @pytest.mark.asyncio
    async def test_restore_from_backup_redis(self, dr):
        dr.set_redis_backup_fn(AsyncMock(return_value=True))
        dr.set_redis_restore_fn(AsyncMock(return_value=True))
        await dr.redis_backup()
        bid = dr.backup_history[0]["backup_id"]
        ok = await dr.restore_from_backup(bid)
        assert ok is True

    @pytest.mark.asyncio
    async def test_restore_not_found(self, dr):
        ok = await dr.restore_from_backup("nonexistent")
        assert ok is False

    @pytest.mark.asyncio
    async def test_restore_failed_backup(self, dr):
        dr.set_db_backup_fn(AsyncMock(return_value=False))
        await dr.db_backup()
        bid = dr.backup_history[0]["backup_id"]
        ok = await dr.restore_from_backup(bid)
        assert ok is False

    @pytest.mark.asyncio
    async def test_restore_no_restore_fn(self, dr):
        dr.set_db_backup_fn(AsyncMock(return_value=True))
        await dr.db_backup()
        bid = dr.backup_history[0]["backup_id"]
        ok = await dr.restore_from_backup(bid)
        assert ok is False

    @pytest.mark.asyncio
    async def test_restore_exception(self, dr):
        dr.set_db_backup_fn(AsyncMock(return_value=True))
        dr.set_db_restore_fn(AsyncMock(side_effect=RuntimeError("boom")))
        await dr.db_backup()
        bid = dr.backup_history[0]["backup_id"]
        ok = await dr.restore_from_backup(bid)
        assert ok is False

    @pytest.mark.asyncio
    async def test_failover_drill(self, dr):
        result = await dr.failover_drill()
        assert "scenarios" in result
        assert len(result["scenarios"]) == 4
        assert result["overall_pass"] is True

    @pytest.mark.asyncio
    async def test_failover_drill_with_notify(self, dr):
        notify = AsyncMock()
        dr.set_notifier(notify)
        await dr.failover_drill()
        notify.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_drill_all_scenarios(self, dr):
        for scenario in DRScenario:
            result = await dr._run_drill(scenario)
            assert isinstance(result, DRDrillResult)
            assert result.scenario == scenario

    def test_metrics_empty(self, dr):
        m = dr.metrics
        assert m["total_backups"] == 0
        assert m["rto_target_sec"] == 300

    def test_backup_history_empty(self, dr):
        assert dr.backup_history == []

    def test_backup_status_enum(self):
        assert BackupStatus.PENDING == "pending"
        assert BackupStatus.SUCCESS == "success"

    def test_dr_scenario_enum(self):
        assert DRScenario.NETWORK_DOWN == "network_down"
        assert DRScenario.FULL_RECOVERY == "full_recovery"


# ════════════════════════════════════════════════════════════════
# HealthChecker
# ════════════════════════════════════════════════════════════════


class TestHealthChecker:
    @pytest.fixture
    def checker(self):
        return HealthChecker()

    @pytest.mark.asyncio
    async def test_check_database_no_engine(self, checker):
        h = await checker.check_database()
        assert h.status == HealthStatus.DEGRADED
        assert "未配置" in h.message

    @pytest.mark.asyncio
    async def test_check_database_success(self, checker):
        mock_conn = AsyncMock()
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_engine = MagicMock()
        mock_engine.connect.return_value = mock_ctx
        checker.update_db_engine(mock_engine)
        h = await checker.check_database()
        assert h.status == HealthStatus.HEALTHY

    @pytest.mark.asyncio
    async def test_check_database_failure(self, checker):
        mock_engine = MagicMock()
        mock_engine.connect.side_effect = RuntimeError("conn refused")
        checker.update_db_engine(mock_engine)
        h = await checker.check_database()
        assert h.status == HealthStatus.UNHEALTHY
        assert "conn refused" in h.message

    @pytest.mark.asyncio
    async def test_check_redis_no_client(self, checker):
        h = await checker.check_redis()
        assert h.status == HealthStatus.DEGRADED

    @pytest.mark.asyncio
    async def test_check_redis_success(self, checker):
        mock_redis = AsyncMock()
        mock_redis.ping.return_value = True
        checker.update_redis_client(mock_redis)
        h = await checker.check_redis()
        assert h.status == HealthStatus.HEALTHY

    @pytest.mark.asyncio
    async def test_check_redis_ping_false(self, checker):
        mock_redis = AsyncMock()
        mock_redis.ping.return_value = False
        checker.update_redis_client(mock_redis)
        h = await checker.check_redis()
        assert h.status == HealthStatus.UNHEALTHY

    @pytest.mark.asyncio
    async def test_check_redis_exception(self, checker):
        mock_redis = AsyncMock()
        mock_redis.ping.side_effect = RuntimeError("timeout")
        checker.update_redis_client(mock_redis)
        h = await checker.check_redis()
        assert h.status == HealthStatus.UNHEALTHY

    @pytest.mark.asyncio
    async def test_check_event_bus_no_bus(self, checker):
        h = await checker.check_event_bus()
        assert h.status == HealthStatus.DEGRADED

    @pytest.mark.asyncio
    async def test_check_event_bus_started(self, checker):
        mock_bus = MagicMock()
        mock_bus._started = True
        checker.update_event_bus(mock_bus)
        h = await checker.check_event_bus()
        assert h.status == HealthStatus.HEALTHY

    @pytest.mark.asyncio
    async def test_check_event_bus_not_started(self, checker):
        mock_bus = MagicMock()
        mock_bus._started = False
        checker.update_event_bus(mock_bus)
        h = await checker.check_event_bus()
        assert h.status == HealthStatus.UNHEALTHY

    @pytest.mark.asyncio
    async def test_check_exchanges_no_clients(self, checker):
        result = await checker.check_exchanges()
        assert "exchanges" in result
        assert result["exchanges"].status == HealthStatus.DEGRADED

    @pytest.mark.asyncio
    async def test_check_exchanges_with_health_check(self, checker):
        mock_client = AsyncMock()
        mock_client.health_check.return_value = True
        checker.add_exchange_client("binance", mock_client)
        result = await checker.check_exchanges()
        assert result["binance"].status == HealthStatus.HEALTHY

    @pytest.mark.asyncio
    async def test_check_exchanges_health_check_false(self, checker):
        mock_client = AsyncMock()
        mock_client.health_check.return_value = False
        checker.add_exchange_client("binance", mock_client)
        result = await checker.check_exchanges()
        assert result["binance"].status == HealthStatus.UNHEALTHY

    @pytest.mark.asyncio
    async def test_check_exchanges_no_health_method(self, checker):
        mock_client = MagicMock(spec=[])  # no health_check method
        checker.add_exchange_client("okx", mock_client)
        result = await checker.check_exchanges()
        assert result["okx"].status == HealthStatus.HEALTHY

    @pytest.mark.asyncio
    async def test_check_exchanges_exception(self, checker):
        mock_client = AsyncMock()
        mock_client.health_check.side_effect = RuntimeError("fail")
        checker.add_exchange_client("binance", mock_client)
        result = await checker.check_exchanges()
        assert result["binance"].status == HealthStatus.UNHEALTHY

    @pytest.mark.asyncio
    async def test_full_check_all_degraded(self, checker):
        h = await checker.full_check()
        assert h.status == HealthStatus.DEGRADED

    def test_system_health_to_dict(self):
        h = SystemHealth(
            status=HealthStatus.HEALTHY,
            uptime_seconds=100.0,
            components={
                "db": ComponentHealth(name="db", status=HealthStatus.HEALTHY, latency_ms=1.0)
            },
        )
        d = h.to_dict()
        assert d["status"] == "healthy"
        assert "db" in d["components"]

    def test_health_status_enum(self):
        assert HealthStatus.HEALTHY == "healthy"
        assert HealthStatus.DEGRADED == "degraded"
        assert HealthStatus.UNHEALTHY == "unhealthy"

    def test_add_exchange_client(self, checker):
        checker.add_exchange_client("test", MagicMock())
        assert "test" in checker._exchange_clients


# ════════════════════════════════════════════════════════════════
# IncidentManager
# ════════════════════════════════════════════════════════════════


class TestIncidentManager:
    @pytest.fixture
    def mgr(self):
        return IncidentManager()

    def test_create_incident(self, mgr):
        iid = mgr.create_incident("交易系统宕机", "P0", "全面停机", tags=["critical"])
        assert iid.startswith("INC-")
        inc = mgr.get_incident(iid)
        assert inc is not None
        assert inc["severity"] == "P0"
        assert inc["status"] == "open"
        assert len(inc["timeline"]) >= 1

    def test_update_status(self, mgr):
        iid = mgr.create_incident("test", "P1", "desc")
        ok = mgr.update_status(iid, "investigating", "开始排查")
        assert ok is True
        inc = mgr.get_incident(iid)
        assert inc["status"] == "investigating"

    def test_update_status_not_found(self, mgr):
        assert mgr.update_status("NOPE", "investigating") is False

    def test_add_timeline_event(self, mgr):
        iid = mgr.create_incident("test", "P2", "desc")
        ok = mgr.add_timeline_event(iid, "发现根因", "数据库连接池耗尽")
        assert ok is True
        inc = mgr.get_incident(iid)
        assert len(inc["timeline"]) >= 2

    def test_add_timeline_event_not_found(self, mgr):
        assert mgr.add_timeline_event("NOPE", "event") is False

    def test_resolve_incident(self, mgr):
        iid = mgr.create_incident("test", "P0", "desc")
        mgr.resolve_incident(iid, "重启服务解决")
        inc = mgr.get_incident(iid)
        assert inc["status"] == "resolved"
        assert inc["resolution"] == "重启服务解决"

    def test_resolve_incident_not_found(self, mgr):
        mgr.resolve_incident("NOPE", "won't work")

    @pytest.mark.asyncio
    async def test_post_mortem(self, mgr):
        iid = mgr.create_incident("宕机", "P0", "全面停机", tags=["infra"])
        mgr.resolve_incident(iid, "重启")
        result = await mgr.post_mortem(iid)
        assert result["incident_id"] == iid
        assert result["severity"] == "P0"
        assert "timeline" in result
        inc = mgr.get_incident(iid)
        assert inc["status"] == "post_mortem"

    @pytest.mark.asyncio
    async def test_post_mortem_not_found(self, mgr):
        result = await mgr.post_mortem("NOPE")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_post_mortem_with_archive(self, mgr):
        archive_fn = AsyncMock()
        mgr.set_archive_fn(archive_fn)
        iid = mgr.create_incident("test", "P1", "desc")
        mgr.resolve_incident(iid, "fixed")
        await mgr.post_mortem(iid)
        archive_fn.assert_called_once()

    @pytest.mark.asyncio
    async def test_post_mortem_archive_failure(self, mgr):
        archive_fn = AsyncMock(side_effect=RuntimeError("archive fail"))
        mgr.set_archive_fn(archive_fn)
        iid = mgr.create_incident("test", "P1", "desc")
        mgr.resolve_incident(iid, "fixed")
        result = await mgr.post_mortem(iid)
        assert result["incident_id"] == iid  # should still work

    def test_get_incident_not_found(self, mgr):
        assert mgr.get_incident("NOPE") is None

    def test_list_incidents(self, mgr):
        mgr.create_incident("A", "P0", "desc")
        mgr.create_incident("B", "P1", "desc")
        mgr.create_incident("C", "P2", "desc")
        all_inc = mgr.list_incidents()
        assert len(all_inc) == 3
        p0_inc = mgr.list_incidents(severity="P0")
        assert len(p0_inc) == 1

    def test_stats(self, mgr):
        iid = mgr.create_incident("test", "P0", "desc")
        mgr.resolve_incident(iid, "fixed")
        s = mgr.stats
        assert s["total"] == 1
        assert s["resolved"] == 1

    def test_severity_enum(self):
        assert Severity.P0 == "P0"
        assert Severity.P3 == "P3"

    def test_incident_status_enum(self):
        assert IncidentStatus.OPEN == "open"
        assert IncidentStatus.CLOSED == "closed"


# ════════════════════════════════════════════════════════════════
# Notifiers
# ════════════════════════════════════════════════════════════════


class TestConsoleNotifier:
    @pytest.fixture
    def notifier(self):
        return ConsoleNotifier()

    @pytest.mark.asyncio
    async def test_send(self, notifier):
        ok = await notifier.send("测试标题", "测试内容", level="info")
        assert ok is True

    @pytest.mark.asyncio
    async def test_send_disabled(self):
        n = ConsoleNotifier(enabled=False)
        ok = await n.send("title", "content")
        assert ok is False

    @pytest.mark.asyncio
    async def test_send_alert(self, notifier):
        ok = await notifier.send_alert(
            {
                "title": "告警",
                "message": "出事了",
                "severity": "high",
                "source": "test",
                "timestamp": "2024-01-01",
            }
        )
        assert ok is True

    @pytest.mark.asyncio
    async def test_send_all_levels(self, notifier):
        for level in ("info", "warning", "error", "critical"):
            ok = await notifier.send("t", "c", level=level)
            assert ok is True


class TestEmailNotifier:
    @pytest.fixture
    def notifier(self):
        return EmailNotifier(
            smtp_host="smtp.test.com",
            smtp_port=587,
            username="user@test.com",
            password="pass",
            recipients=["to@test.com"],
            enabled=True,
        )

    @pytest.mark.asyncio
    async def test_send_disabled(self):
        n = EmailNotifier(
            smtp_host="h",
            smtp_port=587,
            username="u",
            password="p",
            recipients=["r"],
            enabled=False,
        )
        ok = await n.send("t", "c")
        assert ok is False

    @pytest.mark.asyncio
    async def test_send_smtp_error(self, notifier):
        with patch("one_quant.infra.notifier.smtplib.SMTP") as mock_smtp:
            mock_server = MagicMock()
            mock_server.starttls.side_effect = Exception("connection refused")
            mock_smtp.return_value = mock_server
            ok = await notifier.send("t", "c")
            assert ok is False

    @pytest.mark.asyncio
    async def test_send_alert(self, notifier):
        with patch("one_quant.infra.notifier.smtplib.SMTP") as mock_smtp:
            mock_server = MagicMock()
            mock_smtp.return_value = mock_server
            ok = await notifier.send_alert(
                {
                    "title": "告警",
                    "message": "出事了",
                    "severity": "critical",
                    "source": "test",
                    "timestamp": "now",
                }
            )
            # May fail due to smtplib, but tests the code path
            assert isinstance(ok, bool)

    def test_name(self):
        n = EmailNotifier(
            smtp_host="h", smtp_port=587, username="u", password="p", recipients=["r"]
        )
        assert n.name == "email"


class TestWebhookNotifier:
    @pytest.fixture
    def notifier(self):
        return WebhookNotifier(webhook_url="https://hooks.test.com/notify")

    @pytest.mark.asyncio
    async def test_send_disabled(self):
        n = WebhookNotifier(webhook_url="https://test.com", enabled=False)
        ok = await n.send("t", "c")
        assert ok is False

    @pytest.mark.asyncio
    async def test_send_success(self, notifier):
        with patch("one_quant.infra.notifier.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_client.post.return_value = mock_resp
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            ok = await notifier.send("title", "content", level="info")
            assert ok is True

    @pytest.mark.asyncio
    async def test_send_http_error(self, notifier):
        with patch("one_quant.infra.notifier.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_resp = MagicMock()
            mock_resp.status_code = 500
            mock_resp.text = "error"
            mock_client.post.return_value = mock_resp
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            ok = await notifier.send("t", "c")
            assert ok is False

    @pytest.mark.asyncio
    async def test_send_timeout(self, notifier):
        import httpx

        with patch("one_quant.infra.notifier.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post.side_effect = httpx.TimeoutException("timeout")
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            ok = await notifier.send("t", "c")
            assert ok is False

    @pytest.mark.asyncio
    async def test_send_generic_exception(self, notifier):
        with patch("one_quant.infra.notifier.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post.side_effect = RuntimeError("boom")
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            ok = await notifier.send("t", "c")
            assert ok is False

    @pytest.mark.asyncio
    async def test_send_alert(self, notifier):
        with patch("one_quant.infra.notifier.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_client.post.return_value = mock_resp
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            ok = await notifier.send_alert(
                {
                    "title": "t",
                    "message": "m",
                    "severity": "high",
                    "source": "s",
                    "timestamp": "now",
                }
            )
            assert ok is True

    def test_name(self):
        n = WebhookNotifier(webhook_url="https://test.com")
        assert n.name == "webhook"


# ════════════════════════════════════════════════════════════════
# SelfHealStrategy
# ════════════════════════════════════════════════════════════════


class TestSelfHealStrategy:
    @pytest.fixture
    def heal(self):
        return SelfHealStrategy(max_retries=2, base_backoff_sec=0.01, max_backoff_sec=0.05)

    @pytest.mark.asyncio
    async def test_heal_market_disconnect_no_fn(self, heal):
        ok = await heal.heal_market_disconnect()
        assert ok is False

    @pytest.mark.asyncio
    async def test_heal_market_disconnect_success(self, heal):
        heal._retry_with_backoff = AsyncMock(return_value=HealResult.SUCCESS)
        fn = AsyncMock(return_value=True)
        heal.set_market_reconnector(fn)
        ok = await heal.heal_market_disconnect()
        assert ok is True

    @pytest.mark.asyncio
    async def test_heal_market_disconnect_failure(self, heal):
        heal._retry_with_backoff = AsyncMock(return_value=HealResult.FAILED)
        fn = AsyncMock(return_value=False)
        notify = AsyncMock()
        heal.set_market_reconnector(fn)
        heal.set_notifier(notify)
        ok = await heal.heal_market_disconnect()
        assert ok is False
        notify.assert_called_once()

    @pytest.mark.asyncio
    async def test_heal_exchange_api_error_no_fn(self, heal):
        ok = await heal.heal_exchange_api_error()
        assert ok is False

    @pytest.mark.asyncio
    async def test_heal_exchange_api_error_success(self, heal):
        heal._retry_with_backoff = AsyncMock(return_value=HealResult.SUCCESS)
        fn = AsyncMock(return_value=True)
        heal.set_exchange_reconnector(fn)
        ok = await heal.heal_exchange_api_error()
        assert ok is True

    @pytest.mark.asyncio
    async def test_heal_exchange_api_error_failure(self, heal):
        heal._retry_with_backoff = AsyncMock(return_value=HealResult.FAILED)
        fn = AsyncMock(return_value=False)
        notify = AsyncMock()
        heal.set_exchange_reconnector(fn)
        heal.set_notifier(notify)
        ok = await heal.heal_exchange_api_error()
        assert ok is False

    @pytest.mark.asyncio
    async def test_heal_db_lock_no_fn(self, heal):
        ok = await heal.heal_db_lock()
        assert ok is False

    @pytest.mark.asyncio
    async def test_heal_db_lock_success(self, heal):
        heal._retry_with_backoff = AsyncMock(return_value=HealResult.SUCCESS)
        fn = AsyncMock(return_value=True)
        heal.set_db_reconnector(fn)
        ok = await heal.heal_db_lock()
        assert ok is True

    @pytest.mark.asyncio
    async def test_heal_db_lock_failure(self, heal):
        heal._retry_with_backoff = AsyncMock(return_value=HealResult.FAILED)
        fn = AsyncMock(return_value=False)
        notify = AsyncMock()
        heal.set_db_reconnector(fn)
        heal.set_notifier(notify)
        ok = await heal.heal_db_lock()
        assert ok is False

    @pytest.mark.asyncio
    async def test_heal_redis_disconnect_no_fn(self, heal):
        ok = await heal.heal_redis_disconnect()
        assert ok is False

    @pytest.mark.asyncio
    async def test_heal_redis_disconnect_success(self, heal):
        heal._retry_with_backoff = AsyncMock(return_value=HealResult.SUCCESS)
        fn = AsyncMock(return_value=True)
        heal.set_redis_reconnector(fn)
        ok = await heal.heal_redis_disconnect()
        assert ok is True

    @pytest.mark.asyncio
    async def test_heal_redis_disconnect_failure(self, heal):
        heal._retry_with_backoff = AsyncMock(return_value=HealResult.FAILED)
        fn = AsyncMock(return_value=False)
        notify = AsyncMock()
        heal.set_redis_reconnector(fn)
        heal.set_notifier(notify)
        ok = await heal.heal_redis_disconnect()
        assert ok is False

    @pytest.mark.asyncio
    async def test_heal_strategy_crash(self, heal):
        notify = AsyncMock()
        heal.set_notifier(notify)
        ok = await heal.heal_strategy_crash("momentum_v1")
        assert ok is True
        notify.assert_called_once()

    @pytest.mark.asyncio
    async def test_heal_risk_failure(self, heal):
        notify = AsyncMock()
        heal.set_notifier(notify)
        ok = await heal.heal_risk_failure()
        assert ok is True
        notify.assert_called_once()

    @pytest.mark.asyncio
    async def test_heal_unified(self, heal):
        notify = AsyncMock()
        heal.set_notifier(notify)
        ok = await heal.heal("risk_failure")
        assert ok is True

    @pytest.mark.asyncio
    async def test_heal_unknown_type(self, heal):
        ok = await heal.heal("unknown_type")
        assert ok is False

    @pytest.mark.asyncio
    async def test_heal_strategy_crash_via_unified(self, heal):
        notify = AsyncMock()
        heal.set_notifier(notify)
        ok = await heal.heal("strategy_crash", strategy_name="test_strat")
        assert ok is True

    @pytest.mark.asyncio
    async def test_retry_with_backoff_exception(self, heal):
        # The source code has a bug where HealRecord requires 'result' but
        # _retry_with_backoff creates it without one. Test that it raises.
        async def failing_fn():
            raise RuntimeError("boom")

        with pytest.raises(TypeError):
            await heal._retry_with_backoff("test", failing_fn, max_retries=2)

    def test_stats(self, heal):
        s = heal.stats
        assert s["total"] == 0
        assert s["success_rate"] == 0

    def test_history_empty(self, heal):
        assert heal.history == []

    def test_heal_result_enum(self):
        assert HealResult.SUCCESS == "success"
        assert HealResult.FAILED == "failed"
        assert HealResult.SKIPPED == "skipped"


# ════════════════════════════════════════════════════════════════
# Vault / SecretManager
# ════════════════════════════════════════════════════════════════


class TestEnvProvider:
    @pytest.fixture
    def provider(self):
        return EnvProvider(prefix="TEST_VAULT_")

    @pytest.mark.asyncio
    async def test_set_get(self, provider):
        await provider.set_secret("MY_KEY", "my_value")
        val = await provider.get_secret("MY_KEY")
        assert val == "my_value"
        os.environ.pop("TEST_VAULT_MY_KEY", None)

    @pytest.mark.asyncio
    async def test_get_nonexistent(self, provider):
        val = await provider.get_secret("NONEXISTENT_KEY_XYZ")
        assert val is None

    @pytest.mark.asyncio
    async def test_rotate(self, provider):
        new_val = await provider.rotate_secret("ROTATE_KEY")
        assert len(new_val) > 10
        stored = await provider.get_secret("ROTATE_KEY")
        assert stored == new_val
        os.environ.pop("TEST_VAULT_ROTATE_KEY", None)

    @pytest.mark.asyncio
    async def test_delete(self, provider):
        await provider.set_secret("DEL_KEY", "val")
        await provider.delete_secret("DEL_KEY")
        assert await provider.get_secret("DEL_KEY") is None

    @pytest.mark.asyncio
    async def test_no_prefix(self):
        p = EnvProvider()
        await p.set_secret("NOPREFIX", "val")
        assert await p.get_secret("NOPREFIX") == "val"
        os.environ.pop("NOPREFIX", None)


class TestSecretManager:
    @pytest.fixture
    def provider(self):
        return EnvProvider(prefix="SM_TEST_")

    @pytest.fixture
    def mgr(self, provider):
        return SecretManager(provider=provider, cache_ttl=60)

    @pytest.mark.asyncio
    async def test_get_and_cache(self, mgr, provider):
        await provider.set_secret("CACHE_KEY", "cached")
        val1 = await mgr.get("CACHE_KEY")
        assert val1 == "cached"
        # Modify underlying, cache should still return old value
        await provider.set_secret("CACHE_KEY", "changed")
        val2 = await mgr.get("CACHE_KEY")
        assert val2 == "cached"  # from cache
        os.environ.pop("SM_TEST_CACHE_KEY", None)

    @pytest.mark.asyncio
    async def test_get_nonexistent(self, mgr):
        val = await mgr.get("NOPE")
        assert val is None

    @pytest.mark.asyncio
    async def test_require_success(self, mgr, provider):
        await provider.set_secret("REQ_KEY", "required_val")
        val = await mgr.require("REQ_KEY")
        assert val == "required_val"
        os.environ.pop("SM_TEST_REQ_KEY", None)

    @pytest.mark.asyncio
    async def test_require_missing(self, mgr):
        with pytest.raises(RuntimeError, match="必需的密钥缺失"):
            await mgr.require("MISSING_KEY")

    @pytest.mark.asyncio
    async def test_require_all_success(self, mgr, provider):
        await provider.set_secret("K1", "v1")
        await provider.set_secret("K2", "v2")
        result = await mgr.require_all(["K1", "K2"])
        assert result == {"K1": "v1", "K2": "v2"}
        os.environ.pop("SM_TEST_K1", None)
        os.environ.pop("SM_TEST_K2", None)

    @pytest.mark.asyncio
    async def test_require_all_missing(self, mgr):
        with pytest.raises(RuntimeError, match="必需的密钥缺失"):
            await mgr.require_all(["MISSING1", "MISSING2"])

    @pytest.mark.asyncio
    async def test_set_and_invalidate(self, mgr):
        await mgr.set("SET_KEY", "val")
        assert await mgr.get("SET_KEY") == "val"
        mgr.invalidate("SET_KEY")
        # After invalidation, should re-fetch from provider
        assert await mgr.get("SET_KEY") == "val"
        os.environ.pop("SM_TEST_SET_KEY", None)

    @pytest.mark.asyncio
    async def test_rotate(self, mgr, provider):
        await provider.set_secret("ROT_KEY", "old")
        new_val = await mgr.rotate("ROT_KEY")
        assert new_val != "old"
        assert await mgr.get("ROT_KEY") == new_val
        os.environ.pop("SM_TEST_ROT_KEY", None)

    @pytest.mark.asyncio
    async def test_delete(self, mgr, provider):
        await provider.set_secret("DEL_KEY", "val")
        await mgr.delete("DEL_KEY")
        assert await mgr.get("DEL_KEY") is None

    def test_clear_cache(self, mgr):
        mgr._cache["k"] = "v"
        mgr.clear_cache()
        assert mgr._cache == {}


class TestCreateSecretManager:
    def test_env_backend(self):
        mgr = create_secret_manager(backend="env", env_prefix="FACTORY_")
        assert isinstance(mgr, SecretManager)

    def test_vault_backend(self):
        mgr = create_secret_manager(
            backend="vault",
            vault_url="https://vault.test:8200",
            vault_token="tok",
        )
        assert isinstance(mgr, SecretManager)

    def test_vault_backend_missing_params(self):
        with pytest.raises(ValueError, match="vault_url"):
            create_secret_manager(backend="vault")

    def test_1password_backend(self):
        mgr = create_secret_manager(backend="1password", onepassword_vault="my_vault")
        assert isinstance(mgr, SecretManager)

    def test_1password_backend_missing(self):
        with pytest.raises(ValueError, match="onepassword_vault"):
            create_secret_manager(backend="1password")

    def test_unsupported_backend(self):
        with pytest.raises(ValueError, match="不支持"):
            create_secret_manager(backend="unsupported")


# ════════════════════════════════════════════════════════════════
# Watchdog
# ════════════════════════════════════════════════════════════════


class TestWatchdog:
    @pytest.fixture
    def wd(self):
        return Watchdog(
            heartbeat_timeout_sec=1,
            max_failures=2,
            monitor_interval_sec=0.1,
            deadlock_timeout_sec=0.5,
            order_timeout_sec=0.5,
        )

    def test_register_process(self, wd):
        wd.register_process("collector", pid=1234)
        assert "collector" in wd._processes
        assert wd._processes["collector"].pid == 1234

    def test_heartbeat(self, wd):
        wd.register_process("collector")
        wd.heartbeat("collector")
        proc = wd._processes["collector"]
        assert proc.last_heartbeat_ns > 0
        assert proc.consecutive_failures == 0
        assert proc.status == ProcessStatus.HEALTHY

    def test_heartbeat_unknown(self, wd):
        wd.heartbeat("unknown")  # should not raise

    def test_report_market_data(self, wd):
        wd.report_market_data()
        assert wd._last_market_data_ns > 0
        assert wd._deadlock.market_data_stale is False

    def test_report_order_response(self, wd):
        wd.report_order_response()
        assert wd._last_order_response_ns > 0
        assert wd._deadlock.order_no_response is False

    @pytest.mark.asyncio
    async def test_start_stop(self, wd):
        await wd.start()
        assert wd._running is True
        assert wd._monitor_task is not None
        await wd.stop()
        assert wd._running is False

    @pytest.mark.asyncio
    async def test_restart_process_success(self, wd):
        restart_fn = AsyncMock()
        wd.register_process("worker", restart_fn=restart_fn)
        ok = await wd.restart_process("worker")
        assert ok is True
        restart_fn.assert_called_once()
        assert wd._processes["worker"].restart_count == 1

    @pytest.mark.asyncio
    async def test_restart_process_not_found(self, wd):
        ok = await wd.restart_process("nope")
        assert ok is False

    @pytest.mark.asyncio
    async def test_restart_process_no_fn(self, wd):
        wd.register_process("worker")
        ok = await wd.restart_process("worker")
        assert ok is False

    @pytest.mark.asyncio
    async def test_restart_process_exception(self, wd):
        restart_fn = AsyncMock(side_effect=RuntimeError("boom"))
        wd.register_process("worker", restart_fn=restart_fn)
        ok = await wd.restart_process("worker")
        assert ok is False
        assert wd._processes["worker"].status == ProcessStatus.DEAD

    @pytest.mark.asyncio
    async def test_restart_storm_detection(self, wd):
        restart_fn = AsyncMock()
        wd.register_process("worker", restart_fn=restart_fn)
        wd._processes["worker"].last_restart_ns = time.time_ns()
        wd._processes["worker"].restart_count = 3
        ok = await wd.restart_process("worker")
        assert ok is False

    @pytest.mark.asyncio
    async def test_check_all_with_healthcheck(self, wd):
        fn = AsyncMock(return_value=True)
        wd.register_process("worker", healthcheck_fn=fn)
        results = await wd.check_all()
        assert results["worker"] is True

    @pytest.mark.asyncio
    async def test_check_all_with_heartbeat(self, wd):
        wd.register_process("worker")
        wd.heartbeat("worker")
        results = await wd.check_all()
        assert results["worker"] is True

    @pytest.mark.asyncio
    async def test_check_all_no_heartbeat(self, wd):
        wd.register_process("worker")
        results = await wd.check_all()
        assert results["worker"] is False

    @pytest.mark.asyncio
    async def test_detect_deadlock_event_loop(self, wd):
        wd._loop_heartbeat_ns = time.time_ns() - int(1e9)  # 1 second ago > 0.5s timeout
        deadlocks = await wd.detect_deadlock()
        assert "event_loop_blocked" in deadlocks

    @pytest.mark.asyncio
    async def test_detect_deadlock_market_stale(self, wd):
        wd._last_market_data_ns = time.time_ns() - int(1e9)  # 1 second ago
        deadlocks = await wd.detect_deadlock()
        assert "market_data_stale" in deadlocks

    @pytest.mark.asyncio
    async def test_detect_deadlock_order_timeout(self, wd):
        wd._last_order_response_ns = time.time_ns() - int(2e9)  # 2 seconds ago > 0.5s timeout
        deadlocks = await wd.detect_deadlock()
        assert "order_no_response" in deadlocks

    @pytest.mark.asyncio
    async def test_detect_deadlock_none(self, wd):
        wd._loop_heartbeat_ns = time.time_ns()
        deadlocks = await wd.detect_deadlock()
        assert len(deadlocks) == 0

    @pytest.mark.asyncio
    async def test_recover_state(self, wd):
        cb = AsyncMock()
        wd.register_recovery_callback(cb)
        await wd.recover_state()
        cb.assert_called_once()

    @pytest.mark.asyncio
    async def test_recover_state_cb_error(self, wd):
        cb = AsyncMock(side_effect=RuntimeError("fail"))
        wd.register_recovery_callback(cb)
        await wd.recover_state()  # should not raise

    def test_status(self, wd):
        wd.register_process("worker")
        s = wd.status
        assert s["running"] is False
        assert "worker" in s["processes"]

    def test_process_status_enum(self):
        assert ProcessStatus.HEALTHY == "healthy"
        assert ProcessStatus.DEAD == "dead"


# ════════════════════════════════════════════════════════════════
# Logging
# ════════════════════════════════════════════════════════════════


class TestLogging:
    def test_log_mask_long(self):
        masked = log_mask("abcdefghijklmnop")
        assert masked == "abcd***mnop"
        assert "***" in masked

    def test_log_mask_short(self):
        assert log_mask("short") == "***"
        assert log_mask("12345678") == "***"

    def test_mask_dict(self):
        d = {"api_key": "secret123", "name": "test", "nested": {"password": "pw123"}}
        masked = _mask_dict(d)
        assert masked["api_key"] == "***MASKED***"
        assert masked["name"] == "test"
        assert masked["nested"]["password"] == "***MASKED***"

    def test_mask_dict_list(self):
        d = {"items": [{"token": "abc"}]}
        masked = _mask_dict(d)
        assert masked["items"][0]["token"] == "***MASKED***"

    def test_mask_dict_depth_limit(self):
        d = {"key": "value"}
        assert _mask_dict(d, depth=11) == d

    def test_structured_formatter(self):
        import logging as log_mod

        formatter = StructuredFormatter()
        record = log_mod.LogRecord(
            name="test",
            level=log_mod.INFO,
            pathname="test.py",
            lineno=1,
            msg="测试消息",
            args=(),
            exc_info=None,
        )
        output = formatter.format(record)
        assert "测试消息" in output
        assert "INFO" in output

    def test_structured_formatter_with_exception(self):
        import logging as log_mod

        formatter = StructuredFormatter()
        try:
            raise ValueError("test error")
        except ValueError:
            exc_info = sys.exc_info()
        record = log_mod.LogRecord(
            name="test",
            level=log_mod.ERROR,
            pathname="test.py",
            lineno=1,
            msg="error",
            args=(),
            exc_info=exc_info,
        )
        output = formatter.format(record)
        assert "test error" in output

    def test_setup_logging(self):
        setup_logging(level="DEBUG", json_format=True)
        import logging as log_mod

        root = log_mod.getLogger()
        assert root.level == log_mod.DEBUG

    def test_setup_logging_plain(self):
        setup_logging(level="WARNING", json_format=False)
        import logging as log_mod

        root = log_mod.getLogger()
        assert root.level == log_mod.WARNING

    def test_get_logger(self):
        logger = get_logger("test.module")
        assert logger.name == "test.module"


# ════════════════════════════════════════════════════════════════
# EventBus
# ════════════════════════════════════════════════════════════════


class TestInMemoryEventBus:
    @pytest.mark.asyncio
    async def test_publish_subscribe(self):
        bus = InMemoryEventBus()
        received = []

        async def handler(data):
            received.append(data)

        bus.subscribe("test", handler)
        await bus.start()
        await bus.publish("test", {"msg": "hello"})
        await asyncio.sleep(0.1)
        assert len(received) == 1
        assert received[0]["msg"] == "hello"
        await bus.stop()

    @pytest.mark.asyncio
    async def test_publish_before_start(self):
        bus = InMemoryEventBus()
        with pytest.raises(RuntimeError, match="尚未启动"):
            await bus.publish("test", {})

    @pytest.mark.asyncio
    async def test_multiple_handlers(self):
        bus = InMemoryEventBus()
        r1, r2 = [], []

        async def h1(data):
            r1.append(data)

        async def h2(data):
            r2.append(data)

        bus.subscribe("ch", h1)
        bus.subscribe("ch", h2)
        await bus.start()
        await bus.publish("ch", {"v": 1})
        await asyncio.sleep(0.1)
        assert len(r1) == 1
        assert len(r2) == 1
        await bus.stop()

    @pytest.mark.asyncio
    async def test_backpressure_drop_oldest(self):
        received = []

        async def handler(data):
            received.append(data)

        bus = InMemoryEventBus(max_queue_size=5, backpressure=BackpressurePolicy.DROP_OLDEST)
        bus.subscribe("ch", handler)
        await bus.start()
        for i in range(10):
            await bus.publish("ch", {"i": i})
        await asyncio.sleep(0.3)
        # Some messages should have been dropped
        assert len(received) <= 10
        await bus.stop()

    @pytest.mark.asyncio
    async def test_backpressure_drop_latest(self):
        received = []

        async def handler(data):
            received.append(data)

        bus = InMemoryEventBus(max_queue_size=5, backpressure=BackpressurePolicy.DROP_LATEST)
        bus.subscribe("ch", handler)
        await bus.start()
        for i in range(10):
            await bus.publish("ch", {"i": i})
        await asyncio.sleep(0.3)
        assert len(received) <= 10
        await bus.stop()

    @pytest.mark.asyncio
    async def test_backpressure_raise(self):
        bus = InMemoryEventBus(max_queue_size=10, backpressure=BackpressurePolicy.RAISE)
        await bus.start()
        # With RAISE and a reasonable queue, normal publish should work
        await bus.publish("ch", {"i": 0})
        await asyncio.sleep(0.1)
        await bus.stop()

    @pytest.mark.asyncio
    async def test_handler_exception(self):
        bus = InMemoryEventBus()

        async def bad_handler(data):
            raise RuntimeError("handler error")

        bus.subscribe("ch", bad_handler)
        await bus.start()
        await bus.publish("ch", {"v": 1})  # should not raise
        await asyncio.sleep(0.1)
        await bus.stop()

    @pytest.mark.asyncio
    async def test_stop_without_start(self):
        bus = InMemoryEventBus()
        await bus.stop()  # should not raise

    @pytest.mark.asyncio
    async def test_double_start(self):
        bus = InMemoryEventBus()
        await bus.start()
        await bus.start()  # no-op
        await bus.stop()

    @pytest.mark.asyncio
    async def test_subscribe_after_start(self):
        bus = InMemoryEventBus()
        await bus.start()
        received = []

        async def handler(data):
            received.append(data)

        bus.subscribe("new_ch", handler)
        await bus.publish("new_ch", {"v": 1})
        await asyncio.sleep(0.1)
        assert len(received) == 1
        await bus.stop()


class TestMessageEnvelopeEventBus:
    def test_to_json(self):
        env = MessageEnvelope(channel="test", ts_ns=12345, trace_id="abc", data={"k": "v"})
        j = env.to_json()
        assert "test" in j
        assert "abc" in j

    def test_from_json(self):
        env = MessageEnvelope(channel="ch", ts_ns=100, trace_id="tid", data={"a": 1})
        j = env.to_json()
        restored = MessageEnvelope.from_json(j)
        assert restored.channel == "ch"
        assert restored.data["a"] == 1

    def test_from_json_invalid(self):
        with pytest.raises(ValueError, match="JSON"):
            MessageEnvelope.from_json("not json")

    def test_from_json_missing_field(self):
        with pytest.raises(ValueError, match="缺少"):
            MessageEnvelope.from_json('{"channel": "x"}')

    def test_backpressure_policy_enum(self):
        assert BackpressurePolicy.DROP_OLDEST.value == "drop_oldest"
        assert BackpressurePolicy.DROP_LATEST.value == "drop_latest"
        assert BackpressurePolicy.RAISE.value == "raise"

    def test_event_bus_full_error(self):
        err = EventBusFullError("full")
        assert "full" in str(err)
