"""特征商店 — 离线(Parquet) + 在线(Redis) 双存储"""

import json
from pathlib import Path
from typing import Any

try:
    import pyarrow.parquet as pq

    HAS_PYARROW = True
except ImportError:
    HAS_PYARROW = False


class FeatureStore:
    """特征商店。

    离线训练与在线推理特征同源，杜绝训练-服务偏差。
    - 离线: Parquet 文件存储 (训练用)
    - 在线: Redis 存储 (推理用，毫秒取数)
    """

    def __init__(
        self,
        offline_path: str = "data/gold/features",
        redis_client: Any | None = None,
    ) -> None:
        self._offline_path = Path(offline_path)
        self._redis = redis_client
        self._offline_path.mkdir(parents=True, exist_ok=True)

    def save_offline(self, symbol: str, features: dict[str, Any], timestamp_ns: int) -> None:
        """保存特征到离线存储 (Parquet)。

        Args:
            symbol: 标的符号
            features: 特征字典
            timestamp_ns: 时间戳
        """
        record = {
            "symbol": symbol,
            "timestamp_ns": timestamp_ns,
            **features,
        }

        if HAS_PYARROW:
            filepath = self._offline_path / f"{symbol}_{timestamp_ns}.parquet"
            table = pq.Table.from_pylist([record])
            pq.write_table(table, str(filepath), compression="zstd")
        else:
            filepath = self._offline_path / f"{symbol}_{timestamp_ns}.json"
            filepath.write_text(json.dumps(record, default=str, ensure_ascii=False))

    async def save_online(self, symbol: str, features: dict[str, Any], ttl_sec: int = 3600) -> None:
        """保存特征到在线存储 (Redis)。

        Args:
            symbol: 标的符号
            features: 特征字典
            ttl_sec: 过期时间(秒)
        """
        if not self._redis:
            return

        key = f"features:{symbol}"
        await self._redis.setex(key, ttl_sec, json.dumps(features, default=str))

    async def get_online(self, symbol: str) -> dict[str, Any] | None:
        """从在线存储获取特征 (毫秒级)。

        Args:
            symbol: 标的符号

        Returns:
            特征字典，不存在返回 None
        """
        if not self._redis:
            return None

        key = f"features:{symbol}"
        data = await self._redis.get(key)
        if data:
            return json.loads(data)
        return None

    def get_offline(self, symbol: str, start_ns: int, end_ns: int) -> list[dict[str, Any]]:
        """从离线存储获取历史特征 (训练用)。

        Args:
            symbol: 标的符号
            start_ns: 开始时间戳
            end_ns: 结束时间戳

        Returns:
            特征记录列表
        """
        records = []
        for filepath in sorted(self._offline_path.glob(f"{symbol}_*.parquet")):
            if HAS_PYARROW:
                table = pq.read_table(str(filepath))
                for row in table.to_pylist():
                    ts = row.get("timestamp_ns", 0)
                    if start_ns <= ts <= end_ns:
                        records.append(row)
        return records

    async def ensure_consistency(self) -> bool:
        """校验离线/在线特征一致性。

        Returns:
            是否一致
        """
        # 骨架：实际实现需要对比最近 N 条特征的离线/在线版本
        return True
