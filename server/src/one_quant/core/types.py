"""
ONE量化 - 核心领域类型定义

所有类型基于 Pydantic v2，不可变（frozen=True），保证数据一致性和线程安全。
使用 Decimal 精确表示金额/数量，纳秒时间戳统一时间精度。
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel

# ──────────────────────────── 枚举 ────────────────────────────


class Market(str, Enum):
    """市场类型枚举"""

    SPOT = "SPOT"  # 现货
    FUTURES = "FUTURES"  # 合约
    OPTION = "OPTION"  # 期权
    STOCK = "STOCK"  # 股票


class InstrumentType(str, Enum):
    """标的类型枚举"""

    SPOT = "SPOT"  # 现货
    PERPETUAL = "PERPETUAL"  # 永续合约
    FUTURES = "FUTURES"  # 交割合约
    OPTION = "OPTION"  # 期权
    STOCK = "STOCK"  # 股票


# ──────────────────────────── 行情数据 ────────────────────────────


class Ticker(BaseModel, frozen=True):
    """实时行情快照

    Attributes:
        symbol: 标的符号（内部统一命名，如 BTC/USDT）
        market: 所属市场
        exchange: 交易所名称
        last_price: 最新成交价
        bid: 买一价
        ask: 卖一价
        volume_24h: 24小时成交量
        timestamp_ns: 纳秒级时间戳（Unix epoch）
    """

    symbol: str
    market: Market
    exchange: str
    last_price: Decimal
    bid: Decimal
    ask: Decimal
    volume_24h: Decimal
    timestamp_ns: int


class Kline(BaseModel, frozen=True):
    """K线（蜡烛图）数据

    Attributes:
        symbol: 标的符号
        market: 所属市场
        exchange: 交易所名称
        interval: K线周期，如 "1s","1m","5m","15m","1h","4h","1d"
        open: 开盘价
        high: 最高价
        low: 最低价
        close: 收盘价
        volume: 成交量
        timestamp_ns: 周期起始纳秒时间戳
    """

    symbol: str
    market: Market
    exchange: str
    interval: str
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    timestamp_ns: int


class Trade(BaseModel, frozen=True):
    """逐笔成交记录

    Attributes:
        symbol: 标的符号
        exchange: 交易所名称
        price: 成交价
        quantity: 成交量
        side: 买卖方向
        trade_id: 交易所成交ID
        timestamp_ns: 纳秒时间戳
    """

    symbol: str
    exchange: str
    price: Decimal
    quantity: Decimal
    side: Literal["buy", "sell"]
    trade_id: str
    timestamp_ns: int


# ──────────────────────────── 盘口数据 ────────────────────────────


class OrderBookLevel(BaseModel, frozen=True):
    """盘口单档报价

    Attributes:
        price: 价格
        quantity: 数量
    """

    price: Decimal
    quantity: Decimal


class OrderBook(BaseModel, frozen=True):
    """盘口快照（订单簿）

    Attributes:
        symbol: 标的符号
        exchange: 交易所名称
        bids: 买盘列表（价格降序）
        asks: 卖盘列表（价格升序）
        timestamp_ns: 纳秒时间戳
    """

    symbol: str
    exchange: str
    bids: list[OrderBookLevel]
    asks: list[OrderBookLevel]
    timestamp_ns: int


# ──────────────────────────── 期权 ────────────────────────────


class OptionQuote(BaseModel, frozen=True):
    """期权报价（含希腊字母）

    Attributes:
        symbol: 期权合约符号
        underlying: 标的资产符号
        strike: 行权价
        expiry: 到期日
        option_type: 期权类型（call/put）
        bid: 买价
        ask: 卖价
        iv: 隐含波动率
        delta: Delta
        gamma: Gamma
        theta: Theta
        vega: Vega
        open_interest: 未平仓量
        timestamp_ns: 纳秒时间戳
    """

    symbol: str
    underlying: str
    strike: Decimal
    expiry: date
    option_type: Literal["call", "put"]
    bid: Decimal
    ask: Decimal
    iv: Decimal
    delta: Decimal
    gamma: Decimal
    theta: Decimal
    vega: Decimal
    open_interest: Decimal
    timestamp_ns: int


# ──────────────────────────── 策略信号 ────────────────────────────


class Signal(BaseModel, frozen=True):
    """策略产生的交易信号

    Attributes:
        symbol: 标的符号
        market: 所属市场
        side: 买卖方向
        strength: 信号强度，取值 0~1
        strategy_name: 产生信号的策略名称
        reason: 中文信号理由（便于人工审查）
        metadata: 附加元数据（因子值、阈值等）
        timestamp_ns: 纳秒时间戳
    """

    symbol: str
    market: Market
    side: Literal["buy", "sell"]
    strength: float
    strategy_name: str
    reason: str
    metadata: dict[str, Any] = {}
    timestamp_ns: int


# ──────────────────────────── 订单与成交 ────────────────────────────


class Fill(BaseModel, frozen=True):
    """成交回报

    Attributes:
        order_id: 关联订单ID
        symbol: 标的符号
        side: 买卖方向
        price: 成交价
        quantity: 成交量
        fee: 手续费
        fee_currency: 手续费币种
        exchange: 交易所名称
        timestamp_ns: 纳秒时间戳
    """

    order_id: str
    symbol: str
    side: Literal["buy", "sell"]
    price: Decimal
    quantity: Decimal
    fee: Decimal
    fee_currency: str
    exchange: str
    timestamp_ns: int


class Order(BaseModel, frozen=True):
    """订单

    Attributes:
        client_order_id: 客户端订单ID（UUIDv4，幂等键）
        symbol: 标的符号
        market: 所属市场
        side: 买卖方向
        order_type: 订单类型（限价/市价/止损限价/止损市价）
        quantity: 委托数量
        price: 委托价格（市价单可为 None）
        stop_price: 触发价格（非止损单为 None）
        status: 订单状态
        exchange: 交易所名称
        timestamp_ns: 纳秒时间戳
    """

    client_order_id: str
    symbol: str
    market: Market
    side: Literal["buy", "sell"]
    order_type: Literal["limit", "market", "stop_limit", "stop_market"]
    quantity: Decimal
    price: Decimal | None
    stop_price: Decimal | None
    status: Literal["pending", "submitted", "partial", "filled", "cancelled", "rejected"]
    exchange: str
    timestamp_ns: int


# ──────────────────────────── 持仓与标的 ────────────────────────────


class PositionState(BaseModel, frozen=True):
    """持仓状态快照

    Attributes:
        symbol: 标的符号
        market: 所属市场
        side: 持仓方向（多/空/空仓）
        quantity: 持仓数量
        entry_price: 开仓均价
        unrealized_pnl: 未实现盈亏
        realized_pnl: 已实现盈亏
        timestamp_ns: 纳秒时间戳
    """

    symbol: str
    market: Market
    side: Literal["long", "short", "flat"]
    quantity: Decimal
    entry_price: Decimal
    unrealized_pnl: Decimal
    realized_pnl: Decimal
    timestamp_ns: int


class Instrument(BaseModel, frozen=True):
    """统一标的定义

    Attributes:
        internal_id: 内部统一ID（跨交易所唯一）
        symbol: 交易所原始符号
        market: 所属市场
        instrument_type: 标的类型
        exchange: 交易所名称
        base_currency: 基础币种
        quote_currency: 计价币种
        tick_size: 最小价格变动
        lot_size: 最小下单数量
        contract_multiplier: 合约乘数（现货默认 1）
        is_active: 是否活跃可交易
    """

    internal_id: str
    symbol: str
    market: Market
    instrument_type: InstrumentType
    exchange: str
    base_currency: str
    quote_currency: str
    tick_size: Decimal
    lot_size: Decimal
    contract_multiplier: Decimal = Decimal("1")
    is_active: bool = True
