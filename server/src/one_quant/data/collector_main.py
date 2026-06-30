"""one-collector 进程入口 — 全量数据采集落湖"""

import asyncio
import signal
import sys

from one_quant.data.bronze import BronzeStorage
from one_quant.data.quality import DataQualityGate
from one_quant.data.tick_collector import TickCollector
from one_quant.infra.event_bus import EventBus, RedisEventBus
from one_quant.infra.logging import get_logger

logger = get_logger("collector")


async def main() -> None:
    """one-collector 主循环。

    负责：
    1. 订阅 EventBus 行情通道
    2. 经过质检门
    3. 原始数据落 Bronze 层
    """
    from one_quant.infra.config import get_settings

    settings = get_settings()

    # 初始化组件
    event_bus = RedisEventBus(settings.redis.REDIS_URL)
    storage = BronzeStorage(base_path="data/bronze")
    quality_gate = DataQualityGate()
    collector = TickCollector(event_bus, storage, quality_gate)

    # 优雅关闭
    shutdown_event = asyncio.Event()

    def _shutdown_handler(sig: int, frame: object) -> None:
        logger.info("收到关闭信号，正在优雅退出...", signal=sig)
        shutdown_event.set()

    signal.signal(signal.SIGINT, _shutdown_handler)
    signal.signal(signal.SIGTERM, _shutdown_handler)

    # 启动
    await event_bus.start()
    await collector.start_collecting()
    logger.info("one-collector 已启动，开始采集数据")

    # 等待关闭信号
    await shutdown_event.wait()

    # 优雅关闭
    await collector.stop()
    await storage.flush_all()
    await event_bus.stop()
    logger.info("one-collector 已关闭", stats=collector.stats)


if __name__ == "__main__":
    asyncio.run(main())
