"""
ONE量化 - 数据质检门

对原始数据进行质量检查：乱序丢弃+告警、跳变标记、缺口检测、去重。
不合格数据被拦截并记录，不进入 Silver 层。
"""

from __future__ import annotations

import logging
from decimal import Decimal

logger = logging.getLogger(__name__)


class DataQualityGate:
    """数据质检门。

    检查项：
    1. 时间戳单调递增（乱序丢弃+告警）。
    2. 价格跳变检测（相对前值变化超过阈值）。
    3. 缺口检测（连续数据中断）。
    4. 重复数据过滤。

    Attributes:
        max_price_jump_pct: 价格跳变阈值（百分比）。
        max_gap_seconds: 最大允许缺口（秒）。
    """

    def __init__(
        self,
        max_price_jump_pct: float = 10.0,
        max_gap_seconds: float = 60.0,
    ) -> None:
        """初始化质检门。

        Args:
            max_price_jump_pct: 价格跳变阈值（百分比）。
            max_gap_seconds: 最大允许缺口（秒）。
        """
        self.max_price_jump_pct = max_price_jump_pct
        self.max_gap_seconds = max_gap_seconds

        # 每个 symbol 的最后一条记录
        self._last_timestamp: dict[str, int] = {}
        self._last_price: dict[str, Decimal] = {}
        self._seen_ids: dict[str, set[str]] = {}

        # 统计
        self._total_checked = 0
        self._total_rejected = 0
        self._total_warnings = 0

    def check(
        self,
        symbol: str,
        timestamp_ns: int,
        price: Decimal | None = None,
        record_id: str | None = None,
    ) -> tuple[bool, list[str]]:
        """执行质检。

        Args:
            symbol: 标的符号。
            timestamp_ns: 时间戳（纳秒）。
            price: 价格（可选）。
            record_id: 记录唯一 ID（可选，用于去重）。

        Returns:
            (是否通过, 警告消息列表)。
        """
        self._total_checked += 1
        warnings: list[str] = []
        passed = True

        # 1. 去重检查
        if record_id is not None:
            if symbol not in self._seen_ids:
                self._seen_ids[symbol] = set()
            if record_id in self._seen_ids[symbol]:
                self._total_rejected += 1
                return False, ["重复记录"]
            self._seen_ids[symbol].add(record_id)
            # 限制内存：只保留最近 10000 个 ID
            if len(self._seen_ids[symbol]) > 10000:
                ids = self._seen_ids[symbol]
                self._seen_ids[symbol] = set(list(ids)[-5000:])

        # 2. 时间戳单调性检查
        last_ts = self._last_timestamp.get(symbol)
        if last_ts is not None and timestamp_ns < last_ts:
            self._total_rejected += 1
            return False, [f"时间戳乱序: {timestamp_ns} < {last_ts}"]
        self._last_timestamp[symbol] = timestamp_ns

        # 3. 价格跳变检查
        if price is not None:
            last_price = self._last_price.get(symbol)
            if last_price is not None and last_price > 0:
                jump_pct = abs(price - last_price) / last_price * 100
                if jump_pct > self.max_price_jump_pct:
                    warnings.append(f"价格跳变: {last_price} → {price} ({jump_pct:.2f}%)")
                    self._total_warnings += 1
            self._last_price[symbol] = price

        # 4. 缺口检测
        if last_ts is not None:
            gap_seconds = (timestamp_ns - last_ts) / 1_000_000_000
            if gap_seconds > self.max_gap_seconds:
                warnings.append(f"数据缺口: {gap_seconds:.1f}s (阈值 {self.max_gap_seconds}s)")
                self._total_warnings += 1

        return passed, warnings

    @property
    def stats(self) -> dict[str, int]:
        """质检统计。"""
        return {
            "total_checked": self._total_checked,
            "total_rejected": self._total_rejected,
            "total_warnings": self._total_warnings,
        }
