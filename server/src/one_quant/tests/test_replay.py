"""Tests for data/replay.py — Tick 级历史回放"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from one_quant.data.replay import TickReplayer


@pytest.fixture
def mock_bronze():
    bronze = AsyncMock()
    bronze.replay = AsyncMock(return_value=[])
    return bronze


@pytest.fixture
def mock_event_bus():
    bus = AsyncMock()
    bus.publish = AsyncMock()
    return bus


@pytest.fixture
def mock_silver():
    silver = MagicMock()
    silver.process_batch = MagicMock(side_effect=lambda records: records)
    return silver


@pytest.fixture
def replayer(mock_bronze, mock_event_bus, mock_silver):
    return TickReplayer(
        bronze_storage=mock_bronze,
        event_bus=mock_event_bus,
        silver_processor=mock_silver,
    )


# ── Replay basics ──────────────────────────────────────────────


class TestReplayBasics:
    @pytest.mark.asyncio
    async def test_replay_empty_returns_zero(self, replayer, mock_bronze):
        mock_bronze.replay = AsyncMock(return_value=[])
        now = datetime.now(UTC)
        count = await replayer.replay("ticker", now, now)
        assert count == 0

    @pytest.mark.asyncio
    async def test_replay_processes_records(self, replayer, mock_bronze, mock_silver):
        raw = [{"symbol": "BTC", "timestamp_ns": 100}, {"symbol": "BTC", "timestamp_ns": 200}]
        mock_bronze.replay = AsyncMock(return_value=raw)
        mock_silver.process_batch = MagicMock(return_value=raw)

        now = datetime.now(UTC)
        count = await replayer.replay("ticker", now, now, speed=0)
        assert count == 2

    @pytest.mark.asyncio
    async def test_replay_publishes_to_event_bus(
        self, replayer, mock_bronze, mock_silver, mock_event_bus
    ):
        raw = [{"symbol": "BTC", "timestamp_ns": 100}]
        mock_bronze.replay = AsyncMock(return_value=raw)
        mock_silver.process_batch = MagicMock(return_value=raw)

        now = datetime.now(UTC)
        await replayer.replay("trade", now, now, speed=0)
        mock_event_bus.publish.assert_called_once_with("market.trade", raw[0])

    @pytest.mark.asyncio
    async def test_replay_with_custom_handler(self, replayer, mock_bronze, mock_silver):
        raw = [{"symbol": "X", "timestamp_ns": 50}]
        mock_bronze.replay = AsyncMock(return_value=raw)
        mock_silver.process_batch = MagicMock(return_value=raw)

        collected = []

        async def handler(record):
            collected.append(record)

        now = datetime.now(UTC)
        await replayer.replay("t", now, now, speed=0, handler=handler)
        assert len(collected) == 1
        assert collected[0]["symbol"] == "X"

    @pytest.mark.asyncio
    async def test_replay_sorts_by_timestamp(self, replayer, mock_bronze, mock_silver):
        raw = [
            {"symbol": "A", "timestamp_ns": 300},
            {"symbol": "A", "timestamp_ns": 100},
            {"symbol": "A", "timestamp_ns": 200},
        ]
        mock_bronze.replay = AsyncMock(return_value=raw)
        # Silver returns same order
        mock_silver.process_batch = MagicMock(return_value=raw)

        collected = []

        async def handler(record):
            collected.append(record["timestamp_ns"])

        now = datetime.now(UTC)
        await replayer.replay("t", now, now, speed=0, handler=handler)
        assert handler  # reference it
        assert collected == [100, 200, 300]


# ── Stop mechanism ─────────────────────────────────────────────


class TestReplayStop:
    @pytest.mark.asyncio
    async def test_stop_halts_replay(self, replayer, mock_bronze, mock_silver):
        raw = [{"symbol": "X", "timestamp_ns": i} for i in range(100)]
        mock_bronze.replay = AsyncMock(return_value=raw)
        mock_silver.process_batch = MagicMock(return_value=raw)

        processed = []

        async def handler(record):
            processed.append(record)
            if len(processed) >= 2:
                replayer.stop()

        now = datetime.now(UTC)
        count = await replayer.replay("t", now, now, speed=0, handler=handler)
        assert count == 2


# ── Stats ──────────────────────────────────────────────────────


class TestReplayStats:
    def test_initial_stats(self, replayer):
        assert replayer.stats == {"replayed": 0}

    @pytest.mark.asyncio
    async def test_stats_after_replay(self, replayer, mock_bronze, mock_silver):
        raw = [{"symbol": "X", "timestamp_ns": 1}]
        mock_bronze.replay = AsyncMock(return_value=raw)
        mock_silver.process_batch = MagicMock(return_value=raw)

        now = datetime.now(UTC)
        await replayer.replay("t", now, now, speed=0)
        assert replayer.stats["replayed"] == 1


# ── Stream replay ──────────────────────────────────────────────


class TestReplayStream:
    @pytest.mark.asyncio
    async def test_replay_stream_yields_records(self, replayer, mock_bronze, mock_silver):
        raw = [
            {"symbol": "X", "timestamp_ns": 10},
            {"symbol": "X", "timestamp_ns": 20},
        ]
        mock_bronze.replay = AsyncMock(return_value=raw)
        mock_silver.process_batch = MagicMock(return_value=raw)

        now = datetime.now(UTC)
        records = []
        async for record in replayer.replay_stream("t", now, now, speed=0):
            records.append(record)
        assert len(records) == 2
        assert records[0]["timestamp_ns"] == 10

    @pytest.mark.asyncio
    async def test_replay_stream_empty(self, replayer, mock_bronze):
        mock_bronze.replay = AsyncMock(return_value=[])
        now = datetime.now(UTC)
        records = []
        async for record in replayer.replay_stream("t", now, now):
            records.append(record)
        assert records == []
