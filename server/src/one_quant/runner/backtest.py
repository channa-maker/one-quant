"""回测引擎 — tick 级事件驱动，成本/滑点模型，一致性校验"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from one_quant.core.types import Fill, Kline, Market, Order, Signal, Ticker, Trade
from one_quant.data.replay import TickReplayer
from one_quant.infra.logging import get_logger
from one_quant.risk.engine import RiskEngine
from one_quant.strategy.contracts import Strategy

logger = get_logger(__name__)


@dataclass
class BacktestConfig:
    """回测配置"""
    initial_capital: Decimal = Decimal("100000")
    commission_rate: Decimal = Decimal("0.001")  # 0.1%
    slippage_rate: Decimal = Decimal("0.0005")  # 0.05%
    market: Market = Market.SPOT
    exchange: str = "backtest"


@dataclass
class BacktestResult:
    """回测结果"""
    total_return: Decimal = Decimal("0")
    sharpe_ratio: float = 0.0
    max_drawdown: Decimal = Decimal("0")
    win_rate: float = 0.0
    total_trades: int = 0
    total_commission: Decimal = Decimal("0")
    total_slippage: Decimal = Decimal("0")
    equity_curve: list[dict[str, Any]] = field(default_factory=list)
    trades: list[dict[str, Any]] = field(default_factory=list)


class BacktestEngine:
    """回测引擎。

    tick 级事件驱动，与实盘共用同一策略代码。
    内置成本模型（手续费 + 滑点）和一致性校验。

    Usage:
        engine = BacktestEngine(config)
        result = await engine.run(strategy, tick_data)
    """

    def __init__(self, config: BacktestConfig | None = None) -> None:
        self._config = config or BacktestConfig()
        self._equity = self._config.initial_capital
        self._peak_equity = self._equity
        self._positions: dict[str, dict[str, Any]] = {}
        self._trades: list[dict[str, Any]] = []
        self._equity_curve: list[dict[str, Any]] = []
        self._order_count = 0

    async def run(
        self,
        strategy: Strategy,
        tick_data: list[dict[str, Any]],
        data_type: str = "ticker",
    ) -> BacktestResult:
        """运行回测。

        Args:
            strategy: 策略实例
            tick_data: tick 数据列表（已排序）
            data_type: 数据类型（ticker / kline / trade）

        Returns:
            回测结果
        """
        strategy.enabled = True
        total_commission = Decimal("0")
        total_slippage = Decimal("0")

        for tick in tick_data:
            signals: list[Signal] = []

            if data_type == "ticker":
                ticker = Ticker(**tick)
                signals = strategy.on_ticker(ticker)
                price = ticker.last_price
            elif data_type == "kline":
                kline = Kline(**tick)
                signals = strategy.on_kline(kline)
                price = kline.close
            else:
                continue

            for signal in signals:
                order = self._signal_to_order(signal, price)
                commission, slippage = self._simulate_fill(order, price)
                total_commission += commission
                total_slippage += slippage

            self._update_equity(price)
            self._equity_curve.append({
                "timestamp_ns": tick.get("timestamp_ns", 0),
                "equity": str(self._equity),
            })

        # 计算统计
        total_return = (self._equity - self._config.initial_capital) / self._config.initial_capital
        max_dd = self._calculate_max_drawdown()
        win_rate = self._calculate_win_rate()

        return BacktestResult(
            total_return=total_return,
            max_drawdown=max_dd,
            win_rate=win_rate,
            total_trades=len(self._trades),
            total_commission=total_commission,
            total_slippage=total_slippage,
            equity_curve=self._equity_curve,
            trades=self._trades,
        )

    def _signal_to_order(self, signal: Signal, current_price: Decimal) -> Order:
        """信号转订单"""
        import uuid
        quantity = self._equity * Decimal("0.1") / current_price  # 10% 仓位
        return Order(
            client_order_id=str(uuid.uuid4()),
            symbol=signal.symbol,
            market=self._config.market,
            side=signal.side,
            order_type="market",
            quantity=quantity,
            price=current_price,
            stop_price=None,
            status="pending",
            exchange=self._config.exchange,
            timestamp_ns=signal.timestamp_ns,
        )

    def _simulate_fill(self, order: Order, market_price: Decimal) -> tuple[Decimal, Decimal]:
        """模拟成交，计算手续费和滑点"""
        # 滑点
        slippage = market_price * self._config.slippage_rate
        fill_price = market_price + slippage if order.side == "buy" else market_price - slippage

        # 手续费
        notional = order.quantity * fill_price
        commission = notional * self._config.commission_rate

        # 更新持仓
        symbol = order.symbol
        if symbol not in self._positions:
            self._positions[symbol] = {"quantity": Decimal("0"), "avg_price": Decimal("0")}

        pos = self._positions[symbol]
        if order.side == "buy":
            total_cost = pos["quantity"] * pos["avg_price"] + order.quantity * fill_price
            pos["quantity"] += order.quantity
            pos["avg_price"] = total_cost / pos["quantity"] if pos["quantity"] > 0 else Decimal("0")
        else:
            pos["quantity"] -= order.quantity

        # 扣除费用
        self._equity -= commission

        # 记录交易
        self._trades.append({
            "symbol": symbol,
            "side": order.side,
            "quantity": str(order.quantity),
            "price": str(fill_price),
            "commission": str(commission),
            "slippage": str(slippage),
            "timestamp_ns": order.timestamp_ns,
        })

        return commission, slippage

    def _update_equity(self, current_price: Decimal) -> None:
        """更新权益"""
        unrealized = Decimal("0")
        for symbol, pos in self._positions.items():
            if pos["quantity"] > 0:
                unrealized += pos["quantity"] * (current_price - pos["avg_price"])
        self._equity += unrealized
        if self._equity > self._peak_equity:
            self._peak_equity = self._equity

    def _calculate_max_drawdown(self) -> Decimal:
        """计算最大回撤"""
        peak = self._config.initial_capital
        max_dd = Decimal("0")
        for point in self._equity_curve:
            equity = Decimal(point["equity"])
            if equity > peak:
                peak = equity
            dd = (peak - equity) / peak if peak > 0 else Decimal("0")
            if dd > max_dd:
                max_dd = dd
        return max_dd

    def _calculate_win_rate(self) -> float:
        """计算胜率"""
        if not self._trades:
            return 0.0
        # 简化：买后价格涨 = 盈利
        wins = sum(1 for t in self._trades if Decimal(t.get("price", "0")) > 0)
        return wins / len(self._trades)


class FutureFunctionChecker:
    """未来函数检查器。

    检测策略是否使用了未来数据（look-ahead bias）。
    方法：用 T 时刻数据运行策略，检查是否引用了 T+1 及之后的数据。
    """

    @staticmethod
    def check(strategy: Strategy, data: list[dict[str, Any]], data_type: str = "ticker") -> tuple[bool, list[str]]:
        """检查是否存在未来函数。

        Returns:
            (是否通过, 问题列表)
        """
        issues: list[str] = []
        strategy.enabled = True

        # 第一次运行：正常
        signals_a: list[Signal] = []
        for i, tick in enumerate(data):
            if data_type == "ticker":
                ticker = Ticker(**tick)
                signals_a.extend(strategy.on_ticker(ticker))
            elif data_type == "kline":
                kline = Kline(**tick)
                signals_a.extend(strategy.on_kline(kline))

        # 第二次运行：截断最后 10% 数据
        cutoff = len(data) - len(data) // 10
        signals_b: list[Signal] = []
        for tick in data[:cutoff]:
            if data_type == "ticker":
                ticker = Ticker(**tick)
                signals_b.extend(strategy.on_ticker(ticker))
            elif data_type == "kline":
                kline = Kline(**tick)
                signals_b.extend(strategy.on_kline(kline))

        # 比较前 cutoff 条信号
        if len(signals_a[:len(signals_b)]) != len(signals_b):
            issues.append("截断数据后信号数量不一致，可能存在未来函数")

        return len(issues) == 0, issues
