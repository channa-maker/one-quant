"""
ONE量化 - 币安 WebSocket 行情接入

实现币安交易所的 WebSocket 实时行情接入。

连接地址:
- 现货: wss://stream.binance.com:9443/ws
- 合约: wss://fstream.binance.com/ws

支持的数据流:
- @ticker        → market.ticker (24hr Ticker)
- @kline_<i>     → market.kline  (K线)
- @depth@100ms   → market.orderbook (盘口 L2)
- @trade         → market.trade  (逐笔成交)

币安 WebSocket 文档:
https://binance-docs.github.io/apidocs/spot/en/#websocket-market-streams
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from decimal import Decimal
from typing import Any, Literal

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

# ── 币安 WebSocket 端点 ──────────────────────────────────────────────

BINANCE_WS_SPOT = "wss://stream.binance.com:9443/ws"
BINANCE_WS_FUTURES = "wss://fstream.binance.com/ws"

# 心跳配置
PING_INTERVAL = 20
PING_TIMEOUT = 10


def _to_binance_symbol(internal: str) -> str:
    """内部统一命名 → 币安符号。BTC/USDT → btcusdt"""
    return internal.replace("/", "").lower()


def _from_binance_symbol(binance: str) -> str:
    """币安符号 → 内部统一命名。BTCUSDT → BTC/USDT

    简化实现，按已知报价币种后缀拆分。
    生产环境应使用 Instrument Master 提供精确映射。
    """
    upper = binance.upper()
    for quote in ("USDT", "BUSD", "USDC", "BTC", "ETH"):
        if upper.endswith(quote) and len(upper) > len(quote):
            return f"{upper[: -len(quote)]}/{quote}"
    return upper


# ── K线周期映射 ──────────────────────────────────────────────────────

_INTERVAL_MAP: dict[str, str] = {
    "1s": "1s",
    "1m": "1m",
    "3m": "3m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1h": "1h",
    "2h": "2h",
    "4h": "4h",
    "6h": "6h",
    "8h": "8h",
    "12h": "12h",
    "1d": "1d",
    "3d": "3d",
    "1w": "1w",
    "1M": "1M",
}


class BinanceMarketGateway(MarketGateway):
    """
    币安 WebSocket 行情网关。

    通过组合流（Combined Stream）同时订阅多个 symbol 的多种数据类型。
    数据经归一化后发布到 EventBus 对应通道。

    使用示例::

        from one_quant.infra.event_bus import InMemoryEventBus
        from one_quant.marketgw import BinanceMarketGateway

        bus = InMemoryEventBus()
        await bus.start()

        gw = BinanceMarketGateway(event_bus=bus, is_futures=False)
        await gw.start()
        await gw.connect()
        await gw.subscribe_ticker(["BTC/USDT", "ETH/USDT"])

        # 持续运行...
        await asyncio.Event().wait()
    """

    def __init__(
        self,
        event_bus: EventBus,
        is_futures: bool = False,
    ) -> None:
        """
        初始化币安行情网关。

        Args:
            event_bus: 事件总线实例
            is_futures: 是否使用合约端点，默认 False（现货）
        """
        super().__init__(event_bus)
        self._is_futures = is_futures
        self._ws_url = BINANCE_WS_FUTURES if is_futures else BINANCE_WS_SPOT
        self._ws: websockets.ClientConnection | None = None
        self._reconnect = ReconnectManager(initial_delay=1.0, max_delay=60.0)
        self._streams: list[str] = []  # 已订阅的 stream（用于重连后重新订阅）
        self._recv_task: asyncio.Task[None] | None = None
        self._seq_counter = 0

    async def connect(self) -> None:
        """建立 WebSocket 连接并启动接收循环"""
        logger.info("币安网关: 正在连接 %s", self._ws_url)
        self._ws = await websockets.connect(
            self._ws_url,
            ping_interval=PING_INTERVAL,
            ping_timeout=PING_TIMEOUT,
            close_timeout=5,
        )
        logger.info("币安网关: WebSocket 连接成功")
        self._recv_task = asyncio.create_task(self._receive_loop())

    async def disconnect(self) -> None:
        """断开 WebSocket 连接"""
        if self._recv_task and not self._recv_task.done():
            self._recv_task.cancel()
            try:
                await self._recv_task
            except asyncio.CancelledError:
                pass
        if self._ws:
            await self._ws.close()
            self._ws = None
        logger.info("币安网关: 已断开连接")

    async def _receive_loop(self) -> None:
        """WebSocket 消息接收循环"""
        assert self._ws is not None
        try:
            async for raw_msg in self._ws:
                if not self._running:
                    break
                try:
                    msg = json.loads(raw_msg)
                    await self._dispatch(msg)
                except json.JSONDecodeError:
                    logger.warning("币安网关: 无法解析消息: %s", raw_msg[:200])
                except Exception:
                    logger.exception("币安网关: 消息处理异常")
        except ConnectionClosed as exc:
            logger.warning("币安网关: 连接断开 code=%s reason=%s", exc.code, exc.reason)
            raise
        except asyncio.CancelledError:
            raise

    async def _dispatch(self, msg: dict[str, Any]) -> None:
        """
        分发消息到对应的归一化处理函数。

        支持组合流格式 {"stream": "...", "data": {...}} 和单流格式。
        """
        # 组合流格式
        data = msg.get("data", msg)
        event_type = data.get("e", "")

        market = Market.FUTURES if self._is_futures else Market.SPOT

        if event_type == "24hrTicker":
            ticker = Ticker(
                symbol=_from_binance_symbol(data["s"]),
                market=market,
                exchange="binance",
                last_price=Decimal(data["c"]),
                bid=Decimal(data["b"]),
                ask=Decimal(data["a"]),
                volume_24h=Decimal(data["v"]),
                timestamp_ns=int(data.get("E", time.time() * 1000)) * 1_000_000,
            )
            await self._event_bus.publish("market.ticker", ticker.model_dump(mode="json"))

        elif event_type == "kline":
            k = data["k"]
            kline = Kline(
                symbol=_from_binance_symbol(data["s"]),
                market=market,
                exchange="binance",
                interval=k["i"],
                open=Decimal(k["o"]),
                high=Decimal(k["h"]),
                low=Decimal(k["l"]),
                close=Decimal(k["c"]),
                volume=Decimal(k["v"]),
                timestamp_ns=int(k["t"]) * 1_000_000,
            )
            await self._event_bus.publish("market.kline", kline.model_dump(mode="json"))

        elif event_type == "depthUpdate":
            symbol = _from_binance_symbol(data.get("s", ""))
            bids = [
                OrderBookLevel(price=Decimal(lv[0]), quantity=Decimal(lv[1]))
                for lv in data.get("b", [])
            ]
            asks = [
                OrderBookLevel(price=Decimal(lv[0]), quantity=Decimal(lv[1]))
                for lv in data.get("a", [])
            ]
            ts_ns = int(data["E"]) * 1_000_000 if "E" in data else time.time_ns()
            orderbook = OrderBook(
                symbol=symbol,
                exchange="binance",
                bids=bids,
                asks=asks,
                timestamp_ns=ts_ns,
            )
            await self._event_bus.publish("market.orderbook", orderbook.model_dump(mode="json"))

        elif event_type == "trade":
            symbol = _from_binance_symbol(data["s"])
            # m=True → 买方是 maker → 卖方主动 → side="sell"
            side: Literal["buy", "sell"] = "sell" if data.get("m", False) else "buy"
            trade = Trade(
                symbol=symbol,
                exchange="binance",
                price=Decimal(data["p"]),
                quantity=Decimal(data["q"]),
                side=side,
                trade_id=str(data.get("t", "")),
                timestamp_ns=int(data["T"]) * 1_000_000,
            )
            await self._event_bus.publish("market.trade", trade.model_dump(mode="json"))

    async def _send_subscribe(self, streams: list[str]) -> None:
        """发送订阅请求"""
        if self._ws is None:
            raise RuntimeError("WebSocket 未连接")
        self._seq_counter += 1
        msg = json.dumps(
            {
                "method": "SUBSCRIBE",
                "params": streams,
                "id": self._seq_counter,
            }
        )
        await self._ws.send(msg)
        logger.info("币安网关: 订阅 %d 个 stream", len(streams))

    async def subscribe_ticker(self, symbols: list[str]) -> None:
        """订阅 24hr Ticker"""
        streams = [f"{_to_binance_symbol(s)}@ticker" for s in symbols]
        self._streams.extend(streams)
        await self._send_subscribe(streams)

    async def subscribe_kline(self, symbols: list[str], interval: str = "1m") -> None:
        """订阅 K 线"""
        mapped = _INTERVAL_MAP.get(interval, interval)
        streams = [f"{_to_binance_symbol(s)}@kline_{mapped}" for s in symbols]
        self._streams.extend(streams)
        await self._send_subscribe(streams)

    async def subscribe_orderbook(self, symbols: list[str], depth: int = 20) -> None:
        """订阅盘口 L2"""
        streams = [f"{_to_binance_symbol(s)}@depth{depth}@100ms" for s in symbols]
        self._streams.extend(streams)
        await self._send_subscribe(streams)

    async def subscribe_trades(self, symbols: list[str]) -> None:
        """订阅逐笔成交"""
        streams = [f"{_to_binance_symbol(s)}@trade" for s in symbols]
        self._streams.extend(streams)
        await self._send_subscribe(streams)

    async def start(self) -> None:
        """启动网关（含断线重连）"""
        self._running = True
        logger.info("币安网关: 启动 (futures=%s)", self._is_futures)

        async def _connect_and_run():
            await self.connect()
            if self._recv_task:
                await self._recv_task

        async def _on_connected():
            if self._streams:
                await self._send_subscribe(self._streams)

        await self._reconnect.run_forever(
            connect_fn=_connect_and_run,
            on_connected=_on_connected,
            should_continue=lambda: self._running,
        )

    async def stop(self) -> None:
        """停止网关"""
        self._running = False
        await self.disconnect()
        logger.info("币安网关: 已停止")
