"""
ONE量化 - 行情数据归一化器

将各交易所的原始 WebSocket 数据归一化为 one_quant.core.types 中的统一领域类型。

支持的交易所:
- Binance (币安): 现货 & 合约
- OKX: 现货 & 合约

归一化原则:
- 使用 Decimal 精确处理价格/数量，避免浮点误差
- 时间戳统一转为纳秒级（Unix epoch）
- symbol 统一为内部格式（如 "BTC/USDT"）
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


def _to_ns_from_sec(ts_sec: float) -> int:
    """将秒级时间戳转为纳秒时间戳"""
    return int(ts_sec * 1_000_000_000)


def _now_ns() -> int:
    """获取当前纳秒级时间戳"""
    return time.time_ns()


def _binance_symbol_to_internal(exchange_symbol: str) -> str:
    """
    将币安交易对符号转为内部统一格式。

    示例: "BTCUSDT" -> "BTC/USDT", "ETHUSDT" -> "ETH/USDT"

    注意: 此为简化实现，通过已知的报价币种后缀拆分。
    生产环境应使用交易所的 exchangeInfo 接口获取精确映射。
    """
    # 常见报价币种后缀（按长度降序排列，避免误匹配）
    quote_currencies = [
        "USDT", "BUSD", "USDC", "TUSD",
        "BTC", "ETH", "BNB",
        "EUR", "GBP", "AUD", "BRL",
        "USD",
    ]
    upper = exchange_symbol.upper()
    for quote in quote_currencies:
        if upper.endswith(quote) and len(upper) > len(quote):
            base = upper[: -len(quote)]
            return f"{base}/{quote}"
    # 无法识别时原样返回
    return exchange_symbol


def _okx_symbol_to_internal(exchange_symbol: str) -> str:
    """
    将 OKX 交易对符号转为内部统一格式。

    示例: "BTC-USDT" -> "BTC/USDT"
    """
    parts = exchange_symbol.split("-")
    if len(parts) == 2:
        return f"{parts[0]}/{parts[1]}"
    return exchange_symbol


def _is_perpetual_binance(exchange_symbol: str) -> bool:
    """判断币安交易对是否为永续合约（以 USDT 结尾且有 PERP 标识，或 fstream 域名）"""
    # 简化判断: 实际应从 exchange info 获取
    upper = exchange_symbol.upper()
    return upper.endswith("PERP") or False


def _is_perpetual_okx(inst_id: str) -> bool:
    """判断 OKX 合约是否为永续（如 BTC-USDT-SWAP）"""
    return inst_id.upper().endswith("-SWAP")


# ──────────────────────────── 币安归一化 ────────────────────────────


def normalize_binance_ticker(raw: dict, market: Market = Market.SPOT) -> Ticker:
    """
    将币安 24hrTicker 消息归一化为 Ticker。

    原始消息格式::

        {
            "e": "24hrTicker",
            "s": "BTCUSDT",
            "c": "50000.00",   # 最新价
            "b": "49999.00",   # 买一价
            "a": "50001.00",   # 卖一价
            "v": "1234.56",    # 24h成交量
            "E": 1234567890    # 事件时间(毫秒)
        }

    Args:
        raw: 币安原始 JSON 消息
        market: 市场类型，默认 SPOT

    Returns:
        Ticker: 归一化后的行情快照
    """
    symbol = _binance_symbol_to_internal(raw["s"])
    ts_ns = _to_ns(raw.get("E", int(time.time() * 1000)))

    return Ticker(
        symbol=symbol,
        market=market,
        exchange="binance",
        last_price=Decimal(raw["c"]),
        bid=Decimal(raw["b"]),
        ask=Decimal(raw["a"]),
        volume_24h=Decimal(raw["v"]),
        timestamp_ns=ts_ns,
    )


def normalize_binance_kline(raw: dict, market: Market = Market.SPOT) -> Kline:
    """
    将币安 kline 消息归一化为 Kline。

    原始消息格式::

        {
            "e": "kline",
            "s": "BTCUSDT",
            "k": {
                "t": 1234567890,  # K线起始时间(毫秒)
                "o": "50000",     # 开盘价
                "h": "50100",     # 最高价
                "l": "49900",     # 最低价
                "c": "50050",     # 收盘价
                "v": "100",       # 成交量
                "i": "1m"         # K线周期
            }
        }

    Args:
        raw: 币安原始 JSON 消息
        market: 市场类型，默认 SPOT

    Returns:
        Kline: 归一化后的 K 线数据
    """
    kline = raw["k"]
    symbol = _binance_symbol_to_internal(raw["s"])
    ts_ns = _to_ns(kline["t"])

    return Kline(
        symbol=symbol,
        market=market,
        exchange="binance",
        interval=kline["i"],
        open=Decimal(kline["o"]),
        high=Decimal(kline["h"]),
        low=Decimal(kline["l"]),
        close=Decimal(kline["c"]),
        volume=Decimal(kline["v"]),
        timestamp_ns=ts_ns,
    )


def normalize_binance_orderbook(
    raw: dict,
    symbol: str,
    market: Market = Market.SPOT,
) -> OrderBook:
    """
    将币安 depthUpdate 或 partial depth 消息归一化为 OrderBook。

    原始消息格式 (diff depth stream)::

        {
            "e": "depthUpdate",
            "s": "BTCUSDT",
            "b": [["49999", "1.5"], ["49998", "2.0"]],  # 买盘
            "a": [["50001", "2.0"], ["50002", "1.0"]]   # 卖盘
        }

    原始消息格式 (partial depth, 无 e/s 字段)::

        {
            "lastUpdateId": 12345,
            "bids": [["49999", "1.5"]],
            "asks": [["50001", "2.0"]]
        }

    Args:
        raw: 币安原始 JSON 消息
        symbol: 内部统一格式的标的符号（如 "BTC/USDT"）
        market: 市场类型，默认 SPOT

    Returns:
        OrderBook: 归一化后的盘口快照
    """
    # 兼容两种格式: depthUpdate 用 "b"/"a", partial depth 用 "bids"/"asks"
    raw_bids = raw.get("b", raw.get("bids", []))
    raw_asks = raw.get("a", raw.get("asks", []))

    # 如果消息中有事件时间戳，使用它；否则用当前时间
    ts_ns = _to_ns(raw["E"]) if "E" in raw else _now_ns()

    bids = [
        OrderBookLevel(price=Decimal(level[0]), quantity=Decimal(level[1]))
        for level in raw_bids
    ]
    asks = [
        OrderBookLevel(price=Decimal(level[0]), quantity=Decimal(level[1]))
        for level in raw_asks
    ]

    return OrderBook(
        symbol=symbol,
        exchange="binance",
        bids=bids,
        asks=asks,
        timestamp_ns=ts_ns,
    )


def normalize_binance_trade(raw: dict, market: Market = Market.SPOT) -> Trade:
    """
    将币安 trade 消息归一化为 Trade。

    原始消息格式::

        {
            "e": "trade",
            "s": "BTCUSDT",
            "p": "50000",       # 成交价
            "q": "0.5",         # 成交量
            "T": 1234567890,    # 成交时间(毫秒)
            "t": 123456789,     # 成交ID
            "m": true           # 是否买方主动成交
        }

    Args:
        raw: 币安原始 JSON 消息
        market: 市场类型，默认 SPOT

    Returns:
        Trade: 归一化后的逐笔成交
    """
    symbol = _binance_symbol_to_internal(raw["s"])
    ts_ns = _to_ns(raw["T"])

    # m=True 表示买方是 taker（卖方主动），side 应为 "sell"
    # m=False 表示卖方是 taker（买方主动），side 应为 "buy"
    side = "sell" if raw.get("m", False) else "buy"

    return Trade(
        symbol=symbol,
        exchange="binance",
        price=Decimal(raw["p"]),
        quantity=Decimal(raw["q"]),
        side=side,
        trade_id=str(raw.get("t", "")),
        timestamp_ns=ts_ns,
    )


# ──────────────────────────── OKX 归一化 ────────────────────────────


def normalize_okx_ticker(raw: dict) -> Ticker:
    """
    将 OKX tickers 消息归一化为 Ticker。

    原始消息格式::

        {
            "arg": {"channel": "tickers", "instId": "BTC-USDT"},
            "data": [{
                "instId": "BTC-USDT",
                "last": "50000.00",
                "bidPx": "49999.00",
                "askPx": "50001.00",
                "vol24h": "1234.56",    # 24h成交量(币)
                "ts": "1234567890000"   # 时间戳(毫秒)
            }]
        }

    Args:
        raw: OKX 原始 JSON 消息（含 arg 和 data 字段）

    Returns:
        Ticker: 归一化后的行情快照
    """
    data = raw["data"][0]
    symbol = _okx_symbol_to_internal(data["instId"])

    # 判断市场类型
    inst_id = data["instId"]
    if _is_perpetual_okx(inst_id):
        market = Market.FUTURES
    else:
        market = Market.SPOT

    ts_ns = _to_ns(int(data["ts"]))

    return Ticker(
        symbol=symbol,
        market=market,
        exchange="okx",
        last_price=Decimal(data["last"]),
        bid=Decimal(data["bidPx"]),
        ask=Decimal(data["askPx"]),
        volume_24h=Decimal(data["vol24h"]),
        timestamp_ns=ts_ns,
    )


def normalize_okx_kline(raw: dict, interval: str = "1m") -> Kline:
    """
    将 OKX candles 消息归一化为 Kline。

    原始消息格式::

        {
            "arg": {"channel": "candles1m", "instId": "BTC-USDT"},
            "data": [["1234567890000", "50000", "50100", "49900", "50050", "100", "5000000"]]
        }

    OKX K线数组顺序: [ts, open, high, low, close, vol, volCcy]

    Args:
        raw: OKX 原始 JSON 消息
        interval: K 线周期，默认 "1m"

    Returns:
        Kline: 归一化后的 K 线数据
    """
    data = raw["data"][0]
    inst_id = raw["arg"]["instId"]
    symbol = _okx_symbol_to_internal(inst_id)

    # 判断市场类型
    if _is_perpetual_okx(inst_id):
        market = Market.FUTURES
    else:
        market = Market.SPOT

    ts_ns = _to_ns(int(data[0]))

    return Kline(
        symbol=symbol,
        market=market,
        exchange="okx",
        interval=interval,
        open=Decimal(data[1]),
        high=Decimal(data[2]),
        low=Decimal(data[3]),
        close=Decimal(data[4]),
        volume=Decimal(data[5]),
        timestamp_ns=ts_ns,
    )


def normalize_okx_orderbook(raw: dict, symbol: str) -> OrderBook:
    """
    将 OKX books 消息归一化为 OrderBook。

    原始消息格式::

        {
            "arg": {"channel": "books", "instId": "BTC-USDT"},
            "data": [{
                "ts": "1234567890000",
                "bids": [["49999", "1.5", "0", "1"]],
                "asks": [["50001", "2.0", "0", "1"]]
            }]
        }

    OKX 盘口数组顺序: [price, quantity, liquidated_orders, order_count]

    Args:
        raw: OKX 原始 JSON 消息
        symbol: 内部统一格式的标的符号

    Returns:
        OrderBook: 归一化后的盘口快照
    """
    data = raw["data"][0]
    ts_ns = _to_ns(int(data["ts"]))

    bids = [
        OrderBookLevel(price=Decimal(level[0]), quantity=Decimal(level[1]))
        for level in data.get("bids", [])
    ]
    asks = [
        OrderBookLevel(price=Decimal(level[0]), quantity=Decimal(level[1]))
        for level in data.get("asks", [])
    ]

    return OrderBook(
        symbol=symbol,
        exchange="okx",
        bids=bids,
        asks=asks,
        timestamp_ns=ts_ns,
    )


def normalize_okx_trade(raw: dict) -> Trade:
    """
    将 OKX trades 消息归一化为 Trade。

    原始消息格式::

        {
            "arg": {"channel": "trades", "instId": "BTC-USDT"},
            "data": [{
                "instId": "BTC-USDT",
                "tradeId": "12345",
                "px": "50000",
                "sz": "0.5",
                "side": "buy",
                "ts": "1234567890000"
            }]
        }

    Args:
        raw: OKX 原始 JSON 消息

    Returns:
        Trade: 归一化后的逐笔成交
    """
    data = raw["data"][0]
    symbol = _okx_symbol_to_internal(data["instId"])
    ts_ns = _to_ns(int(data["ts"]))

    return Trade(
        symbol=symbol,
        exchange="okx",
        price=Decimal(data["px"]),
        quantity=Decimal(data["sz"]),
        side=data["side"],  # OKX 直接返回 "buy" / "sell"
        trade_id=data.get("tradeId", ""),
        timestamp_ns=ts_ns,
    )
