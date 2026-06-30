"""
ONE量化 - 币安 WebSocket 行情网关

接入币安 WebSocket API，接收 tick/L2/K线/逐笔成交数据，
归一化为统一领域类型后发布到 EventBus。

支持：
- 实时行情 (ticker)
- K线数据 (kline)
- 盘口深度 (orderbook L2 增量)
- 逐笔成交 (trade)

断线重连：指数退避 1s → 2s → 4s … 最大 60s。
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

# 币安 WebSocket 基础地址
BINANCE_WS_BASE = "wss://stream.binance.com:9443/ws"
BINANCE_WS_FUTURES = "wss://fstream.binance.com/ws"


class BinanceWSGateway(MarketGateway):
    """币安 WebSocket 行情网关。

    使用 combined streams 同时订阅多个标的和数据类型。
    自动处理断线重连（指数退避）。

    Example::

        gw = BinanceWSGateway(event_bus)
        await gw.start()
        await gw.subscribe_ticker("BTCUSDT")
        await gw.subscribe_trades("BTCUSDT")
    """

    name = "binance"

    def __init__(
        self,
        event_bus: Any,
        is_futures: bool = False,
        reconnect_delay_min: float = 1.0,
        reconnect_delay_max: float = 60.0,
    ) -> None:
        """初始化币安行情网关。

        Args:
            event_bus: 事件总线实例。
            is_futures: 是否使用合约 WebSocket 端点。
            reconnect_delay_min: 最小重连间隔（秒）。
            reconnect_delay_max: 最大重连间隔（秒）。
        """
        super().__init__(event_bus)
        self._ws_base = BINANCE_WS_FUTURES if is_futures else BINANCE_WS_BASE
        self._ws: Any = None
        self._reconnect_delay_min = reconnect_delay_min
        self._reconnect_delay_max = reconnect_delay_max
        self._streams: list[str] = []
        self._receive_task: asyncio.Task[None] | None = None
        self._kline_intervals: dict[str, str] = {}  # symbol -> interval

    # ──────────── 连接管理 ────────────

    async def connect(self) -> None:
        """建立 WebSocket 连接。"""
        await self._connect_ws()

    async def _connect_ws(self) -> None:
        """内部连接实现。"""
        if not self._streams:
            logger.warning("无订阅流，跳过连接")
            return

        # 构建 combined streams URL
        streams = "/".join(self._streams)
        url = f"{self._ws_base}/{streams}"

        try:
            self._ws = await websockets.connect(
                url,
                ping_interval=20,
                ping_timeout=10,
                close_timeout=5,
            )
            logger.info("币安 WebSocket 已连接: %d 个流", len(self._streams))

            # 启动接收任务
            if self._receive_task is None or self._receive_task.done():
                self._receive_task = asyncio.create_task(
                    self._receive_loop(),
                    name="binance-ws-receive",
                )
        except Exception as exc:
            logger.error("币安 WebSocket 连接失败: %s", exc)
            raise

    async def disconnect(self) -> None:
        """断开 WebSocket 连接。"""
        self._running = False
        if self._receive_task is not None:
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass
            self._receive_task = None

        if self._ws is not None:
            await self._ws.close()
            self._ws = None
        logger.info("币安 WebSocket 已断开")

    # ──────────── 订阅 ────────────

    async def subscribe_ticker(self, symbol: str) -> None:
        """订阅实时行情。

        Args:
            symbol: 币安符号（如 "BTCUSDT"）。
        """
        stream = f"{symbol.lower()}@ticker"
        self._streams.append(stream)
        self._subscribed_symbols.add(symbol)
        logger.info("订阅币安行情: %s", symbol)

    async def subscribe_kline(self, symbol: str, interval: str) -> None:
        """订阅K线。

        Args:
            symbol: 币安符号。
            interval: K线周期（如 "1m", "5m", "1h"）。
        """
        stream = f"{symbol.lower()}@kline_{interval}"
        self._streams.append(stream)
        self._kline_intervals[symbol] = interval
        logger.info("订阅币安K线: %s %s", symbol, interval)

    async def subscribe_orderbook(self, symbol: str, depth: int = 20) -> None:
        """订阅盘口深度（快照）。

        Args:
            symbol: 币安符号。
            depth: 深度档位（5/10/20）。
        """
        stream = f"{symbol.lower()}@depth{depth}@100ms"
        self._streams.append(stream)
        logger.info("订阅币安盘口: %s depth=%d", symbol, depth)

    async def subscribe_trades(self, symbol: str) -> None:
        """订阅逐笔成交。

        Args:
            symbol: 币安符号。
        """
        stream = f"{symbol.lower()}@trade"
        self._streams.append(stream)
        logger.info("订阅币安成交: %s", symbol)

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
                logger.warning("币安 WebSocket 断开 (code=%s), %.1fs 后重连", exc.code, delay)
            except Exception as exc:
                logger.error("币安 WebSocket 异常: %s, %.1fs 后重连", exc, delay)

            if not self._running:
                break

            await asyncio.sleep(delay)
            delay = min(delay * 2, self._reconnect_delay_max)

    # ──────────── 消息分发 ────────────

    async def _dispatch(self, msg: dict[str, Any]) -> None:
        """将币安原始消息归一化并发布到 EventBus。

        Args:
            msg: 币安 WebSocket 原始 JSON 消息。
        """
        event = msg.get("e")

        if event == "24hrTicker":
            await self._handle_ticker(msg)
        elif event == "kline":
            await self._handle_kline(msg)
        elif event == "depthUpdate":
            await self._handle_orderbook(msg)
        elif event == "trade":
            await self._handle_trade(msg)
        else:
            logger.debug("忽略未知事件类型: %s", event)

    async def _handle_ticker(self, msg: dict[str, Any]) -> None:
        """处理实时行情消息。"""
        ticker = Ticker(
            symbol=msg["s"],
            market=Market.SPOT,  # TODO: 根据端点区分
            exchange="binance",
            last_price=Decimal(msg["c"]),
            bid=Decimal(msg["b"]),
            ask=Decimal(msg["a"]),
            volume_24h=Decimal(msg["v"]),
            timestamp_ns=int(msg["E"]) * 1_000_000,  # 毫秒转纳秒
        )
        await self._event_bus.publish(
            "market.ticker",
            ticker.model_dump(mode="json"),
        )

    async def _handle_kline(self, msg: dict[str, Any]) -> None:
        """处理K线消息。"""
        k = msg["k"]
        kline = Kline(
            symbol=k["s"],
            market=Market.SPOT,
            exchange="binance",
            interval=k["i"],
            open=Decimal(k["o"]),
            high=Decimal(k["h"]),
            low=Decimal(k["l"]),
            close=Decimal(k["c"]),
            volume=Decimal(k["v"]),
            timestamp_ns=int(k["t"]) * 1_000_000,
        )
        await self._event_bus.publish(
            "market.kline",
            kline.model_dump(mode="json"),
        )

    async def _handle_orderbook(self, msg: dict[str, Any]) -> None:
        """处理盘口深度更新。"""
        orderbook = OrderBook(
            symbol=msg["s"],
            exchange="binance",
            bids=[OrderBookLevel(price=Decimal(b[0]), quantity=Decimal(b[1])) for b in msg.get("b", [])],
            asks=[OrderBookLevel(price=Decimal(a[0]), quantity=Decimal(a[1])) for a in msg.get("a", [])],
            timestamp_ns=int(msg["E"]) * 1_000_000,
        )
        await self._event_bus.publish(
            "market.orderbook",
            orderbook.model_dump(mode="json"),
        )

    async def _handle_trade(self, msg: dict[str, Any]) -> None:
        """处理逐笔成交。"""
        trade = Trade(
            symbol=msg["s"],
            exchange="binance",
            price=Decimal(msg["p"]),
            quantity=Decimal(msg["q"]),
            side="buy" if msg["m"] else "sell",  # m=True 表示买方是 maker（主动卖）
            trade_id=str(msg["t"]),
            timestamp_ns=int(msg["T"]) * 1_000_000,
        )
        await self._event_bus.publish(
            "market.trade",
            trade.model_dump(mode="json"),
        )
