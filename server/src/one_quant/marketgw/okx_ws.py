"""
ONE量化 - OKX WebSocket 行情网关

接入 OKX WebSocket API，接收 tick/K线/盘口/成交数据，
归一化为统一领域类型后发布到 EventBus。

OKX 使用单 WebSocket 连接 + subscribe/unsubscribe 消息模式。
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
from one_quant.marketgw.base import MarketGateway

logger = logging.getLogger(__name__)

OKX_WS_PUBLIC = "wss://ws.okx.com:8443/ws/v5/public"


class OKXWSGateway(MarketGateway):
    """OKX WebSocket 行情网关。

    使用 OKX v5 WebSocket API，支持多频道订阅。
    自动处理断线重连和心跳保活。

    Example::

        gw = OKXWSGateway(event_bus)
        await gw.start()
        await gw.subscribe_ticker("BTC-USDT")
    """

    name = "okx"

    def __init__(
        self,
        event_bus: Any,
        reconnect_delay_min: float = 1.0,
        reconnect_delay_max: float = 60.0,
    ) -> None:
        """初始化 OKX 行情网关。

        Args:
            event_bus: 事件总线实例。
            reconnect_delay_min: 最小重连间隔（秒）。
            reconnect_delay_max: 最大重连间隔（秒）。
        """
        super().__init__(event_bus)
        self._ws: Any = None
        self._reconnect_delay_min = reconnect_delay_min
        self._reconnect_delay_max = reconnect_delay_max
        self._receive_task: asyncio.Task[None] | None = None
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._pending_subscribes: list[dict[str, Any]] = []

    # ──────────── 连接管理 ────────────

    async def connect(self) -> None:
        """建立 WebSocket 连接。"""
        await self._connect_ws()

    async def _connect_ws(self) -> None:
        """内部连接实现。"""
        try:
            self._ws = await websockets.connect(
                OKX_WS_PUBLIC,
                ping_interval=20,
                ping_timeout=10,
                close_timeout=5,
            )
            logger.info("OKX WebSocket 已连接")

            # 启动接收和心跳任务
            if self._receive_task is None or self._receive_task.done():
                self._receive_task = asyncio.create_task(
                    self._receive_loop(), name="okx-ws-receive"
                )
            if self._heartbeat_task is None or self._heartbeat_task.done():
                self._heartbeat_task = asyncio.create_task(
                    self._heartbeat_loop(), name="okx-ws-heartbeat"
                )

            # 重新订阅之前的频道
            for sub_msg in self._pending_subscribes:
                await self._send(sub_msg)

        except Exception as exc:
            logger.error("OKX WebSocket 连接失败: %s", exc)
            raise

    async def disconnect(self) -> None:
        """断开连接。"""
        self._running = False
        for task in (self._receive_task, self._heartbeat_task):
            if task is not None:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._receive_task = None
        self._heartbeat_task = None

        if self._ws is not None:
            await self._ws.close()
            self._ws = None
        logger.info("OKX WebSocket 已断开")

    async def _send(self, msg: dict[str, Any]) -> None:
        """发送消息到 WebSocket。"""
        if self._ws is not None and not self._ws.closed:
            await self._ws.send(json.dumps(msg))

    # ──────────── 订阅 ────────────

    async def subscribe_ticker(self, symbol: str) -> None:
        """订阅实时行情。

        Args:
            symbol: OKX 符号（如 "BTC-USDT"）。
        """
        sub_msg = {
            "op": "subscribe",
            "args": [{"channel": "tickers", "instId": symbol}],
        }
        self._pending_subscribes.append(sub_msg)
        self._subscribed_symbols.add(symbol)
        await self._send(sub_msg)
        logger.info("订阅 OKX 行情: %s", symbol)

    async def subscribe_kline(self, symbol: str, interval: str) -> None:
        """订阅K线。

        Args:
            symbol: OKX 符号。
            interval: K线周期（如 "1m", "5m", "1H"）。
        """
        # OKX K线频道: candle1m, candle5m, candle1H 等
        okx_interval = interval.replace("m", "m").replace("h", "H").replace("d", "D")
        sub_msg = {
            "op": "subscribe",
            "args": [{"channel": f"candle{okx_interval}", "instId": symbol}],
        }
        self._pending_subscribes.append(sub_msg)
        await self._send(sub_msg)
        logger.info("订阅 OKX K线: %s %s", symbol, interval)

    async def subscribe_orderbook(self, symbol: str, depth: int = 20) -> None:
        """订阅盘口深度。

        Args:
            symbol: OKX 符号。
            depth: 深度档位（5/20/400）。
        """
        channel = "books5" if depth <= 5 else "books"
        sub_msg = {
            "op": "subscribe",
            "args": [{"channel": channel, "instId": symbol}],
        }
        self._pending_subscribes.append(sub_msg)
        await self._send(sub_msg)
        logger.info("订阅 OKX 盘口: %s depth=%d", symbol, depth)

    async def subscribe_trades(self, symbol: str) -> None:
        """订阅逐笔成交。

        Args:
            symbol: OKX 符号。
        """
        sub_msg = {
            "op": "subscribe",
            "args": [{"channel": "trades", "instId": symbol}],
        }
        self._pending_subscribes.append(sub_msg)
        await self._send(sub_msg)
        logger.info("订阅 OKX 成交: %s", symbol)

    # ──────────── 接收循环 ────────────

    async def _receive_loop(self) -> None:
        """带指数退避重连的接收循环。"""
        delay = self._reconnect_delay_min

        while self._running:
            try:
                if self._ws is None or self._ws.closed:
                    await self._connect_ws()
                    delay = self._reconnect_delay_min

                async for raw_msg in self._ws:
                    if not self._running:
                        break
                    try:
                        msg = json.loads(raw_msg)
                        await self._dispatch(msg)
                    except json.JSONDecodeError:
                        logger.warning("收到无法解析的消息: %s", raw_msg[:200])
                    except Exception:
                        logger.exception("处理消息时异常")

            except asyncio.CancelledError:
                break
            except ConnectionClosed as exc:
                logger.warning("OKX WebSocket 断开 (code=%s), %.1fs 后重连", exc.code, delay)
            except Exception as exc:
                logger.error("OKX WebSocket 异常: %s, %.1fs 后重连", exc, delay)

            if not self._running:
                break

            await asyncio.sleep(delay)
            delay = min(delay * 2, self._reconnect_delay_max)

    async def _heartbeat_loop(self) -> None:
        """心跳保活循环（每 25 秒发送 ping）。"""
        while self._running:
            try:
                await asyncio.sleep(25)
                await self._send("ping")
            except asyncio.CancelledError:
                break
            except Exception:
                logger.debug("OKX 心跳发送异常", exc_info=True)

    # ──────────── 消息分发 ────────────

    async def _dispatch(self, msg: Any) -> None:
        """分发 OKX 消息。

        Args:
            msg: OKX WebSocket 原始消息（dict 或 str）。
        """
        if isinstance(msg, str):
            # pong 响应
            return

        if not isinstance(msg, dict):
            return

        arg = msg.get("arg", {})
        channel = arg.get("channel", "")
        data_list = msg.get("data", [])

        for data in data_list:
            if channel == "tickers":
                await self._handle_ticker(data)
            elif channel.startswith("candle"):
                await self._handle_kline(data, channel)
            elif channel in ("books", "books5"):
                await self._handle_orderbook(data)
            elif channel == "trades":
                await self._handle_trade(data)

    async def _handle_ticker(self, data: dict[str, Any]) -> None:
        """处理实时行情。"""
        ticker = Ticker(
            symbol=data["instId"],
            market=Market.SPOT,
            exchange="okx",
            last_price=Decimal(data["last"]),
            bid=Decimal(data["bidPx"]),
            ask=Decimal(data["askPx"]),
            volume_24h=Decimal(data["vol24h"]),
            timestamp_ns=int(data["ts"]) * 1_000_000,
        )
        await self._event_bus.publish(
            "market.ticker",
            ticker.model_dump(mode="json"),
        )

    async def _handle_kline(self, data: dict[str, Any], channel: str) -> None:
        """处理K线。"""
        # OKX K线数据: [ts, o, h, l, c, vol, volCcy, volCcyQuote, confirm]
        interval = channel.replace("candle", "")
        kline = Kline(
            symbol=data["instId"],
            market=Market.SPOT,
            exchange="okx",
            interval=interval,
            open=Decimal(data["o"]),
            high=Decimal(data["h"]),
            low=Decimal(data["l"]),
            close=Decimal(data["c"]),
            volume=Decimal(data["vol"]),
            timestamp_ns=int(data["ts"]) * 1_000_000,
        )
        await self._event_bus.publish(
            "market.kline",
            kline.model_dump(mode="json"),
        )

    async def _handle_orderbook(self, data: dict[str, Any]) -> None:
        """处理盘口深度。"""
        orderbook = OrderBook(
            symbol=data["instId"],
            exchange="okx",
            bids=[OrderBookLevel(price=Decimal(b[0]), quantity=Decimal(b[1])) for b in data.get("bids", [])],
            asks=[OrderBookLevel(price=Decimal(a[0]), quantity=Decimal(a[1])) for a in data.get("asks", [])],
            timestamp_ns=int(data["ts"]) * 1_000_000,
        )
        await self._event_bus.publish(
            "market.orderbook",
            orderbook.model_dump(mode="json"),
        )

    async def _handle_trade(self, data: dict[str, Any]) -> None:
        """处理逐笔成交。"""
        trade = Trade(
            symbol=data["instId"],
            exchange="okx",
            price=Decimal(data["px"]),
            quantity=Decimal(data["sz"]),
            side=data["side"],  # OKX 直接给 "buy"/"sell"
            trade_id=data["tradeId"],
            timestamp_ns=int(data["ts"]) * 1_000_000,
        )
        await self._event_bus.publish(
            "market.trade",
            trade.model_dump(mode="json"),
        )
