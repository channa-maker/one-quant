"""
ONE量化 - 回测引擎

tick 级事件驱动回测引擎，支持 ticker 和 kline 两种粒度数据。

核心原则：
  - 事件时间驱动（不用系统时钟）
  - 回测/实盘偏差 < 0.05%
  - 严防未来函数（只用当前及历史数据）
  - 包含交易成本和滑点模型
"""

from __future__ import annotations

import uuid
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from pydantic import BaseModel

from one_quant.core.types import (
    Fill,
    Kline,
    Market,
    OrderBook,
    PositionState,
    Signal,
    Ticker,
)
from one_quant.strategy.contracts import Strategy

# ──────────────────────────── 回测结果 ────────────────────────────


class BacktestResult(BaseModel, frozen=True):
    """回测结果

    Attributes:
        total_return: 总收益率
        annual_return: 年化收益
        max_drawdown: 最大回撤
        sharpe_ratio: 夏普比率（年化，无风险利率默认 0）
        calmar_ratio: 卡玛比率（年化收益 / 最大回撤）
        win_rate: 胜率（盈利交易 / 总交易）
        profit_factor: 盈亏比（总盈利 / 总亏损）
        turnover_rate: 换手率（总成交金额 / 初始资金）
        total_trades: 总交易次数
        equity_curve: 权益曲线 [(timestamp_ns, equity), ...]
        sample_in_metrics: 样本内指标（可扩展）
        sample_out_metrics: 样本外指标（可扩展）
    """

    total_return: Decimal
    annual_return: Decimal
    max_drawdown: Decimal
    sharpe_ratio: float
    calmar_ratio: float
    win_rate: float
    profit_factor: float
    turnover_rate: float
    total_trades: int
    equity_curve: list[tuple[int, Decimal]]
    sample_in_metrics: dict[str, Any] = {}
    sample_out_metrics: dict[str, Any] = {}


# ──────────────────────────── 回测引擎 ────────────────────────────


class BacktestEngine:
    """tick 级回测引擎。

    核心流程：
      1. 按事件时间顺序遍历行情数据
      2. 解析数据类型（Ticker / Kline / OrderBook / Trade）
      3. 调用策略对应回调，获取信号
      4. 模拟撮合（含滑点 + 手续费）
      5. 更新持仓和权益
      6. 记录权益曲线
      7. 计算回测指标

    Attributes:
        _strategy: 策略实例
        _capital: 当前可用资金
        _initial_capital: 初始资金
        _commission_rate: 手续费率
        _slippage_rate: 滑点率
        _positions: 持仓映射 {symbol: PositionState}
        _trades: 成交记录列表
        _equity_curve: 权益曲线 [(timestamp_ns, equity)]
        _total_turnover: 累计成交金额（用于计算换手率）
    """

    def __init__(
        self,
        strategy: Strategy,
        initial_capital: Decimal = Decimal("100000"),
        commission_rate: Decimal = Decimal("0.001"),  # 0.1% 手续费
        slippage_rate: Decimal = Decimal("0.0005"),  # 0.05% 滑点
    ) -> None:
        self._strategy = strategy
        self._initial_capital = initial_capital
        self._capital = initial_capital
        self._commission_rate = commission_rate
        self._slippage_rate = slippage_rate
        self._positions: dict[str, PositionState] = {}
        self._trades: list[Fill] = []
        self._equity_curve: list[tuple[int, Decimal]] = []
        self._total_turnover: Decimal = Decimal("0")

    # ──────────────────── 公开接口 ────────────────────

    async def run(self, data: list[dict[str, Any]]) -> BacktestResult:
        """运行回测。

        按事件时间顺序处理每条行情数据，驱动策略回调并模拟撮合。

        Args:
            data: 按时间排序的行情数据列表。
                  每条数据为 dict[str, Any]，必须包含 ``_type`` 字段标识类型：
                    - ``_type == "ticker"`` → 构造 Ticker 并调用 on_ticker
                    - ``_type == "kline"``  → 构造 Kline 并调用 on_kline
                    - ``_type == "orderbook"`` → 构造 OrderBook 并调用 on_orderbook
                    - ``_type == "trade"``  → 作为成交数据（不触发策略回调，仅用于行情参考）
                  其余字段直接传给对应类型构造函数。

        Returns:
            BacktestResult 包含各项回测指标。
        """
        # 重置状态（支持重复调用）
        self._reset()

        for item in data:
            event_type = item.get("_type", "")
            timestamp_ns = item.get("timestamp_ns", 0)

            # 根据数据类型分发
            signals: list[Signal] = []

            if event_type == "ticker":
                ticker = self._build_ticker(item)
                signals = self._strategy.on_ticker(ticker)

            elif event_type == "kline":
                kline = self._build_kline(item)
                signals = self._strategy.on_kline(kline)

            elif event_type == "orderbook":
                ob = self._build_orderbook(item)
                signals = self._strategy.on_orderbook(ob)

            elif event_type == "trade":
                # 逐笔成交不触发策略回调，仅跳过
                continue

            else:
                # 未知类型，跳过
                continue

            # 处理信号 → 模拟撮合
            for signal in signals:
                # 取当前行情价格作为撮合基准价
                price = self._extract_price(item, signal.symbol)
                if price is None:
                    continue

                fill = self._simulate_fill(signal, price, timestamp_ns)
                if fill is not None:
                    self._apply_fill(fill, timestamp_ns)

            # 记录当前权益（每条数据都记录，保证曲线粒度）
            equity = self._calculate_equity(timestamp_ns, item)
            self._equity_curve.append((timestamp_ns, equity))

        # 计算指标
        metrics = self._calculate_metrics()
        return BacktestResult(
            total_return=metrics["total_return"],
            annual_return=metrics["annual_return"],
            max_drawdown=metrics["max_drawdown"],
            sharpe_ratio=metrics["sharpe_ratio"],
            calmar_ratio=metrics["calmar_ratio"],
            win_rate=metrics["win_rate"],
            profit_factor=metrics["profit_factor"],
            turnover_rate=metrics["turnover_rate"],
            total_trades=metrics["total_trades"],
            equity_curve=self._equity_curve,
            sample_in_metrics={},
            sample_out_metrics={},
        )

    @property
    def trades(self) -> list[Fill]:
        """获取所有成交记录（只读副本）。"""
        return list(self._trades)

    @property
    def positions(self) -> dict[str, PositionState]:
        """获取当前持仓快照（只读副本）。"""
        return dict(self._positions)

    @property
    def equity_curve(self) -> list[tuple[int, Decimal]]:
        """获取权益曲线（只读副本）。"""
        return list(self._equity_curve)

    # ──────────────────── 内部方法 ────────────────────

    def _reset(self) -> None:
        """重置引擎状态，支持重复运行。"""
        self._capital = self._initial_capital
        self._positions.clear()
        self._trades.clear()
        self._equity_curve.clear()
        self._total_turnover = Decimal("0")

    # ──── 数据构造 ────

    @staticmethod
    def _build_ticker(item: dict[str, Any]) -> Ticker:
        """从 dict[str, Any] 构造 Ticker 对象。"""
        return Ticker(
            symbol=item["symbol"],
            market=Market(item.get("market", "SPOT")),
            exchange=item.get("exchange", ""),
            last_price=Decimal(str(item["last_price"])),
            bid=Decimal(str(item.get("bid", item["last_price"]))),
            ask=Decimal(str(item.get("ask", item["last_price"]))),
            volume_24h=Decimal(str(item.get("volume_24h", 0))),
            timestamp_ns=item["timestamp_ns"],
        )

    @staticmethod
    def _build_kline(item: dict[str, Any]) -> Kline:
        """从 dict[str, Any] 构造 Kline 对象。"""
        return Kline(
            symbol=item["symbol"],
            market=Market(item.get("market", "SPOT")),
            exchange=item.get("exchange", ""),
            interval=item.get("interval", "1m"),
            open=Decimal(str(item["open"])),
            high=Decimal(str(item["high"])),
            low=Decimal(str(item["low"])),
            close=Decimal(str(item["close"])),
            volume=Decimal(str(item.get("volume", 0))),
            timestamp_ns=item["timestamp_ns"],
        )

    @staticmethod
    def _build_orderbook(item: dict[str, Any]) -> OrderBook:
        """从 dict[str, Any] 构造 OrderBook 对象。"""
        bids = [
            {"price": Decimal(str(lvl["price"])), "quantity": Decimal(str(lvl["quantity"]))}
            for lvl in item.get("bids", [])
        ]
        asks = [
            {"price": Decimal(str(lvl["price"])), "quantity": Decimal(str(lvl["quantity"]))}
            for lvl in item.get("asks", [])
        ]
        # OrderBookLevel 需要显式构造
        from one_quant.core.types import OrderBookLevel

        return OrderBook(
            symbol=item["symbol"],
            exchange=item.get("exchange", ""),
            bids=[OrderBookLevel(**b) for b in bids],
            asks=[OrderBookLevel(**a) for a in asks],
            timestamp_ns=item["timestamp_ns"],
        )

    # ──── 价格提取 ────

    @staticmethod
    def _extract_price(item: dict[str, Any], symbol: str) -> Decimal | None:
        """从行情数据中提取撮合基准价格。

        优先级：last_price > close > open > bid/ask 中间价
        """
        if "last_price" in item:
            return Decimal(str(item["last_price"]))
        if "close" in item:
            return Decimal(str(item["close"]))
        if "open" in item:
            return Decimal(str(item["open"]))
        if "bid" in item and "ask" in item:
            bid = Decimal(str(item["bid"]))
            ask = Decimal(str(item["ask"]))
            return (bid + ask) / Decimal("2")
        return None

    # ──── 模拟撮合 ────

    def _simulate_fill(self, signal: Signal, price: Decimal, timestamp_ns: int) -> Fill | None:
        """模拟撮合：将信号转化为成交记录。

        包含滑点和手续费计算。

        滑点模型：
          - 买入：成交价 = 价格 × (1 + slippage_rate)
          - 卖出：成交价 = 价格 × (1 - slippage_rate)

        手续费模型：
          - 手续费 = 成交金额 × commission_rate

        信号过滤：
          - signal.strength == 0 → 不成交
          - 信号强度决定成交数量比例

        Args:
            signal: 策略产生的信号
            price: 当前行情基准价
            timestamp_ns: 事件时间戳

        Returns:
            Fill 成交记录，或 None（信号被过滤）
        """
        # 信号强度为 0，不产生成交
        if signal.strength <= 0:
            return None

        # 根据信号方向计算滑点后价格
        if signal.side == "buy":
            exec_price = price * (Decimal("1") + self._slippage_rate)
        else:
            exec_price = price * (Decimal("1") - self._slippage_rate)

        # 价格精度：保留 8 位小数
        exec_price = exec_price.quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)

        # 计算成交数量：基于信号强度和可用资金
        # 默认每笔交易使用总资金的 10% × signal.strength
        trade_value = self._initial_capital * Decimal("0.1") * Decimal(str(signal.strength))
        quantity = trade_value / exec_price if exec_price > 0 else Decimal("0")

        if quantity <= 0:
            return None

        # 计算手续费
        trade_amount = exec_price * quantity
        fee = (trade_amount * self._commission_rate).quantize(
            Decimal("0.00000001"), rounding=ROUND_HALF_UP
        )

        return Fill(
            order_id=str(uuid.uuid4()),
            symbol=signal.symbol,
            side=signal.side,
            price=exec_price,
            quantity=quantity,
            fee=fee,
            fee_currency="USDT",
            exchange="backtest",
            timestamp_ns=timestamp_ns,
        )

    # ──── 持仓更新 ────

    def _apply_fill(self, fill: Fill, timestamp_ns: int) -> None:
        """应用成交记录，更新持仓和资金。

        多空逻辑：
          - 买入：增加多头持仓 / 减少空头持仓
          - 卖出：减少多头持仓 / 增加空头持仓

        资金变动：
          - 买入：资金 -= 成交金额 + 手续费
          - 卖出：资金 += 成交金额 - 手续费

        Args:
            fill: 成交记录
            timestamp_ns: 当前时间戳
        """
        symbol = fill.symbol
        current_pos = self._positions.get(symbol)

        trade_amount = fill.price * fill.quantity
        self._total_turnover += trade_amount

        if fill.side == "buy":
            # 扣除资金：成交金额 + 手续费
            self._capital -= trade_amount + fill.fee

            if current_pos is None or current_pos.side == "flat":
                # 开多仓
                self._positions[symbol] = PositionState(
                    symbol=symbol,
                    market=Market.SPOT,
                    side="long",
                    quantity=fill.quantity,
                    entry_price=fill.price,
                    unrealized_pnl=Decimal("0"),
                    realized_pnl=Decimal("0"),
                    timestamp_ns=timestamp_ns,
                )
            elif current_pos.side == "long":
                # 加仓：更新均价
                old_amount = current_pos.entry_price * current_pos.quantity
                new_quantity = current_pos.quantity + fill.quantity
                new_entry = (
                    (old_amount + trade_amount) / new_quantity if new_quantity > 0 else Decimal("0")
                )
                self._positions[symbol] = current_pos.model_copy(
                    update={
                        "quantity": new_quantity,
                        "entry_price": new_entry.quantize(
                            Decimal("0.00000001"), rounding=ROUND_HALF_UP
                        ),
                        "timestamp_ns": timestamp_ns,
                    }
                )
            elif current_pos.side == "short":
                # 平空仓（全部或部分）
                close_qty = min(fill.quantity, current_pos.quantity)
                pnl = (current_pos.entry_price - fill.price) * close_qty
                remaining = current_pos.quantity - close_qty

                # 更新已实现盈亏
                new_realized = current_pos.realized_pnl + pnl
                self._capital += pnl  # 空头盈亏计入资金

                if remaining <= 0:
                    # 完全平仓
                    self._positions[symbol] = PositionState(
                        symbol=symbol,
                        market=Market.SPOT,
                        side="flat",
                        quantity=Decimal("0"),
                        entry_price=Decimal("0"),
                        unrealized_pnl=Decimal("0"),
                        realized_pnl=new_realized,
                        timestamp_ns=timestamp_ns,
                    )
                else:
                    # 部分平仓
                    self._positions[symbol] = current_pos.model_copy(
                        update={
                            "quantity": remaining,
                            "realized_pnl": new_realized,
                            "timestamp_ns": timestamp_ns,
                        }
                    )

        elif fill.side == "sell":
            # 收回资金：成交金额 - 手续费
            self._capital += trade_amount - fill.fee

            if current_pos is None or current_pos.side == "flat":
                # 开空仓
                self._positions[symbol] = PositionState(
                    symbol=symbol,
                    market=Market.SPOT,
                    side="short",
                    quantity=fill.quantity,
                    entry_price=fill.price,
                    unrealized_pnl=Decimal("0"),
                    realized_pnl=Decimal("0"),
                    timestamp_ns=timestamp_ns,
                )
            elif current_pos.side == "short":
                # 加空仓
                old_amount = current_pos.entry_price * current_pos.quantity
                new_quantity = current_pos.quantity + fill.quantity
                new_entry = (
                    (old_amount + trade_amount) / new_quantity if new_quantity > 0 else Decimal("0")
                )
                self._positions[symbol] = current_pos.model_copy(
                    update={
                        "quantity": new_quantity,
                        "entry_price": new_entry.quantize(
                            Decimal("0.00000001"), rounding=ROUND_HALF_UP
                        ),
                        "timestamp_ns": timestamp_ns,
                    }
                )
            elif current_pos.side == "long":
                # 平多仓（全部或部分）
                close_qty = min(fill.quantity, current_pos.quantity)
                pnl = (fill.price - current_pos.entry_price) * close_qty
                remaining = current_pos.quantity - close_qty

                new_realized = current_pos.realized_pnl + pnl

                if remaining <= 0:
                    self._positions[symbol] = PositionState(
                        symbol=symbol,
                        market=Market.SPOT,
                        side="flat",
                        quantity=Decimal("0"),
                        entry_price=Decimal("0"),
                        unrealized_pnl=Decimal("0"),
                        realized_pnl=new_realized,
                        timestamp_ns=timestamp_ns,
                    )
                else:
                    self._positions[symbol] = current_pos.model_copy(
                        update={
                            "quantity": remaining,
                            "realized_pnl": new_realized,
                            "timestamp_ns": timestamp_ns,
                        }
                    )

        # 记录成交
        self._trades.append(fill)
        # 通知策略
        self._strategy.on_fill(fill)

    # ──── 权益计算 ────

    def _calculate_equity(self, timestamp_ns: int, item: dict[str, Any]) -> Decimal:
        """计算当前总权益 = 可用资金 + 持仓市值。

        Args:
            timestamp_ns: 当前时间戳
            item: 当前行情数据（用于获取最新价格）

        Returns:
            总权益
        """
        equity = self._capital

        for symbol, pos in self._positions.items():
            if pos.side == "flat" or pos.quantity <= 0:
                continue

            # 获取最新价格
            current_price = self._extract_price(item, symbol)
            if current_price is None:
                # 无法获取价格，使用入场价估算
                current_price = pos.entry_price

            if pos.side == "long":
                unrealized = (current_price - pos.entry_price) * pos.quantity
                equity += pos.entry_price * pos.quantity + unrealized
            elif pos.side == "short":
                unrealized = (pos.entry_price - current_price) * pos.quantity
                equity += pos.entry_price * pos.quantity + unrealized

        return equity.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    # ──── 指标计算 ────

    def _calculate_metrics(self) -> dict[str, Any]:
        """计算回测指标。

        包含：
          - total_return: 总收益率
          - annual_return: 年化收益
          - max_drawdown: 最大回撤
          - sharpe_ratio: 夏普比率（年化，无风险利率 = 0）
          - calmar_ratio: 卡玛比率
          - win_rate: 胜率
          - profit_factor: 盈亏比
          - turnover_rate: 换手率

        Returns:
            指标字典
        """
        if not self._equity_curve:
            return self._empty_metrics()

        # ── 总收益率 ──
        initial = self._initial_capital
        final_equity = self._equity_curve[-1][1]
        total_return = (final_equity - initial) / initial if initial > 0 else Decimal("0")

        # ── 年化收益 ──
        # 计算回测时间跨度（纳秒 → 年）
        start_ns = self._equity_curve[0][0]
        end_ns = self._equity_curve[-1][0]
        duration_ns = end_ns - start_ns
        # 一年 ≈ 365.25 天 × 24 × 3600 × 1e9 纳秒
        ns_per_year = Decimal("365.25") * Decimal("86400") * Decimal("1000000000")

        if duration_ns > 0:
            years = Decimal(str(duration_ns)) / ns_per_year
            if years > 0 and total_return > Decimal("-1"):
                # 年化 = (1 + total_return) ^ (1/years) - 1
                # 使用简化近似：total_return / years（线性近似，适用于短期回测）
                annual_return = total_return / years
            else:
                annual_return = Decimal("0")
        else:
            annual_return = Decimal("0")

        # ── 最大回撤 ──
        max_dd = self._calculate_max_drawdown()

        # ── 夏普比率 ──
        sharpe = self._calculate_sharpe_ratio()

        # ── 卡玛比率 ──
        calmar = float(annual_return / max_dd) if max_dd > 0 else 0.0

        # ── 胜率和盈亏比 ──
        win_rate, profit_factor = self._calculate_trade_stats()

        # ── 换手率 ──
        turnover = float(self._total_turnover / initial) if initial > 0 else 0.0

        return {
            "total_return": total_return,
            "annual_return": annual_return.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP),
            "max_drawdown": max_dd.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP),
            "sharpe_ratio": round(sharpe, 4),
            "calmar_ratio": round(calmar, 4),
            "win_rate": round(win_rate, 4),
            "profit_factor": round(profit_factor, 4),
            "turnover_rate": round(turnover, 4),
            "total_trades": len(self._trades),
        }

    def _calculate_max_drawdown(self) -> Decimal:
        """计算最大回撤。

        最大回撤 = max((peak - trough) / peak)

        Returns:
            最大回撤（正数，如 0.15 表示 15% 回撤）
        """
        if not self._equity_curve:
            return Decimal("0")

        peak = self._equity_curve[0][1]
        max_dd = Decimal("0")

        for _, equity in self._equity_curve:
            if equity > peak:
                peak = equity
            if peak > 0:
                dd = (peak - equity) / peak
                if dd > max_dd:
                    max_dd = dd

        return max_dd

    def _calculate_sharpe_ratio(self, risk_free_rate: float = 0.0) -> float:
        """计算夏普比率（年化）。

        夏普 = (年化收益 - 无风险利率) / 年化波动率
        年化波动率 = 日收益标准差 × sqrt(365)

        Args:
            risk_free_rate: 无风险利率（默认 0）

        Returns:
            夏普比率
        """
        if len(self._equity_curve) < 2:
            return 0.0

        # 计算逐期收益率
        returns: list[float] = []
        for i in range(1, len(self._equity_curve)):
            prev_equity = self._equity_curve[i - 1][1]
            curr_equity = self._equity_curve[i][1]
            if prev_equity > 0:
                r = float((curr_equity - prev_equity) / prev_equity)
                returns.append(r)

        if not returns:
            return 0.0

        # 均值和标准差
        mean_return = sum(returns) / len(returns)
        if len(returns) < 2:
            return 0.0

        variance = sum((r - mean_return) ** 2 for r in returns) / (len(returns) - 1)
        std_return = variance**0.5

        if std_return == 0:
            return 0.0

        # 年化：假设每条数据代表一天（简化处理）
        # 实际应用中应根据数据频率调整
        annual_factor = 365.0**0.5
        annualized_return = mean_return * 365.0
        annualized_std = std_return * annual_factor

        return (annualized_return - risk_free_rate) / annualized_std

    def _calculate_trade_stats(self) -> tuple[float, float]:
        """计算胜率和盈亏比。

        将成交记录按 symbol 配对（buy/sell），计算每笔交易的盈亏。

        Returns:
            (胜率, 盈亏比)
        """
        if not self._trades:
            return 0.0, 0.0

        # 按 symbol 分组
        trades_by_symbol: dict[str, list[Fill]] = {}
        for fill in self._trades:
            trades_by_symbol.setdefault(fill.symbol, []).append(fill)

        wins = 0
        losses = 0
        total_profit = Decimal("0")
        total_loss = Decimal("0")

        for symbol, fills in trades_by_symbol.items():
            # 简单配对：buy → sell 为一组
            buys = [f for f in fills if f.side == "buy"]
            sells = [f for f in fills if f.side == "sell"]

            # 配对数量取较小值
            pairs = min(len(buys), len(sells))
            for i in range(pairs):
                pnl = (sells[i].price - buys[i].price) * min(buys[i].quantity, sells[i].quantity)
                # 扣除双边手续费
                pnl -= buys[i].fee + sells[i].fee

                if pnl > 0:
                    wins += 1
                    total_profit += pnl
                elif pnl < 0:
                    losses += 1
                    total_loss += abs(pnl)

        total_trades = wins + losses
        win_rate = wins / total_trades if total_trades > 0 else 0.0
        profit_factor = float(total_profit / total_loss) if total_loss > 0 else 0.0

        return win_rate, profit_factor

    def _empty_metrics(self) -> dict[str, Any]:
        """返回空指标字典。"""
        return {
            "total_return": Decimal("0"),
            "annual_return": Decimal("0"),
            "max_drawdown": Decimal("0"),
            "sharpe_ratio": 0.0,
            "calmar_ratio": 0.0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "turnover_rate": 0.0,
            "total_trades": 0,
        }
