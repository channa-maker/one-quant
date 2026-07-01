"""Smoke tests for infra/self_heal.py — P0-4

验证：能构造 → 能执行一轮自愈 → 优雅关闭/状态查询。
"""

from unittest.mock import AsyncMock

import pytest

from one_quant.infra.self_heal import HealResult, SelfHealStrategy


class TestSelfHealSmoke:
    """self_heal 自愈模块冒烟测试"""

    def test_constructable(self):
        """能正常构造 SelfHealStrategy"""
        heal = SelfHealStrategy()
        assert heal._max_retries == 5
        assert heal._base_backoff == 1.0
        assert heal._max_backoff == 60.0
        assert heal._history == []

    def test_constructable_with_params(self):
        """自定义参数构造"""
        heal = SelfHealStrategy(max_retries=3, base_backoff_sec=0.5, max_backoff_sec=10.0)
        assert heal._max_retries == 3
        assert heal._base_backoff == 0.5
        assert heal._max_backoff == 10.0

    @pytest.mark.asyncio
    async def test_heal_round_success(self):
        """能执行一轮自愈（成功路径）"""
        heal = SelfHealStrategy(max_retries=2, base_backoff_sec=0.01, max_backoff_sec=0.05)

        reconnect_fn = AsyncMock(return_value=True)
        heal.set_market_reconnector(reconnect_fn)

        result = await heal.heal_market_disconnect()
        assert result is True
        reconnect_fn.assert_called()

        # 验证历史记录
        assert len(heal.history) == 1
        assert heal.history[0]["result"] == "success"
        assert heal.stats["success"] == 1

    @pytest.mark.asyncio
    async def test_heal_round_failure(self):
        """能执行一轮自愈（失败路径）"""
        heal = SelfHealStrategy(max_retries=2, base_backoff_sec=0.01, max_backoff_sec=0.05)

        reconnect_fn = AsyncMock(return_value=False)
        notify_fn = AsyncMock()
        heal.set_market_reconnector(reconnect_fn)
        heal.set_notifier(notify_fn)

        result = await heal.heal_market_disconnect()
        assert result is False
        notify_fn.assert_called_once()

        assert heal.stats["failed"] == 1

    @pytest.mark.asyncio
    async def test_heal_strategy_crash_isolation(self):
        """策略异常：能隔离不影响其他策略"""
        heal = SelfHealStrategy()

        result = await heal.heal_strategy_crash("momentum_v1")
        assert result is True

        history = heal.history
        assert len(history) == 1
        assert "momentum_v1" in history[0]["strategy"]

    @pytest.mark.asyncio
    async def test_heal_risk_failure_circuit_break(self):
        """风控异常：能触发熔断"""
        heal = SelfHealStrategy()
        notify_fn = AsyncMock()
        heal.set_notifier(notify_fn)

        result = await heal.heal_risk_failure()
        assert result is True
        notify_fn.assert_called_once()
        # 验证通知内容包含熔断关键词
        call_args = notify_fn.call_args[0]
        assert "熔断" in call_args[0] or "熔断" in call_args[1]

    @pytest.mark.asyncio
    async def test_unified_heal_entry(self):
        """统一入口 heal() 能路由到正确策略"""
        heal = SelfHealStrategy(max_retries=1, base_backoff_sec=0.01, max_backoff_sec=0.01)

        # 注入一个成功的重连函数
        fn = AsyncMock(return_value=True)
        heal.set_redis_reconnector(fn)

        result = await heal.heal("redis_disconnect")
        assert result is True

    @pytest.mark.asyncio
    async def test_unified_heal_unknown_type(self):
        """统一入口处理未知类型"""
        heal = SelfHealStrategy()
        result = await heal.heal("unknown_incident")
        assert result is False

    def test_stats_and_history(self):
        """状态查询正常工作"""
        heal = SelfHealStrategy()
        assert heal.stats == {"total": 0, "success": 0, "failed": 0, "success_rate": 0}
        assert heal.history == []

    def test_heal_result_enum(self):
        """HealResult 枚举值正确"""
        assert HealResult.SUCCESS == "success"
        assert HealResult.FAILED == "failed"
        assert HealResult.SKIPPED == "skipped"
        assert HealResult.PARTIAL == "partial"
