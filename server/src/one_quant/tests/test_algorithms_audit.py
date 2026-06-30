"""
Tests for execution.algorithms (TWAP/VWAP/Iceberg) and execution.audit
"""

import json
import time
import uuid
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from one_quant.core.types import Market, Order
from one_quant.execution.algorithms import IcebergAlgo, TWAPAlgo, VWAPAlgo
from one_quant.execution.audit import AuditLog, AuditRecord


def _make_order(qty: str = "1.0", price: str = "50000", side: str = "buy") -> Order:
    return Order(
        client_order_id=str(uuid.uuid4()),
        symbol="BTCUSDT",
        market=Market.SPOT,
        side=side,
        order_type="limit",
        quantity=Decimal(qty),
        price=Decimal(price),
        stop_price=None,
        status="pending",
        exchange="binance",
        timestamp_ns=time.time_ns(),
    )


# ═══════════════════════ TWAPAlgo ═══════════════════════


class TestTWAPAlgo:
    def test_name(self):
        algo = TWAPAlgo()
        assert algo.name == "twap"

    def test_default_params(self):
        algo = TWAPAlgo()
        assert algo._slices == 10
        assert algo._interval == 60.0

    def test_custom_params(self):
        algo = TWAPAlgo(slices=5, interval_sec=30.0)
        assert algo._slices == 5
        assert algo._interval == 30.0

    @pytest.mark.asyncio
    async def test_execute_produces_child_orders(self):
        algo = TWAPAlgo(slices=3, interval_sec=0)
        submit_fn = AsyncMock()
        cancel_fn = AsyncMock()
        parent = _make_order(qty="0.9")

        children = await algo.execute(parent, submit_fn, cancel_fn)

        assert len(children) == 3
        assert submit_fn.call_count == 3
        # Each child should have 1/3 of parent quantity
        for child in children:
            assert child.quantity == Decimal("0.9") / 3

    @pytest.mark.asyncio
    async def test_execute_sets_submitted_status(self):
        algo = TWAPAlgo(slices=2, interval_sec=0)
        submit_fn = AsyncMock()
        parent = _make_order(qty="1.0")

        children = await algo.execute(parent, submit_fn, AsyncMock())

        for child in children:
            assert child.status == "submitted"

    @pytest.mark.asyncio
    async def test_execute_submit_failure_sets_rejected(self):
        algo = TWAPAlgo(slices=2, interval_sec=0)
        call_count = 0

        async def failing_submit(order):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise ConnectionError("network error")

        parent = _make_order(qty="1.0")
        children = await algo.execute(parent, failing_submit, AsyncMock())

        assert len(children) == 2
        assert children[0].status == "submitted"
        assert children[1].status == "rejected"

    @pytest.mark.asyncio
    async def test_execute_preserves_symbol_and_side(self):
        algo = TWAPAlgo(slices=2, interval_sec=0)
        parent = _make_order(qty="1.0", side="sell")

        children = await algo.execute(parent, AsyncMock(), AsyncMock())

        for child in children:
            assert child.symbol == "BTCUSDT"
            assert child.side == "sell"
            assert child.exchange == "binance"

    @pytest.mark.asyncio
    async def test_execute_single_slice(self):
        algo = TWAPAlgo(slices=1, interval_sec=0)
        parent = _make_order(qty="0.5")

        children = await algo.execute(parent, AsyncMock(), AsyncMock())

        assert len(children) == 1
        assert children[0].quantity == Decimal("0.5")


# ═══════════════════════ VWAPAlgo ═══════════════════════


class TestVWAPAlgo:
    def test_name(self):
        algo = VWAPAlgo()
        assert algo.name == "vwap"

    def test_default_volume_profile(self):
        algo = VWAPAlgo(slices=5)
        assert len(algo._volume_profile) == 5
        # Should sum to ~1.0
        total = sum(algo._volume_profile)
        assert abs(total - 1.0) < 1e-10

    def test_custom_volume_profile(self):
        profile = [0.5, 0.3, 0.2]
        algo = VWAPAlgo(slices=3, volume_profile=profile)
        assert algo._volume_profile == profile

    @pytest.mark.asyncio
    async def test_execute_with_uniform_profile(self):
        algo = VWAPAlgo(slices=4, interval_sec=0)
        submit_fn = AsyncMock()
        parent = _make_order(qty="2.0")

        children = await algo.execute(parent, submit_fn, AsyncMock())

        assert len(children) == 4
        assert submit_fn.call_count == 4

    @pytest.mark.asyncio
    async def test_execute_with_weighted_profile(self):
        profile = [0.6, 0.4]
        algo = VWAPAlgo(slices=2, interval_sec=0, volume_profile=profile)
        submit_fn = AsyncMock()
        parent = _make_order(qty="1.0")

        children = await algo.execute(parent, submit_fn, AsyncMock())

        assert len(children) == 2
        # Quantities should reflect weights
        assert children[0].quantity > children[1].quantity

    @pytest.mark.asyncio
    async def test_execute_submit_failure_keeps_order(self):
        async def failing_submit(order):
            raise RuntimeError("fail")

        algo = VWAPAlgo(slices=2, interval_sec=0)
        parent = _make_order(qty="1.0")

        children = await algo.execute(parent, failing_submit, AsyncMock())

        # Orders are still appended even on failure
        assert len(children) == 2

    @pytest.mark.asyncio
    async def test_execute_preserves_parent_attrs(self):
        algo = VWAPAlgo(slices=2, interval_sec=0)
        parent = _make_order(qty="1.0", side="sell")

        children = await algo.execute(parent, AsyncMock(), AsyncMock())

        for child in children:
            assert child.symbol == parent.symbol
            assert child.side == parent.side
            assert child.exchange == parent.exchange
            assert child.market == parent.market


# ═══════════════════════ IcebergAlgo ═══════════════════════


class TestIcebergAlgo:
    def test_name(self):
        algo = IcebergAlgo()
        assert algo.name == "iceberg"

    def test_default_params(self):
        algo = IcebergAlgo()
        assert algo._visible_pct == Decimal("0.1")
        assert algo._max_retries == 3

    @pytest.mark.asyncio
    async def test_execute_splits_into_batches(self):
        algo = IcebergAlgo(visible_qty_pct=Decimal("0.5"))
        submit_fn = AsyncMock()
        parent = _make_order(qty="1.0")

        children = await algo.execute(parent, submit_fn, AsyncMock())

        # 1.0 * 0.5 = 0.5 per batch → 2 batches
        assert len(children) == 2
        assert submit_fn.call_count == 2

    @pytest.mark.asyncio
    async def test_execute_reduces_remaining(self):
        algo = IcebergAlgo(visible_qty_pct=Decimal("0.1"))
        submit_fn = AsyncMock()
        parent = _make_order(qty="1.0")

        children = await algo.execute(parent, submit_fn, AsyncMock())

        # 1.0 * 0.1 = 0.1 per batch → 10 batches
        assert len(children) == 10

    @pytest.mark.asyncio
    async def test_execute_submit_failure_continues(self):
        call_count = 0

        async def sometimes_fail(order):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise RuntimeError("fail")

        algo = IcebergAlgo(visible_qty_pct=Decimal("0.5"))
        parent = _make_order(qty="1.0")

        children = await algo.execute(parent, sometimes_fail, AsyncMock())

        # First batch succeeds, second fails, third succeeds
        assert len(children) >= 2
        # At least one rejected
        rejected = [c for c in children if c.status == "rejected"]
        assert len(rejected) >= 1

    @pytest.mark.asyncio
    async def test_execute_all_submitted_on_success(self):
        algo = IcebergAlgo(visible_qty_pct=Decimal("0.25"))
        parent = _make_order(qty="1.0")

        children = await algo.execute(parent, AsyncMock(), AsyncMock())

        for child in children:
            assert child.status == "submitted"

    @pytest.mark.asyncio
    async def test_execute_small_order_single_batch(self):
        algo = IcebergAlgo(visible_qty_pct=Decimal("1.0"))
        parent = _make_order(qty="0.5")

        children = await algo.execute(parent, AsyncMock(), AsyncMock())

        assert len(children) == 1
        assert children[0].quantity == Decimal("0.5")


# ═══════════════════════ AuditLog ═══════════════════════


class TestAuditLog:
    def test_create_log(self):
        log = AuditLog()
        assert log.count == 0

    def test_record_single_event(self):
        log = AuditLog()
        rec = log.record(
            event_type="order.submit",
            source="test_strategy",
            data={"order_id": "ORD-001"},
        )

        assert isinstance(rec, AuditRecord)
        assert rec.event_type == "order.submit"
        assert rec.source == "test_strategy"
        assert rec.data == {"order_id": "ORD-001"}
        assert rec.record_id.startswith("AUDIT-")
        assert log.count == 1

    def test_record_with_state_snapshot(self):
        log = AuditLog()
        snapshot = {"balance": "100000", "position": "0"}
        rec = log.record(
            event_type="system.state_change",
            source="system",
            data={},
            state_snapshot=snapshot,
        )
        assert rec.state_snapshot == snapshot

    def test_record_with_trace_id(self):
        log = AuditLog()
        rec = log.record(
            event_type="order.fill",
            source="ems",
            data={},
            trace_id="trace-abc-123",
        )
        assert rec.trace_id == "trace-abc-123"

    def test_record_increments_counter(self):
        log = AuditLog()
        r1 = log.record(event_type="a", source="s", data={})
        r2 = log.record(event_type="b", source="s", data={})

        assert r1.record_id == "AUDIT-000000000001"
        assert r2.record_id == "AUDIT-000000000002"
        assert log.count == 2

    def test_query_by_event_type(self):
        log = AuditLog()
        log.record(event_type="order.submit", source="s", data={})
        log.record(event_type="order.fill", source="s", data={})
        log.record(event_type="order.submit", source="s", data={})

        results = log.query(event_type="order.submit")
        assert len(results) == 2
        for r in results:
            assert r.event_type == "order.submit"

    def test_query_by_source(self):
        log = AuditLog()
        log.record(event_type="a", source="strategy_a", data={})
        log.record(event_type="a", source="strategy_b", data={})

        results = log.query(source="strategy_a")
        assert len(results) == 1
        assert results[0].source == "strategy_a"

    def test_query_by_time_range(self):
        log = AuditLog()
        log.record(event_type="a", source="s", data={})

        rec = log._records[0]
        # Query with exact timestamp range
        results = log.query(start_ns=rec.timestamp_ns, end_ns=rec.timestamp_ns)
        assert len(results) == 1

    def test_query_with_limit(self):
        log = AuditLog()
        for i in range(10):
            log.record(event_type="a", source="s", data={"i": i})

        results = log.query(limit=3)
        assert len(results) == 3

    def test_query_returns_newest_first(self):
        log = AuditLog()
        log.record(event_type="a", source="s", data={"order": 1})
        log.record(event_type="a", source="s", data={"order": 2})
        log.record(event_type="a", source="s", data={"order": 3})

        results = log.query()
        assert results[0].data["order"] == 3
        assert results[1].data["order"] == 2
        assert results[2].data["order"] == 1

    def test_query_no_match(self):
        log = AuditLog()
        log.record(event_type="a", source="s", data={})

        results = log.query(event_type="nonexistent")
        assert len(results) == 0

    def test_query_combined_filters(self):
        log = AuditLog()
        log.record(event_type="a", source="x", data={})
        log.record(event_type="b", source="x", data={})
        log.record(event_type="a", source="y", data={})

        results = log.query(event_type="a", source="x")
        assert len(results) == 1

    def test_export_jsonl(self, tmp_path):
        log = AuditLog()
        log.record(event_type="order.submit", source="test", data={"key": "value"})
        log.record(event_type="order.fill", source="test", data={"key": "value2"})

        filepath = str(tmp_path / "audit.jsonl")
        count = log.export_jsonl(filepath)

        assert count == 2
        with open(filepath, encoding="utf-8") as f:
            lines = f.readlines()
        assert len(lines) == 2
        # Each line is valid JSON
        for line in lines:
            obj = json.loads(line)
            assert "record_id" in obj
            assert "event_type" in obj

    def test_export_jsonl_appends(self, tmp_path):
        log = AuditLog()
        log.record(event_type="a", source="s", data={})

        filepath = str(tmp_path / "audit.jsonl")
        log.export_jsonl(filepath)
        log.export_jsonl(filepath)  # append again

        with open(filepath, encoding="utf-8") as f:
            lines = f.readlines()
        assert len(lines) == 2  # appended, not overwritten

    def test_audit_record_is_frozen(self):
        log = AuditLog()
        rec = log.record(event_type="a", source="s", data={})

        with pytest.raises(Exception):
            rec.event_type = "changed"  # type: ignore

    def test_empty_query(self):
        log = AuditLog()
        results = log.query()
        assert results == []
