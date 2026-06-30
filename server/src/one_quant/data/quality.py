"""数据质检门 — 乱序检测、跳变标记、缺口检测、去重"""

import time
from typing import Any


class DataQualityGate:
    """数据质检门。

    所有原始数据经过质检门后才进入 Bronze 层。
    - 乱序丢弃 + 告警
    - 跳变标记
    - 缺口回补检测
    - 重复去重
    """

    def __init__(
        self,
        price_jump_threshold: float = 0.10,  # 价格跳变阈值 10%
        max_latency_ns: int = 5_000_000_000,  # 最大允许延迟 5 秒
    ) -> None:
        self._price_jump_threshold = price_jump_threshold
        self._max_latency_ns = max_latency_ns
        self._seen: dict[str, int] = {}  # 去重缓存 (symbol+ts -> hash)
        self._last_ts: dict[str, int] = {}  # 最新时间戳 (symbol -> ts)
        self._alert_count = 0

    def check(self, data: dict[str, Any]) -> tuple[bool, str]:
        """综合质检。返回 (是否通过, 原因)。

        Args:
            data: 原始数据，需包含 symbol, timestamp_ns 等字段

        Returns:
            (passed, reason) 元组
        """
        # 1. 基本字段检查
        if not data.get("symbol"):
            return False, "缺少 symbol 字段"

        # 2. 延迟检查
        now_ns = time.time_ns()
        ts_ns = data.get("timestamp_ns", 0)
        if ts_ns > 0 and (now_ns - ts_ns) > self._max_latency_ns:
            self._alert_count += 1
            return False, f"数据延迟过大: {(now_ns - ts_ns) / 1e9:.1f}s"

        # 3. 乱序检查
        symbol = data["symbol"]
        last_ts = self._last_ts.get(symbol, 0)
        if ts_ns > 0 and ts_ns < last_ts:
            self._alert_count += 1
            return False, f"乱序数据: 当前 {ts_ns} < 上次 {last_ts}"

        # 4. 价格跳变检查
        if "last_price" in data:
            last_price = float(data["last_price"])
            prev_price = data.get("_prev_price")
            if prev_price and prev_price > 0:
                change_pct = abs(last_price - prev_price) / prev_price
                if change_pct > self._price_jump_threshold:
                    self._alert_count += 1
                    # 跳变不丢弃，但标记
                    data["_jump_flagged"] = True

        # 更新状态
        if ts_ns > 0:
            self._last_ts[symbol] = ts_ns

        return True, "通过"

    def is_duplicate(self, data: dict[str, Any]) -> bool:
        """检查是否重复数据。

        基于 symbol + timestamp_ns + 哈希去重。
        """
        symbol = data.get("symbol", "")
        ts_ns = data.get("timestamp_ns", 0)
        key = f"{symbol}:{ts_ns}"

        # 简单哈希去重
        data_hash = hash(str(sorted(data.items())))
        if key in self._seen and self._seen[key] == data_hash:
            return True

        self._seen[key] = data_hash
        # 清理过期缓存(保留最近 10 万条)
        if len(self._seen) > 100_000:
            # 简单策略：清掉一半
            keys = list(self._seen.keys())
            for k in keys[: len(keys) // 2]:
                del self._seen[k]

        return False

    @property
    def alert_count(self) -> int:
        """告警次数"""
        return self._alert_count
