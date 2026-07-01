"""Tests for data/tick_collector.py — P0-1 签名修复验证

验证 TickCollector 接受 storage + quality_gate 参数，
采集流程经过质检门后落 Bronze 层。
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from one_quant.data.tick_collector import TickCollector
from one_quant.infra.event_bus import InMemoryEventBus


class TestTickCollectorSignature:
    """P0-1: TickCollector 签名修复"""

    @pytest.mark.asyncio
    async def test_accepts_storage_and_quality_gate(self):
        """TickCollector 构造函数接受 storage 和 quality_gate 参数"""
        bus = InMemoryEventBus()
        storage = AsyncMock()
        quality_gate = MagicMock()

        collector = TickCollector(
            event_bus=bus,
            storage=storage,
            quality_gate=quality_gate,
        )

        assert collector._storage is storage
        assert collector._quality_gate is quality_gate

    @pytest.mark.asyncio
    async def test_backward_compatible_defaults(self):
        """不传 storage/quality_gate 时使用默认值（向后兼容）"""
        bus = InMemoryEventBus()

        collector = TickCollector(event_bus=bus)

        assert collector._storage is None
        assert collector._quality_gate is None
        assert str(collector._output_dir) == "data/bronze"
        assert collector._batch_size == 1000
        assert collector._flush_interval == 10.0

    @pytest.mark.asyncio
    async def test_custom_output_dir_and_batch(self):
        """自定义 output_dir / batch_size / flush_interval"""
        bus = InMemoryEventBus()

        collector = TickCollector(
            event_bus=bus,
            output_dir="/tmp/test_bronze",
            batch_size=500,
            flush_interval=5.0,
        )

        assert str(collector._output_dir) == "/tmp/test_bronze"
        assert collector._batch_size == 500
        assert collector._flush_interval == 5.0


class TestTickCollectorQualityGate:
    """TickCollector 集成 quality_gate 质检"""

    @pytest.mark.asyncio
    async def test_data_passes_quality_gate(self):
        """通过质检的数据进入缓冲区"""
        bus = InMemoryEventBus()
        quality_gate = MagicMock()
        quality_gate.check.return_value = (True, [])  # 通过

        collector = TickCollector(event_bus=bus, quality_gate=quality_gate)
        collector._running = True

        data = {"symbol": "BTCUSDT", "timestamp_ns": 1700000000000000000, "price": "50000"}
        await collector._on_data(data)

        assert len(collector._buffer) == 1
        assert collector._collected_count == 1

    @pytest.mark.asyncio
    async def test_data_rejected_by_quality_gate(self):
        """未通过质检的数据被丢弃"""
        bus = InMemoryEventBus()
        quality_gate = MagicMock()
        quality_gate.check.return_value = (False, ["重复记录"])

        collector = TickCollector(event_bus=bus, quality_gate=quality_gate)
        collector._running = True

        data = {"symbol": "BTCUSDT", "timestamp_ns": 1700000000000000000, "price": "50000"}
        await collector._on_data(data)

        assert len(collector._buffer) == 0

    @pytest.mark.asyncio
    async def test_no_quality_gate_passthrough(self):
        """无质检门时数据直接通过"""
        bus = InMemoryEventBus()

        collector = TickCollector(event_bus=bus)
        collector._running = True

        data = {"symbol": "BTCUSDT", "timestamp_ns": 1700000000000000000}
        await collector._on_data(data)

        assert len(collector._buffer) == 1


class TestTickCollectorStorage:
    """TickCollector 集成 BronzeStorage"""

    @pytest.mark.asyncio
    async def test_flush_to_storage(self):
        """有 storage 时刷盘写入 BronzeStorage"""
        bus = InMemoryEventBus()
        storage = AsyncMock()

        collector = TickCollector(
            event_bus=bus,
            storage=storage,
            batch_size=2,
            output_dir="/tmp/test",
        )
        collector._running = True

        # 写入 2 条触发批量刷盘
        await collector._on_data({"symbol": "BTCUSDT", "price": "50000"})
        await collector._on_data({"symbol": "ETHUSDT", "price": "3000"})

        storage.append.assert_called_once()
        call_args = storage.append.call_args
        assert call_args[0][0] == "tick"  # table name
        assert len(call_args[0][1]) == 2  # 2 records

    @pytest.mark.asyncio
    async def test_flush_to_file_when_no_storage(self):
        """无 storage 时回退到文件写入（原有行为）"""
        import tempfile

        bus = InMemoryEventBus()
        with tempfile.TemporaryDirectory() as tmpdir:
            collector = TickCollector(
                event_bus=bus,
                output_dir=tmpdir,
                batch_size=1,
            )
            collector._running = True

            await collector._on_data({"symbol": "BTCUSDT", "price": "50000"})

            # 应该写入了文件
            from pathlib import Path

            files = list(Path(tmpdir).glob("*.jsonl"))
            assert len(files) == 1

    @pytest.mark.asyncio
    async def test_stop_flushes_remaining(self):
        """stop() 时刷出剩余缓冲"""
        bus = InMemoryEventBus()
        storage = AsyncMock()

        collector = TickCollector(event_bus=bus, storage=storage, batch_size=100)
        collector._running = True

        await collector._on_data({"symbol": "BTCUSDT", "price": "50000"})
        assert storage.append.call_count == 0  # 未达批量

        await collector.stop()
        storage.append.assert_called_once()  # stop 时刷出
