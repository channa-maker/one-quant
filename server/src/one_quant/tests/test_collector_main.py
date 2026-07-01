"""Smoke tests for data/collector_main.py — P0-4

验证：能构造 → 能启动一轮 → 优雅关闭。
"""

import asyncio
import signal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestCollectorMainSmoke:
    """collector_main 入口冒烟测试"""

    @pytest.mark.asyncio
    async def test_main_constructable_and_lifecycle(self):
        """能构造所有组件 + 启动一轮采集 + 优雅关闭"""
        from one_quant.data.collector_main import main

        mock_settings = MagicMock()
        mock_settings.redis.REDIS_URL = "redis://localhost:6379/0"

        mock_bus = AsyncMock()
        mock_bus.start = AsyncMock()
        mock_bus.stop = AsyncMock()

        mock_storage = AsyncMock()
        mock_storage.flush_all = AsyncMock()

        mock_quality_gate = MagicMock()

        mock_collector = AsyncMock()
        mock_collector.start_collecting = AsyncMock()
        mock_collector.stop = AsyncMock()
        mock_collector.stats = {"collected": 42, "errors": 0}

        # Patch signal.signal to capture the shutdown handler
        captured_handlers = {}

        def fake_signal(signum, handler):
            captured_handlers[signum] = handler

        # get_settings is imported inside main(), so mock at source
        with (
            patch("one_quant.infra.config.get_settings", return_value=mock_settings),
            patch("one_quant.data.collector_main.RedisEventBus", return_value=mock_bus),
            patch("one_quant.data.collector_main.BronzeStorage", return_value=mock_storage),
            patch("one_quant.data.collector_main.DataQualityGate", return_value=mock_quality_gate),
            patch("one_quant.data.collector_main.TickCollector", return_value=mock_collector),
            patch("one_quant.data.collector_main.signal.signal", side_effect=fake_signal),
        ):
            task = asyncio.create_task(main())
            await asyncio.sleep(0.05)

            # Verify startup
            mock_bus.start.assert_awaited_once()
            mock_collector.start_collecting.assert_awaited_once()

            # Verify signal handlers registered
            assert signal.SIGINT in captured_handlers
            assert signal.SIGTERM in captured_handlers

            # Trigger graceful shutdown
            captured_handlers[signal.SIGINT](signal.SIGINT, None)
            await asyncio.wait_for(task, timeout=2.0)

            # Verify shutdown sequence
            mock_collector.stop.assert_awaited_once()
            mock_storage.flush_all.assert_awaited_once()
            mock_bus.stop.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_main_importable(self):
        """main() 可导入且是协程"""
        from one_quant.data.collector_main import main

        assert asyncio.iscoroutinefunction(main)

    def test_module_has_main_guard(self):
        """模块有 if __name__ == '__main__' 保护"""
        import one_quant.data.collector_main as mod

        source = open(mod.__file__).read()
        assert "if __name__" in source
