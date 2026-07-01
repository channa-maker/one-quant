"""
ONE量化 - 历史数据加载器

支持 Parquet / CSV / JSONL 三种格式的历史行情数据加载。

核心功能：
  - 自动识别文件格式（按扩展名）
  - 按事件时间排序（timestamp_ns / timestamp / date）
  - 支持指定时间范围过滤（start / end）
  - 流式加载（逐批产出，控制内存）
  - 倍速回放（模拟实时或加速回放）

使用示例::

    loader = DataLoader("path/to/data.parquet")
    for batch in loader.stream(batch_size=1000):
        engine.feed(batch)

    # 指定时间范围 + 倍速回放
    loader = DataLoader("data.csv", start="2024-01-01", end="2024-06-30")
    for batch in loader.stream(batch_size=500, speed=10.0):
        engine.feed(batch)
"""

from __future__ import annotations

import csv
import json
import time
from collections.abc import Generator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from one_quant.infra.logging import get_logger

logger = get_logger(__name__)


class DataLoader:
    """历史数据加载器。

    支持 Parquet / CSV / JSONL 格式，自动按事件时间排序，
    支持时间范围过滤和倍速流式回放。

    Attributes:
        _file_path: 数据文件路径
        _start_ns: 起始时间戳（纳秒），None 表示不限
        _end_ns: 结束时间戳（纳秒），None 表示不限
        _sorted_cache: 排序后的数据缓存（首次加载后复用）
    """

    # ──────────────────── 时间字段优先级 ────────────────────
    # 按此顺序查找时间字段
    _TIME_FIELDS = ("timestamp_ns", "timestamp", "date", "datetime", "time")

    def __init__(
        self,
        file_path: str | Path,
        start: str | int | float | None = None,
        end: str | int | float | None = None,
    ) -> None:
        """初始化加载器。

        Args:
            file_path: 数据文件路径（支持 .parquet / .csv / .jsonl / .json）
            start: 起始时间。支持以下格式：
                   - 纳秒时间戳（int）
                   - 秒级时间戳（float，自动转纳秒）
                   - ISO 日期字符串，如 "2024-01-01" 或 "2024-01-01T00:00:00"
                   - None 表示不限制
            end: 结束时间，格式同 start
        """
        self._file_path = Path(file_path)
        if not self._file_path.exists():
            raise FileNotFoundError(f"数据文件不存在: {self._file_path}")

        # 解析时间范围（统一转为纳秒时间戳或 None）
        self._start_ns = self._parse_time(start)
        self._end_ns = self._parse_time(end)
        self._sorted_cache: list[dict[str, Any]] | None = None

        logger.info(
            "数据加载器初始化: file=%s, start=%s, end=%s",
            self._file_path.name,
            self._ns_to_iso(self._start_ns) if self._start_ns else "不限",
            self._ns_to_iso(self._end_ns) if self._end_ns else "不限",
        )

    # ──────────────────── 公开接口 ────────────────────

    def load_all(self) -> list[dict[str, Any]]:
        """加载全部数据（已排序、已过滤时间范围）。

        首次调用后会缓存结果，后续调用直接返回缓存。

        Returns:
            按事件时间升序排列的行情数据列表
        """
        if self._sorted_cache is not None:
            return self._sorted_cache

        # 根据文件格式加载
        suffix = self._file_path.suffix.lower()
        if suffix == ".parquet":
            self._load_parquet()
        elif suffix == ".csv":
            rows = self._load_csv()
        elif suffix in (".jsonl", ".json"):
            rows = self._load_jsonl()
        else:
            raise ValueError(f"不支持的文件格式: {suffix}（仅支持 .parquet / .csv / .jsonl）")

        logger.info("原始数据加载完成，共 %d 条", len(rows))

        # 过滤时间范围
        rows = self._filter_by_time(rows)
        logger.info("时间范围过滤后，剩余 %d 条", len(rows))

        # 按事件时间排序
        rows = self._sort_by_time(rows)
        logger.info("数据排序完成")

        self._sorted_cache = rows
        return rows

    def stream(
        self,
        batch_size: int = 1000,
        speed: float = 0.0,
    ) -> Generator[list[dict[str, Any]], None, None]:
        """流式加载数据（逐批产出）。

        支持倍速回放：
          - speed = 0：不等待，尽快产出（默认，适合快速回测）
          - speed = 1.0：按原始时间间隔实时回放
          - speed = 10.0：10 倍速回放（等待时间为原始间隔的 1/10）

        Args:
            batch_size: 每批数据条数
            speed: 回放倍速。0 表示不等待，> 0 表示倍速回放。

        Yields:
            一批行情数据（list[dict]），按时间升序排列。
        """
        all_data = self.load_all()
        total = len(all_data)

        if total == 0:
            logger.warning("无数据可回放")
            return

        logger.info(
            "开始流式回放: 总数据 %d 条, 批大小 %d, 倍速 %s",
            total,
            batch_size,
            f"{speed}x" if speed > 0 else "尽快",
        )

        last_ts_ns: int | None = None

        for i in range(0, total, batch_size):
            batch = all_data[i : i + batch_size]

            # 倍速回放：根据时间间隔等待
            if speed > 0 and batch:
                first_ts = self._extract_timestamp(batch[0])
                if first_ts is not None and last_ts_ns is not None:
                    # 计算与上一批的时间间隔
                    interval_ns = first_ts - last_ts_ns
                    if interval_ns > 0:
                        # 等待时间 = 间隔 / 倍速（秒）
                        wait_sec = interval_ns / (speed * 1_000_000_000)
                        # 限制最大等待时间，避免极端情况
                        wait_sec = min(wait_sec, 5.0)
                        if wait_sec > 0.001:
                            time.sleep(wait_sec)

                # 更新上一批最后一条的时间戳
                last_ts_in_batch = self._extract_timestamp(batch[-1])
                if last_ts_in_batch is not None:
                    last_ts_ns = last_ts_in_batch

            progress = min(i + batch_size, total)
            logger.debug("回放进度: %d / %d", progress, total)
            yield batch

        logger.info("流式回放完成")

    @property
    def data_range(self) -> tuple[str | None, str | None]:
        """获取当前数据的时间范围（ISO 格式）。

        Returns:
            (起始时间, 结束时间)，可能为 None
        """
        return (
            self._ns_to_iso(self._start_ns),
            self._ns_to_iso(self._end_ns),
        )

    @property
    def record_count(self) -> int:
        """获取当前数据记录总数（触发加载）。"""
        return len(self.load_all())

    # ──────────────────── 格式加载 ────────────────────

    def _load_parquet(self) -> list[dict[str, Any]]:
        """加载 Parquet 文件。

        使用 pyarrow 或 pandas 读取，转换为 dict 列表。

        Returns:
            行情数据列表
        """
        try:
            import pyarrow.parquet as pq

            table = pq.read_table(str(self._file_path))
            rows: list[dict[str, Any]] = table.to_pylist()
            logger.info("Parquet 加载完成: %d 条, 列: %s", len(rows), table.column_names)
            return rows
        except ImportError:
            pass

        # 回退到 pandas
        try:
            import pandas as pd

            df = pd.read_parquet(str(self._file_path))
            df.to_dict(orient="records")
            logger.info("Parquet(pandas) 加载完成: %d 条, 列: %s", len(rows), list(df.columns))
            return rows
        except ImportError:
            raise ImportError(
                "加载 Parquet 需要 pyarrow 或 pandas，请安装: "
                "pip install pyarrow  或  pip install pandas"
            )

    def _load_csv(self) -> list[dict[str, Any]]:
        """加载 CSV 文件。

        自动检测编码和分隔符，支持大文件。

        Returns:
            行情数据列表
        """
        rows: list[dict[str, Any]] = []
        file_path = str(self._file_path)

        # 尝试常见编码
        for encoding in ("utf-8", "utf-8-sig", "gbk", "latin-1"):
            try:
                with open(file_path, encoding=encoding, newline="") as f:
                    # 读取前几行检测分隔符
                    sample = f.read(8192)
                    f.seek(0)

                    # 自动检测分隔符
                    sniffer = csv.Sniffer()
                    try:
                        dialect = sniffer.sniff(sample, delimiters=",;\t|")
                    except csv.Error:
                        dialect = csv.excel  # 默认逗号分隔

                    reader = csv.DictReader(f, dialect=dialect)
                    for row in reader:
                        # 尝试将数值字段转换为数字
                        rows.append(self._convert_row_types(row))

                logger.info("CSV 加载完成: %d 条, 编码: %s", len(rows), encoding)
                return rows
            except UnicodeDecodeError:
                continue

        raise ValueError(f"CSV 文件编码检测失败: {file_path}")

    def _load_jsonl(self) -> list[dict[str, Any]]:
        """加载 JSONL（JSON Lines）文件。

        每行一个 JSON 对象。也支持单个 JSON 数组格式。

        Returns:
            行情数据列表
        """
        rows: list[dict[str, Any]] = []
        content = self._file_path.read_text(encoding="utf-8")

        # 先尝试整体解析为 JSON 数组
        stripped = content.strip()
        if stripped.startswith("["):
            try:
                data = json.loads(stripped)
                if isinstance(data, list):
                    logger.info("JSON 数组加载完成: %d 条", len(data))
                    return data
            except json.JSONDecodeError:
                pass

        # 逐行解析 JSONL
        for line_no, line in enumerate(content.splitlines(), start=1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as e:
                logger.warning("JSONL 第 %d 行解析失败，已跳过: %s", line_no, e)

        logger.info("JSONL 加载完成: %d 条", len(rows))
        return rows

    # ──────────────────── 时间处理 ────────────────────

    @staticmethod
    def _parse_time(value: str | int | float | None) -> int | None:
        """将各种时间格式统一解析为纳秒时间戳。

        Args:
            value: 时间值，支持 str / int / float / None

        Returns:
            纳秒时间戳，或 None
        """
        if value is None:
            return None

        # 已经是整数 → 直接视为纳秒时间戳
        if isinstance(value, int):
            # 简单启发式：如果数值太小，可能是秒级时间戳
            if value < 1_000_000_000_000_000_000:
                return value * 1_000_000_000  # 秒 → 纳秒
            return value

        # 浮点数 → 秒级时间戳转纳秒
        if isinstance(value, float):
            return int(value * 1_000_000_000)

        # 字符串 → 尝试多种格式
        if isinstance(value, str):
            # 尝试纯数字时间戳
            try:
                ts = int(value)
                if ts < 1_000_000_000_000_000_000:
                    return ts * 1_000_000_000
                return ts
            except ValueError:
                pass

            # 尝试 ISO 格式
            for fmt in (
                "%Y-%m-%dT%H:%M:%S.%f%z",
                "%Y-%m-%dT%H:%M:%S%z",
                "%Y-%m-%dT%H:%M:%S.%f",
                "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d %H:%M:%S.%f",
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d",
            ):
                try:
                    dt = datetime.strptime(value, fmt)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=UTC)
                    return int(dt.timestamp() * 1_000_000_000)
                except ValueError:
                    continue

            # 最后尝试 dateutil
            try:
                from dateutil.parser import parse as du_parse

                dt = du_parse(value)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=UTC)
                return int(dt.timestamp() * 1_000_000_000)
            except (ImportError, ValueError):
                pass

        raise ValueError(f"无法解析时间: {value!r}")

    @staticmethod
    def _ns_to_iso(ns: int | None) -> str | None:
        """纳秒时间戳转 ISO 格式字符串。"""
        if ns is None:
            return None
        dt = datetime.fromtimestamp(ns / 1_000_000_000, tz=UTC)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

    def _extract_timestamp(self, row: dict[str, Any]) -> int | None:
        """从数据行中提取纳秒时间戳。

        按 _TIME_FIELDS 优先级查找。

        Args:
            row: 单条行情数据

        Returns:
            纳秒时间戳，或 None（找不到时间字段）
        """
        for field in self._TIME_FIELDS:
            if field in row:
                try:
                    return self._parse_time(row[field])
                except ValueError:
                    continue
        return None

    def _filter_by_time(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """按时间范围过滤数据。

        Args:
            rows: 原始数据列表

        Returns:
            过滤后的数据列表
        """
        if self._start_ns is None and self._end_ns is None:
            return rows

        filtered: list[dict[str, Any]] = []
        skipped = 0

        for row in rows:
            ts = self._extract_timestamp(row)
            if ts is None:
                # 没有时间字段的数据保留
                filtered.append(row)
                continue

            if self._start_ns is not None and ts < self._start_ns:
                skipped += 1
                continue
            if self._end_ns is not None and ts > self._end_ns:
                skipped += 1
                continue

            filtered.append(row)

        if skipped > 0:
            logger.info("时间范围过滤: 跳过 %d 条（范围外）", skipped)

        return filtered

    def _sort_by_time(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """按事件时间升序排序。

        没有时间字段的数据排在最前面。

        Args:
            rows: 待排序数据

        Returns:
            排序后的数据列表（新列表，不修改原列表）
        """

        def sort_key(row: dict[str, Any]) -> int:
            ts = self._extract_timestamp(row)
            return ts if ts is not None else 0

        return sorted(rows, key=sort_key)

    # ──────────────────── 工具方法 ────────────────────

    @staticmethod
    def _convert_row_types(row: dict[str, Any]) -> dict[str, Any]:
        """尝试将 CSV 行中的数值字段转换为数字类型。

        Args:
            row: CSV 行字典

        Returns:
            类型转换后的字典
        """
        converted: dict[str, Any] = {}
        for key, value in row.items():
            if value is None or value == "":
                converted[key] = value
                continue

            # 尝试整数
            try:
                converted[key] = int(value)
                continue
            except (ValueError, TypeError):
                pass

            # 尝试浮点数
            try:
                converted[key] = float(value)
                continue
            except (ValueError, TypeError):
                pass

            # 保持原样
            converted[key] = value

        return converted


def load_and_merge(
    file_paths: list[str | Path],
    start: str | None = None,
    end: str | None = None,
) -> list[dict[str, Any]]:
    """加载多个数据文件并按时间合并排序。

    适用于多品种、多时段数据的合并回测场景。

    Args:
        file_paths: 数据文件路径列表
        start: 起始时间（可选）
        end: 结束时间（可选）

    Returns:
        合并后按事件时间升序排列的数据列表
    """
    all_data: list[dict[str, Any]] = []

    for fp in file_paths:
        loader = DataLoader(fp, start=start, end=end)
        all_data.extend(loader.load_all())
        logger.info("已加载: %s", Path(fp).name)

    # 按时间排序
    def sort_key(row: dict[str, Any]) -> int:
        for field in DataLoader._TIME_FIELDS:
            if field in row:
                try:
                    return DataLoader._parse_time(row[field]) or 0
                except ValueError:
                    continue
        return 0

    merged = sorted(all_data, key=sort_key)
    logger.info("多文件合并完成: %d 个文件, 共 %d 条数据", len(file_paths), len(merged))
    return merged
