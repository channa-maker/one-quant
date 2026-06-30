"""
ONE量化 - OKX WebSocket 行情接入

实现 OKX 交易所的 WebSocket 实时行情接入。

连接地址: wss://ws.okx.com:8443/ws/v5/public

支持的数据流:
- tickers         → market.ticker
- candles<period> → market.kline
- books / books5  → market.orderbook
- trades          → market.trade

OKX WebSocket 文档:
https://www.okx.com/docs-v5/en/#websocket-api-public-channel
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from decimal import Decimal
from typing import Any

import websockets
from websockets.exceptions import ConnectionClosed

from one_quant.core.types import (
    Kline,
    Market,
    OrderBook,
    OrderBookLevel,
    Ticker,
    Trade,
)
from one_quant.infra.event_bus import EventBus
from one_quant.marketgw.base import MarketGateway
from one_quant.marketgw.reconnect import ReconnectManager

logger = logging.getLogger(__name__)

# ── OKX WebSocket 端点 ────────────────────────────────────────────────

OKX_WS_PUBLIC = "wss://ws.okx.com:8443/ws/v5/public"

# 心跳配置
PING_INTERVAL = 25
PING_TIMEOUT = 10

# OKX K 线周期映射
OKX_INTERVAL_MAP = {
    "1m": "1m", "3m": "3m", "5m": "5m", "15m": "15m", "30m": "30m",
    "1h": "1H", "2h": "2H", "4h": "4H", "6h": "6H", "12h": "12H",
    "1d": "1D", "1w": "1W", "1M": "1M",
}


def _to_okx_inst_id(internal: str) -> str:
    """内部统一命名 → OKX instId。BTC/USDT → BTC-USDT"""
    return internal.replace("/", "-")


def _from_okx_inst_id(inst_id: str) -> str:
    """OKX instId → 内部统一命名。BTC-USDT → BTC/USDT"""
    parts = inst_id.split("-")
    if len(parts) >= 2:
        return f"{parts[0]}/{parts[1]}"
    return inst_id


class OKXMarketGateway(MarketGateway):
    """
    OKX WebSocket 行情网关。

    使用示例::

        from one_quant.infra.event_bus import InMemoryEventBus
        from one_quant.marketgw import OKXMarketGateway

        bus = InMemoryEventBus()
        await bus.start()

        gw = OKXMarketGateway(event_bus=bus)
        await gw.start()
        await gw.connect()
        await gw.subscribe_ticker(["BTC/USDT", "ETH/USDT"])
    """

    def __init__(self, event_bus: EventBus) -> None:
        """
        初始化 OKX 行情网关。

        Args:
            event_bus: 事件总线实例
        """
        super().__init__(event_bus)
        self._ws_url = OKX_WS_PUBLIC
        self._ws: websockets.WebSocketClientProtocol | None = None
        self._reconnect = ReconnectManager(initial_delay=1.0, max_delay=60.0)
        self._subscribed_args: list[dict[str, str]] = []  # 已订阅参数（重连用）
        self._recv_task: asyncio.Task[None] | None = None
        self._heartbeat_task: asyncio.Task[None] | None = None

    async def connect(self) -> None:
        """建立 WebSocket 连接并启动接收循环"""
        logger.info("OKX网关: 正在连接 %s", self._ws_url)
        self._ws = await websockets.connect(
            self._ws_url,
            ping_interval=PING_INTERVAL,
            ping_timeout=PING_TIMEOUT,
            close_timeout=5,
        )
        logger.info("OKX网关: WebSocket 连接成功")
        self._recv_task = asyncio.create_task(self._receive_loop())
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    async def disconnect(self) -> None:
        """断开 WebSocket 连接"""
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
        if self._recv_task and not self._recv_task.done():
            self._recv_task.cancel()
            try:
                await self._recv_task
            except asyncio.CancelledError:
                pass
        if self._ws:
            await self._ws.close()
            self._ws = None
        logger.info("OKX网关: 已断开连接")

    async def _receive_loop(self) -> None:
        """WebSocket 消息接收循环"""
        assert self._ws is not None
        try:
            async for raw_msg in self._ws:
                if not self._running:
                    break
                # OKX 心跳: 服务端发送 "ping" 文本，需回复 "pong"
                if raw_msg == "ping":
                    await self._ws.send("pong")
                    continue
                try:
                    msg = json.loads(raw_msg)
                    await self._dispatch(msg)
                except json.JSONDecodeError:
                    logger.warning("OKX网关: 无法解析消息: %s", raw_msg[:200])
                except Exception:
                    logger.exception("OKX网关: 消息处理异常")
        except ConnectionClosed as exc:
            logger.warning("OKX网关: 连接断开 code=%s reason=%s", exc.code, exc.reason)
            raise
        except asyncio.CancelledError:
            raise

    async def _heartbeat_loop(self) -> None:
        """客户端心跳定时器（每 25 秒发送 ping）"""
        while self._running:
            try:
                await asyncio.sleep(PING_INTERVAL)
                if self._ws:
                    await self._ws.send("ping")
            except asyncio.CancelledError:
                break
            except Exception:
                logger.debug("OKX网关: 心跳发送失败")

    async def _dispatch(self, msg: dict[str, Any]) -> None:
        """
        分发消息到对应的归一化处理函数。

        OKX 消息格式:
        - 数据推送: {"arg": {"channel": "...", "instId": "..."}, "data": [...]}
        - 事件响应: {"event": "subscribe" | "error" | ...}
        """
        # 事件响应
        event = msg.get("event")
        if event:
            if event == "error":
                logger.error(
                    "OKX网关: 错误 code=%s msg=%s",
                    msg.get("code"), msg.get("msg"),
                )
            elif event == "subscribe":
                logger.debug("OKX网关: 订阅确认 %s", msg.get("arg"))
            return

        # 数据推送
        arg = msg.get("arg")
        if arg is None:
            return

        channel = arg.get("channel", "")
        data_list = msg.get("data", [])
        if not data_list:
            return

        for data in data_list:
            if channel == "tickers":
                await self._handle_ticker(data)
            elif channel.startswith("candle"):
                interval = channel.replace("candle", "")
                await self._handle_candle(data, interval, arg.get("instId", ""))
            elif channel in ("books", "books5"):
                await self._handle_book(data, arg.get("instId", ""))
            elif channel == "trades":
                await self._handle_trade(data)

    async def _handle_ticker(self, data: dict[str, Any]) -> None:
        """归一化 tickers → Ticker"""
        symbol = _from_okx_inst_id(data["instId"])
        ticker = Ticker(
            symbol=symbol,
            market=Market.SPOT,
            exchange="okx",
            last_price=Decimal(data["last"]),
            bid=Decimal(data.get("bidPx", "0")),
            ask=Decimal(data.get("askPx", "0")),
            volume_24h=Decimal(data.get("vol24h", "0")),
            timestamp_ns=int(data.get("ts", time.time_ns() // 1_000_000)) * 1_000_000,
        )
        await self._event_bus.publish(
            "market.ticker", ticker.model_dump(mode="json")
        )

    async def _handle_candle(
        self, data: list[Any], interval: str, inst_id: str
    ) -> None:
        """
        归一化 candles → Kline

        OKX K线数组: [ts, open, high, low, close, vol, volCcy, volCcyQuote, confirm]
        """
        if len(data) < 6:
            return
        symbol = _from_okx_inst_id(inst_id)
        kline = Kline(
            symbol=symbol,
            market=Market.SPOT,
            exchange="okx",
            interval=interval,
            open=Decimal(data[1]),
            high=Decimal(data[2]),
            low=Decimal(data[3]),
            close=Decimal(data[4]),
            volume=Decimal(data[5]),
            timestamp_ns=int(data[0]) * 1_000_000,
        )
        await self._event_bus.publish(
            "market.kline", kline.model_dump(mode="json")
        )

    async def _handle_book(self, data: dict[str, Any], inst_id: str) -> None:
        """归一化 books/books5 → OrderBook"""
        symbol = _from_okx_inst_id(inst_id)
        bids = [
            OrderBookLevel(price=Decimal(lv[0]), quantity=Decimal(lv[1]))
            for lv in data.get("bids", [])
        ]
        asks = [
            OrderBookLevel(price=Decimal(lv[0]), quantity=Decimal(lv[1]))
            for lv in data.get("asks", [])
        ]
        orderbook = OrderBook(
            symbol=symbol,
            exchange="okx",
            bids=bids,
            asks=asks,
            timestamp_ns=int(data.get("ts", time.time_ns() // 1_000_000)) * 1_000_000,
        )
        await self._event_bus.publish(
            "market.orderbook", orderbook.model_dump(mode="json")
        )

    async def _handle_trade(self, data: dict[str, Any]) -> None:
        """归一化 trades → Trade"""
        symbol = _from_okx_inst_id(data["instId"])
        side_raw = data.get("side", "buy")
        trade = Trade(
            symbol=symbol,
            exchange="okx",
            price=Decimal(data["px"]),
            quantity=Decimal(data["sz"]),
            side=side_raw if side_raw in ("buy", "sell") else "buy",
            trade_id=data.get("tradeId", ""),
            timestamp_ns=int(data.get("ts", time.time_ns() // 1_000_000)) * 1_000_000,
        )
        await self._event_bus.publish(
            "market.trade", trade.model_dump(mode="json")
        )

    async def _send_subscribe(self, args: list[dict[str, str]]) -> None:
        """发送订阅请求"""
        if self._ws is None:
            raise RuntimeError("WebSocket 未连接")
        msg = json.dumps({"op": "subscribe", "args": args})
        await self._ws.send(msg)
        logger.info("OKX网关: 订阅 %d 个通道", len(args))

    async def subscribe_ticker(self, symbols: list[str]) -> None:
        """订阅 tickers"""
        args = [{"channel": "tickers", "instId": _to_okx_inst_id(s)} for s in symbols]
        self._subscribed_args.extend(args)
        await self._send_subscribe(args)

    async def subscribe_kline(self, symbols: list[str], interval: str = "1m") -> None:
        """订阅 candles"""
        okx_interval = OKX_INTERVAL_MAP.get(interval, interval)
        args = [
            {"channel": f"candle{okx_interval}", "instId": _to_okx_inst_id(s)}
            for s in symbols
        ]
        self._subscribed_args.extend(args)
        await self._send_subscribe(args)

    async def subscribe_orderbook(self, symbols: list[str], depth: int = 20) -> None:
        """订阅 books / books5"""
        channel = "books5" if depth <= 5 else "books"
        args = [{"channel": channel, "instId": _to_okx_inst_id(s)} for s in symbols]
        self._subscribed_args.extend(args)
        await self._send_subscribe(args)

    async def subscribe_trades(self, symbols: list[str]) -> None:
        """订阅 trades"""
        args = [{"channel": "trades", "instId": _to_okx_inst_id(s)} for s in symbols]
        self._subscribed_args.extend(args)
        await self._send_subscribe(args)

    async def start(self) -> None:
        """启动网关（含断线重连）"""
        self._running = True
        logger.info("OKX网关: 启动")

        async def _connect_and_run():
            await self.connect()
            # 等待接收循环结束
            if self._recv_task:
                await self._recv_task

        async def _on_connected():
            if self._subscribed_args:
                await self._send_subscribe(self._subscribed_args)

        await self._reconnect.run_forever(
            connect_fn=_connect_and_run,
            on_connected=_on_connected,
            should_continue=lambda: self._running,
        )

    async def stop(self) -> None:
        """停止网关"""
        self._running = False
        await self.disconnect()
        logger.info("OKX网关: 已停止")
