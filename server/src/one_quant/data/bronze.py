"""Bronze 层存储 — 原始未加工数据，只增不改，可重放"""

import json
from datetime import UTC, datetime
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

    async def append(
        self, table: str, records: list[dict[str, Any]], source: str = "default"
    ) -> None:
        """追加写入原始数据。"""
        if not records:
            return

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

        now = datetime.now(UTC)
        partition_dir = self._base_path / buffer_key / now.strftime("%Y/%m/%d")
        partition_dir.mkdir(parents=True, exist_ok=True)

        filename = f"{now.strftime('%H%M%S')}_{now.microsecond:06d}.parquet"
        filepath = partition_dir / filename

        if HAS_PYARROW:
            table = pa.Table.from_pylist(records)
            pq.write_table(table, str(filepath), compression=self._compression)
        else:
            jsonl_path = filepath.with_suffix(".jsonl")
            with open(jsonl_path, "a", encoding="utf-8") as f:
                for record in records:
                    f.write(json.dumps(record, default=str, ensure_ascii=False) + "\n")

    async def flush_all(self) -> None:
        """刷新所有缓冲区"""
        for buffer_key in list(self._buffers.keys()):
            await self._flush(buffer_key)

    async def replay(
        self, table: str, start: datetime, end: datetime, source: str = "default"
    ) -> list[dict[str, Any]]:
        """重放指定时间范围的数据。"""
        buffer_key = f"{source}/{table}"
        base = self._base_path / buffer_key
        if not base.exists():
            return []

        results: list[dict[str, Any]] = []
        for f in sorted(base.rglob("*")):
            if not f.is_file():
                continue
            if f.suffix == ".jsonl":
                with open(f, encoding="utf-8") as fh:
                    for line in fh:
                        if line.strip():
                            results.append(json.loads(line))
            elif f.suffix == ".parquet" and HAS_PYARROW:
                pf = pq.read_table(str(f))
                for row in pf.to_pylist():
                    results.append(row)

        # 按时间过滤
        filtered = []
        for r in results:
            ts = r.get("timestamp", r.get("ts", 0))
            if isinstance(ts, (int, float)):
                dt = datetime.fromtimestamp(ts / 1e9 if ts > 1e18 else ts, tz=UTC)
            else:
                dt = datetime.now(UTC)
            if start <= dt <= end:
                filtered.append(r)
        return filtered
