"""P0-2 + P0-3 修复验证测试

P0-2: self_heal._retry_with_backoff 创建 HealRecord 时缺少 result 参数
P0-3: stream_persistence / position_recovery logger 调用传了 kwargs 而非 %s 格式化
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from one_quant.infra.self_heal import HealResult, SelfHealStrategy

# ════════════════════════════════════════════════════════════════
# P0-2: HealRecord result 参数补齐
# ════════════════════════════════════════════════════════════════


class TestHealRecordResultFix:
    """验证 _retry_with_backoff 能正确创建 HealRecord（含 result 字段）"""

    @pytest.fixture
    def heal(self):
        return SelfHealStrategy(max_retries=2, base_backoff_sec=0.01, max_backoff_sec=0.05)

    @pytest.mark.asyncio
    async def test_retry_success_records_success_result(self, heal):
        """成功重试后 history 中应有 SUCCESS 记录"""

        async def ok_fn():
            return True

        result = await heal._retry_with_backoff("test_ok", ok_fn, max_retries=2)
        assert result == HealResult.SUCCESS
        assert len(heal._history) == 1
        rec = heal._history[0]
        assert rec.result == HealResult.SUCCESS
        assert rec.strategy == "test_ok"
        assert rec.attempts == 1
        assert rec.finished_at > 0

    @pytest.mark.asyncio
    async def test_retry_failure_records_failed_result(self, heal):
        """所有重试失败后 history 中应有 FAILED 记录"""

        async def fail_fn():
            return False

        result = await heal._retry_with_backoff("test_fail", fail_fn, max_retries=2)
        assert result == HealResult.FAILED
        assert len(heal._history) == 1
        rec = heal._history[0]
        assert rec.result == HealResult.FAILED
        assert rec.attempts == 2

    @pytest.mark.asyncio
    async def test_retry_exception_records_failed_result(self, heal):
        """重试函数抛异常后 history 中应有 FAILED 记录（不抛 TypeError）"""

        async def boom_fn():
            raise RuntimeError("boom")

        result = await heal._retry_with_backoff("test_exc", boom_fn, max_retries=2)
        assert result == HealResult.FAILED
        assert len(heal._history) == 1
        rec = heal._history[0]
        assert rec.result == HealResult.FAILED
        assert "boom" in rec.detail

    @pytest.mark.asyncio
    async def test_retry_second_attempt_succeeds(self, heal):
        """第一次失败、第二次成功 → SUCCESS 记录，attempts=2"""
        call_count = 0

        async def flaky_fn():
            nonlocal call_count
            call_count += 1
            return call_count >= 2

        result = await heal._retry_with_backoff("test_flaky", flaky_fn, max_retries=3)
        assert result == HealResult.SUCCESS
        rec = heal._history[0]
        assert rec.result == HealResult.SUCCESS
        assert rec.attempts == 2


# ════════════════════════════════════════════════════════════════
# P0-3: Logger %s 格式化验证
# ════════════════════════════════════════════════════════════════


class TestStreamPersistenceLogger:
    """验证 stream_persistence 的 logger 调用使用 %s 格式化"""

    @pytest.mark.asyncio
    async def test_persist_exception_uses_percent_format(self):
        """persist 异常时 logger.exception 应使用 %s 格式化，不传 kwargs"""
        from one_quant.infra.stream_persistence import StreamPersistence

        sp = StreamPersistence()
        sp._enabled = True
        sp._redis = MagicMock()
        sp._redis.xadd = AsyncMock(side_effect=RuntimeError("redis down"))

        with patch("one_quant.infra.stream_persistence.logger") as mock_log:
            await sp.persist("order.update", {"k": "v"}, trace_id="t1")
            mock_log.exception.assert_called_once()
            args, kwargs = mock_log.exception.call_args
            # 必须用 %s 位置参数，不能有 channel= keyword
            assert "channel" not in kwargs
            # 消息字符串中应包含 channel 信息
            assert "order.update" in str(args)

    @pytest.mark.asyncio
    async def test_replay_exception_uses_percent_format(self):
        """replay 异常时 logger.exception 应使用 %s 格式化，不传 kwargs"""
        from one_quant.infra.stream_persistence import StreamPersistence

        sp = StreamPersistence()
        sp._enabled = True
        sp._redis = MagicMock()
        sp._redis.xrange = AsyncMock(side_effect=RuntimeError("redis down"))

        with patch("one_quant.infra.stream_persistence.logger") as mock_log:
            result = await sp.replay("fill.executed")
            assert result == []
            mock_log.exception.assert_called_once()
            args, kwargs = mock_log.exception.call_args
            assert "channel" not in kwargs
            assert "fill.executed" in str(args)


class TestPositionRecoveryLogger:
    """验证 position_recovery 的 logger 调用使用 %s 格式化"""

    @pytest.mark.asyncio
    async def test_recover_logger_uses_percent_format(self):
        """recover 完成时 logger.info 应使用 %s 格式化，不传 **kwargs"""
        from one_quant.core.types import PositionState
        from one_quant.execution.position_recovery import PositionRecoveryManager

        bus = MagicMock()
        bus.publish = AsyncMock()

        mgr = PositionRecoveryManager(bus)

        pos = MagicMock(spec=PositionState)
        pos.symbol = "BTCUSDT"
        pos.quantity = 1.0
        pos.side = "long"
        pos.model_dump.return_value = {"symbol": "BTCUSDT", "qty": 1.0}

        with patch("one_quant.execution.position_recovery.logger") as mock_log:
            await mgr.recover([pos], {})
            # 找到 "持仓恢复完成" 的那次调用
            info_calls = [c for c in mock_log.info.call_args_list if "持仓恢复完成" in str(c)]
            assert len(info_calls) == 1
            args, kwargs = info_calls[0]
            # 不能有 **kwargs 传入
            assert kwargs == {} or len(kwargs) == 0
            # 消息应使用 %s 格式化
            assert "%s" in args[0]
