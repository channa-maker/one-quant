"""
ONE量化 - Tick 数据采集器

从 EventBus 订阅市场数据，写入 Bronze 层（Parquet 文件）。
只增不改，保证原始数据可重放。
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from one_quant.data.collector import DataCollector
from one_quant.infra.event_bus import EventBus

logger = logging.getLogger(__name__)


class TickCollector(DataCollector):
    """Tick 数据采集器。

    从 EventBus 订阅 market.* 通道，将原始数据追加写入 Parquet 文件。
    Bronze 层数据只增不改，保证任意时刻可从头重放。

    Attributes:
        output_dir: Bronze 层输出目录。
        batch_size: 批量写入阈值（条数）。
        flush_interval: 定期刷盘间隔（秒）。
    """

    def __init__(
        self,
        event_bus: EventBus,
        storage: Any | None = None,
        quality_gate: Any | None = None,
        output_dir: str = "data/bronze",
        batch_size: int = 1000,
        flush_interval: float = 10.0,
    ) -> None:
        """初始化 Tick 采集器。

        Args:
            event_bus: 事件总线实例。
            storage: BronzeStorage 实例（可选，优先使用）。
            quality_gate: DataQualityGate 实例（可选，启用质检）。
            output_dir: Bronze 层输出目录（storage 未提供时使用）。
            batch_size: 批量写入阈值。
            flush_interval: 定期刷盘间隔（秒）。
        """
        super().__init__(event_bus)
        self._storage = storage
        self._quality_gate = quality_gate
        self._output_dir = Path(output_dir)
        self._batch_size = batch_size
        self._flush_interval = flush_interval
        self._buffer: list[dict[str, Any]] = []
        self._flush_task: Any = None

    async def start_collecting(self) -> None:
        """开始采集数据。"""
        self._running = True

        # 确保输出目录存在
        self._output_dir.mkdir(parents=True, exist_ok=True)

        # 订阅市场数据通道
        self._event_bus.subscribe("market.ticker", self._on_data)
        self._event_bus.subscribe("market.kline", self._on_data)
        self._event_bus.subscribe("market.orderbook", self._on_data)
        self._event_bus.subscribe("market.trade", self._on_data)

        # 启动定期刷盘任务
        import asyncio

        self._flush_task = asyncio.create_task(self._periodic_flush(), name="tick-collector-flush")

        logger.info("Tick 采集器已启动，输出目录: %s", self._output_dir)

    async def stop(self) -> None:
        """停止采集并刷盘。"""
        self._running = False
        if self._flush_task is not None:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except Exception:
                pass
        await self._flush_buffer()
        logger.info(
            "Tick 采集器已停止，共采集 %d 条，错误 %d 条",
            self._collected_count,
            self._error_count,
        )

    async def _on_data(self, data: dict[str, Any]) -> None:
        """处理市场数据。经质检门后进入缓冲区。"""
        try:
            # 质检
            if self._quality_gate is not None:
                symbol = data.get("symbol", "unknown")
                timestamp_ns = data.get("timestamp_ns", data.get("ts", 0))
                price = data.get("price")
                record_id = data.get("id")

                from decimal import Decimal

                price_dec = Decimal(str(price)) if price is not None else None
                passed, warnings = self._quality_gate.check(
                    symbol=symbol,
                    timestamp_ns=int(timestamp_ns),
                    price=price_dec,
                    record_id=record_id,
                )
                if not passed:
                    logger.debug("数据未通过质检: %s %s", symbol, warnings)
                    return
                if warnings:
                    logger.warning("质检警告: %s %s", symbol, warnings)

            self._buffer.append(data)
            self._collected_count += 1

            if len(self._buffer) >= self._batch_size:
                await self._flush_buffer()
        except Exception:
            self._error_count += 1
            logger.exception("处理市场数据异常")

    async def _flush_buffer(self) -> None:
        """将缓冲区数据写入 BronzeStorage 或文件。"""
        if not self._buffer:
            return

        try:
            records = list(self._buffer)
            self._buffer.clear()

            if self._storage is not None:
                # 优先使用 BronzeStorage
                await self._storage.append("tick", records)
                logger.debug("刷盘 %d 条到 BronzeStorage", len(records))
            else:
                # 回退到文件写入
                date_str = time.strftime("%Y-%m-%d")
                hour_str = time.strftime("%H")
                file_path = self._output_dir / f"tick_{date_str}_{hour_str}.jsonl"

                with open(file_path, "a", encoding="utf-8") as f:
                    for record in records:
                        f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

                logger.debug("刷盘 %d 条到 %s", len(records), file_path)

        except Exception:
            self._error_count += 1
            logger.exception("刷盘异常")

    async def _periodic_flush(self) -> None:
        """定期刷盘循环。"""
        import asyncio

        while self._running:
            try:
                await asyncio.sleep(self._flush_interval)
                await self._flush_buffer()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("定期刷盘异常")
