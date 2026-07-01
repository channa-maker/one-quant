"""
ONE量化 - 风控审计日志完整测试

覆盖 risk/audit.py 所有代码路径:
  - record() 含 order / 不含 order
  - 持久化路径 (成功 / OSError)
  - query() 时间范围 + strategy_id 过滤
  - count / clear 属性
  - 线程安全
"""

from __future__ import annotations

import json
import tempfile
import threading
import time
from decimal import Decimal
from pathlib import Path

from one_quant.core.types import Market, Order
from one_quant.risk.audit import RiskAuditLog
from one_quant.risk.contracts import RiskCheckResult, RiskDecision

# ──────────────────── 辅助工具 ────────────────────


def _make_decision(
    decision: RiskDecision = RiskDecision.APPROVE,
    rule_name: str = "test_rule",
    reason: str = "测试通过",
    timestamp_ns: int | None = None,
) -> RiskCheckResult:
    return RiskCheckResult(
        decision=decision,
        rule_name=rule_name,
        reason=reason,
        timestamp_ns=timestamp_ns or time.time_ns(),
    )


def _make_order(
    symbol: str = "BTC/USDT",
    client_order_id: str = "test-uuid-001",
) -> Order:
    return Order(
        client_order_id=client_order_id,
        symbol=symbol,
        market=Market.SPOT,
        side="buy",
        order_type="limit",
        quantity=Decimal("0.1"),
        price=Decimal("50000"),
        stop_price=None,
        status="pending",
        exchange="binance",
        timestamp_ns=time.time_ns(),
    )


# ──────────────────── record() 测试 ────────────────────


class TestAuditRecord:
    """审计日志 record() 测试"""

    def test_record_with_order(self):
        """记录含订单的审计日志。"""
        log = RiskAuditLog()
        decision = _make_decision()
        order = _make_order()
        snapshot = {"equity": 100000, "positions": 3}

        log.record(decision, order, snapshot, strategy_id="strat_001")

        assert log.count == 1
        records = log.query(0, time.time_ns() + 1_000_000_000)
        assert len(records) == 1
        r = records[0]
        assert r["strategy_id"] == "strat_001"
        assert r["order_id"] == "test-uuid-001"
        assert r["symbol"] == "BTC/USDT"
        assert r["decision"] == "APPROVE"
        assert r["rule_name"] == "test_rule"
        assert r["reason"] == "测试通过"
        assert r["snapshot"] == snapshot

    def test_record_without_order(self):
        """记录无订单的审计日志 (halt_all 场景)。"""
        log = RiskAuditLog()
        decision = _make_decision(decision=RiskDecision.FLATTEN, reason="全局熔断")

        log.record(decision, None, {"halted": True})

        assert log.count == 1
        records = log.query(0, time.time_ns() + 1_000_000_000)
        r = records[0]
        assert r["order_id"] is None
        assert r["symbol"] is None
        assert r["decision"] == "FLATTEN"

    def test_record_without_strategy_id(self):
        """记录不含策略ID的审计日志。"""
        log = RiskAuditLog()
        decision = _make_decision()
        order = _make_order()

        log.record(decision, order, {})

        records = log.query(0, time.time_ns() + 1_000_000_000)
        assert records[0]["strategy_id"] is None

    def test_record_multiple(self):
        """多条记录递增。"""
        log = RiskAuditLog()
        for i in range(5):
            log.record(
                _make_decision(timestamp_ns=1000 + i),
                _make_order(client_order_id=f"order-{i}"),
                {"i": i},
                strategy_id=f"strat_{i}",
            )
        assert log.count == 5


# ──────────────────── query() 测试 ────────────────────


class TestAuditQuery:
    """审计日志 query() 测试"""

    def test_query_time_range(self):
        """按时间范围查询。"""
        log = RiskAuditLog()
        log.record(_make_decision(timestamp_ns=100), _make_order(), {})
        log.record(_make_decision(timestamp_ns=200), _make_order(), {})
        log.record(_make_decision(timestamp_ns=300), _make_order(), {})

        results = log.query(150, 250)
        assert len(results) == 1
        assert results[0]["timestamp_ns"] == 200

    def test_query_inclusive_boundaries(self):
        """查询包含边界值。"""
        log = RiskAuditLog()
        log.record(_make_decision(timestamp_ns=100), _make_order(), {})
        log.record(_make_decision(timestamp_ns=200), _make_order(), {})

        results = log.query(100, 200)
        assert len(results) == 2

    def test_query_filter_by_strategy_id(self):
        """按策略ID过滤。"""
        log = RiskAuditLog()
        log.record(_make_decision(timestamp_ns=100), _make_order(), {}, strategy_id="A")
        log.record(_make_decision(timestamp_ns=200), _make_order(), {}, strategy_id="B")
        log.record(_make_decision(timestamp_ns=300), _make_order(), {}, strategy_id="A")

        results = log.query(0, 999, strategy_id="A")
        assert len(results) == 2
        for r in results:
            assert r["strategy_id"] == "A"

    def test_query_no_match_strategy_id(self):
        """策略ID不匹配返回空。"""
        log = RiskAuditLog()
        log.record(_make_decision(timestamp_ns=100), _make_order(), {}, strategy_id="A")

        results = log.query(0, 999, strategy_id="nonexistent")
        assert len(results) == 0

    def test_query_strategy_id_none_no_filter(self):
        """strategy_id=None 不过滤。"""
        log = RiskAuditLog()
        log.record(_make_decision(timestamp_ns=100), _make_order(), {}, strategy_id="A")
        log.record(_make_decision(timestamp_ns=200), _make_order(), {}, strategy_id="B")

        results = log.query(0, 999)
        assert len(results) == 2

    def test_query_empty_log(self):
        """空日志查询返回空列表。"""
        log = RiskAuditLog()
        results = log.query(0, 999)
        assert results == []

    def test_query_no_match_time_range(self):
        """时间范围不匹配返回空。"""
        log = RiskAuditLog()
        log.record(_make_decision(timestamp_ns=500), _make_order(), {})

        results = log.query(0, 100)
        assert len(results) == 0


# ──────────────────── count / clear 测试 ────────────────────


class TestAuditCountClear:
    """count / clear 测试"""

    def test_count_empty(self):
        """空日志 count 为 0。"""
        log = RiskAuditLog()
        assert log.count == 0

    def test_count_after_records(self):
        """记录后 count 递增。"""
        log = RiskAuditLog()
        log.record(_make_decision(), _make_order(), {})
        log.record(_make_decision(), _make_order(), {})
        assert log.count == 2

    def test_clear(self):
        """clear 清空内存记录。"""
        log = RiskAuditLog()
        log.record(_make_decision(), _make_order(), {})
        log.record(_make_decision(), _make_order(), {})
        assert log.count == 2

        log.clear()
        assert log.count == 0

    def test_clear_empty_log(self):
        """清空空日志不报错。"""
        log = RiskAuditLog()
        log.clear()
        assert log.count == 0


# ──────────────────── 持久化测试 ────────────────────


class TestAuditPersistence:
    """持久化测试"""

    def test_persist_to_file(self):
        """审计日志写入文件。"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            path = f.name

        try:
            log = RiskAuditLog(persist_path=path)
            decision = _make_decision()
            order = _make_order()
            log.record(decision, order, {"equity": 100000}, strategy_id="test")

            # 读取文件验证
            with open(path, encoding="utf-8") as f:
                lines = f.readlines()
            assert len(lines) == 1
            data = json.loads(lines[0])
            assert data["decision"] == "APPROVE"
            assert data["strategy_id"] == "test"
        finally:
            Path(path).unlink(missing_ok=True)

    def test_persist_multiple_records(self):
        """多条记录追加到文件。"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            path = f.name

        try:
            log = RiskAuditLog(persist_path=path)
            for i in range(3):
                log.record(
                    _make_decision(timestamp_ns=1000 + i),
                    _make_order(client_order_id=f"order-{i}"),
                    {},
                )

            with open(path, encoding="utf-8") as f:
                lines = f.readlines()
            assert len(lines) == 3
        finally:
            Path(path).unlink(missing_ok=True)

    def test_no_persist_when_path_none(self):
        """persist_path=None 时不写文件。"""
        log = RiskAuditLog(persist_path=None)
        log.record(_make_decision(), _make_order(), {})
        assert log.count == 1

    def test_persist_os_error_handled(self):
        """持久化写入失败时记录错误日志但不抛异常。"""
        log = RiskAuditLog(persist_path="/nonexistent/dir/file.jsonl")
        # 不应抛异常
        log.record(_make_decision(), _make_order(), {})
        assert log.count == 1


# ──────────────────── 线程安全测试 ────────────────────


class TestAuditThreadSafety:
    """线程安全测试"""

    def test_concurrent_record(self):
        """并发 record 不丢数据。"""
        log = RiskAuditLog()
        n_threads = 4
        n_records = 100

        def worker(thread_id: int):
            for i in range(n_records):
                log.record(
                    _make_decision(timestamp_ns=thread_id * 1_000_000 + i),
                    _make_order(client_order_id=f"t{thread_id}-{i}"),
                    {"thread": thread_id},
                )

        threads = [threading.Thread(target=worker, args=(tid,)) for tid in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert log.count == n_threads * n_records


# ──────────────────── 不同决策类型测试 ────────────────────


class TestAuditDecisions:
    """不同决策类型测试"""

    def test_record_all_decision_types(self):
        """记录所有四种决策类型。"""
        log = RiskAuditLog()
        for decision_type in RiskDecision:
            log.record(
                _make_decision(decision=decision_type),
                _make_order(),
                {},
            )

        assert log.count == 4
        records = log.query(0, time.time_ns() + 1_000_000_000)
        decisions = {r["decision"] for r in records}
        assert decisions == {"APPROVE", "REJECT", "REDUCE", "FLATTEN"}

    def test_snapshot_preserved(self):
        """快照数据完整保存。"""
        log = RiskAuditLog()
        snapshot = {
            "equity": 100000,
            "peak_equity": 120000,
            "drawdown_pct": 16.67,
            "positions": [{"symbol": "BTC", "qty": 0.5}],
        }
        log.record(_make_decision(), _make_order(), snapshot)

        records = log.query(0, time.time_ns() + 1_000_000_000)
        assert records[0]["snapshot"] == snapshot
