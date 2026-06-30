"""
ONE量化 - AI 智能体基类

所有智能体继承此基类，实现 run 方法。
智能体只产出建议/信号，永远绕不过风控。
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Any

from one_quant.infra.logging import get_logger

logger = get_logger(__name__)


class BaseAgent(ABC):
    """AI 智能体基类。

    每个智能体有明确职责，接收输入输出结构化结果。
    智能体只产出建议/信号，永远绕不过风控。

    Attributes:
        name: 智能体名称（如 "briefer", "watcher", "sentiment"）。
        description: 智能体职责描述。
    """

    name: str
    description: str

    def __init__(self) -> None:
        self._run_count = 0
        self._total_tokens = 0
        self._total_cost_usd = 0.0

    @abstractmethod
    async def run(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """执行智能体任务。

        Args:
            input_data: 输入数据，格式由具体智能体定义。

        Returns:
            结构化输出，格式由具体智能体定义。
        """
        ...

    async def safe_run(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """安全执行（带异常捕获和统计）。

        Args:
            input_data: 输入数据。

        Returns:
            智能体输出，异常时返回错误信息。
        """
        self._run_count += 1
        start = time.time()

        try:
            result = await self.run(input_data)
            elapsed = time.time() - start
            logger.info(
                "智能体 %s 执行完成，耗时 %.2fs",
                self.name,
                elapsed,
            )
            return result
        except Exception as exc:
            elapsed = time.time() - start
            logger.error(
                "智能体 %s 执行异常，耗时 %.2fs: %s",
                self.name,
                elapsed,
                exc,
            )
            return {
                "success": False,
                "error": str(exc),
                "agent": self.name,
            }

    @property
    def stats(self) -> dict[str, Any]:
        """统计信息。"""
        return {
            "name": self.name,
            "run_count": self._run_count,
            "total_tokens": self._total_tokens,
            "total_cost_usd": self._total_cost_usd,
        }
