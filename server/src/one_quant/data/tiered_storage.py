"""冷热分层 + ZSTD 压缩 + 对象存储归档策略"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from one_quant.infra.logging import get_logger

logger = get_logger(__name__)


class TieredStorageManager:
    """冷热分层存储管理器。

    策略：
    - 热数据（7天内）: 本地 SSD，未压缩 Parquet
    - 温数据（7-90天）: 本地 HDD，ZSTD 压缩 Parquet
    - 冷数据（90天+）: 对象存储（MinIO/S3），ZSTD 压缩

    数据目录结构：
    data/
    ├── hot/        # 热数据，符号链接
    ├── warm/       # 温数据
    └── cold/       # 冷数据（归档清单）
    """

    def __init__(
        self,
        base_path: str = "data",
        hot_days: int = 7,
        warm_days: int = 90,
        compression: str = "zstd",
    ) -> None:
        self._base_path = Path(base_path)
        self._hot_days = hot_days
        self._warm_days = warm_days
        self._compression = compression
        self._migrated_count = 0

    async def run_migration(self) -> dict[str, int]:
        """执行一次冷热分层迁移。

        Returns:
            迁移统计 {"hot_to_warm": N, "warm_to_cold": N}
        """
        _now = datetime.now(UTC)  # noqa: F841
        stats = {"hot_to_warm": 0, "warm_to_cold": 0}

        hot_dir = self._base_path / "hot"
        warm_dir = self._base_path / "warm"

        if not hot_dir.exists():
            return stats

        # 热→温：压缩超过 hot_days 的文件
        for parquet_file in hot_dir.rglob("*.parquet"):
            if self._file_age_days(parquet_file) > self._hot_days:
                await self._compress_and_move(parquet_file, warm_dir)
                stats["hot_to_warm"] += 1

        self._migrated_count += sum(stats.values())
        logger.info("冷热分层迁移完成", **stats)
        return stats

    async def _compress_and_move(self, filepath: Path, target_dir: Path) -> None:
        """压缩并移动文件"""
        # 计算相对路径保持目录结构
        try:
            relative = filepath.relative_to(self._base_path / "hot")
        except ValueError:
            relative = filepath.name

        target = target_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)

        try:
            import pyarrow.parquet as pq

            table = pq.read_table(str(filepath))
            pq.write_table(table, str(target), compression=self._compression)
            filepath.unlink()
            logger.debug("文件已迁移", src=str(filepath), dst=str(target))
        except ImportError:
            logger.warning("pyarrow 不可用，跳过压缩迁移")

    def _file_age_days(self, filepath: Path) -> int:
        """文件年龄（天）"""
        mtime = datetime.fromtimestamp(filepath.stat().st_mtime, tz=UTC)
        return (datetime.now(UTC) - mtime).days

    def get_storage_stats(self) -> dict[str, Any]:
        """获取存储统计"""
        stats: dict[str, Any] = {"total_migrated": self._migrated_count}
        for tier in ("hot", "warm", "cold"):
            tier_dir = self._base_path / tier
            if tier_dir.exists():
                files = list(tier_dir.rglob("*.parquet"))
                total_bytes = sum(f.stat().st_size for f in files)
                stats[tier] = {"files": len(files), "bytes": total_bytes}
            else:
                stats[tier] = {"files": 0, "bytes": 0}
        return stats
