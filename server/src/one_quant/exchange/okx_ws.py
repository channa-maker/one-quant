"""OKX WebSocket 行情网关 — tick + L2 增量 + K线，归一化到领域类型"""

from __future__ import annotations

import asyncio
import json
import time
from decimal import Decimal
from typing import Any

import httpx
import websockets

from one_quant.core.types import Kline, Market, OrderBook, OrderBookLevel, Ticker, Trade
from one_quant.exchange.gateway_base import MarketDataGateway
from one_quant.infra.event_bus import EventBus
from one_quant.infra.logging import get_logger

logger = get_logger(__name__)

# ── OKX WebSocket 端点 ────────────────────────────────────────────────

OKX_WS_PUBLIC = "wss://ws.okx.com:8443/ws/v5/public"
OKX_REST_BASE = "https://www.okx.com"


def _to_okx_inst_id(internal: str) -> str:
    """内部统一命名 → OKX instId。BTC/USDT → BTC-USDT"""
    return internal.replace("/", "-")


def _from_okx_inst_id(inst_id: str) -> str:
    """OKX instId → 内部统一命名。BTC-USDT → BTC/USDT"""
    parts = inst_id.split("-")
    if len(parts) >= 2:
        return f"{parts[0]}/{parts[1]}"
    return inst_id


class OKXWSGateway(MarketDataGateway):
    """OKX WebSocket 行情网关。

    订阅三种数据流：
    - tickers       → Ticker
    - books5        → OrderBook (L2 top5 推送)
    - trades        → Trade (逐笔成交)
    - candle<period> → K线

    归一化为领域类型后发布到 EventBus：
    - market.ticker
    - market.orderbook
    - market.trade
    - market.kline
    """

    exchange = "okx"

    def __init__(
        self,
        event_bus: EventBus,
        kline_intervals: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(event_bus, **kwargs)
        self._kline_intervals = kline_intervals or ["1m", "5m", "1H"]

    # ── 连接 ──────────────────────────────────────────────────────────

    async def _connect(self) -> None:
        """连接 OKX 公共 WebSocket"""
        self._ws = await websockets.connect(
            OKX_WS_PUBLIC,
            ping_interval=20,
            ping_timeout=10,
            close_timeout=5,
        )
        logger.info("OKX WebSocket 已连接", url=OKX_WS_PUBLIC)

    async def _disconnect(self) -> None:
        """断开 WebSocket"""
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

    # ── 订阅 ──────────────────────────────────────────────────────────

    async def _subscribe(self, symbols: list[str]) -> None:
        """发送订阅请求"""
        args: list[dict[str, str]] = []
        for sym in symbols:
            inst_id = _to_okx_inst_id(sym)
            args.extend([
                {"channel": "tickers", "instId": inst_id},
                {"channel": "books5", "instId": inst_id},
                {"channel": "trades", "instId": inst_id},
            ])
            for interval in self._kline_intervals:
                args.append({"channel": f"candle{interval}", "instId": inst_id})

        # OKX 单次订阅最多 200 个 channel
        batch_size = 200
        for i in range(0, len(args), batch_size):
            batch = args[i:i + batch_size]
            msg = json.dumps({"op": "subscribe", "args": batch})
            if self._ws is not None:
                await self._ws.send(msg)
                logger.info(
                    "OKX 订阅请求已发送",
                    batch_index=i // batch_size,
                    channel_count=len(batch),
                )

    async def _request_snapshot(self, symbols: list[str]) -> None:
        """OKX books5 是推送模式，无需额外快照请求"""
        pass

    # ── 消息处理 ──────────────────────────────────────────────────────

    async def _on_message(self, raw: str | bytes) -> None:
        """处理 OKX WebSocket 消息"""
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")

        msg = json.loads(raw)

        # 订阅确认 / 错误
        if "event" in msg:
            event = msg["event"]
            if event == "subscribe":
                logger.debug("OKX 订阅确认", channel=msg.get("arg", {}).get("channel"))
            elif event == "error":
                logger.error("OKX 错误", code=msg.get("code"), msg=msg.get("msg"))
            return

        # 数据推送
        arg = msg.get("arg", {})
        channel = arg.get("channel", "")
        data_list = msg.get("data", [])

        if not data_list:
            return

        if channel == "tickers":
            for d in data_list:
                await self._handle_ticker(d)
        elif channel == "books5":
            for d in data_list:
                await self._handle_book(d, arg.get("instId", ""))
        elif channel == "trades":
            for d in data_list:
                await self._handle_trade(d)
        elif channel.startswith("candle"):
            for d in data_list:
                await self._handle_candle(d, channel, arg.get("instId", ""))

    async def _handle_ticker(self, data: dict[str, Any]) -> None:
        """处理 tickers → Ticker"""
        symbol = _from_okx_inst_id(data["instId"])
        ticker = Ticker(
            symbol=symbol,
            market=Market.SPOT,
            exchange="okx",
            last_price=Decimal(data["last"]),
            bid=Decimal(data.get("bidPx", "0")),
            ask=Decimal(data.get("askPx", "0")),
            volume_24h=Decimal(data.get("vol24h", "0")),
            timestamp_ns=int(data.get("ts", time.time_ns() * 1_000_000)),
        )
        await self._event_bus.publish("market.ticker", ticker.model_dump(mode="json"))

    async def _handle_book(self, data: dict[str, Any], inst_id: str) -> None:
        """处理 books5 → OrderBook"""
        symbol = _from_okx_inst_id(inst_id)
        bids = [
            OrderBookLevel(price=Decimal(b[0]), quantity=Decimal(b[1]))
            for b in data.get("bids", [])
        ]
        asks = [
            OrderBookLevel(price=Decimal(a[0]), quantity=Decimal(a[1]))
            for a in data.get("asks", [])
        ]
        orderbook = OrderBook(
            symbol=symbol,
            exchange="okx",
            bids=bids,
            asks=asks,
            timestamp_ns=int(data.get("ts", time.time_ns() * 1_000_000)),
        )
        await self._event_bus.publish("market.orderbook", orderbook.model_dump(mode="json"))

    async def _handle_trade(self, data: dict[str, Any]) -> None:
        """处理 trades → Trade"""
        symbol = _from_okx_inst_id(data["instId"])
        # OKX side: "buy" / "sell"
        side_raw = data.get("side", "buy")
        trade = Trade(
            symbol=symbol,
            exchange="okx",
            price=Decimal(data["px"]),
            quantity=Decimal(data["sz"]),
            side=side_raw if side_raw in ("buy", "sell") else "buy",
            trade_id=data.get("tradeId", ""),
            timestamp_ns=int(data.get("ts", time.time_ns() * 1_000_000)),
        )
        await self._event_bus.publish("market.trade", trade.model_dump(mode="json"))

    async def _handle_candle(self, data: list[Any], channel: str, inst_id: str) -> None:
        """处理 candle<period> → KLine

        OKX candle 数据格式: [ts, o, h, l, c, vol, volCcy, volCcyQuote, confirm]
        """
        if len(data) < 6:
            return

        symbol = _from_okx_inst_id(inst_id)
        interval = channel.replace("candle", "")
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
        await self._event_bus.publish("market.kline", kline.model_dump(mode="json"))

    # ── 重写 receive_loop ─────────────────────────────────────────────

    async def _receive_loop(self) -> None:
        """WebSocket 消息接收循环"""
        if self._ws is None:
            return
        async for message in self._ws:
            if self._stopping:
                break
            self._last_message_ts_ns = time.time_ns()
            try:
                await self._on_message(message)
            except Exception:
                logger.exception(
                    "OKX 消息处理异常",
                    msg_preview=str(message)[:200],
                )
