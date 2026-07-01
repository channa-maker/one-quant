"""通知器协议 — 统一告警推送接口"""

from __future__ import annotations

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Protocol

import httpx

from one_quant.infra.logging import get_logger
from one_quant.infra.notification_channels import NotificationRouter

logger = get_logger(__name__)


# ── 通知器协议 ────────────────────────────────────────────


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


# ── 邮件通知器 ────────────────────────────────────────────


class EmailNotifier:
    """邮件通知器 — 通过 SMTP 发送邮件通知。

    支持 TLS 加密连接，适用于企业邮件通知场景。

    Attributes:
        name: 通知器名称
        enabled: 是否启用
    """

    name = "email"

    def __init__(
        self,
        smtp_host: str,
        smtp_port: int,
        username: str,
        password: str,
        recipients: list[str],
        sender: str = "",
        use_tls: bool = True,
        enabled: bool = True,
    ) -> None:
        """初始化邮件通知器。

        Args:
            smtp_host: SMTP 服务器地址
            smtp_port: SMTP 端口（通常 587/TLS 或 465/SSL）
            username: 登录用户名
            password: 登录密码
            recipients: 收件人邮箱列表
            sender: 发件人地址，默认同 username
            use_tls: 是否使用 TLS 加密
            enabled: 是否启用
        """
        self.enabled = enabled
        self._smtp_host = smtp_host
        self._smtp_port = smtp_port
        self._username = username
        self._password = password
        self._recipients = recipients
        self._sender = sender or username
        self._use_tls = use_tls

    async def send(self, title: str, content: str, level: str = "info", **kwargs: Any) -> bool:
        """通过 SMTP 发送邮件通知。

        Args:
            title: 邮件标题
            content: 邮件正文（支持 Markdown）
            level: 级别（info / warning / error / critical）
            **kwargs: 可选 recipients 覆盖默认收件人

        Returns:
            是否发送成功
        """
        if not self.enabled:
            logger.debug("邮件通知器已禁用，跳过发送")
            return False

        recipients = kwargs.get("recipients", self._recipients)

        # 级别前缀标记
        level_prefix = {
            "info": "[INFO]",
            "warning": "[⚠️ WARNING]",
            "error": "[❌ ERROR]",
            "critical": "[🚨 CRITICAL]",
        }
        subject = f"{level_prefix.get(level, '[INFO]')} {title}"

        # 构建邮件
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self._sender
        msg["To"] = ", ".join(recipients)

        # 纯文本正文
        msg.attach(MIMEText(content, "plain", "utf-8"))

        try:
            # smtplib 是同步库，在异步方法中通过 asyncio.to_thread 包装
            import asyncio

            def _send_sync() -> None:
                if self._use_tls:
                    server = smtplib.SMTP(self._smtp_host, self._smtp_port, timeout=30)
                    server.ehlo()
                    server.starttls()
                else:
                    server = smtplib.SMTP_SSL(self._smtp_host, self._smtp_port, timeout=30)

                server.login(self._username, self._password)
                server.sendmail(self._sender, recipients, msg.as_string())
                server.quit()

            await asyncio.to_thread(_send_sync)
            logger.info("邮件发送成功: title=%s recipients=%s", title, recipients)
            return True

        except smtplib.SMTPAuthenticationError as exc:
            logger.error("邮件认证失败: %s", exc)
            return False
        except smtplib.SMTPException as exc:
            logger.error("邮件发送失败: %s", exc)
            return False
        except Exception as exc:
            logger.error("邮件发送异常: %s", exc)
            return False

    async def send_alert(self, alert: dict[str, Any]) -> bool:
        """发送结构化告警为邮件。

        Args:
            alert: 告警数据（含 title, message, severity, source, timestamp）

        Returns:
            是否发送成功
        """
        title = alert.get("title", "系统告警")
        message = alert.get("message", "")
        severity = alert.get("severity", "info")
        source = alert.get("source", "unknown")
        timestamp = alert.get("timestamp", "")

        content = f"来源: {source}\n时间: {timestamp}\n级别: {severity}\n\n---\n\n{message}"

        # severity 映射到 level
        level_map = {"low": "info", "medium": "warning", "high": "error", "critical": "critical"}
        level = level_map.get(severity, "info")

        return await self.send(title=title, content=content, level=level)


# ── Webhook 通知器 ────────────────────────────────────────


class WebhookNotifier:
    """Webhook 通知器 — 通过 HTTP POST 推送通知。

    支持自定义 payload 格式，兼容钉钉/飞书/Slack/企业微信等
    Webhook 接口。

    Attributes:
        name: 通知器名称
        enabled: 是否启用
    """

    name = "webhook"

    def __init__(
        self,
        webhook_url: str,
        headers: dict[str, str] | None = None,
        timeout: float = 30.0,
        enabled: bool = True,
    ) -> None:
        """初始化 Webhook 通知器。

        Args:
            webhook_url: Webhook 推送地址
            headers: 自定义请求头（如鉴权 token）
            timeout: HTTP 超时（秒）
            enabled: 是否启用
        """
        self.enabled = enabled
        self._webhook_url = webhook_url
        self._headers = headers or {"Content-Type": "application/json"}
        self._timeout = timeout

    async def send(self, title: str, content: str, level: str = "info", **kwargs: Any) -> bool:
        """通过 HTTP POST 推送通知到 Webhook。

        默认发送 JSON payload: {"title": ..., "content": ..., "level": ...}
        可通过 kwargs["payload"] 传入自定义 payload 覆盖。

        Args:
            title: 通知标题
            content: 通知内容
            level: 级别（info / warning / error / critical）
            **kwargs: 可选 payload（自定义请求体）、extra_headers 等

        Returns:
            是否发送成功
        """
        if not self.enabled:
            logger.debug("Webhook 通知器已禁用，跳过发送")
            return False

        # 允许调用方传入自定义 payload
        payload = kwargs.get(
            "payload",
            {
                "title": title,
                "content": content,
                "level": level,
            },
        )

        headers = {**self._headers, **kwargs.get("extra_headers", {})}

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    self._webhook_url,
                    headers=headers,
                    json=payload,
                )

                if resp.status_code >= 400:
                    logger.error(
                        "Webhook 推送失败: status=%d body=%s",
                        resp.status_code,
                        resp.text[:500],
                    )
                    return False

                logger.info("Webhook 推送成功: title=%s url=%s", title, self._webhook_url)
                return True

        except httpx.TimeoutException:
            logger.error("Webhook 推送超时: url=%s timeout=%.1fs", self._webhook_url, self._timeout)
            return False
        except httpx.HTTPError as exc:
            logger.error("Webhook 推送 HTTP 错误: %s", exc)
            return False
        except Exception as exc:
            logger.error("Webhook 推送异常: %s", exc)
            return False

    async def send_alert(self, alert: dict[str, Any]) -> bool:
        """发送结构化告警到 Webhook。

        Args:
            alert: 告警数据（含 title, message, severity, source, timestamp）

        Returns:
            是否发送成功
        """
        title = alert.get("title", "系统告警")
        message = alert.get("message", "")
        severity = alert.get("severity", "info")
        source = alert.get("source", "unknown")
        _timestamp = alert.get("timestamp", "")  # noqa: F841

        level_map = {"low": "info", "medium": "warning", "high": "error", "critical": "critical"}
        level = level_map.get(severity, "info")

        content = f"[{source}] {message}"

        return await self.send(title=title, content=content, level=level)


# ── 控制台通知器 ──────────────────────────────────────────


class ConsoleNotifier:
    """控制台通知器 — 通过日志输出通知。

    用于开发/调试环境，将通知输出到控制台和日志系统。

    Attributes:
        name: 通知器名称
        enabled: 是否启用
    """

    name = "console"

    def __init__(self, enabled: bool = True) -> None:
        """初始化控制台通知器。

        Args:
            enabled: 是否启用
        """
        self.enabled = enabled

    async def send(self, title: str, content: str, level: str = "info", **kwargs: Any) -> bool:
        """通过日志系统输出通知。

        根据 level 选择对应的日志级别输出。

        Args:
            title: 通知标题
            content: 通知内容
            level: 级别（info / warning / error / critical）
            **kwargs: 未使用

        Returns:
            始终返回 True（控制台输出不会失败）
        """
        if not self.enabled:
            return False

        level_str = level.upper().ljust(8)
        message = f"🔔 [{level_str}] {title}\n{content}"

        # 按级别选择日志方法
        log_methods: dict[str, Any] = {
            "info": logger.info,
            "warning": logger.warning,
            "error": logger.error,
            "critical": logger.critical,
        }
        log_fn = log_methods.get(level, logger.info)
        log_fn("通知: %s | %s", title, content[:200])

        # 同时打印到控制台（开发可见）
        print(message)

        return True

    async def send_alert(self, alert: dict[str, Any]) -> bool:
        """发送结构化告警到控制台。

        Args:
            alert: 告警数据（含 title, message, severity, source, timestamp）

        Returns:
            是否发送成功
        """
        title = alert.get("title", "系统告警")
        message = alert.get("message", "")
        severity = alert.get("severity", "info")
        source = alert.get("source", "unknown")
        timestamp = alert.get("timestamp", "")

        content = f"来源: {source} | 时间: {timestamp}\n{message}"

        level_map = {"low": "info", "medium": "warning", "high": "error", "critical": "critical"}
        level = level_map.get(severity, "info")

        return await self.send(title=title, content=content, level=level)


# ── 多渠道通知器 ──────────────────────────────────────────


class MultiChannelNotifier:
    """多渠道通知器 — 基于 NotificationRouter 按级别分发通知。

    包装 NotificationRouter，实现 Notifier 协议，
    可与现有告警系统无缝集成。

    路由规则（接 B-2 降噪层）:
      critical → 全渠道（飞书 + 企微 + Telegram）
      error    → 飞书 + 企微
      warning  → 飞书
      info     → 仅日志

    Attributes:
        name: 通知器名称
        enabled: 是否启用
    """

    name = "multi_channel"

    def __init__(
        self,
        router: NotificationRouter | None = None,
        enabled: bool = True,
    ) -> None:
        """初始化多渠道通知器。

        Args:
            router: 通知路由器实例，为 None 时使用空路由器
            enabled: 是否启用
        """
        from one_quant.infra.notification_channels import NotificationRouter

        self.enabled = enabled
        self._router = router or NotificationRouter()

    @property
    def router(self) -> NotificationRouter:
        """获取内部路由器。"""
        return self._router

    async def send(self, title: str, content: str, level: str = "info", **kwargs: Any) -> bool:
        """通过路由器按级别分发通知。

        Args:
            title: 通知标题
            content: 通知内容（支持 Markdown）
            level: 级别（info / warning / error / critical）
            **kwargs: 未使用

        Returns:
            是否至少一个渠道发送成功（info 级别返回 True）
        """
        if not self.enabled:
            logger.debug("多渠道通知器已禁用，跳过发送")
            return False

        results = await self._router.route(title=title, message=content, level=level)

        # info 级别无渠道发送，视为成功
        if not results:
            return True

        # 至少一个渠道成功即返回 True
        return any(results.values())

    async def send_alert(self, alert: dict[str, Any]) -> bool:
        """发送结构化告警。

        Args:
            alert: 告警数据（含 title, message, severity, source, timestamp）

        Returns:
            是否发送成功
        """
        title = alert.get("title", "系统告警")
        message = alert.get("message", "")
        severity = alert.get("severity", "info")
        source = alert.get("source", "unknown")
        timestamp = alert.get("timestamp", "")

        content = f"来源: {source}\n时间: {timestamp}\n\n{message}"

        level_map = {"low": "info", "medium": "warning", "high": "error", "critical": "critical"}
        level = level_map.get(severity, "info")

        return await self.send(title=title, content=content, level=level)


# ── 面板协议 ──────────────────────────────────────────────


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
