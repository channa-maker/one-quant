"""
多渠道通知扩展

实现统一通知接口的多渠道推送:
- 飞书(Feishu/Lark) webhook — 富文本卡片
- 企业微信(WeCom) webhook — markdown 消息
- Telegram Bot API — sendMessage
- NotificationRouter — 按告警级别路由分发

路由规则（接 B-2 降噪层）:
  critical → 全渠道（飞书 + 企微 + Telegram）
  error    → 飞书 + 企微
  warning  → 飞书
  info     → 仅日志（不推送）
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol

import httpx

from one_quant.infra.logging import get_logger

logger = get_logger(__name__)


# ── 通知级别枚举 ─────────────────────────────────────────


class LogLevel(StrEnum):
    """通知告警级别。"""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


# ── 通知通道协议 ─────────────────────────────────────────


class NotificationChannel(Protocol):
    """通知通道统一协议。

    所有渠道（飞书/企微/Telegram）实现此协议。
    """

    name: str
    enabled: bool

    async def send(self, title: str, content: str, level: str = "info", **kwargs: Any) -> bool:
        """发送通知。

        Args:
            title: 通知标题
            content: 通知内容
            level: 告警级别

        Returns:
            是否发送成功
        """
        ...


# ── 飞书通道 ─────────────────────────────────────────────


class FeishuChannel:
    """飞书(Feishu/Lark) Webhook 通道。

    通过飞书自定义机器人 webhook 发送富文本卡片消息。
    文档: https://open.feishu.cn/document/client-docs/bot-v3/add-custom-bot

    Attributes:
        name: 通道名称
        enabled: 是否启用
    """

    name = "feishu"

    def __init__(
        self,
        webhook_url: str,
        secret: str | None = None,
        timeout: float = 30.0,
        enabled: bool = True,
    ) -> None:
        """初始化飞书通道。

        Args:
            webhook_url: 飞书 webhook 地址
            secret: 签名校验密钥（可选）
            timeout: HTTP 超时秒数
            enabled: 是否启用
        """
        self.enabled = enabled
        self._webhook_url = webhook_url
        self._secret = secret
        self._timeout = timeout

    def _build_card_payload(self, title: str, content: str, level: str) -> dict[str, Any]:
        """构造飞书富文本卡片 payload。

        Args:
            title: 标题
            content: 内容
            level: 告警级别

        Returns:
            飞书消息体
        """
        # 级别颜色映射
        color_map = {
            "info": "blue",
            "warning": "orange",
            "error": "red",
            "critical": "red",
        }
        header_color = color_map.get(level, "blue")

        # 级别 emoji
        emoji_map = {
            "info": "ℹ️",
            "warning": "⚠️",
            "error": "❌",
            "critical": "🚨",
        }
        emoji = emoji_map.get(level, "ℹ️")

        payload = {
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {"tag": "plain_text", "content": f"{emoji} {title}"},
                    "template": header_color,
                },
                "elements": [
                    {
                        "tag": "div",
                        "text": {
                            "tag": "lark_md",
                            "content": content,
                        },
                    },
                ],
            },
        }

        # 如果配置了签名密钥，添加签名
        if self._secret:
            import hashlib
            import hmac
            import time

            timestamp = str(int(time.time()))
            string_to_sign = f"{timestamp}\n{self._secret}"
            hmac_code = hmac.new(
                string_to_sign.encode("utf-8"),
                digestmod=hashlib.sha256,
            ).digest()
            import base64

            sign = base64.b64encode(hmac_code).decode("utf-8")
            payload["timestamp"] = timestamp
            payload["sign"] = sign

        return payload

    async def send(self, title: str, content: str, level: str = "info", **kwargs: Any) -> bool:
        """通过飞书 webhook 发送通知。

        Args:
            title: 通知标题
            content: 通知内容
            level: 告警级别

        Returns:
            是否发送成功
        """
        if not self.enabled:
            logger.debug("飞书通道已禁用，跳过发送")
            return False

        payload = self._build_card_payload(title, content, level)

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    self._webhook_url,
                    headers={"Content-Type": "application/json"},
                    json=payload,
                )

                if resp.status_code >= 400:
                    logger.error(
                        "飞书推送失败: status=%d body=%s",
                        resp.status_code,
                        resp.text[:500],
                    )
                    return False

                # 飞书 API 返回 code=0 表示成功
                resp_data = resp.json()
                if resp_data.get("code", -1) != 0:
                    logger.error(
                        "飞书 API 错误: code=%s msg=%s",
                        resp_data.get("code"),
                        resp_data.get("msg"),
                    )
                    return False

                logger.info("飞书推送成功: title=%s", title)
                return True

        except httpx.TimeoutException:
            logger.error("飞书推送超时: url=%s", self._webhook_url)
            return False
        except httpx.HTTPError as exc:
            logger.error("飞书推送 HTTP 错误: %s", exc)
            return False
        except Exception as exc:
            logger.error("飞书推送异常: %s", exc)
            return False


# ── 企业微信通道 ──────────────────────────────────────────


class WeComChannel:
    """企业微信(WeCom) Webhook 通道。

    通过企业微信群机器人 webhook 发送 markdown 消息。
    文档: https://developer.work.weixin.qq.com/document/path/91770

    Attributes:
        name: 通道名称
        enabled: 是否启用
    """

    name = "wecom"

    def __init__(
        self,
        webhook_url: str,
        timeout: float = 30.0,
        enabled: bool = True,
    ) -> None:
        """初始化企业微信通道。

        Args:
            webhook_url: 企微 webhook 地址
            timeout: HTTP 超时秒数
            enabled: 是否启用
        """
        self.enabled = enabled
        self._webhook_url = webhook_url
        self._timeout = timeout

    def _build_markdown_payload(self, title: str, content: str, level: str) -> dict[str, Any]:
        """构造企微 markdown 消息 payload。

        Args:
            title: 标题
            content: 内容
            level: 告警级别

        Returns:
            企微消息体
        """
        # 级别颜色标记
        color_map = {
            "info": "info",
            "warning": "warning",
            "error": "warning",
            "critical": "warning",
        }
        # 级别 emoji
        emoji_map = {
            "info": "ℹ️",
            "warning": "⚠️",
            "error": "❌",
            "critical": "🚨",
        }
        emoji = emoji_map.get(level, "ℹ️")
        color = color_map.get(level, "info")

        # 企微 markdown 语法
        md_content = (
            f"## {emoji} {title}\n"
            f'> 告警级别: <font color="{color}">{level.upper()}</font>\n\n'
            f"{content}"
        )

        return {
            "msgtype": "markdown",
            "markdown": {
                "content": md_content,
            },
        }

    async def send(self, title: str, content: str, level: str = "info", **kwargs: Any) -> bool:
        """通过企微 webhook 发送通知。

        Args:
            title: 通知标题
            content: 通知内容
            level: 告警级别

        Returns:
            是否发送成功
        """
        if not self.enabled:
            logger.debug("企微通道已禁用，跳过发送")
            return False

        payload = self._build_markdown_payload(title, content, level)

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    self._webhook_url,
                    headers={"Content-Type": "application/json"},
                    json=payload,
                )

                if resp.status_code >= 400:
                    logger.error(
                        "企微推送失败: status=%d body=%s",
                        resp.status_code,
                        resp.text[:500],
                    )
                    return False

                # 企微 API 返回 errcode=0 表示成功
                resp_data = resp.json()
                if resp_data.get("errcode", -1) != 0:
                    logger.error(
                        "企微 API 错误: errcode=%s errmsg=%s",
                        resp_data.get("errcode"),
                        resp_data.get("errmsg"),
                    )
                    return False

                logger.info("企微推送成功: title=%s", title)
                return True

        except httpx.TimeoutException:
            logger.error("企微推送超时: url=%s", self._webhook_url)
            return False
        except httpx.HTTPError as exc:
            logger.error("企微推送 HTTP 错误: %s", exc)
            return False
        except Exception as exc:
            logger.error("企微推送异常: %s", exc)
            return False


# ── Telegram 通道 ─────────────────────────────────────────


class TelegramChannel:
    """Telegram Bot API 通道。

    通过 Telegram Bot API 的 sendMessage 接口推送消息。
    文档: https://core.telegram.org/bots/api#sendmessage

    Attributes:
        name: 通道名称
        enabled: 是否启用
    """

    name = "telegram"

    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        timeout: float = 30.0,
        enabled: bool = True,
    ) -> None:
        """初始化 Telegram 通道。

        Args:
            bot_token: Telegram Bot Token
            chat_id: 目标聊天 ID（群组/频道/用户）
            timeout: HTTP 超时秒数
            enabled: 是否启用
        """
        self.enabled = enabled
        self._chat_id = chat_id
        self._timeout = timeout
        self._api_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    def _build_message_payload(self, title: str, content: str, level: str) -> dict[str, Any]:
        """构造 Telegram sendMessage payload。

        Args:
            title: 标题
            content: 内容
            level: 告警级别

        Returns:
            Telegram API 消息体
        """
        # 级别 emoji
        emoji_map = {
            "info": "ℹ️",
            "warning": "⚠️",
            "error": "❌",
            "critical": "🚨",
        }
        emoji = emoji_map.get(level, "ℹ️")

        # Markdown 格式消息
        text = f"{emoji} *{title}*\n\n{content}\n\n_Level: {level.upper()}_"

        return {
            "chat_id": self._chat_id,
            "text": text,
            "parse_mode": "Markdown",
        }

    async def send(self, title: str, content: str, level: str = "info", **kwargs: Any) -> bool:
        """通过 Telegram Bot API 发送通知。

        Args:
            title: 通知标题
            content: 通知内容
            level: 告警级别

        Returns:
            是否发送成功
        """
        if not self.enabled:
            logger.debug("Telegram 通道已禁用，跳过发送")
            return False

        payload = self._build_message_payload(title, content, level)

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    self._api_url,
                    headers={"Content-Type": "application/json"},
                    json=payload,
                )

                if resp.status_code >= 400:
                    logger.error(
                        "Telegram 推送失败: status=%d body=%s",
                        resp.status_code,
                        resp.text[:500],
                    )
                    return False

                # Telegram API 返回 ok=true 表示成功
                resp_data = resp.json()
                if not resp_data.get("ok", False):
                    logger.error(
                        "Telegram API 错误: description=%s",
                        resp_data.get("description"),
                    )
                    return False

                logger.info("Telegram 推送成功: title=%s", title)
                return True

        except httpx.TimeoutException:
            logger.error("Telegram 推送超时: url=%s", self._api_url)
            return False
        except httpx.HTTPError as exc:
            logger.error("Telegram 推送 HTTP 错误: %s", exc)
            return False
        except Exception as exc:
            logger.error("Telegram 推送异常: %s", exc)
            return False


# ── 路由策略配置 ──────────────────────────────────────────

# 路由表: 级别 → 需要发送的通道名称列表
# info 级别不在表中，表示仅日志不推送
_ROUTING_TABLE: dict[str, list[str]] = {
    "critical": ["feishu", "wecom", "telegram"],
    "error": ["feishu", "wecom"],
    "warning": ["feishu"],
    # info: 不在路由表中 → 仅日志
}


# ── 通知路由器 ────────────────────────────────────────────


@dataclass
class NotificationRouter:
    """通知路由器。

    根据告警级别选择对应的通道进行推送。
    单个通道失败不阻塞其他通道。

    Attributes:
        channels: 已注册的通道字典 {name: channel}
    """

    channels: dict[str, Any] = field(default_factory=dict[str, Any])

    async def route(self, title: str, message: str, level: str = "info") -> dict[str, bool]:
        """按告警级别路由通知到对应通道。

        路由规则:
          critical → 全渠道
          error    → 飞书 + 企微
          warning  → 飞书
          info     → 仅日志

        Args:
            title: 通知标题
            message: 通知内容
            level: 告警级别

        Returns:
            各通道发送结果 {channel_name: success}
        """
        # 获取该级别需要发送的通道列表
        target_channels = _ROUTING_TABLE.get(level, [])

        if not target_channels:
            # info 或未知级别: 仅日志
            logger.info("[通知-日志] [%s] %s: %s", level.upper(), title, message)
            return {}

        # 并发发送到所有目标通道
        results: dict[str, bool] = {}

        async def _send_to_channel(channel_name: str) -> tuple[str, bool]:
            """发送到单个通道，捕获异常不阻塞其他通道。"""
            channel = self.channels.get(channel_name)
            if channel is None or not channel.enabled:
                return channel_name, False

            try:
                success = await channel.send(title=title, content=message, level=level)
                return channel_name, success
            except Exception as exc:
                logger.error(
                    "通道 %s 发送异常: %s",
                    channel_name,
                    exc,
                )
                return channel_name, False

        # 并发执行所有发送任务
        tasks = [_send_to_channel(name) for name in target_channels]
        outcomes = await asyncio.gather(*tasks, return_exceptions=True)

        for outcome in outcomes:
            if isinstance(outcome, BaseException):
                # gather 本身出错（极端情况）
                logger.error("路由任务异常: %s", outcome)
                continue
            name, success = outcome
            results[name] = success

        return results


# ── 工厂函数 ─────────────────────────────────────────────


def build_default_router(
    feishu_webhook: str | None = None,
    wecom_webhook: str | None = None,
    telegram_bot_token: str | None = None,
    telegram_chat_id: str | None = None,
    feishu_secret: str | None = None,
) -> NotificationRouter:
    """构建默认通知路由器。

    根据传入的配置参数自动创建对应的通道并注册到路由器。
    未配置的通道不会创建。

    Args:
        feishu_webhook: 飞书 webhook URL
        wecom_webhook: 企微 webhook URL
        telegram_bot_token: Telegram Bot Token
        telegram_chat_id: Telegram 聊天 ID
        feishu_secret: 飞书签名密钥（可选）

    Returns:
        配置好的 NotificationRouter 实例
    """
    channels: dict[str, Any] = {}

    if feishu_webhook:
        channels["feishu"] = FeishuChannel(
            webhook_url=feishu_webhook,
            secret=feishu_secret,
        )

    if wecom_webhook:
        channels["wecom"] = WeComChannel(
            webhook_url=wecom_webhook,
        )

    if telegram_bot_token and telegram_chat_id:
        channels["telegram"] = TelegramChannel(
            bot_token=telegram_bot_token,
            chat_id=telegram_chat_id,
        )

    return NotificationRouter(channels=channels)
