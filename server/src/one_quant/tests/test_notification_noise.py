"""通知降噪层测试 — NotificationDeduplicator"""

from __future__ import annotations

import time

import pytest

from one_quant.infra.notification_noise import (
    NotificationDeduplicator,
    Severity,
    SignalGrade,
)

# ── 辅助工厂 ──────────────────────────────────────────────


def _make_dedup(**kwargs) -> NotificationDeduplicator:
    """创建测试用去重器实例。"""
    return NotificationDeduplicator(**kwargs)


def _freeze_time(monkeypatch, ts: float, hour: int = 10):
    """冻结 time.time() 和 time.localtime()。

    默认 hour=10（白天，不在默认静默时段 22~7 内）。
    """
    monkeypatch.setattr(time, "time", lambda: ts)

    def fake_localtime(_=None):
        return time.struct_time((2026, 1, 15, hour, 30, 0, 2, 15, 0))

    monkeypatch.setattr(time, "localtime", fake_localtime)


# ── 严重度分级测试 ─────────────────────────────────────────


class TestSeverityRouting:
    """验证不同路由的默认严重度分级。"""

    def test_report_route_defaults_to_info(self):
        dedup = _make_dedup()
        assert dedup.get_default_severity("report") == Severity.INFO

    def test_alert_route_defaults_to_warning(self):
        dedup = _make_dedup()
        assert dedup.get_default_severity("alert") == Severity.WARNING

    def test_signal_route_uses_provided_level(self):
        dedup = _make_dedup()
        # signal 路由应尊重传入的级别
        assert dedup.get_default_severity("signal", level="error") == Severity.ERROR
        assert dedup.get_default_severity("signal", level="critical") == Severity.CRITICAL

    def test_unknown_route_defaults_to_info(self):
        dedup = _make_dedup()
        assert dedup.get_default_severity("unknown_route") == Severity.INFO


# ── 去重测试 ───────────────────────────────────────────────


class TestDeduplication:
    """验证同内容消息在 N 分钟内被抑制。"""

    @pytest.mark.asyncio
    async def test_duplicate_message_suppressed(self, monkeypatch):
        dedup = _make_dedup(dedup_window_min=5)
        _freeze_time(monkeypatch, 1000.0)

        # 第一条应通过
        d1 = await dedup.check("BTCUSDT", "涨破关键位", route="report")
        assert d1.allow is True

        # 第二条相同内容在窗口内应被抑制
        _freeze_time(monkeypatch, 1000.0 + 60)  # 1 分钟后
        d2 = await dedup.check("BTCUSDT", "涨破关键位", route="report")
        assert d2.allow is False
        assert d2.reason == "dedup"

    @pytest.mark.asyncio
    async def test_different_content_not_suppressed(self, monkeypatch):
        dedup = _make_dedup(dedup_window_min=5)
        _freeze_time(monkeypatch, 1000.0)

        d1 = await dedup.check("BTCUSDT", "涨破关键位", route="report")
        assert d1.allow is True

        d2 = await dedup.check("BTCUSDT", "跌破支撑位", route="report")
        assert d2.allow is True

    @pytest.mark.asyncio
    async def test_same_content_after_window_passes(self, monkeypatch):
        dedup = _make_dedup(dedup_window_min=5)
        _freeze_time(monkeypatch, 1000.0)

        d1 = await dedup.check("BTCUSDT", "涨破关键位", route="report")
        assert d1.allow is True

        # 超过去重窗口
        _freeze_time(monkeypatch, 1000.0 + 6 * 60)
        d2 = await dedup.check("BTCUSDT", "涨破关键位", route="report")
        assert d2.allow is True


# ── 冷却测试 ───────────────────────────────────────────────


class TestCooldown:
    """验证同标的同方向信号在冷却期内被抑制。"""

    @pytest.mark.asyncio
    async def test_same_symbol_direction_suppressed_in_cooldown(self, monkeypatch):
        dedup = _make_dedup(cooldown_min=10)
        _freeze_time(monkeypatch, 1000.0)

        d1 = await dedup.check(
            "ETHUSDT", "看多信号", route="signal", direction="long", level="warning"
        )
        assert d1.allow is True

        # 同标的同方向，冷却期内
        _freeze_time(monkeypatch, 1000.0 + 5 * 60)
        d2 = await dedup.check(
            "ETHUSDT", "再次看多", route="signal", direction="long", level="warning"
        )
        assert d2.allow is False
        assert d2.reason == "cooldown"

    @pytest.mark.asyncio
    async def test_same_symbol_different_direction_passes(self, monkeypatch):
        dedup = _make_dedup(cooldown_min=10)
        _freeze_time(monkeypatch, 1000.0)

        d1 = await dedup.check(
            "ETHUSDT", "看多信号", route="signal", direction="long", level="warning"
        )
        assert d1.allow is True

        # 同标的不同方向，应通过
        _freeze_time(monkeypatch, 1000.0 + 2 * 60)
        d2 = await dedup.check(
            "ETHUSDT", "看空信号", route="signal", direction="short", level="warning"
        )
        assert d2.allow is True

    @pytest.mark.asyncio
    async def test_different_symbol_same_direction_passes(self, monkeypatch):
        dedup = _make_dedup(cooldown_min=10)
        _freeze_time(monkeypatch, 1000.0)

        d1 = await dedup.check(
            "ETHUSDT", "看多信号", route="signal", direction="long", level="warning"
        )
        assert d1.allow is True

        _freeze_time(monkeypatch, 1000.0 + 2 * 60)
        d2 = await dedup.check(
            "BTCUSDT", "看多信号", route="signal", direction="long", level="warning"
        )
        assert d2.allow is True

    @pytest.mark.asyncio
    async def test_cooldown_expires(self, monkeypatch):
        dedup = _make_dedup(cooldown_min=10)
        _freeze_time(monkeypatch, 1000.0)

        d1 = await dedup.check(
            "ETHUSDT", "看多信号", route="signal", direction="long", level="warning"
        )
        assert d1.allow is True

        # 超过冷却期
        _freeze_time(monkeypatch, 1000.0 + 11 * 60)
        d2 = await dedup.check(
            "ETHUSDT", "看多信号", route="signal", direction="long", level="warning"
        )
        assert d2.allow is True


# ── 静默时段测试 ───────────────────────────────────────────


class TestQuietHours:
    """验证夜间静默时段抑制非 critical 消息。"""

    @pytest.mark.asyncio
    async def test_non_critical_suppressed_during_quiet_hours(self, monkeypatch):
        dedup = _make_dedup(quiet_start=22, quiet_end=7)
        _freeze_time(monkeypatch, 1000.0, hour=2)  # 凌晨 2 点

        d = await dedup.check("BTCUSDT", "普通报告", route="report", level="info")
        assert d.allow is False
        assert d.reason == "quiet_hours"

    @pytest.mark.asyncio
    async def test_critical_not_suppressed_during_quiet_hours(self, monkeypatch):
        dedup = _make_dedup(quiet_start=22, quiet_end=7)
        _freeze_time(monkeypatch, 1000.0, hour=2)  # 凌晨 2 点

        # critical 在静默时段应放行；注意 alert 默认 warning，需要显式传 level
        d = await dedup.check("BTCUSDT", "紧急告警", route="alert", level="critical")
        assert d.allow is True

    @pytest.mark.asyncio
    async def test_messages_pass_outside_quiet_hours(self, monkeypatch):
        dedup = _make_dedup(quiet_start=22, quiet_end=7)
        _freeze_time(monkeypatch, 1000.0, hour=10)  # 上午 10 点

        d = await dedup.check("BTCUSDT", "普通报告", route="report", level="info")
        assert d.allow is True

    @pytest.mark.asyncio
    async def test_quiet_hours_wrap_around_midnight(self, monkeypatch):
        """quiet_start > quiet_end 时（如 22→7），时段跨越午夜。"""
        dedup = _make_dedup(quiet_start=22, quiet_end=7)
        _freeze_time(monkeypatch, 1000.0, hour=23)  # 晚上 11 点

        d = await dedup.check("BTCUSDT", "夜间消息", route="report", level="info")
        assert d.allow is False
        assert d.reason == "quiet_hours"


# ── S 级信号不被误抑制 ────────────────────────────────────


class TestSignalGrading:
    """验证信号分级推送逻辑。"""

    def test_s_grade_signal(self):
        dedup = _make_dedup()
        grade = dedup.classify_signal(0.95)
        assert grade == SignalGrade.S

    def test_a_grade_signal(self):
        dedup = _make_dedup()
        grade = dedup.classify_signal(0.8)
        assert grade == SignalGrade.A

    def test_b_grade_signal(self):
        dedup = _make_dedup()
        grade = dedup.classify_signal(0.6)
        assert grade == SignalGrade.B

    def test_c_grade_signal(self):
        dedup = _make_dedup()
        grade = dedup.classify_signal(0.3)
        assert grade == SignalGrade.C

    @pytest.mark.asyncio
    async def test_s_grade_not_suppressed_by_cooldown(self, monkeypatch):
        """S 级信号（score ≥ 0.9）应突破冷却期限制。"""
        dedup = _make_dedup(cooldown_min=10)
        _freeze_time(monkeypatch, 1000.0)

        d1 = await dedup.check(
            "BTCUSDT",
            "强信号看多",
            route="signal",
            direction="long",
            level="critical",
            score=0.95,
        )
        assert d1.allow is True

        # 冷却期内，但 S 级应通过
        _freeze_time(monkeypatch, 1000.0 + 2 * 60)
        d2 = await dedup.check(
            "BTCUSDT",
            "更强信号看多",
            route="signal",
            direction="long",
            level="critical",
            score=0.98,
        )
        assert d2.allow is True
        assert d2.signal_grade == SignalGrade.S

    @pytest.mark.asyncio
    async def test_b_grade_suppressed_by_cooldown(self, monkeypatch):
        """B/C 级信号应被冷却期抑制。"""
        dedup = _make_dedup(cooldown_min=10)
        _freeze_time(monkeypatch, 1000.0)

        d1 = await dedup.check(
            "BTCUSDT",
            "普通信号",
            route="signal",
            direction="long",
            level="warning",
            score=0.6,
        )
        assert d1.allow is True

        _freeze_time(monkeypatch, 1000.0 + 2 * 60)
        d2 = await dedup.check(
            "BTCUSDT",
            "普通信号2",
            route="signal",
            direction="long",
            level="warning",
            score=0.5,
        )
        assert d2.allow is False
        assert d2.reason == "cooldown"

    def test_notification_channel_for_s_grade(self):
        dedup = _make_dedup()
        channels = dedup.get_channels(SignalGrade.S)
        assert "sound" in channels
        assert "mobile" in channels

    def test_notification_channel_for_b_grade(self):
        dedup = _make_dedup()
        channels = dedup.get_channels(SignalGrade.B)
        assert "list" in channels
        assert "sound" not in channels
        assert "mobile" not in channels

    def test_notification_channel_for_c_grade(self):
        dedup = _make_dedup()
        channels = dedup.get_channels(SignalGrade.C)
        assert "list" in channels
        assert "sound" not in channels


# ── NotificationDecision 结构 ─────────────────────────────


class TestDecision:
    """验证决策对象的结构。"""

    @pytest.mark.asyncio
    async def test_decision_has_severity(self, monkeypatch):
        dedup = _make_dedup()
        _freeze_time(monkeypatch, 1000.0)
        d = await dedup.check("BTCUSDT", "测试", route="report")
        assert isinstance(d.severity, Severity)

    @pytest.mark.asyncio
    async def test_decision_has_channels(self, monkeypatch):
        dedup = _make_dedup()
        _freeze_time(monkeypatch, 1000.0)
        d = await dedup.check("BTCUSDT", "测试", route="signal", level="critical", score=0.95)
        assert isinstance(d.channels, list)
        assert len(d.channels) > 0

    @pytest.mark.asyncio
    async def test_allowed_decision_has_no_reason(self, monkeypatch):
        dedup = _make_dedup()
        _freeze_time(monkeypatch, 1000.0)
        d = await dedup.check("BTCUSDT", "测试", route="report")
        assert d.allow is True
        assert d.reason is None


# ── 边界与集成 ─────────────────────────────────────────────


class TestEdgeCases:
    """边界场景。"""

    @pytest.mark.asyncio
    async def test_disabled_dedup_always_passes(self, monkeypatch):
        dedup = _make_dedup(enabled=False)
        _freeze_time(monkeypatch, 1000.0)

        d1 = await dedup.check("BTCUSDT", "相同内容", route="report")
        d2 = await dedup.check("BTCUSDT", "相同内容", route="report")
        assert d1.allow is True
        assert d2.allow is True

    @pytest.mark.asyncio
    async def test_reset_clears_state(self, monkeypatch):
        dedup = _make_dedup(dedup_window_min=60)
        _freeze_time(monkeypatch, 1000.0)

        await dedup.check("BTCUSDT", "内容", route="report")
        dedup.reset()

        d = await dedup.check("BTCUSDT", "内容", route="report")
        assert d.allow is True

    @pytest.mark.asyncio
    async def test_stats_returns_counts(self, monkeypatch):
        dedup = _make_dedup()
        _freeze_time(monkeypatch, 1000.0)

        await dedup.check("BTCUSDT", "A", route="report")
        await dedup.check("BTCUSDT", "A", route="report")  # dedup
        await dedup.check("BTCUSDT", "B", route="report")

        stats = dedup.stats()
        assert stats["total_checked"] == 3
        assert stats["suppressed"] == 1
        assert stats["passed"] == 2
