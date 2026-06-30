"""tick 级历史回放接口 — 任意时段重放，与实时同序"""

import asyncio
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator

try:
    import pyarrow.parquet as pq

    HAS_PYARROW = True
except ImportError:
    HAS_PYARROW = False


class TickReplayer:
    """tick 级历史回放器。

    按事件时间顺序重放历史数据，支持倍速。
    与实时数据同序（用于回测一致性验证）。
    """

    def __init__(
        self,
        data_path: str = "data/bronze",
        speed: float = 1.0,
    ) -> None:
        self._data_path = Path(data_path)
        self._speed = speed  # 倍速: 1.0=原速, 0=最快, 2.0=两倍速
        self._replayed_count = 0

    async def replay(
        self,
        symbol: str,
        start_time: datetime,
        end_time: datetime,
        table: str = "ticker",
        source: str = "default",
    ) -> AsyncIterator[dict[str, Any]]:
        """回放指定时段的历史数据。

        Args:
            symbol: 标的符号
            start_time: 开始时间
            end_time: 结束时间
            table: 数据表名
            source: 数据源

        Yields:
            按事件时间排序的原始数据记录
        """
        # 收集所有匹配的记录
        records = await self._load_records(symbol, table, source, start_time, end_time)

        if not records:
            return

        # 按时间戳排序
        records.sort(key=lambda r: r.get("timestamp_ns", 0))

        # 重放
        prev_ts = 0
        for record in records:
            ts_ns = record.get("timestamp_ns", 0)

            # 倍速控制
            if self._speed > 0 and prev_ts > 0 and ts_ns > prev_ts:
                delay_sec = (ts_ns - prev_ns) / 1e9 / self._speed
                if delay_sec > 0:
                    await asyncio.sleep(min(delay_sec, 1.0))  # 最多等 1 秒

            prev_ts = ts_ns
            self._replayed_count += 1
            yield record

    async def _load_records(
        self,
        symbol: str,
        table: str,
        source: str,
        start_time: datetime,
        end_time: datetime,
    ) -> list[dict[str, Any]]:
        """加载指定时段的数据记录"""
        records: list[dict[str, Any]] = []
        buffer_key = f"{source}/{table}"

        # 遍历日期分区
        current = start_time.date()
        end_date = end_time.date()

        while current <= end_date:
            partition_dir = self._data_path / buffer_key / current.strftime("%Y/%m/%d")
            if partition_dir.exists():
                for filepath in sorted(partition_dir.glob("*.parquet")):
                    if HAS_PYARROW:
                        table_data = pq.read_table(str(filepath))
                        for row in table_data.to_pylist():
                            if row.get("symbol") == symbol:
                                records.append(row)
                    else:
                        jsonl_path = filepath.with_suffix(".jsonl")
                        if jsonl_path.exists():
                            import json

                            with open(jsonl_path, encoding="utf-8") as f:
                                for line in f:
                                    if line.strip():
                                        row = json.loads(line)
                                        if row.get("symbol") == symbol:
                                            records.append(row)

            # 下一天
            from datetime import timedelta

            current += timedelta(days=1)

        return records

    @property
    def replayed_count(self) -> int:
        """已重放记录数"""
        return self._replayed_count
