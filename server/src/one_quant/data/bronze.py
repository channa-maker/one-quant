"""Bronze 层存储 — 原始未加工数据，只增不改，可重放"""

import asyncio
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import pyarrow as pa
    import pyarrow.parquet as pq

    HAS_PYARROW = True
except ImportError:
    HAS_PYARROW = False


class BronzeStorage:
    """Bronze 层存储。

    原始未加工数据追加写入，只增不改。
    存储格式：Parquet 文件，按日期分区。
    目录结构：data/bronze/{source}/{table}/{YYYY/MM/DD}/
    支持 ZSTD 压缩。

    Bronze 原始永久保留，任意时刻可从头重放。
    """

    def __init__(
        self,
        base_path: str = "data/bronze",
        compression: str = "zstd",
        batch_size: int = 1000,
    ) -> None:
        self._base_path = Path(base_path)
        self._compression = compression
        self._batch_size = batch_size
        self._buffers: dict[str, list[dict[str, Any]]] = {}
        self._write_lock = asyncio.Lock()

    async def append(self, table: str, records: list[dict[str, Any]], source: str = "default") -> None:
        """追加写入原始数据。

        Args:
            table: 表名 (如 ticker, trade, orderbook)
            records: 原始数据记录列表
            source: 数据源标识 (如 binance, okx)
        """
        if not records:
            return

        async with self._write_lock:
            buffer_key = f"{source}/{table}"
            if buffer_key not in self._buffers:
                self._buffers[buffer_key] = []
            self._buffers[buffer_key].extend(records)

            if len(self._buffers[buffer_key]) >= self._batch_size:
                await self._flush(buffer_key)

    async def _flush(self, buffer_key: str) -> None:
        """将缓冲区写入 Parquet 文件"""
        if buffer_key not in self._buffers or not self._buffers[buffer_key]:
            return

        records = self._buffers[buffer_key]
        self._buffers[buffer_key] = []

        # 按日期分区
        now = datetime.now(timezone.utc)
        partition_dir = self._base_path / buffer_key / now.strftime("%Y/%m/%d")
        partition_dir.mkdir(parents=True, exist_ok=True)

        filename = f"{now.strftime('%H%M%S')}_{now.microsecond:06d}.parquet"
        filepath = partition_dir / filename

        if HAS_PYARROW:
            # 使用 PyArrow 写 Parquet
            table = pa.Table.from_pylist(records)
            pq.write_table(table, str(filepath), compression=self._compression)
        else:
            # 降级为 JSON Lines
            jsonl_path = filepath.with_suffix(".jsonl")
            with open(jsonl_path, "a", encoding="utf-8") as f:
                for record in records:
                    f.write(json.dumps(record, default=str, ensure_ascii=False) + "\n")

    async def flush_all(self) -> None:
        """刷新所有缓冲区"""
        async with self._write_lock:
            for buffer_key in list(self._buffers.keys()):
                await self._flush(buffer_key)

    async def replay(
        self,
        table: str,
        start_time: datetime,
        end_time: datetime,
        source: str = "default",
    ) -> list[dict[str, Any]]:
        """回放指定时段的原始数据。

        Args:
            table: 表名
            start_time: 开始时间
            end_time: 结束时间
            source: 数据源

        Returns:
            原始数据记录列表
        """
        records: list[dict[str, Any]] = []
        buffer_key = f"{source}/{table}"

        # 遍历日期分区
        current = start_time.date()
        end_date = end_time.date()

        while current <= end_date:
            partition_dir = self._base_path / buffer_key / current.strftime("%Y/%m/%d")
            if partition_dir.exists():
                for filepath in sorted(partition_dir.glob("*.parquet")):
                    if HAS_PYARROW:
                        table_data = pq.read_table(str(filepath))
                        for row in table_data.to_pylist():
                            records.append(row)
                    else:
                        jsonl_path = filepath.with_suffix(".jsonl")
                        if jsonl_path.exists():
                            with open(jsonl_path, encoding="utf-8") as f:
                                for line in f:
                                    if line.strip():
                                        records.append(json.loads(line))
            current = current.replace(day=current.day + 1) if current.day < 28 else current

        return records
