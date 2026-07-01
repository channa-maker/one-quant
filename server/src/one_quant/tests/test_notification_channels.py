"""
多渠道通知扩展测试

覆盖:
- 飞书(Feishu/Lark) webhook 富文本卡片
- 企业微信(WeCom) webhook markdown 消息
- Telegram Bot API sendMessage
- NotificationRouter 路由器按告警级别分发
- critical → 全渠道 / error → 飞书+企微 / warning → 飞书 / info → 仅日志
- 渠道失败不阻塞其他渠道
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from one_quant.infra.notification_channels import (
    FeishuChannel,
    NotificationRouter,
    TelegramChannel,
    WeComChannel,
    build_default_router,
)

# ── 辅助工具 ──────────────────────────────────────────────


def _mock_httpx_response(status_code: int = 200, json_data: dict | None = None) -> httpx.Response:
    """构造模拟的 httpx.Response 对象。"""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.text = json.dumps(json_data or {"ok": True})
    resp.json.return_value = json_data or {"ok": True}
    return resp


def _make_alert(
    title: str = "测试告警",
    message: str = "这是一个测试",
    level: str = "warning",
) -> dict:
    """构造标准告警数据。"""
    return {"title": title, "message": message, "level": level}


# ── 飞书通道测试 ──────────────────────────────────────────


class TestFeishuChannel:
    """飞书 Webhook 通道测试。"""

    def test_init_defaults(self):
        """默认初始化参数正确。"""
        ch = FeishuChannel(webhook_url="https://open.feishu.cn/open-apis/bot/v2/hook/test")
        assert ch.name == "feishu"
        assert ch.enabled is True
        assert ch._webhook_url == "https://open.feishu.cn/open-apis/bot/v2/hook/test"

    def test_init_disabled(self):
        """可禁用通道。"""
        ch = FeishuChannel(webhook_url="https://example.com/hook", enabled=False)
        assert ch.enabled is False

    @pytest.mark.asyncio
    async def test_send_success(self):
        """飞书发送成功返回 True。"""
        ch = FeishuChannel(webhook_url="https://open.feishu.cn/open-apis/bot/v2/hook/test")
        mock_resp = _mock_httpx_response(200, {"code": 0, "msg": "success"})

        with patch("httpx.AsyncClient") as mock_client_cls:
            instance = mock_client_cls.return_value.__aenter__.return_value
            instance.post = AsyncMock(return_value=mock_resp)

            result = await ch.send(title="测试", content="内容", level="warning")

        assert result is True

    @pytest.mark.asyncio
    async def test_send_builds_card_payload(self):
        """飞书发送构造富文本卡片 payload。"""
        ch = FeishuChannel(webhook_url="https://open.feishu.cn/open-apis/bot/v2/hook/test")
        mock_resp = _mock_httpx_response(200, {"code": 0, "msg": "success"})

        with patch("httpx.AsyncClient") as mock_client_cls:
            instance = mock_client_cls.return_value.__aenter__.return_value
            instance.post = AsyncMock(return_value=mock_resp)

            await ch.send(title="BTC 暴跌", content="跌幅超过 10%", level="critical")

            # 验证 post 被调用，且 payload 含飞书卡片结构
            call_kwargs = instance.post.call_args
            payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
            assert payload is not None
            assert payload["msg_type"] == "interactive"
            card = payload["card"]
            assert "elements" in card
            # 卡片中应包含告警内容
            card_text = json.dumps(card, ensure_ascii=False)
            assert "BTC 暴跌" in card_text
            assert "跌幅超过 10%" in card_text

    @pytest.mark.asyncio
    async def test_send_http_error_returns_false(self):
        """飞书 HTTP 错误返回 False，不抛异常。"""
        ch = FeishuChannel(webhook_url="https://open.feishu.cn/open-apis/bot/v2/hook/test")
        mock_resp = _mock_httpx_response(500)

        with patch("httpx.AsyncClient") as mock_client_cls:
            instance = mock_client_cls.return_value.__aenter__.return_value
            instance.post = AsyncMock(return_value=mock_resp)

            result = await ch.send(title="测试", content="内容")

        assert result is False

    @pytest.mark.asyncio
    async def test_send_feishu_api_error_returns_false(self):
        """飞书业务错误码返回 False。"""
        ch = FeishuChannel(webhook_url="https://open.feishu.cn/open-apis/bot/v2/hook/test")
        mock_resp = _mock_httpx_response(200, {"code": 19001, "msg": "invalid token"})

        with patch("httpx.AsyncClient") as mock_client_cls:
            instance = mock_client_cls.return_value.__aenter__.return_value
            instance.post = AsyncMock(return_value=mock_resp)

            result = await ch.send(title="测试", content="内容")

        assert result is False

    @pytest.mark.asyncio
    async def test_send_timeout_returns_false(self):
        """飞书超时返回 False。"""
        ch = FeishuChannel(webhook_url="https://open.feishu.cn/open-apis/bot/v2/hook/test")

        with patch("httpx.AsyncClient") as mock_client_cls:
            instance = mock_client_cls.return_value.__aenter__.return_value
            instance.post = AsyncMock(side_effect=httpx.TimeoutException("timeout"))

            result = await ch.send(title="测试", content="内容")

        assert result is False

    @pytest.mark.asyncio
    async def test_send_disabled_returns_false(self):
        """禁用状态直接返回 False。"""
        ch = FeishuChannel(webhook_url="https://example.com", enabled=False)
        result = await ch.send(title="测试", content="内容")
        assert result is False


# ── 企业微信通道测试 ──────────────────────────────────────


class TestWeComChannel:
    """企业微信 Webhook 通道测试。"""

    def test_init_defaults(self):
        """默认初始化参数正确。"""
        ch = WeComChannel(webhook_url="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test")
        assert ch.name == "wecom"
        assert ch.enabled is True

    @pytest.mark.asyncio
    async def test_send_success(self):
        """企微发送成功返回 True。"""
        ch = WeComChannel(webhook_url="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test")
        mock_resp = _mock_httpx_response(200, {"errcode": 0, "errmsg": "ok"})

        with patch("httpx.AsyncClient") as mock_client_cls:
            instance = mock_client_cls.return_value.__aenter__.return_value
            instance.post = AsyncMock(return_value=mock_resp)

            result = await ch.send(title="测试", content="内容", level="error")

        assert result is True

    @pytest.mark.asyncio
    async def test_send_builds_markdown_payload(self):
        """企微发送构造 markdown 消息 payload。"""
        ch = WeComChannel(webhook_url="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test")
        mock_resp = _mock_httpx_response(200, {"errcode": 0, "errmsg": "ok"})

        with patch("httpx.AsyncClient") as mock_client_cls:
            instance = mock_client_cls.return_value.__aenter__.return_value
            instance.post = AsyncMock(return_value=mock_resp)

            await ch.send(title="系统告警", content="CPU 使用率过高", level="error")

            call_kwargs = instance.post.call_args
            payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
            assert payload is not None
            assert payload["msgtype"] == "markdown"
            md_content = payload["markdown"]["content"]
            assert "系统告警" in md_content
            assert "CPU 使用率过高" in md_content

    @pytest.mark.asyncio
    async def test_send_api_error_returns_false(self):
        """企微业务错误码返回 False。"""
        ch = WeComChannel(webhook_url="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test")
        mock_resp = _mock_httpx_response(200, {"errcode": 300001, "errmsg": "invalid key"})

        with patch("httpx.AsyncClient") as mock_client_cls:
            instance = mock_client_cls.return_value.__aenter__.return_value
            instance.post = AsyncMock(return_value=mock_resp)

            result = await ch.send(title="测试", content="内容")

        assert result is False

    @pytest.mark.asyncio
    async def test_send_timeout_returns_false(self):
        """企微超时返回 False。"""
        ch = WeComChannel(webhook_url="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test")

        with patch("httpx.AsyncClient") as mock_client_cls:
            instance = mock_client_cls.return_value.__aenter__.return_value
            instance.post = AsyncMock(side_effect=httpx.TimeoutException("timeout"))

            result = await ch.send(title="测试", content="内容")

        assert result is False

    @pytest.mark.asyncio
    async def test_send_disabled_returns_false(self):
        """禁用状态直接返回 False。"""
        ch = WeComChannel(webhook_url="https://example.com", enabled=False)
        result = await ch.send(title="测试", content="内容")
        assert result is False


# ── Telegram 通道测试 ─────────────────────────────────────


class TestTelegramChannel:
    """Telegram Bot API 通道测试。"""

    def test_init_defaults(self):
        """默认初始化参数正确。"""
        ch = TelegramChannel(bot_token="123:ABC", chat_id="12345")
        assert ch.name == "telegram"
        assert ch.enabled is True
        assert ch._api_url == "https://api.telegram.org/bot123:ABC/sendMessage"

    @pytest.mark.asyncio
    async def test_send_success(self):
        """Telegram 发送成功返回 True。"""
        ch = TelegramChannel(bot_token="123:ABC", chat_id="12345")
        mock_resp = _mock_httpx_response(200, {"ok": True, "result": {}})

        with patch("httpx.AsyncClient") as mock_client_cls:
            instance = mock_client_cls.return_value.__aenter__.return_value
            instance.post = AsyncMock(return_value=mock_resp)

            result = await ch.send(title="测试", content="内容", level="warning")

        assert result is True

    @pytest.mark.asyncio
    async def test_send_builds_correct_payload(self):
        """Telegram 发送构造正确 payload（含 chat_id 和 parse_mode）。"""
        ch = TelegramChannel(bot_token="123:ABC", chat_id="-100123")
        mock_resp = _mock_httpx_response(200, {"ok": True})

        with patch("httpx.AsyncClient") as mock_client_cls:
            instance = mock_client_cls.return_value.__aenter__.return_value
            instance.post = AsyncMock(return_value=mock_resp)

            await ch.send(title="告警", content="ETH 下跌", level="critical")

            call_kwargs = instance.post.call_args
            payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
            assert payload is not None
            assert payload["chat_id"] == "-100123"
            assert payload["parse_mode"] == "Markdown"
            assert "告警" in payload["text"]
            assert "ETH 下跌" in payload["text"]

    @pytest.mark.asyncio
    async def test_send_api_error_returns_false(self):
        """Telegram API 返回 ok=false 时返回 False。"""
        ch = TelegramChannel(bot_token="123:ABC", chat_id="12345")
        mock_resp = _mock_httpx_response(200, {"ok": False, "description": "Bad Request"})

        with patch("httpx.AsyncClient") as mock_client_cls:
            instance = mock_client_cls.return_value.__aenter__.return_value
            instance.post = AsyncMock(return_value=mock_resp)

            result = await ch.send(title="测试", content="内容")

        assert result is False

    @pytest.mark.asyncio
    async def test_send_http_error_returns_false(self):
        """Telegram HTTP 状态码错误返回 False。"""
        ch = TelegramChannel(bot_token="123:ABC", chat_id="12345")
        mock_resp = _mock_httpx_response(401)

        with patch("httpx.AsyncClient") as mock_client_cls:
            instance = mock_client_cls.return_value.__aenter__.return_value
            instance.post = AsyncMock(return_value=mock_resp)

            result = await ch.send(title="测试", content="内容")

        assert result is False

    @pytest.mark.asyncio
    async def test_send_timeout_returns_false(self):
        """Telegram 超时返回 False。"""
        ch = TelegramChannel(bot_token="123:ABC", chat_id="12345")

        with patch("httpx.AsyncClient") as mock_client_cls:
            instance = mock_client_cls.return_value.__aenter__.return_value
            instance.post = AsyncMock(side_effect=httpx.TimeoutException("timeout"))

            result = await ch.send(title="测试", content="内容")

        assert result is False

    @pytest.mark.asyncio
    async def test_send_disabled_returns_false(self):
        """禁用状态直接返回 False。"""
        ch = TelegramChannel(bot_token="123:ABC", chat_id="12345", enabled=False)
        result = await ch.send(title="测试", content="内容")
        assert result is False


# ── NotificationRouter 路由测试 ───────────────────────────


class TestNotificationRouter:
    """NotificationRouter 按告警级别路由测试。"""

    def _make_router_with_mocks(self) -> tuple[NotificationRouter, AsyncMock, AsyncMock, AsyncMock]:
        """创建带 mock 通道的路由器。"""
        feishu = AsyncMock(spec=FeishuChannel)
        feishu.name = "feishu"
        feishu.enabled = True
        feishu.send = AsyncMock(return_value=True)

        wecom = AsyncMock(spec=WeComChannel)
        wecom.name = "wecom"
        wecom.enabled = True
        wecom.send = AsyncMock(return_value=True)

        telegram = AsyncMock(spec=TelegramChannel)
        telegram.name = "telegram"
        telegram.enabled = True
        telegram.send = AsyncMock(return_value=True)

        router = NotificationRouter(
            channels={
                "feishu": feishu,
                "wecom": wecom,
                "telegram": telegram,
            }
        )
        return router, feishu, wecom, telegram

    @pytest.mark.asyncio
    async def test_critical_sends_to_all_channels(self):
        """critical 级别发送到所有渠道。"""
        router, feishu, wecom, telegram = self._make_router_with_mocks()

        result = await router.route(title="紧急", message="系统崩溃", level="critical")

        feishu.send.assert_called_once()
        wecom.send.assert_called_once()
        telegram.send.assert_called_once()
        assert result["feishu"] is True
        assert result["wecom"] is True
        assert result["telegram"] is True

    @pytest.mark.asyncio
    async def test_error_sends_to_feishu_and_wecom(self):
        """error 级别发送到飞书+企微，不发 Telegram。"""
        router, feishu, wecom, telegram = self._make_router_with_mocks()

        result = await router.route(title="错误", message="下单失败", level="error")

        feishu.send.assert_called_once()
        wecom.send.assert_called_once()
        telegram.send.assert_not_called()
        assert result["feishu"] is True
        assert result["wecom"] is True
        assert "telegram" not in result

    @pytest.mark.asyncio
    async def test_warning_sends_to_feishu_only(self):
        """warning 级别仅发送到飞书。"""
        router, feishu, wecom, telegram = self._make_router_with_mocks()

        result = await router.route(title="警告", message="余额不足", level="warning")

        feishu.send.assert_called_once()
        wecom.send.assert_not_called()
        telegram.send.assert_not_called()
        assert result["feishu"] is True
        assert "wecom" not in result
        assert "telegram" not in result

    @pytest.mark.asyncio
    async def test_info_only_logs(self):
        """info 级别仅记录日志，不发送到任何渠道。"""
        router, feishu, wecom, telegram = self._make_router_with_mocks()

        result = await router.route(title="信息", message="策略已启动", level="info")

        feishu.send.assert_not_called()
        wecom.send.assert_not_called()
        telegram.send.assert_not_called()
        assert result == {}

    @pytest.mark.asyncio
    async def test_channel_failure_does_not_block_others(self):
        """单个渠道失败不阻塞其他渠道发送。"""
        router, feishu, wecom, telegram = self._make_router_with_mocks()

        # 飞书发送失败
        feishu.send = AsyncMock(return_value=False)
        wecom.send = AsyncMock(return_value=True)
        telegram.send = AsyncMock(return_value=True)

        result = await router.route(title="紧急", message="全部异常", level="critical")

        # 飞书失败，但企微和 Telegram 仍然发送
        assert result["feishu"] is False
        assert result["wecom"] is True
        assert result["telegram"] is True

    @pytest.mark.asyncio
    async def test_channel_exception_does_not_block_others(self):
        """单个渠道抛异常不阻塞其他渠道。"""
        router, feishu, wecom, telegram = self._make_router_with_mocks()

        # 飞书抛异常
        feishu.send = AsyncMock(side_effect=RuntimeError("网络错误"))
        wecom.send = AsyncMock(return_value=True)

        result = await router.route(title="错误", message="异常测试", level="error")

        assert result["feishu"] is False
        assert result["wecom"] is True

    @pytest.mark.asyncio
    async def test_disabled_channel_skipped(self):
        """禁用的通道被跳过，不调用 send。"""
        router, feishu, wecom, telegram = self._make_router_with_mocks()
        feishu.enabled = False

        result = await router.route(title="紧急", message="测试", level="critical")

        # 禁用的通道未调用 send
        feishu.send.assert_not_called()
        wecom.send.assert_called_once()
        telegram.send.assert_called_once()
        # 禁用通道返回 False
        assert result.get("feishu") is False
        assert result["wecom"] is True
        assert result["telegram"] is True

    @pytest.mark.asyncio
    async def test_unknown_level_defaults_to_log_only(self):
        """未知级别默认仅日志。"""
        router, feishu, wecom, telegram = self._make_router_with_mocks()

        result = await router.route(title="未知", message="未知级别", level="debug")

        feishu.send.assert_not_called()
        wecom.send.assert_not_called()
        telegram.send.assert_not_called()
        assert result == {}


# ── 工厂函数测试 ──────────────────────────────────────────


class TestBuildDefaultRouter:
    """build_default_router 工厂函数测试。"""

    def test_build_with_all_configs(self):
        """传入全部配置时创建三个通道。"""
        router = build_default_router(
            feishu_webhook="https://open.feishu.cn/open-apis/bot/v2/hook/test",
            wecom_webhook="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test",
            telegram_bot_token="123:ABC",
            telegram_chat_id="12345",
        )
        assert "feishu" in router.channels
        assert "wecom" in router.channels
        assert "telegram" in router.channels

    def test_build_with_partial_configs(self):
        """仅传部分配置时只创建对应通道。"""
        router = build_default_router(
            feishu_webhook="https://open.feishu.cn/open-apis/bot/v2/hook/test",
        )
        assert "feishu" in router.channels
        assert "wecom" not in router.channels
        assert "telegram" not in router.channels

    def test_build_with_no_configs(self):
        """不传任何配置时路由器为空。"""
        router = build_default_router()
        assert len(router.channels) == 0
