"""币安 WebSocket 行情网关 — tick + L2 增量 + K线，归一化到领域类型"""

from __future__ import annotations

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

# ── 币安 WebSocket 端点 ──────────────────────────────────────────────

BINANCE_WS_BASE = "wss://stream.binance.com:9443"
BINANCE_WS_COMBINED = f"{BINANCE_WS_BASE}/stream"
BINANCE_REST_BASE = "https://api.binance.com"


def _to_binance_symbol(internal: str) -> str:
    """内部统一命名 → 币安符号。BTC/USDT → btcusdt"""
    return internal.replace("/", "").lower()


def _from_binance_symbol(binance: str, market: Market) -> str:
    """币安符号 → 内部统一命名。

    简单处理：假设所有加密都是 /USDT 对。
    后续由 Instrument Master 提供精确映射。
    """
    binance = binance.upper()
    if binance.endswith("USDT"):
        return f"{binance[:-4]}/USDT"
    if binance.endswith("BUSD"):
        return f"{binance[:-4]}/BUSD"
    if binance.endswith("BTC"):
        return f"{binance[:-3]}/BTC"
    if binance.endswith("ETH"):
        return f"{binance[:-3]}/ETH"
    return binance


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


class BinanceWSGateway(MarketDataGateway):
    """币安 WebSocket 行情网关。

    订阅三种数据流：
    - <symbol>@miniTicker  → Ticker
    - <symbol>@depth@100ms → OrderBook (L2 增量)
    - <symbol>@trade       → Trade (逐笔成交)
    - <symbol>@kline_<interval> → K线

    归一化为领域类型后发布到 EventBus：
    - market.ticker
    - market.orderbook
    - market.trade
    - market.kline
    """

    exchange = "binance"

    def __init__(
        self,
        event_bus: EventBus,
        kline_intervals: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(event_bus, **kwargs)
        self._kline_intervals = kline_intervals or ["1m", "5m", "1h"]
        self._depth_buffer: dict[str, dict[str, Any]] = {}  # symbol → 缓存的 L2 快照

    # ── 连接 ──────────────────────────────────────────────────────────

    async def _connect(self) -> None:
        """连接币安组合流 WebSocket"""
        url = BINANCE_WS_COMBINED
        self._ws = await websockets.connect(
            url,
            ping_interval=20,
            ping_timeout=10,
            close_timeout=5,
        )
        logger.info("币安 WebSocket 已连接", url=url)

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
        """发送订阅请求（组合流格式）"""
        streams: list[str] = []
        for sym in symbols:
            bn = _to_binance_symbol(sym)
            streams.extend(
                [
                    f"{bn}@miniTicker",
                    f"{bn}@depth@100ms",
                    f"{bn}@trade",
                ]
            )
            for interval in self._kline_intervals:
                mapped = _INTERVAL_MAP.get(interval, interval)
                streams.append(f"{bn}@kline_{mapped}")

        # 分批订阅（币安单次最多 200 个 stream）
        batch_size = 200
        for i in range(0, len(streams), batch_size):
            batch = streams[i : i + batch_size]
            msg = json.dumps({"method": "SUBSCRIBE", "params": batch, "id": 1})
            if self._ws is not None:
                await self._ws.send(msg)
                logger.info(
                    "币安订阅请求已发送",
                    batch_index=i // batch_size,
                    stream_count=len(batch),
                )

    async def _request_snapshot(self, symbols: list[str]) -> None:
        """通过 REST API 请求 L2 深度快照，对齐 WebSocket 增量数据"""
        async with httpx.AsyncClient(timeout=10) as client:
            for sym in symbols:
                try:
                    bn = _to_binance_symbol(sym)
                    resp = await client.get(
                        f"{BINANCE_REST_BASE}/api/v3/depth",
                        params={"symbol": bn.upper(), "limit": 100},
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    self._depth_buffer[sym] = {
                        "bids": {Decimal(p): Decimal(q) for p, q in data.get("bids", [])},
                        "asks": {Decimal(p): Decimal(q) for p, q in data.get("asks", [])},
                        "lastUpdateId": data.get("lastUpdateId", 0),
                    }
                    logger.debug("L2 快照已更新", symbol=sym)
                except Exception:
                    logger.exception("请求 L2 快照失败", symbol=sym)

    # ── 消息处理 ──────────────────────────────────────────────────────

    async def _on_message(self, raw: str | bytes) -> None:
        """处理币安 WebSocket 消息"""
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")

        msg = json.loads(raw)

        # 组合流格式: {"stream": "...", "data": {...}}
        if "stream" in msg:
            stream = msg["stream"]
            data = msg["data"]
        else:
            stream = ""
            data = msg

        event_type = data.get("e", "")

        if event_type == "24hrMiniTicker":
            await self._handle_ticker(data)
        elif event_type == "depthUpdate":
            await self._handle_depth(data)
        elif event_type == "trade":
            await self._handle_trade(data)
        elif event_type == "kline":
            await self._handle_kline(data)
        elif "result" in data or "id" in data:
            # 订阅确认消息，忽略
            logger.debug("币安订阅确认", data=data)
        else:
            logger.debug("未知消息类型", event_type=event_type, stream=stream)

    async def _handle_ticker(self, data: dict[str, Any]) -> None:
        """处理 24hr miniTicker → Ticker"""
        symbol = _from_binance_symbol(data["s"], Market.SPOT)
        ticker = Ticker(
            symbol=symbol,
            market=Market.SPOT,
            exchange="binance",
            last_price=Decimal(data["c"]),
            bid=Decimal(data.get("b", "0")),
            ask=Decimal(data.get("a", "0")),
            volume_24h=Decimal(data["v"]),
            timestamp_ns=time.time_ns(),
        )
        await self._event_bus.publish("market.ticker", ticker.model_dump(mode="json"))

    async def _handle_depth(self, data: dict[str, Any]) -> None:
        """处理 depthUpdate → OrderBook (L2 增量合并)"""
        symbol_str = data["s"]
        internal_sym = _from_binance_symbol(symbol_str, Market.SPOT)

        # 增量合并到本地缓存
        buf = self._depth_buffer.get(internal_sym)
        if buf is None:
            return

        for price_str, qty_str in data.get("b", []):
            price, qty = Decimal(price_str), Decimal(qty_str)
            if qty == 0:
                buf["bids"].pop(price, None)
            else:
                buf["bids"][price] = qty

        for price_str, qty_str in data.get("a", []):
            price, qty = Decimal(price_str), Decimal(qty_str)
            if qty == 0:
                buf["asks"].pop(price, None)
            else:
                buf["asks"][price] = qty

        # 构造 OrderBook（取 top 100）
        bids = sorted(buf["bids"].items(), key=lambda x: x[0], reverse=True)[:100]
        asks = sorted(buf["asks"].items(), key=lambda x: x[0])[:100]

        orderbook = OrderBook(
            symbol=internal_sym,
            exchange="binance",
            bids=[OrderBookLevel(price=p, quantity=q) for p, q in bids],
            asks=[OrderBookLevel(price=p, quantity=q) for p, q in asks],
            timestamp_ns=time.time_ns(),
        )
        await self._event_bus.publish("market.orderbook", orderbook.model_dump(mode="json"))

    async def _handle_trade(self, data: dict[str, Any]) -> None:
        """处理 trade → Trade"""
        symbol = _from_binance_symbol(data["s"], Market.SPOT)
        trade = Trade(
            symbol=symbol,
            exchange="binance",
            price=Decimal(data["p"]),
            quantity=Decimal(data["q"]),
            side="buy" if data["m"] is False else "sell",  # m=True → buyer is maker → sell
            trade_id=str(data["t"]),
            timestamp_ns=int(data["T"]) * 1_000_000,  # 毫秒→纳秒
        )
        await self._event_bus.publish("market.trade", trade.model_dump(mode="json"))

    async def _handle_kline(self, data: dict[str, Any]) -> None:
        """处理 kline → KLine"""
        k = data["k"]
        symbol = _from_binance_symbol(data["s"], Market.SPOT)
        kline = Kline(
            symbol=symbol,
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
        await self._event_bus.publish("market.kline", kline.model_dump(mode="json"))

    # ── 重写 receive_loop 以适配 websockets 库 ────────────────────────

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
                    "币安消息处理异常",
                    msg_preview=str(message)[:200],
                )
