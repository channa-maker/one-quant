"""Silver 层处理器单元测试"""

from __future__ import annotations

import time

import pytest

from one_quant.data.silver import SilverProcessor


class TestSilverProcessor:
    @pytest.fixture
    def processor(self) -> SilverProcessor:
        return SilverProcessor()

    def test_process_valid(self, processor: SilverProcessor) -> None:
        data = {
            "symbol": "BTC/USDT",
            "last_price": 42000.50,
            "timestamp_ns": time.time_ns(),
        }
        result = processor.process(data)
        assert result is not None
        assert result["symbol"] == "BTC/USDT"
        assert "_processed_at_ns" in result

    def test_process_missing_symbol(self, processor: SilverProcessor) -> None:
        data = {"last_price": 42000, "timestamp_ns": time.time_ns()}
        result = processor.process(data)
        assert result is None

    def test_dedup_by_timestamp(self, processor: SilverProcessor) -> None:
        ts = time.time_ns()
        data1 = {"symbol": "BTC/USDT", "timestamp_ns": ts}
        data2 = {"symbol": "BTC/USDT", "timestamp_ns": ts}  # 同时间戳

        processor.process(data1)
        result = processor.process(data2)
        assert result is None  # 被去重

    def test_batch_processing(self, processor: SilverProcessor) -> None:
        now = time.time_ns()
        records = [{"symbol": "BTC/USDT", "timestamp_ns": now + i} for i in range(10)]
        results = processor.process_batch(records)
        assert len(results) == 10

    def test_price_decimal_conversion(self, processor: SilverProcessor) -> None:
        data = {
            "symbol": "ETH/USDT",
            "last_price": 3000.123456789,
            "timestamp_ns": time.time_ns(),
        }
        result = processor.process(data)
        assert result is not None
        # 价格应被转为字符串（Decimal 的字符串表示）
        assert isinstance(result["last_price"], str)
