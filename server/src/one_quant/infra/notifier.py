"""通知器协议 — 统一告警推送接口"""

from __future__ import annotations

from typing import Any, Protocol


class Notifier(Protocol):
    """通知器协议。

    所有通知渠道（微信/钉钉/Telegram/邮件/短信）实现此协议。
    通过 @register_notifier 装饰器注册到全局注册表。

    Attributes:
        name: 通知器名称（如 "wechat", "dingtalk", "telegram"）
        enabled: 是否启用
    """

    name: str
    enabled: bool

    async def send(self, title: str, content: str, level: str = "info", **kwargs: Any) -> bool:
        """发送通知。

        Args:
            title: 通知标题
            content: 通知内容（支持 Markdown）
            level: 级别（info / warning / error / critical）
            **kwargs: 渠道特定参数

        Returns:
            是否发送成功
        """
        ...

    async def send_alert(self, alert: dict[str, Any]) -> bool:
        """发送结构化告警。

        Args:
            alert: 告警数据（含 title, message, severity, source, timestamp）

        Returns:
            是否发送成功
        """
        ...


class Panel(Protocol):
    """前端面板接口协议。

    定义前端可注册的面板类型，用于多屏盯盘工作站。

    Attributes:
        name: 面板名称（如 "dom_ladder", "footprint", "tape"）
        title: 中文标题
        category: 分类（行情 / 盘口 / 成交 / 策略 / 风控）
    """

    name: str
    title: str
    category: str

    def get_config_schema(self) -> dict[str, Any]:
        """返回面板配置 JSON Schema"""
        ...

    async def get_data(self, config: dict[str, Any]) -> dict[str, Any]:
        """获取面板数据

        Args:
            config: 面板配置

        Returns:
            面板渲染所需的数据
        """
        ...
