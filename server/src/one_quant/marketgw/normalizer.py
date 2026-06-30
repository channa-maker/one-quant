"""
ONE量化 - 行情数据归一化器

将各交易所的原始 WebSocket 数据归一化为 ``one_quant.core.types`` 中的统一领域类型。

支持的交易所:
- Binance (币安): 现货 & 合约
- OKX: 现货 & 合约

归一化原则:
- 使用 Decimal 精确处理价格/数量，避免浮点误差
- 时间戳统一转为纳秒级（Unix epoch）
- symbol 统一为内部格式（如 "BTC/USDT"）

本模块提供纯函数式的归一化接口，方便:
1. 网关模块调用（在线归一化）
2. 批量/离线数据处理
3. 单元测试
"""

from __future__ import annotations

import time
from decimal import Decimal

from one_quant.core.types import (
    Kline,
    Market,
    OrderBook,
    OrderBookLevel,
    Ticker,
    Trade,
)


# ──────────────────────────── 辅助函数 ────────────────────────────


def _to_ns(ts_ms: int) -> int:
    """将毫秒时间戳转为纳秒时间戳"""
    return ts_ms * 1_000_000


def _now_ns() -> int:
    """获取当前纳秒级时间戳"""
    return time.time_ns()


def binance_symbol_to_internal(exchange_symbol: str) -> str:
    """
    将币安交易对符号转为内部统一格式。

    示例: "BTCUSDT" → "BTC/USDT", "ETHUSDT" → "ETH/USDT"

    注意: 简化实现，按已知报价币种后缀拆分。
    生产环境应使用 Instrument Master 提供精确映射。
    """
    upper = exchange_symbol.upper()
    for quote in ("USDT", "BUSD", "USDC", "BTC", "ETH"):
        if upper.endswith(quote) and len(upper) > len(quote):
            base = upper[: -len(quote)]
            return f"{base}/{quote}"
    return exchange_symbol


def okx_symbol_to_internal(exchange_symbol: str) -> str:
    """
    将 OKX 交易对符号转为内部统一格式。

    示例: "BTC-USDT" → "BTC/USDT"
    """
    parts = exchange_symbol.split("-")
    if len(parts) >= 2:
        return f"{parts[0]}/{parts[1]}"
    return exchange_symbol


# ──────────────────────────── 币安归一化 ────────────────────────────


def normalize_binance_ticker(raw: dict, market: Market = Market.SPOT) -> Ticker:
    """
    将币安 24hrTicker 消息归一化为 Ticker。

    原始消息格式::

        {"e":"24hrTicker","s":"BTCUSDT","c":"50000","b":"49999","a":"50001","v":"1234","E":1234567890}

    Args:
        raw: 币安原始 JSON 消息
        market: 市场类型

    Returns:
        Ticker: 归一化后的行情快照
    """
    return Ticker(
        symbol=binance_symbol_to_internal(raw["s"]),
        market=market,
        exchange="binance",
        last_price=Decimal(raw["c"]),
        bid=Decimal(raw["b"]),
        ask=Decimal(raw["a"]),
        volume_24h=Decimal(raw["v"]),
        timestamp_ns=_to_ns(raw.get("E", int(time.time() * 1000))),
    )


def normalize_binance_kline(raw: dict, market: Market = Market.SPOT) -> Kline:
    """
    将币安 kline 消息归一化为 Kline。

    原始消息格式::

        {"e":"kline","s":"BTCUSDT","k":{"t":1234,"o":"50000","h":"50100","l":"49900","c":"50050","v":"100","i":"1m"}}

    Args:
        raw: 币安原始 JSON 消息
        market: 市场类型

    Returns:
        Kline: 归一化后的 K 线数据
    """
    k = raw["k"]
    return Kline(
        symbol=binance_symbol_to_internal(raw["s"]),
        market=market,
        exchange="binance",
        interval=k["i"],
        open=Decimal(k["o"]),
        high=Decimal(k["h"]),
        low=Decimal(k["l"]),
        close=Decimal(k["c"]),
        volume=Decimal(k["v"]),
        timestamp_ns=_to_ns(k["t"]),
    )


def normalize_binance_orderbook(
    raw: dict,
    symbol: str,
    market: Market = Market.SPOT,
) -> OrderBook:
    """
    将币安 depthUpdate 或 partial depth 消息归一化为 OrderBook。

    支持两种格式:
    - depthUpdate: {"b":[["49999","1.5"]],"a":[["50001","2.0"]],"E":1234}
    - partial depth: {"bids":[["49999","1.5"]],"asks":[["50001","2.0"]]}

    Args:
        raw: 币安原始 JSON 消息
        symbol: 内部统一格式的标的符号
        market: 市场类型

    Returns:
        OrderBook: 归一化后的盘口快照
    """
    raw_bids = raw.get("b", raw.get("bids", []))
    raw_asks = raw.get("a", raw.get("asks", []))
    ts_ns = _to_ns(raw["E"]) if "E" in raw else _now_ns()

    return OrderBook(
        symbol=symbol,
        exchange="binance",
        bids=[OrderBookLevel(price=Decimal(lv[0]), quantity=Decimal(lv[1])) for lv in raw_bids],
        asks=[OrderBookLevel(price=Decimal(lv[0]), quantity=Decimal(lv[1])) for lv in raw_asks],
        timestamp_ns=ts_ns,
    )


def normalize_binance_trade(raw: dict, market: Market = Market.SPOT) -> Trade:
    """
    将币安 trade 消息归一化为 Trade。

    原始消息格式::

        {"e":"trade","s":"BTCUSDT","p":"50000","q":"0.5","T":1234,"t":12345,"m":true}

    Args:
        raw: 币安原始 JSON 消息
        market: 市场类型

    Returns:
        Trade: 归一化后的逐笔成交
    """
    # m=True → 买方是 maker → 卖方主动 → side="sell"
    side = "sell" if raw.get("m", False) else "buy"
    return Trade(
        symbol=binance_symbol_to_internal(raw["s"]),
        exchange="binance",
        price=Decimal(raw["p"]),
        quantity=Decimal(raw["q"]),
        side=side,
        trade_id=str(raw.get("t", "")),
        timestamp_ns=_to_ns(raw["T"]),
    )


# ──────────────────────────── OKX 归一化 ────────────────────────────


def normalize_okx_ticker(raw: dict) -> Ticker:
    """
    将 OKX tickers 数据归一化为 Ticker。

    原始数据格式 (data 数组中的单条)::

        {"instId":"BTC-USDT","last":"50000","bidPx":"49999","askPx":"50001","vol24h":"1234","ts":"1234567890000"}

    Args:
        raw: OKX data 数组中的单条消息

    Returns:
        Ticker: 归一化后的行情快照
    """
    symbol = okx_symbol_to_internal(raw["instId"])
    inst_id = raw["instId"]
    market = Market.FUTURES if inst_id.upper().endswith("-SWAP") else Market.SPOT

    return Ticker(
        symbol=symbol,
        market=market,
        exchange="okx",
        last_price=Decimal(raw["last"]),
        bid=Decimal(raw.get("bidPx", "0")),
        ask=Decimal(raw.get("askPx", "0")),
        volume_24h=Decimal(raw.get("vol24h", "0")),
        timestamp_ns=_to_ns(int(raw.get("ts", time.time_ns() // 1_000_000))),
    )


def normalize_okx_kline(raw: list, inst_id: str, interval: str = "1m") -> Kline:
    """
    将 OKX candles 数据归一化为 Kline。

    原始数据格式 (数组): [ts, open, high, low, close, vol, volCcy, volCcyQuote, confirm]

    Args:
        raw: OKX K线数组
        inst_id: OKX 交易对符号（如 "BTC-USDT"）
        interval: K线周期

    Returns:
        Kline: 归一化后的 K 线数据
    """
    symbol = okx_symbol_to_internal(inst_id)
    market = Market.FUTURES if inst_id.upper().endswith("-SWAP") else Market.SPOT

    return Kline(
        symbol=symbol,
        market=market,
        exchange="okx",
        interval=interval,
        open=Decimal(raw[1]),
        high=Decimal(raw[2]),
        low=Decimal(raw[3]),
        close=Decimal(raw[4]),
        volume=Decimal(raw[5]),
        timestamp_ns=_to_ns(int(raw[0])),
    )


def normalize_okx_orderbook(raw: dict, symbol: str) -> OrderBook:
    """
    将 OKX books/books5 数据归一化为 OrderBook。

    原始数据格式::

        {"ts":"1234567890000","bids":[["49999","1.5","0","1"]],"asks":[["50001","2.0","0","1"]]}

    Args:
        raw: OKX data 数组中的单条消息
        symbol: 内部统一格式的标的符号

    Returns:
        OrderBook: 归一化后的盘口快照
    """
    return OrderBook(
        symbol=symbol,
        exchange="okx",
        bids=[OrderBookLevel(price=Decimal(lv[0]), quantity=Decimal(lv[1])) for lv in raw.get("bids", [])],
        asks=[OrderBookLevel(price=Decimal(lv[0]), quantity=Decimal(lv[1])) for lv in raw.get("asks", [])],
        timestamp_ns=_to_ns(int(raw.get("ts", time.time_ns() // 1_000_000))),
    )


def normalize_okx_trade(raw: dict) -> Trade:
    """
    将 OKX trades 数据归一化为 Trade。

    原始数据格式::

        {"instId":"BTC-USDT","tradeId":"12345","px":"50000","sz":"0.5","side":"buy","ts":"1234567890000"}

    Args:
        raw: OKX data 数组中的单条消息

    Returns:
        Trade: 归一化后的逐笔成交
    """
    return Trade(
        symbol=okx_symbol_to_internal(raw["instId"]),
        exchange="okx",
        price=Decimal(raw["px"]),
        quantity=Decimal(raw["sz"]),
        side=raw.get("side", "buy") if raw.get("side") in ("buy", "sell") else "buy",
        trade_id=raw.get("tradeId", ""),
        timestamp_ns=_to_ns(int(raw.get("ts", time.time_ns() // 1_000_000))),
    )
