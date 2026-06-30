"""策略模板 — 快速创建新策略

用法:
    MyStrategy = create_strategy(
        name="my_ema",
        on_kline=lambda self, kline: [Signal(...)] if kline.close > 50000 else []
    )
"""

from __future__ import annotations
from typing import Callable, Any
from one_quant.core.types import Ticker, Kline, Signal, OrderBook, OptionQuote, Fill, PositionState


def create_strategy(
    name: str,
    on_ticker: Callable[[Any, Ticker], list[Signal]] | None = None,
    on_kline: Callable[[Any, Kline], list[Signal]] | None = None,
    on_orderbook: Callable[[Any, OrderBook], list[Signal]] | None = None,
    on_option_quote: Callable[[Any, OptionQuote], list[Signal]] | None = None,
    on_fill: Callable[[Any, Fill], None] | None = None,
    on_recover: Callable[[Any, PositionState], None] | None = None,
) -> type:
    """快速创建策略类

    Args:
        name: 策略名称
        on_ticker: 行情回调
        on_kline: K线回调
        on_orderbook: 盘口回调（可选）
        on_option_quote: 期权报价回调（可选）
        on_fill: 成交回报回调（可选）
        on_recover: 状态恢复回调（可选）

    Returns:
        策略类（可直接实例化使用）
    """
    from one_quant.strategy.contracts import Strategy

    def default_on_ticker(self, ticker):
        return []

    def default_on_kline(self, kline):
        return []

    attrs = {
        "name": name,
        "enabled": True,
        "on_ticker": on_ticker or default_on_ticker,
        "on_kline": on_kline or default_on_kline,
    }

    if on_orderbook:
        attrs["on_orderbook"] = on_orderbook
    if on_option_quote:
        attrs["on_option_quote"] = on_option_quote
    if on_fill:
        attrs["on_fill"] = on_fill
    if on_recover:
        attrs["on_recover"] = on_recover

    strategy_class = type(name, (Strategy,), attrs)
    return strategy_class
