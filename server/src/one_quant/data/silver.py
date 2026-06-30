"""Silver 层 — 清洗对齐：去重、事件时间对齐、归一化"""

import time
from decimal import Decimal
from typing import Any


class SilverProcessor:
    """Silver 层数据处理器。

    将 Bronze 原始数据清洗对齐后写入 TimescaleDB(热) + ClickHouse(温)。
    - 去重
    - 事件时间对齐
    - 归一化
    - 时间戳单调递增保证
    """

    def __init__(self) -> None:
        self._processed_count = 0
        self._dedup_count = 0
        self._last_ts: dict[str, int] = {}

    def process(self, raw_data: dict[str, Any]) -> dict[str, Any] | None:
        """清洗单条原始数据。

        Args:
            raw_data: Bronze 层原始数据

        Returns:
            清洗后的数据，如果被过滤则返回 None
        """
        # 1. 基本字段校验
        if not raw_data.get("symbol"):
            return None

        # 2. 去重
        symbol = raw_data["symbol"]
        ts_ns = raw_data.get("timestamp_ns", 0)
        last_ts = self._last_ts.get(symbol, 0)

        if ts_ns > 0 and ts_ns <= last_ts:
            self._dedup_count += 1
            return None

        # 3. 归一化价格字段为 Decimal
        cleaned = dict(raw_data)
        price_fields = [
            "last_price",
            "bid",
            "ask",
            "open",
            "high",
            "low",
            "close",
            "price",
            "quantity",
            "volume",
        ]
        for field in price_fields:
            if field in cleaned and cleaned[field] is not None:
                try:
                    cleaned[field] = str(Decimal(str(cleaned[field])))
                except Exception:
                    cleaned[field] = "0"

        # 4. 时间戳单调递增保证
        if ts_ns > 0:
            if ts_ns <= last_ts:
                ts_ns = last_ts + 1
                cleaned["timestamp_ns"] = ts_ns
            self._last_ts[symbol] = ts_ns

        # 5. 添加处理时间
        cleaned["_processed_at_ns"] = time.time_ns()

        self._processed_count += 1
        return cleaned

    def process_batch(self, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """批量清洗。

        Args:
            records: Bronze 层原始数据列表

        Returns:
            清洗后的数据列表
        """
        results = []
        for record in records:
            cleaned = self.process(record)
            if cleaned is not None:
                results.append(cleaned)
        return results

    @property
    def stats(self) -> dict[str, int]:
        """处理统计"""
        return {
            "processed": self._processed_count,
            "deduplicated": self._dedup_count,
        }
