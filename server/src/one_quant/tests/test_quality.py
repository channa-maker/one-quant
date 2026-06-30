"""数据质检门单元测试"""

from __future__ import annotations

import time

import pytest

from one_quant.data.quality import DataQualityGate


class TestDataQualityGate:
    @pytest.fixture
    def gate(self) -> DataQualityGate:
        return DataQualityGate(price_jump_threshold=0.10, max_latency_ns=5_000_000_000)

    def test_pass_valid_data(self, gate: DataQualityGate) -> None:
        data = {
            "symbol": "BTC/USDT",
            "last_price": 42000.0,
            "timestamp_ns": time.time_ns(),
        }
        passed, reason = gate.check(data)
        assert passed is True
        assert reason == "通过"

    def test_reject_missing_symbol(self, gate: DataQualityGate) -> None:
        data = {"last_price": 42000.0, "timestamp_ns": time.time_ns()}
        passed, reason = gate.check(data)
        assert passed is False
        assert "symbol" in reason

    def test_reject_out_of_order(self, gate: DataQualityGate) -> None:
        now = time.time_ns()
        # 第一条正常
        data1 = {"symbol": "BTC/USDT", "timestamp_ns": now}
        gate.check(data1)

        # 第二条时间戳更早 → 乱序
        data2 = {"symbol": "BTC/USDT", "timestamp_ns": now - 1000}
        passed, reason = gate.check(data2)
        assert passed is False
        assert "乱序" in reason

    def test_price_jump_flagging(self, gate: DataQualityGate) -> None:
        now = time.time_ns()
        # 正常价格
        data1 = {"symbol": "ETH/USDT", "last_price": 3000.0, "timestamp_ns": now}
        gate.check(data1)

        # 价格跳变 50%（超过 10% 阈值）
        data2 = {"symbol": "ETH/USDT", "last_price": 4500.0, "timestamp_ns": now + 1000}
        passed, reason = gate.check(data2)
        assert passed is True  # 跳变不丢弃，但标记
        assert data2.get("_jump_flagged") is True

    def test_duplicate_detection(self, gate: DataQualityGate) -> None:
        data = {"symbol": "BTC/USDT", "price": 42000, "timestamp_ns": 100}
        assert gate.is_duplicate(data) is False
        assert gate.is_duplicate(data) is True

    def test_alert_count(self, gate: DataQualityGate) -> None:
        assert gate.alert_count == 0

        now = time.time_ns()
        gate.check({"symbol": "X", "timestamp_ns": now})
        gate.check({"symbol": "X", "timestamp_ns": now - 1})  # 乱序
        assert gate.alert_count == 1
