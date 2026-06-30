"""
ONE量化 - 策略相关协议

定义因子、执行算法、数据源、AI 智能体、选股模型等可插拔组件的协议。
所有协议通过注册表管理，新组件只需实现协议 + 注册即可接入。
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class Factor(Protocol):
    """因子协议。

    因子是策略的基本构建块，接收行情数据输出数值。
    命名规范：{类别}_{名称}_{窗口}，如 rsi_14、ema_cross_fast。

    Attributes:
        name: 因子唯一名称。
    """

    name: str

    def compute(self, data: dict[str, Any]) -> float | None:
        """计算因子值。

        Args:
            data: 输入数据（K线、成交等）。

        Returns:
            因子值。NaN 或数据不足时返回 None。
        """
        ...


@runtime_checkable
class ExecutionAlgo(Protocol):
    """执行算法协议。

    将大单拆分为小单，控制市场冲击和滑点。

    Attributes:
        name: 算法名称（如 "twap", "vwap", "iceberg"）。
    """

    name: str

    async def execute(
        self,
        symbol: str,
        side: str,
        quantity: float,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """执行算法拆单。

        Args:
            symbol: 标的符号。
            side: 买卖方向。
            quantity: 总数量。

        Returns:
            拆单后的子订单列表。
        """
        ...


@runtime_checkable
class DataSource(Protocol):
    """数据源协议。

    提供历史行情、基本面等数据的统一接口。

    Attributes:
        name: 数据源名称。
    """

    name: str

    async def fetch_klines(
        self,
        symbol: str,
        interval: str,
        start: int,
        end: int,
    ) -> list[dict[str, Any]]:
        """获取历史K线。

        Args:
            symbol: 标的符号。
            interval: K线周期。
            start: 起始时间戳。
            end: 结束时间戳。

        Returns:
            K线数据列表。
        """
        ...


@runtime_checkable
class Agent(Protocol):
    """AI 智能体协议。

    每个智能体有明确职责，接收输入输出结构化结果。

    Attributes:
        name: 智能体名称（如 "briefer", "watcher", "sentiment"）。
    """

    name: str

    async def run(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """执行智能体任务。

        Args:
            input_data: 输入数据。

        Returns:
            结构化输出。
        """
        ...


@runtime_checkable
class ScreenerModel(Protocol):
    """选股选币模型协议。

    对标的池进行打分排序，输出候选池。

    Attributes:
        name: 模型名称。
    """

    name: str

    def score(self, features: dict[str, Any]) -> float:
        """对单个标的打分。

        Args:
            features: 特征数据。

        Returns:
            得分（0-100）。
        """
        ...


@runtime_checkable
class Notifier(Protocol):
    """告警通知协议。

    将告警消息推送到指定通道（企微/飞书/钉钉/邮件等）。

    Attributes:
        name: 通知器名称。
        channel: 推送渠道。
    """

    name: str
    channel: str

    async def send(self, title: str, body: str, level: str = "info") -> bool:
        """发送通知。

        Args:
            title: 通知标题。
            body: 通知正文。
            level: 告警级别（info/warning/error/critical）。

        Returns:
            是否发送成功。
        """
        ...
