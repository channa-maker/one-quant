"""
ONE量化 - 币安 WebSocket 行情网关测试 (binance_ws.py)

覆盖：
  - 符号转换工具函数
  - K线周期映射
  - 网关初始化
  - 连接/断开
  - 订阅
  - 快照请求
  - 消息处理 (ticker/depth/trade/kline)
  - 深度增量合并
  - 接收循环
"""

import json
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from one_quant.core.types import Market
from one_quant.exchange.binance_ws import (
    _INTERVAL_MAP,
    BinanceWSGateway,
    _from_binance_symbol,
    _to_binance_symbol,
)


class TestSymbolConversion:
    """符号转换测试"""

    def test_to_binance_symbol(self):
        """内部符号 → 币安符号。"""
        assert _to_binance_symbol("BTC/USDT") == "btcusdt"
        assert _to_binance_symbol("ETH/USDT") == "ethusdt"

    def test_from_binance_symbol_usdt(self):
        """币安 USDT 对 → 内部符号。"""
        assert _from_binance_symbol("BTCUSDT", Market.SPOT) == "BTC/USDT"
        assert _from_binance_symbol("btcusdt", Market.SPOT) == "BTC/USDT"

    def test_from_binance_symbol_busd(self):
        """币安 BUSD 对 → 内部符号。"""
        assert _from_binance_symbol("BTCBUSD", Market.SPOT) == "BTC/BUSD"

    def test_from_binance_symbol_btc(self):
        """币安 BTC 对 → 内部符号。"""
        assert _from_binance_symbol("ETHBTC", Market.SPOT) == "ETH/BTC"

    def test_from_binance_symbol_eth(self):
        """币安 ETH 对 → 内部符号。"""
        assert _from_binance_symbol("LINKETH", Market.SPOT) == "LINK/ETH"

    def test_from_binance_symbol_unknown(self):
        """未知后缀返回原符号。"""
        assert _from_binance_symbol("UNKNOWN", Market.SPOT) == "UNKNOWN"

    def test_roundtrip(self):
        """符号转换可往返。"""
        internal = "BTC/USDT"
        binance = _to_binance_symbol(internal)
        back = _from_binance_symbol(binance, Market.SPOT)
        assert back == internal


class TestIntervalMap:
    """K线周期映射测试"""

    def test_common_intervals(self):
        """常用周期映射正确。"""
        assert _INTERVAL_MAP["1m"] == "1m"
        assert _INTERVAL_MAP["5m"] == "5m"
        assert _INTERVAL_MAP["1h"] == "1h"
        assert _INTERVAL_MAP["1d"] == "1d"
        assert _INTERVAL_MAP["1w"] == "1w"

    def test_all_intervals(self):
        """所有周期都有映射。"""
        expected = {
            "1s",
            "1m",
            "3m",
            "5m",
            "15m",
            "30m",
            "1h",
            "2h",
            "4h",
            "6h",
            "8h",
            "12h",
            "1d",
            "3d",
            "1w",
            "1M",
        }
        assert set(_INTERVAL_MAP.keys()) == expected


class TestBinanceWSGatewayInit:
    """网关初始化测试"""

    def test_exchange_name(self):
        """交易所名称。"""
        bus = MagicMock()
        gw = BinanceWSGateway(bus)
        assert gw.exchange == "binance"

    def test_default_kline_intervals(self):
        """默认 K 线周期。"""
        bus = MagicMock()
        gw = BinanceWSGateway(bus)
        assert gw._kline_intervals == ["1m", "5m", "1h"]

    def test_custom_kline_intervals(self):
        """自定义 K 线周期。"""
        bus = MagicMock()
        gw = BinanceWSGateway(bus, kline_intervals=["15m", "4h"])
        assert gw._kline_intervals == ["15m", "4h"]

    def test_depth_buffer_empty(self):
        """初始深度缓冲为空。"""
        bus = MagicMock()
        gw = BinanceWSGateway(bus)
        assert gw._depth_buffer == {}


class TestBinanceWSGatewayConnect:
    """连接测试"""

    @pytest.mark.asyncio
    async def test_connect(self):
        """连接创建 WebSocket。"""
        bus = MagicMock()
        gw = BinanceWSGateway(bus)
        with patch(
            "one_quant.exchange.binance_ws.websockets.connect", new_callable=AsyncMock
        ) as mock_ws:
            mock_ws.return_value = AsyncMock()
            await gw._connect()
            assert gw._ws is not None

    @pytest.mark.asyncio
    async def test_disconnect(self):
        """断开关闭 WebSocket。"""
        bus = MagicMock()
        gw = BinanceWSGateway(bus)
        mock_ws = AsyncMock()
        gw._ws = mock_ws
        await gw._disconnect()
        mock_ws.close.assert_awaited_once()
        assert gw._ws is None

    @pytest.mark.asyncio
    async def test_disconnect_no_ws(self):
        """无 WebSocket 时断开不报错。"""
        bus = MagicMock()
        gw = BinanceWSGateway(bus)
        gw._ws = None
        await gw._disconnect()


class TestBinanceWSGatewaySubscribe:
    """订阅测试"""

    @pytest.mark.asyncio
    async def test_subscribe_sends_message(self):
        """订阅发送 SUBSCRIBE 消息。"""
        bus = MagicMock()
        gw = BinanceWSGateway(bus)
        mock_ws = AsyncMock()
        gw._ws = mock_ws

        await gw._subscribe(["BTC/USDT"])
        mock_ws.send.assert_awaited_once()
        sent = json.loads(mock_ws.send.call_args[0][0])
        assert sent["method"] == "SUBSCRIBE"
        assert "btcusdt@miniTicker" in sent["params"]
        assert "btcusdt@depth@100ms" in sent["params"]
        assert "btcusdt@trade" in sent["params"]

    @pytest.mark.asyncio
    async def test_subscribe_includes_klines(self):
        """订阅包含 K 线流。"""
        bus = MagicMock()
        gw = BinanceWSGateway(bus, kline_intervals=["1m", "1h"])
        mock_ws = AsyncMock()
        gw._ws = mock_ws

        await gw._subscribe(["BTC/USDT"])
        sent = json.loads(mock_ws.send.call_args[0][0])
        assert "btcusdt@kline_1m" in sent["params"]
        assert "btcusdt@kline_1h" in sent["params"]

    @pytest.mark.asyncio
    async def test_subscribe_multiple_symbols(self):
        """多符号订阅。"""
        bus = MagicMock()
        gw = BinanceWSGateway(bus)
        mock_ws = AsyncMock()
        gw._ws = mock_ws

        await gw._subscribe(["BTC/USDT", "ETH/USDT"])
        sent = json.loads(mock_ws.send.call_args[0][0])
        assert "btcusdt@miniTicker" in sent["params"]
        assert "ethusdt@miniTicker" in sent["params"]

    @pytest.mark.asyncio
    async def test_subscribe_no_ws(self):
        """无 WebSocket 时订阅不报错。"""
        bus = MagicMock()
        gw = BinanceWSGateway(bus)
        gw._ws = None
        await gw._subscribe(["BTC/USDT"])


class TestBinanceWSGatewaySnapshot:
    """快照请求测试"""

    @pytest.mark.asyncio
    async def test_request_snapshot(self):
        """请求 L2 快照。"""
        bus = MagicMock()
        gw = BinanceWSGateway(bus)

        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "bids": [["49999", "1.5"], ["49998", "2.0"]],
            "asks": [["50001", "1.0"], ["50002", "3.0"]],
            "lastUpdateId": 12345,
        }

        with patch("one_quant.exchange.binance_ws.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock()
            mock_cls.return_value = mock_client

            await gw._request_snapshot(["BTC/USDT"])

        # 验证请求被调用（快照可能异步写入缓冲区）
        mock_client.get.assert_called_once()

    @pytest.mark.asyncio
    async def test_request_snapshot_failure(self):
        """快照请求失败不抛异常。"""
        bus = MagicMock()
        gw = BinanceWSGateway(bus)

        with patch("one_quant.exchange.binance_ws.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get.side_effect = Exception("Network error")
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock()
            mock_cls.return_value = mock_client

            await gw._request_snapshot(["BTC/USDT"])

        assert "BTC/USDT" not in gw._depth_buffer


class TestBinanceWSGatewayOnMessage:
    """消息处理测试"""

    @pytest.mark.asyncio
    async def test_handle_ticker(self):
        """处理 miniTicker 消息。"""
        bus = AsyncMock()
        gw = BinanceWSGateway(bus)

        data = {
            "e": "24hrMiniTicker",
            "s": "BTCUSDT",
            "c": "50000",
            "b": "49999",
            "a": "50001",
            "v": "1234.56",
        }
        msg = json.dumps({"stream": "btcusdt@miniTicker", "data": data})
        await gw._on_message(msg)

        bus.publish.assert_awaited_once()
        call_args = bus.publish.call_args
        assert call_args[0][0] == "market.ticker"
        published = call_args[0][1]
        assert published["symbol"] == "BTC/USDT"
        assert published["last_price"] == "50000"

    @pytest.mark.asyncio
    async def test_handle_trade(self):
        """处理 trade 消息。"""
        bus = AsyncMock()
        gw = BinanceWSGateway(bus)

        data = {
            "e": "trade",
            "s": "BTCUSDT",
            "p": "50000.50",
            "q": "0.1",
            "m": False,  # buyer is taker → buy
            "t": 123456,
            "T": 1583971200000,
        }
        msg = json.dumps({"stream": "btcusdt@trade", "data": data})
        await gw._on_message(msg)

        bus.publish.assert_awaited_once()
        call_args = bus.publish.call_args
        assert call_args[0][0] == "market.trade"
        published = call_args[0][1]
        assert published["symbol"] == "BTC/USDT"
        assert published["side"] == "buy"

    @pytest.mark.asyncio
    async def test_handle_trade_sell(self):
        """处理卖出方向 trade。"""
        bus = AsyncMock()
        gw = BinanceWSGateway(bus)

        data = {
            "e": "trade",
            "s": "ETHUSDT",
            "p": "3000",
            "q": "1.0",
            "m": True,  # buyer is maker → sell
            "t": 789,
            "T": 1583971200000,
        }
        msg = json.dumps({"stream": "ethusdt@trade", "data": data})
        await gw._on_message(msg)

        call_args = bus.publish.call_args
        published = call_args[0][1]
        assert published["side"] == "sell"

    @pytest.mark.asyncio
    async def test_handle_kline(self):
        """处理 kline 消息。"""
        bus = AsyncMock()
        gw = BinanceWSGateway(bus)

        data = {
            "e": "kline",
            "s": "BTCUSDT",
            "k": {
                "i": "1m",
                "o": "50000",
                "h": "50100",
                "l": "49900",
                "c": "50050",
                "v": "100",
                "t": 1583971200000,
            },
        }
        msg = json.dumps({"stream": "btcusdt@kline_1m", "data": data})
        await gw._on_message(msg)

        bus.publish.assert_awaited_once()
        call_args = bus.publish.call_args
        assert call_args[0][0] == "market.kline"
        published = call_args[0][1]
        assert published["symbol"] == "BTC/USDT"
        assert published["interval"] == "1m"

    @pytest.mark.asyncio
    async def test_handle_depth_with_buffer(self):
        """处理 depthUpdate 消息（有缓冲）。"""
        bus = AsyncMock()
        gw = BinanceWSGateway(bus)

        # 预设深度缓冲
        gw._depth_buffer["BTC/USDT"] = {
            "bids": {Decimal("49999"): Decimal("1.0")},
            "asks": {Decimal("50001"): Decimal("1.0")},
            "lastUpdateId": 100,
        }

        data = {
            "e": "depthUpdate",
            "s": "BTCUSDT",
            "b": [["49999", "2.0"], ["49998", "0.5"]],
            "a": [["50001", "0"]],  # 删除
        }
        msg = json.dumps({"stream": "btcusdt@depth@100ms", "data": data})
        await gw._on_message(msg)

        buf = gw._depth_buffer["BTC/USDT"]
        assert buf["bids"][Decimal("49999")] == Decimal("2.0")  # 更新
        assert Decimal("49998") in buf["bids"]  # 新增
        assert Decimal("50001") not in buf["asks"]  # 删除

        bus.publish.assert_awaited_once()
        call_args = bus.publish.call_args
        assert call_args[0][0] == "market.orderbook"

    @pytest.mark.asyncio
    async def test_handle_depth_no_buffer(self):
        """无缓冲时 depthUpdate 忽略。"""
        bus = AsyncMock()
        gw = BinanceWSGateway(bus)

        data = {
            "e": "depthUpdate",
            "s": "BTCUSDT",
            "b": [["49999", "1.0"]],
            "a": [["50001", "1.0"]],
        }
        msg = json.dumps({"stream": "btcusdt@depth@100ms", "data": data})
        await gw._on_message(msg)

        bus.publish.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_handle_subscription_confirmation(self):
        """订阅确认消息忽略。"""
        bus = AsyncMock()
        gw = BinanceWSGateway(bus)

        msg = json.dumps({"result": None, "id": 1})
        await gw._on_message(msg)

        bus.publish.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_handle_unknown_event(self):
        """未知事件类型忽略。"""
        bus = AsyncMock()
        gw = BinanceWSGateway(bus)

        msg = json.dumps({"e": "unknownEvent", "s": "BTCUSDT"})
        await gw._on_message(msg)

        bus.publish.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_on_message_bytes(self):
        """字节消息解码处理。"""
        bus = AsyncMock()
        gw = BinanceWSGateway(bus)

        data = {
            "e": "24hrMiniTicker",
            "s": "BTCUSDT",
            "c": "50000",
            "b": "49999",
            "a": "50001",
            "v": "100",
        }
        msg_bytes = json.dumps({"stream": "btcusdt@miniTicker", "data": data}).encode("utf-8")
        await gw._on_message(msg_bytes)

        bus.publish.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_on_message_no_stream_key(self):
        """无 stream 键的消息直接处理 data。"""
        bus = AsyncMock()
        gw = BinanceWSGateway(bus)

        data = {
            "e": "24hrMiniTicker",
            "s": "BTCUSDT",
            "c": "50000",
            "b": "49999",
            "a": "50001",
            "v": "100",
        }
        msg = json.dumps(data)  # 无 stream 包装
        await gw._on_message(msg)

        bus.publish.assert_awaited_once()


class TestBinanceWSGatewayReceiveLoop:
    """接收循环测试"""

    @pytest.mark.asyncio
    async def test_receive_loop(self):
        """接收循环处理消息。"""
        bus = AsyncMock()
        gw = BinanceWSGateway(bus)

        messages = [
            json.dumps(
                {
                    "stream": "btcusdt@miniTicker",
                    "data": {
                        "e": "24hrMiniTicker",
                        "s": "BTCUSDT",
                        "c": "50000",
                        "b": "49999",
                        "a": "50001",
                        "v": "100",
                    },
                }
            ),
        ]

        async def mock_iter():
            for m in messages:
                yield m

        mock_ws = MagicMock()
        mock_ws.__aiter__ = lambda self: mock_iter()
        gw._ws = mock_ws
        gw._stopping = False

        await gw._receive_loop()
        bus.publish.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_receive_loop_no_ws(self):
        """无 WebSocket 时接收循环立即返回。"""
        bus = AsyncMock()
        gw = BinanceWSGateway(bus)
        gw._ws = None
        await gw._receive_loop()

    @pytest.mark.asyncio
    async def test_receive_loop_stops_on_flag(self):
        """停止标志触发时接收循环退出。"""
        bus = AsyncMock()
        gw = BinanceWSGateway(bus)
        gw._stopping = True

        messages = [
            json.dumps(
                {
                    "stream": "btcusdt@miniTicker",
                    "data": {
                        "e": "24hrMiniTicker",
                        "s": "BTCUSDT",
                        "c": "50000",
                        "b": "49999",
                        "a": "50001",
                        "v": "100",
                    },
                }
            ),
        ]

        async def mock_iter():
            for m in messages:
                yield m

        mock_ws = MagicMock()
        mock_ws.__aiter__ = lambda self: mock_iter()
        gw._ws = mock_ws

        await gw._receive_loop()
        bus.publish.assert_not_awaited()
