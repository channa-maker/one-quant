"""
ONE量化 - 网格策略

核心思想：
  在价格中枢上下均匀布设网格，价格下跌触网时买入，上涨触网时卖出，
  通过反复低买高卖赚取网格利润。属于做市类策略。

适用市场环境：
  - 震荡行情（价格在区间内反复波动）：网格反复成交获利
  - 低波动行情：网格间距合理时稳定收益
  - 单边趋势行情：需要仓位上限保护，否则可能在持续下跌中不断买入被套
  - 建议设置总仓位上限和止损线，防止极端行情损失

参数说明：
  - grid_count: 网格数量，越多覆盖范围越广但单格利润越薄（默认 10）
  - grid_spacing_pct: 网格间距百分比，如 0.01 表示 1%（默认 1%）
  - position_per_grid: 每格仓位占总资金比例（默认 5%）
  - factor_name 示例: grid_10_0.0100
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from one_quant.core.types import Fill, Kline, Market, Signal, Ticker
from one_quant.strategy.contracts import Strategy


@dataclass
class _GridLevel:
    """单个网格层级。

    Attributes:
        price: 网格触发价格
        side: 该层级的方向（buy/sell）
        filled: 是否已成交
    """
    price: Decimal
    side: str  # "buy" 或 "sell"
    filled: bool = False


@dataclass
class _SymbolGridState:
    """单个标的的网格状态。

    Attributes:
        center_price: 价格中枢
        levels: 所有网格层级
        position_qty: 当前持仓数量
        position_cost: 持仓成本
        total_position_limit: 总仓位上限（数量）
    """
    center_price: Decimal
    levels: list[_GridLevel] = field(default_factory=list)
    position_qty: Decimal = Decimal(0)
    position_cost: Decimal = Decimal(0)
    total_position_limit: Decimal = Decimal(0)


class GridStrategy(Strategy):
    """网格策略。

    原理：在价格区间内均匀布网，低买高卖。
    适用：震荡行情。

    参数：
    - grid_count: 网格数量（默认 10）
    - grid_spacing_pct: 网格间距百分比（默认 1%）
    - position_per_grid: 每格仓位（默认总资金的 5%）

    因子命名：grid_{grid_count}_{grid_spacing_pct}
    """

    name = "grid"
    enabled = False

    def __init__(
        self,
        grid_count: int = 10,
        grid_spacing_pct: Decimal = Decimal("0.01"),
        position_per_grid: Decimal = Decimal("0.05"),
    ) -> None:
        if grid_count <= 0:
            raise ValueError("网格数量必须为正整数")
        if grid_spacing_pct <= 0:
            raise ValueError("网格间距必须为正数")
        if not Decimal(0) < position_per_grid <= Decimal(1):
            raise ValueError("每格仓位比例必须在 (0, 1] 范围内")

        self.grid_count: int = grid_count
        self.grid_spacing_pct: Decimal = grid_spacing_pct
        self.position_per_grid: Decimal = position_per_grid

        # 每个 symbol 独立维护网格状态
        self._states: dict[str, _SymbolGridState] = {}

        # 是否已在 on_fill 中注册（用于首次布网）
        self._initialized: set[str] = set()

    @property
    def factor_name(self) -> str:
        """因子命名：grid_{grid_count}_{grid_spacing_pct}"""
        return f"grid_{self.grid_count}_{self.grid_spacing_pct:.4f}"

    def _build_grid(self, symbol: str, center_price: Decimal, market: Market) -> _SymbolGridState:
        """围绕价格中枢构建网格。

        以 center_price 为中心，上下各布设 grid_count/2 个网格层级。
        上方为卖单网格，下方为买单网格。

        Args:
            symbol: 标的符号
            center_price: 价格中枢
            market: 市场类型

        Returns:
            初始化的网格状态
        """
        half = self.grid_count // 2
        levels: list[_GridLevel] = []

        # 下方买单网格（价格从高到低）
        for i in range(1, half + 1):
            price = center_price * (Decimal(1) - self.grid_spacing_pct * Decimal(i))
            if price > 0:
                levels.append(_GridLevel(price=price, side="buy"))

        # 上方卖单网格（价格从低到高）
        for i in range(1, half + 1):
            price = center_price * (Decimal(1) + self.grid_spacing_pct * Decimal(i))
            levels.append(_GridLevel(price=price, side="sell"))

        # 按价格排序
        levels.sort(key=lambda lv: lv.price)

        state = _SymbolGridState(
            center_price=center_price,
            levels=levels,
            # 总仓位上限 = 每格仓位 * 买单网格数量（防止单边行情无限买入）
            total_position_limit=self.position_per_grid * Decimal(half),
        )
        self._states[symbol] = state
        self._initialized.add(symbol)
        return state

    def _process_price(self, symbol: str, price: Decimal, market: Market, timestamp_ns: int) -> list[Signal]:
        """处理价格更新，检测是否触网。

        流程：
        1. 首次收到价格 → 以此为中枢构建网格
        2. 检查价格是否穿越任何网格层级
        3. 触网时检查仓位限制，生成信号

        Args:
            symbol: 标的符号
            price: 当前价格
            market: 市场类型
            timestamp_ns: 时间戳

        Returns:
            信号列表
        """
        # 首次收到价格，构建网格
        if symbol not in self._states:
            self._build_grid(symbol, price, market)
            return []

        state = self._states[symbol]
        signals: list[Signal] = []

        for level in state.levels:
            if level.filled:
                continue

            # 买单触发：价格 <= 网格价格
            if level.side == "buy" and price <= level.price:
                # 检查总仓位上限
                if state.position_qty >= state.total_position_limit:
                    continue

                level.filled = True
                strength = self._compute_strength(price, state.center_price)
                signals.append(
                    Signal(
                        symbol=symbol,
                        market=market,
                        side="buy",
                        strength=strength,
                        strategy_name=self.name,
                        reason=(
                            f"网格买入：价格{price:.4f}触及买单网格{level.price:.4f}，"
                            f"距中枢{state.center_price:.4f}，信号强度{strength:.2f}"
                        ),
                        metadata={
                            "factor": self.factor_name,
                            "grid_price": str(level.price),
                            "center_price": str(state.center_price),
                            "position_qty": str(state.position_qty),
                            "position_limit": str(state.total_position_limit),
                        },
                        timestamp_ns=timestamp_ns,
                    )
                )

            # 卖单触发：价格 >= 网格价格
            elif level.side == "sell" and price >= level.price:
                # 有持仓才能卖
                if state.position_qty <= 0:
                    continue

                level.filled = True
                strength = self._compute_strength(price, state.center_price)
                signals.append(
                    Signal(
                        symbol=symbol,
                        market=market,
                        side="sell",
                        strength=strength,
                        strategy_name=self.name,
                        reason=(
                            f"网格卖出：价格{price:.4f}触及卖单网格{level.price:.4f}，"
                            f"距中枢{state.center_price:.4f}，信号强度{strength:.2f}"
                        ),
                        metadata={
                            "factor": self.factor_name,
                            "grid_price": str(level.price),
                            "center_price": str(state.center_price),
                            "position_qty": str(state.position_qty),
                        },
                        timestamp_ns=timestamp_ns,
                    )
                )

        return signals

    def _compute_strength(self, price: Decimal, center: Decimal) -> float:
        """计算信号强度。

        价格偏离中枢越远，信号越强（越值得交易）。
        使用网格间距作为归一化基准。

        Args:
            price: 当前价格
            center: 中枢价格

        Returns:
            信号强度 [0, 1]
        """
        if center <= 0:
            return 0.5
        deviation_pct = abs(price - center) / center
        # 用 (grid_count/2 * spacing) 作为最大偏离基准
        max_deviation = self.grid_spacing_pct * Decimal(self.grid_count // 2)
        if max_deviation <= 0:
            return 0.5
        strength = float(min(deviation_pct / max_deviation, Decimal(1)))
        return max(strength, 0.1)  # 最低 0.1，保证有信号就有一定强度

    def on_ticker(self, ticker: Ticker) -> list[Signal]:
        """处理实时行情更新。

        Args:
            ticker: 最新行情快照

        Returns:
            信号列表。无信号时返回空列表。
        """
        return self._process_price(
            symbol=ticker.symbol,
            price=ticker.last_price,
            market=ticker.market,
            timestamp_ns=ticker.timestamp_ns,
        )

    def on_kline(self, kline: Kline) -> list[Signal]:
        """处理K线更新。

        Args:
            kline: 最新K线数据

        Returns:
            信号列表。无信号时返回空列表。
        """
        return self._process_price(
            symbol=kline.symbol,
            price=kline.close,
            market=kline.market,
            timestamp_ns=kline.timestamp_ns,
        )

    def on_fill(self, fill: Fill) -> None:
        """处理成交回报，更新持仓状态。

        成交后更新持仓数量和成本，如果所有买单网格都已成交，
        以当前价格为中心重新布网。

        Args:
            fill: 成交回报
        """
        symbol = fill.symbol
        if symbol not in self._states:
            return

        state = self._states[symbol]

        if fill.side == "buy":
            # 买入成交：增加持仓
            state.position_cost += fill.price * fill.quantity
            state.position_qty += fill.quantity
        else:
            # 卖出成交：减少持仓
            if state.position_qty > 0:
                # 按比例减少成本
                sell_ratio = min(fill.quantity / state.position_qty, Decimal(1))
                state.position_cost *= (Decimal(1) - sell_ratio)
                state.position_qty = max(Decimal(0), state.position_qty - fill.quantity)

        # 检查是否需要重新布网：所有买单都已成交
        all_buy_filled = all(
            lv.filled for lv in state.levels if lv.side == "buy"
        )
        if all_buy_filled and state.position_qty > 0:
            # 以最新成交价为中心重新布网
            self._build_grid(symbol, fill.price, Market(fill.symbol.split("/")[-1]) if "/" in fill.symbol else Market.SPOT)

    def on_recover(self, state: "PositionState") -> None:
        """恢复持仓状态。

        系统重启后恢复持仓信息，并以当前价格重新构建网格。

        Args:
            state: 当前持仓快照
        """
        symbol = state.symbol
        if symbol not in self._states and state.entry_price > 0:
            grid_state = self._build_grid(symbol, state.entry_price, state.market)
            grid_state.position_qty = state.quantity
            grid_state.position_cost = state.entry_price * state.quantity
