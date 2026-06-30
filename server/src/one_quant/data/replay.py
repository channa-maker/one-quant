"""tick 级历史回放接口 — 任意时段数据回放，与实时同序"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Awaitable, Callable
from datetime import datetime
from typing import Any

from one_quant.data.bronze import BronzeStorage
from one_quant.data.silver import SilverProcessor
from one_quant.infra.event_bus import EventBus
from one_quant.infra.logging import get_logger

logger = get_logger(__name__)

# 回放事件处理器签名
ReplayHandler = Callable[[dict[str, Any]], Awaitable[None]]


class TickReplayer:
    """tick 级历史数据回放器。

    从 Bronze 层读取原始数据，经 Silver 清洗后，
    按原始时序回放到 EventBus，用于：
    - 回测引擎的 tick 级回放
    - 故障重现与调试
    - 数据一致性校验

    支持：
    - 任意时段回放
    - 可控速率（实时 / 加速 / 全速）
    - 与实时数据同序（EventBus 统一通道）
    """

    def __init__(
        self,
        bronze_storage: BronzeStorage,
        event_bus: EventBus,
        silver_processor: SilverProcessor | None = None,
    ) -> None:
        self._bronze = bronze_storage
        self._event_bus = event_bus
        self._silver = silver_processor or SilverProcessor()
        self._replay_count = 0
        self._running = False

    async def replay(
        self,
        table: str,
        start_time: datetime,
        end_time: datetime,
        source: str = "default",
        speed: float = 1.0,
        handler: ReplayHandler | None = None,
    ) -> int:
        """回放指定时段的历史数据。

        Args:
            table: 数据表名（ticker / trade / orderbook）
            start_time: 开始时间
            end_time: 结束时间
            source: 数据源标识
            speed: 回放速率（1.0=实时, 2.0=2倍速, 0=全速）
            handler: 可选的自定义处理器，不经过 EventBus

        Returns:
            回放的记录数
        """
        self._running = True
        self._replay_count = 0

        logger.info(
            "开始回放",
            table=table,
            start=start_time.isoformat(),
            end=end_time.isoformat(),
            speed=speed,
        )

        # 从 Bronze 读取原始数据
        raw_records = await self._bronze.replay(table, start_time, end_time, source)

        if not raw_records:
            logger.info("无数据可回放", table=table)
            return 0

        # Silver 清洗
        cleaned = self._silver.process_batch(raw_records)

        logger.info(
            "数据已加载",
            raw_count=len(raw_records),
            cleaned_count=len(cleaned),
        )

        # 按时间戳排序
        cleaned.sort(key=lambda r: r.get("timestamp_ns", 0))

        prev_ts = 0
        for record in cleaned:
            if not self._running:
                break

            # 速率控制
            if speed > 0 and prev_ts > 0:
                ts_diff_ns = record.get("timestamp_ns", 0) - prev_ts
                if ts_diff_ns > 0:
                    sleep_sec = (ts_diff_ns / 1e9) / speed
                    await asyncio.sleep(min(sleep_sec, 60))  # 最大等 60 秒

            prev_ts = record.get("timestamp_ns", 0)

            # 分发
            if handler:
                await handler(record)
            else:
                channel = f"market.{table}"
                await self._event_bus.publish(channel, record)

            self._replay_count += 1

        logger.info("回放完成", count=self._replay_count, table=table)
        return self._replay_count

    async def replay_stream(
        self,
        table: str,
        start_time: datetime,
        end_time: datetime,
        source: str = "default",
        speed: float = 1.0,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """流式回放（逐条 yield），适用于回测引擎逐事件消费。

        Args:
            table: 数据表名
            start_time: 开始时间
            end_time: 结束时间
            source: 数据源标识
            speed: 回放速率

        Yields:
            清洗后的数据记录
        """
        raw_records = await self._bronze.replay(table, start_time, end_time, source)
        cleaned = self._silver.process_batch(raw_records)
        cleaned.sort(key=lambda r: r.get("timestamp_ns", 0))

        prev_ts = 0
        for record in cleaned:
            if speed > 0 and prev_ts > 0:
                ts_diff_ns = record.get("timestamp_ns", 0) - prev_ts
                if ts_diff_ns > 0:
                    sleep_sec = (ts_diff_ns / 1e9) / speed
                    await asyncio.sleep(min(sleep_sec, 60))

            prev_ts = record.get("timestamp_ns", 0)
            yield record

    def stop(self) -> None:
        """停止回放"""
        self._running = False

    @property
    def stats(self) -> dict[str, int]:
        return {"replayed": self._replay_count}
