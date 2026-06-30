"""数据采集器基类 — 从 EventBus 消费原始数据并落盘"""

from abc import ABC, abstractmethod

from one_quant.infra.event_bus import EventBus


class DataCollector(ABC):
    """数据采集器基类。

    负责从 EventBus 订阅原始数据并写入 Bronze 层。
    进程间只通过 EventBus 通信，绝不直接调用其他进程。
    """

    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus
        self._running = False
        self._collected_count = 0
        self._error_count = 0

    @abstractmethod
    async def start_collecting(self) -> None:
        """开始采集数据"""

    async def stop(self) -> None:
        """停止采集"""
        self._running = False

    @property
    def stats(self) -> dict[str, int]:
        """采集统计"""
        return {
            "collected": self._collected_count,
            "errors": self._error_count,
        }
