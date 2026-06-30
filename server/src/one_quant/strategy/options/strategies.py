"""期权策略实现 — 垂直价差、跨式、铁鹰、日历价差、领口、Delta中性"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from one_quant.core.types import Kline, Market, OptionQuote, Signal, Ticker
from one_quant.strategy.contracts import Strategy


class VerticalSpreadStrategy(Strategy):
    """垂直价差策略。"""

    name = "vertical_spread"
    enabled = False

    def __init__(
        self,
        spread_width: Decimal = Decimal("500"),
        delta_threshold: Decimal = Decimal("0.3"),
    ):
        self.spread_width = spread_width
        self.delta_threshold = delta_threshold

    def on_ticker(self, ticker: Ticker) -> list[Signal]:
        return []

    def on_kline(self, kline: Kline) -> list[Signal]:
        return []

    def on_option_quote(self, q: OptionQuote) -> list[Signal]:
        signals: list[Signal] = []
        delta = q.delta
        abs_delta = abs(delta)

        if q.option_type == "call" and delta >= self.delta_threshold:
            strength = min(float(abs_delta / Decimal("0.5")), 1.0)
            signals.append(
                Signal(
                    symbol=q.symbol,
                    market=Market.OPTION,
                    side="buy",
                    strength=strength,
                    strategy_name=self.name,
                    reason=(
                        f"Bull Call Spread：Delta={delta}，行权价={q.strike}，"
                        f"到期={q.expiry}，预期温和上涨"
                    ),
                    metadata={
                        "spread_type": "bull_call",
                        "strike": str(q.strike),
                        "expiry": q.expiry.isoformat(),
                        "delta": str(delta),
                        "iv": str(q.iv),
                    },
                    timestamp_ns=q.timestamp_ns,
                )
            )

        if q.option_type == "put" and delta <= -self.delta_threshold:
            strength = min(float(abs_delta / Decimal("0.5")), 1.0)
            signals.append(
                Signal(
                    symbol=q.symbol,
                    market=Market.OPTION,
                    side="sell",
                    strength=strength,
                    strategy_name=self.name,
                    reason=(
                        f"Bear Put Spread：Delta={delta}，行权价={q.strike}，"
                        f"到期={q.expiry}，预期温和下跌"
                    ),
                    metadata={
                        "spread_type": "bear_put",
                        "strike": str(q.strike),
                        "expiry": q.expiry.isoformat(),
                        "delta": str(delta),
                        "iv": str(q.iv),
                    },
                    timestamp_ns=q.timestamp_ns,
                )
            )

        return signals


class StraddleStrategy(Strategy):
    """跨式策略。"""

    name = "straddle"
    enabled = False

    def __init__(
        self,
        iv_percentile_low: float = 0.2,
        iv_percentile_high: float = 0.8,
    ):
        self.iv_percentile_low = iv_percentile_low
        self.iv_percentile_high = iv_percentile_high

    def on_ticker(self, ticker: Ticker) -> list[Signal]:
        return []

    def on_kline(self, kline: Kline) -> list[Signal]:
        return []

    def on_option_quote(self, q: OptionQuote) -> list[Signal]:
        signals: list[Signal] = []
        abs_delta = abs(q.delta)
        iv = float(q.iv)

        is_atm = Decimal("0.45") <= abs_delta <= Decimal("0.55")
        if not is_atm:
            return signals

        if iv < self.iv_percentile_low:
            strength = max(0.0, min(1.0, (self.iv_percentile_low - iv) / self.iv_percentile_low))
            signals.append(
                Signal(
                    symbol=q.symbol,
                    market=Market.OPTION,
                    side="buy",
                    strength=strength,
                    strategy_name=self.name,
                    reason=f"买入跨式：IV={iv:.1%}（低位），ATM期权 Delta={q.delta}，预期大波动",
                    metadata={
                        "strategy_variant": "long_straddle",
                        "strike": str(q.strike),
                        "expiry": q.expiry.isoformat(),
                        "iv": str(q.iv),
                        "delta": str(q.delta),
                    },
                    timestamp_ns=q.timestamp_ns,
                )
            )

        if iv > self.iv_percentile_high:
            strength = max(
                0.0,
                min(1.0, (iv - self.iv_percentile_high) / (1.0 - self.iv_percentile_high)),
            )
            signals.append(
                Signal(
                    symbol=q.symbol,
                    market=Market.OPTION,
                    side="sell",
                    strength=strength,
                    strategy_name=self.name,
                    reason=f"卖出跨式：IV={iv:.1%}（高位），ATM期权 Delta={q.delta}，预期横盘",
                    metadata={
                        "strategy_variant": "short_straddle",
                        "strike": str(q.strike),
                        "expiry": q.expiry.isoformat(),
                        "iv": str(q.iv),
                        "delta": str(q.delta),
                    },
                    timestamp_ns=q.timestamp_ns,
                )
            )

        return signals


class IronCondorStrategy(Strategy):
    """铁鹰策略。"""

    name = "iron_condor"
    enabled = False

    def __init__(
        self,
        wing_width: Decimal = Decimal("200"),
        min_premium: Decimal = Decimal("10"),
        delta_short: Decimal = Decimal("0.3"),
    ):
        self.wing_width = wing_width
        self.min_premium = min_premium
        self.delta_short = delta_short

    def on_ticker(self, ticker: Ticker) -> list[Signal]:
        return []

    def on_kline(self, kline: Kline) -> list[Signal]:
        return []

    def on_option_quote(self, q: OptionQuote) -> list[Signal]:
        signals: list[Signal] = []
        abs_delta = abs(q.delta)
        mid_price = (q.bid + q.ask) / Decimal("2")

        delta_ok = abs_delta >= (self.delta_short - Decimal("0.05")) and abs_delta <= (
            self.delta_short + Decimal("0.05")
        )
        if not delta_ok:
            return signals

        if mid_price < self.min_premium:
            return signals

        if q.option_type == "call":
            signals.append(
                Signal(
                    symbol=q.symbol,
                    market=Market.OPTION,
                    side="sell",
                    strength=0.7,
                    strategy_name=self.name,
                    reason=f"铁鹰-卖出Call腿：Delta={q.delta}，行权价={q.strike}，权利金={mid_price}",
                    metadata={
                        "leg": "short_call",
                        "strike": str(q.strike),
                        "expiry": q.expiry.isoformat(),
                        "delta": str(q.delta),
                        "premium": str(mid_price),
                        "wing_width": str(self.wing_width),
                    },
                    timestamp_ns=q.timestamp_ns,
                )
            )
        elif q.option_type == "put":
            signals.append(
                Signal(
                    symbol=q.symbol,
                    market=Market.OPTION,
                    side="sell",
                    strength=0.7,
                    strategy_name=self.name,
                    reason=f"铁鹰-卖出Put腿：Delta={q.delta}，行权价={q.strike}，权利金={mid_price}",
                    metadata={
                        "leg": "short_put",
                        "strike": str(q.strike),
                        "expiry": q.expiry.isoformat(),
                        "delta": str(q.delta),
                        "premium": str(mid_price),
                        "wing_width": str(self.wing_width),
                    },
                    timestamp_ns=q.timestamp_ns,
                )
            )

        return signals


class CalendarSpreadStrategy(Strategy):
    """日历价差策略。"""

    name = "calendar_spread"
    enabled = False

    def __init__(
        self,
        min_dte_near: int = 7,
        max_dte_near: int = 30,
        min_dte_far: int = 60,
    ):
        self.min_dte_near = min_dte_near
        self.max_dte_near = max_dte_near
        self.min_dte_far = min_dte_far

    def on_ticker(self, ticker: Ticker) -> list[Signal]:
        return []

    def on_kline(self, kline: Kline) -> list[Signal]:
        return []

    def on_option_quote(self, q: OptionQuote) -> list[Signal]:
        signals: list[Signal] = []
        dte = (q.expiry - date.today()).days
        abs_delta = abs(q.delta)
        is_atm = Decimal("0.40") <= abs_delta <= Decimal("0.60")

        if not is_atm:
            return signals

        if self.min_dte_near <= dte <= self.max_dte_near:
            signals.append(
                Signal(
                    symbol=q.symbol,
                    market=Market.OPTION,
                    side="sell",
                    strength=0.6,
                    strategy_name=self.name,
                    reason=f"日历价差-卖出近月：DTE={dte}，Delta={q.delta}，行权价={q.strike}",
                    metadata={
                        "leg": "short_near_term",
                        "dte": dte,
                        "strike": str(q.strike),
                        "expiry": q.expiry.isoformat(),
                        "option_type": q.option_type,
                    },
                    timestamp_ns=q.timestamp_ns,
                )
            )

        if dte >= self.min_dte_far:
            signals.append(
                Signal(
                    symbol=q.symbol,
                    market=Market.OPTION,
                    side="buy",
                    strength=0.6,
                    strategy_name=self.name,
                    reason=f"日历价差-买入远月：DTE={dte}，Delta={q.delta}，行权价={q.strike}",
                    metadata={
                        "leg": "long_far_term",
                        "dte": dte,
                        "strike": str(q.strike),
                        "expiry": q.expiry.isoformat(),
                        "option_type": q.option_type,
                    },
                    timestamp_ns=q.timestamp_ns,
                )
            )

        return signals


class CollarStrategy(Strategy):
    """领口策略。"""

    name = "collar"
    enabled = False

    def __init__(
        self,
        put_delta: Decimal = Decimal("0.2"),
        call_delta: Decimal = Decimal("0.3"),
    ):
        self.put_delta = put_delta
        self.call_delta = call_delta

    def on_ticker(self, ticker: Ticker) -> list[Signal]:
        return []

    def on_kline(self, kline: Kline) -> list[Signal]:
        return []

    def on_option_quote(self, q: OptionQuote) -> list[Signal]:
        signals: list[Signal] = []
        abs_delta = abs(q.delta)

        if q.option_type == "put":
            delta_ok = abs_delta >= (self.put_delta - Decimal("0.05")) and abs_delta <= (
                self.put_delta + Decimal("0.05")
            )
            if delta_ok:
                signals.append(
                    Signal(
                        symbol=q.symbol,
                        market=Market.OPTION,
                        side="buy",
                        strength=0.8,
                        strategy_name=self.name,
                        reason=f"领口策略-买入保护性Put：Delta={q.delta}，行权价={q.strike}，保护下行风险",
                        metadata={
                            "leg": "protective_put",
                            "strike": str(q.strike),
                            "expiry": q.expiry.isoformat(),
                            "delta": str(q.delta),
                        },
                        timestamp_ns=q.timestamp_ns,
                    )
                )

        if q.option_type == "call":
            delta_ok = abs_delta >= (self.call_delta - Decimal("0.05")) and abs_delta <= (
                self.call_delta + Decimal("0.05")
            )
            if delta_ok:
                signals.append(
                    Signal(
                        symbol=q.symbol,
                        market=Market.OPTION,
                        side="sell",
                        strength=0.8,
                        strategy_name=self.name,
                        reason=f"领口策略-卖出备兑Call：Delta={q.delta}，行权价={q.strike}，降低对冲成本",
                        metadata={
                            "leg": "covered_call",
                            "strike": str(q.strike),
                            "expiry": q.expiry.isoformat(),
                            "delta": str(q.delta),
                        },
                        timestamp_ns=q.timestamp_ns,
                    )
                )

        return signals


class DeltaNeutralStrategy(Strategy):
    """Delta 中性策略。"""

    name = "delta_neutral"
    enabled = False

    def __init__(
        self,
        delta_tolerance: Decimal = Decimal("50"),
        hedge_ratio: float = 1.0,
    ):
        self.delta_tolerance = delta_tolerance
        self.hedge_ratio = hedge_ratio

    def on_ticker(self, ticker: Ticker) -> list[Signal]:
        return []

    def on_kline(self, kline: Kline) -> list[Signal]:
        return []

    def on_option_quote(self, q: OptionQuote) -> list[Signal]:
        signals: list[Signal] = []
        abs_delta = abs(q.delta)

        if abs_delta < self.delta_tolerance:
            return signals

        strength = min(float(abs_delta / (self.delta_tolerance * Decimal("3"))), 1.0)

        if q.option_type == "call" and q.delta > 0:
            hedge_qty = q.delta * Decimal(str(self.hedge_ratio))
            signals.append(
                Signal(
                    symbol=q.underlying,
                    market=Market.SPOT,
                    side="sell",
                    strength=strength,
                    strategy_name=self.name,
                    reason=f"Delta中性对冲：卖出标的，期权Delta={q.delta}，对冲数量={hedge_qty:.2f}",
                    metadata={
                        "hedge_type": "delta_neutral",
                        "option_symbol": q.symbol,
                        "option_delta": str(q.delta),
                        "hedge_quantity": str(hedge_qty),
                    },
                    timestamp_ns=q.timestamp_ns,
                )
            )

        if q.option_type == "put" and q.delta < 0:
            hedge_qty = abs(q.delta) * Decimal(str(self.hedge_ratio))
            signals.append(
                Signal(
                    symbol=q.underlying,
                    market=Market.SPOT,
                    side="buy",
                    strength=strength,
                    strategy_name=self.name,
                    reason=f"Delta中性对冲：买入标的，期权Delta={q.delta}，对冲数量={hedge_qty:.2f}",
                    metadata={
                        "hedge_type": "delta_neutral",
                        "option_symbol": q.symbol,
                        "option_delta": str(q.delta),
                        "hedge_quantity": str(hedge_qty),
                    },
                    timestamp_ns=q.timestamp_ns,
                )
            )

        return signals
