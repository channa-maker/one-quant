"""tick/L2 数据采集器 — 订阅 EventBus 行情通道并落盘"""

import asyncio
import time
from typing import Any

from one_quant.data.bronze import BronzeStorage
from one_quant.data.collector import DataCollector
from one_quant.data.quality import DataQualityGate
from one_quant.infra.event_bus import EventBus


class TickCollector(DataCollector):
    """tick/L2 数据采集器。

    订阅 EventBus 的 market.ticker / market.trade / market.orderbook 通道，
    经过质检门后原始数据直接落 Bronze 层。
    支持批量写入（每 100 条或每秒 flush 一次）。
    """

    def __init__(
        self,
        event_bus: EventBus,
        storage: BronzeStorage,
        quality_gate: DataQualityGate,
        batch_size: int = 100,
        flush_interval_sec: float = 1.0,
    ) -> None:
        super().__init__(event_bus)
        self._storage = storage
        self._quality_gate = quality_gate
        self._batch_size = batch_size
        self._flush_interval = flush_interval_sec
        self._buffer: list[dict[str, Any]] = []
        self._buffer_lock = asyncio.Lock()

    async def start_collecting(self) -> None:
        """开始采集 tick/L2 数据"""
        self._running = True

        # 订阅各通道
        self._event_bus.subscribe("market.ticker", self._on_ticker)
        self._event_bus.subscribe("market.trade", self._on_trade)
        self._event_bus.subscribe("market.orderbook", self._on_orderbook)

        # 启动定时 flush
        asyncio.create_task(self._periodic_flush())

    async def _on_ticker(self, data: dict[str, Any]) -> None:
        """处理 ticker 数据"""
        await self._process("ticker", data)

    async def _on_trade(self, data: dict[str, Any]) -> None:
        """处理逐笔成交数据"""
        await self._process("trade", data)

    async def _on_orderbook(self, data: dict[str, Any]) -> None:
        """处理盘口 L2 数据"""
        await self._process("orderbook", data)

    async def _process(self, table: str, data: dict[str, Any]) -> None:
        """通用处理流程：质检 → 缓冲 → 批量写入"""
        if not self._running:
            return

        # 质检门
        passed, reason = self._quality_gate.check(data)
        if not passed:
            self._error_count += 1
            return

        # 去重
        if self._quality_gate.is_duplicate(data):
            return

        async with self._buffer_lock:
            self._buffer.append({"table": table, "data": data, "ingested_at": time.time_ns()})
            self._collected_count += 1

            # 批量 flush
            if len(self._buffer) >= self._batch_size:
                await self._flush()

    async def _flush(self) -> None:
        """将缓冲区数据写入 Bronze 层"""
        if not self._buffer:
            return
        batch = self._buffer.copy()
        self._buffer.clear()

        # 按 table 分组写入
        by_table: dict[str, list] = {}
        for item in batch:
            table = item["table"]
            if table not in by_table:
                by_table[table] = []
            by_table[table].append(item["data"])

        for table, records in by_table.items():
            await self._storage.append(table, records)

    async def _periodic_flush(self) -> None:
        """定时 flush"""
        while self._running:
            await asyncio.sleep(self._flush_interval)
            async with self._buffer_lock:
                await self._flush()
