"""Redis Streams 持久化 — 订单/成交/风控消息不丢可重放"""

from __future__ import annotations

import json
import time
from typing import Any

from one_quant.infra.logging import get_logger

logger = get_logger(__name__)


class StreamPersistence:
    """基于 Redis Streams 的关键通道持久化。

    对以下通道的消息追加写入 Redis Stream，保证：
    - 不丢（XADD，消费者崩溃后可从 last_id 重放）
    - 可重放（任意时间点回放）
    - 有上限（MAXLEN 自动裁剪，防内存溢出）

    持久化通道：
    - order.*     — 订单状态变更
    - fill.*      — 成交回报
    - risk.*      — 风控决策
    """

    # 需要持久化的通道前缀
    PERSIST_PREFIXES: tuple[str, ...] = ("order", "fill", "risk")

    # 每个 Stream 最大长度（近似裁剪）
    MAXLEN: int = 1_000_000

    def __init__(self, redis_url: str = "redis://localhost:6379/0") -> None:
        self._redis_url = redis_url
        self._redis: Any = None
        self._enabled = False

    async def connect(self) -> None:
        """连接 Redis"""
        try:
            import redis.asyncio as aioredis

            self._redis = aioredis.from_url(
                self._redis_url,
                decode_responses=True,
                socket_connect_timeout=5,
            )
            await self._redis.ping()
            self._enabled = True
            logger.info("Redis Streams 持久化已连接", url=self._redis_url)
        except Exception:
            logger.warning("Redis Streams 持久化不可用，将跳过持久化")
            self._enabled = False

    async def disconnect(self) -> None:
        """断开连接"""
        if self._redis is not None:
            await self._redis.close()
            self._redis = None
        self._enabled = False

    def _should_persist(self, channel: str) -> bool:
        """判断通道是否需要持久化"""
        return any(channel.startswith(prefix) for prefix in self.PERSIST_PREFIXES)

    async def persist(self, channel: str, data: dict[str, Any], trace_id: str = "") -> None:
        """将消息追加到对应的 Redis Stream。

        Args:
            channel: EventBus 通道名（如 "order.update", "fill.executed"）
            data: 业务数据
            trace_id: 全链路追踪 ID
        """
        if not self._enabled or not self._should_persist(channel):
            return

        try:
            stream_key = f"stream:{channel}"
            entry = {
                "data": json.dumps(data, default=str, ensure_ascii=False),
                "trace_id": trace_id,
                "persisted_at": str(time.time_ns()),
            }
            await self._redis.xadd(
                stream_key,
                entry,
                maxlen=self.MAXLEN,
                approximate=True,
            )
        except Exception:
            logger.exception("Redis Stream 写入失败", channel=channel)

    async def replay(
        self,
        channel: str,
        start_id: str = "0",
        end_id: str = "+",
        count: int = 1000,
    ) -> list[dict[str, Any]]:
        """从 Redis Stream 回放消息。

        Args:
            channel: 通道名
            start_id: 起始 ID（"0" 从头开始，具体 ID 如 "1700000000000-0"）
            end_id: 结束 ID（"+" 表示最新）
            count: 单次最多读取条数

        Returns:
            消息列表
        """
        if not self._enabled:
            return []

        try:
            stream_key = f"stream:{channel}"
            entries = await self._redis.xrange(stream_key, min=start_id, max=end_id, count=count)
            results = []
            for entry_id, fields in entries:
                data = json.loads(fields.get("data", "{}"))
                data["_stream_id"] = entry_id
                data["_trace_id"] = fields.get("trace_id", "")
                results.append(data)
            return results
        except Exception:
            logger.exception("Redis Stream 回放失败", channel=channel)
            return []

    async def get_stream_info(self, channel: str) -> dict[str, Any]:
        """获取 Stream 信息（长度、首尾 ID 等）"""
        if not self._enabled:
            return {}

        try:
            stream_key = f"stream:{channel}"
            info = await self._redis.xinfo_stream(stream_key)
            return {
                "length": info.get("length", 0),
                "first_entry_id": info.get("first-entry", (None,))[0],
                "last_entry_id": info.get("last-entry", (None,))[0],
            }
        except Exception:
            return {}
