"""Tests for infra/disaster_recovery.py — 灾备管理"""

import logging

import pytest

from one_quant.infra.disaster_recovery import (
    BackupStatus,
    DisasterRecovery,
    DRScenario,
)


@pytest.fixture
def dr():
    return DisasterRecovery(rto_target_sec=300, rpo_target_sec=1)


class TestBackup:
    @pytest.mark.asyncio
    async def test_db_backup_no_fn(self, dr, caplog):
        """DB backup fails gracefully when no backup fn injected."""
        with caplog.at_level(logging.ERROR, logger="one_quant.infra.disaster_recovery"):
            result = await dr.db_backup()
        assert result is False
        assert len(dr._backup_history) == 1
        assert dr._backup_history[0].status == BackupStatus.FAILED
        assert "未注入" in dr._backup_history[0].error

    @pytest.mark.asyncio
    async def test_db_backup_success(self, dr, caplog):
        """DB backup succeeds with injected fn."""

        async def mock_backup():
            return True

        dr.set_db_backup_fn(mock_backup)
        with caplog.at_level(logging.INFO, logger="one_quant.infra.disaster_recovery"):
            result = await dr.db_backup()
        assert result is True
        assert dr._backup_history[0].status == BackupStatus.SUCCESS
        assert "DB备份成功" in caplog.text

    @pytest.mark.asyncio
    async def test_db_backup_failure(self, dr, caplog):
        """DB backup records failure when fn returns False."""

        async def mock_backup():
            return False

        dr.set_db_backup_fn(mock_backup)
        with caplog.at_level(logging.ERROR, logger="one_quant.infra.disaster_recovery"):
            result = await dr.db_backup()
        assert result is False
        assert dr._backup_history[0].status == BackupStatus.FAILED

    @pytest.mark.asyncio
    async def test_db_backup_exception(self, dr, caplog):
        """DB backup handles exception from backup fn."""

        async def mock_backup():
            raise RuntimeError("connection lost")

        dr.set_db_backup_fn(mock_backup)
        with caplog.at_level(logging.ERROR, logger="one_quant.infra.disaster_recovery"):
            result = await dr.db_backup()
        assert result is False
        assert "connection lost" in dr._backup_history[0].error

    @pytest.mark.asyncio
    async def test_redis_backup_no_fn(self, dr, caplog):
        """Redis backup fails gracefully when no fn injected."""
        with caplog.at_level(logging.ERROR, logger="one_quant.infra.disaster_recovery"):
            result = await dr.redis_backup()
        assert result is False

    @pytest.mark.asyncio
    async def test_redis_backup_success(self, dr, caplog):
        """Redis backup succeeds with injected fn."""

        async def mock_backup():
            return True

        dr.set_redis_backup_fn(mock_backup)
        with caplog.at_level(logging.INFO, logger="one_quant.infra.disaster_recovery"):
            result = await dr.redis_backup()
        assert result is True
        assert "Redis备份成功" in caplog.text


class TestRestore:
    @pytest.mark.asyncio
    async def test_restore_nonexistent(self, dr, caplog):
        """Restore fails for unknown backup_id."""
        with caplog.at_level(logging.ERROR, logger="one_quant.infra.disaster_recovery"):
            result = await dr.restore_from_backup("nonexistent")
        assert result is False
        assert "不存在" in caplog.text

    @pytest.mark.asyncio
    async def test_restore_failed_backup(self, dr, caplog):
        """Restore fails for a backup that had failed."""

        async def mock_backup():
            return False

        dr.set_db_backup_fn(mock_backup)
        await dr.db_backup()
        backup_id = dr._backup_history[0].backup_id

        with caplog.at_level(logging.ERROR, logger="one_quant.infra.disaster_recovery"):
            result = await dr.restore_from_backup(backup_id)
        assert result is False
        assert "状态异常" in caplog.text

    @pytest.mark.asyncio
    async def test_restore_db_success(self, dr, caplog):
        """DB restore succeeds."""

        async def mock_backup():
            return True

        async def mock_restore(backup_id):
            return True

        dr.set_db_backup_fn(mock_backup)
        dr.set_db_restore_fn(mock_restore)
        await dr.db_backup()
        backup_id = dr._backup_history[0].backup_id

        with caplog.at_level(logging.INFO, logger="one_quant.infra.disaster_recovery"):
            result = await dr.restore_from_backup(backup_id)
        assert result is True
        assert "备份恢复成功" in caplog.text

    @pytest.mark.asyncio
    async def test_restore_redis_success(self, dr, caplog):
        """Redis restore succeeds."""

        async def mock_backup():
            return True

        async def mock_restore(backup_id):
            return True

        dr.set_redis_backup_fn(mock_backup)
        dr.set_redis_restore_fn(mock_restore)
        await dr.redis_backup()
        backup_id = dr._backup_history[0].backup_id

        with caplog.at_level(logging.INFO, logger="one_quant.infra.disaster_recovery"):
            result = await dr.restore_from_backup(backup_id)
        assert result is True


class TestDrill:
    @pytest.mark.asyncio
    async def test_failover_drill_runs_all_scenarios(self, dr):
        """Drill runs all 4 scenarios."""
        results = await dr.failover_drill()
        assert len(results["scenarios"]) == 4
        for scenario in DRScenario:
            if scenario != DRScenario.FULL_RECOVERY:
                assert scenario.value in results["scenarios"]

    @pytest.mark.asyncio
    async def test_failover_drill_logs_scenario(self, dr, caplog):
        """Drill logs each scenario start with %s format (not kwargs)."""
        with caplog.at_level(logging.INFO, logger="one_quant.infra.disaster_recovery"):
            await dr.failover_drill()
        # Each scenario should be logged
        assert "network_down" in caplog.text
        assert "db_down" in caplog.text

    @pytest.mark.asyncio
    async def test_drill_history_recorded(self, dr):
        """Drill results are recorded in history."""
        await dr.failover_drill()
        assert len(dr._drill_history) == 4


class TestMetrics:
    def test_metrics_empty(self, dr):
        """Metrics with no history."""
        m = dr.metrics
        assert m["total_backups"] == 0
        assert m["total_drills"] == 0

    @pytest.mark.asyncio
    async def test_metrics_after_backup(self, dr):
        async def mock_backup():
            return True

        dr.set_db_backup_fn(mock_backup)
        await dr.db_backup()
        m = dr.metrics
        assert m["total_backups"] == 1
        assert m["successful_backups"] == 1

    def test_backup_history_format(self, dr):
        """backup_history returns list of dicts."""
        assert dr.backup_history == []
