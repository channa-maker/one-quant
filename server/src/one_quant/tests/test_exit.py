"""
ONE量化 - 出场系统测试

覆盖：
  - 止损触发
  - 止盈触发
  - 移动止损触发
  - 不触发场景
  - 边界值测试
  - ExitBrain 影子层
"""

from decimal import Decimal

import pytest

from one_quant.core.types import Market, PositionState
from one_quant.strategy.exit import ExitBrain, FixedExitStrategy

# ──────────────────────────── 辅助工具 ────────────────────────────


def _make_exit_strategy(
    stop_loss: str = "0.05",
    take_profit: str = "0.10",
    trailing_stop: str = "0.03",
) -> FixedExitStrategy:
    """创建出场策略实例。"""
    return FixedExitStrategy(
        stop_loss_pct=Decimal(stop_loss),
        take_profit_pct=Decimal(take_profit),
        trailing_stop_pct=Decimal(trailing_stop),
    )


def _make_position(
    side: str = "long",
    entry_price: str = "100",
    quantity: str = "10",
) -> PositionState:
    """创建持仓状态。"""
    return PositionState(
        symbol="BTCUSDT",
        market=Market.SPOT,
        side=side,
        quantity=Decimal(quantity),
        entry_price=Decimal(entry_price),
        unrealized_pnl=Decimal("0"),
        realized_pnl=Decimal("0"),
        timestamp_ns=1_000_000_000,
    )


# ──────────────────────────── 止损测试 ────────────────────────────


class TestStopLoss:
    """止损触发测试"""

    def test_long_stop_loss_triggered(self):
        """多头持仓亏损超过止损线，触发止损。"""
        strategy = _make_exit_strategy(stop_loss="0.05")
        # 入场价100，当前价94（亏损6% > 5%止损线）
        signal = strategy.check_exit(
            symbol="BTCUSDT",
            entry_price=Decimal("100"),
            current_price=Decimal("94"),
            side="long",
            high_since_entry=Decimal("105"),
        )
        assert signal is not None
        assert signal.side == "sell"
        assert signal.metadata["exit_type"] == "stop_loss"
        assert signal.strength == 1.0

    def test_short_stop_loss_triggered(self):
        """空头持仓亏损超过止损线，触发止损。"""
        strategy = _make_exit_strategy(stop_loss="0.05")
        # 入场价100，当前价106（空头亏损6% > 5%止损线）
        signal = strategy.check_exit(
            symbol="BTCUSDT",
            entry_price=Decimal("100"),
            current_price=Decimal("106"),
            side="short",
            high_since_entry=Decimal("95"),
        )
        assert signal is not None
        assert signal.side == "buy"
        assert signal.metadata["exit_type"] == "stop_loss"

    def test_stop_loss_exact_threshold(self):
        """亏损恰好等于止损线时触发止损（边界值）。"""
        strategy = _make_exit_strategy(stop_loss="0.05")
        # 亏损恰好 5%
        signal = strategy.check_exit(
            symbol="BTCUSDT",
            entry_price=Decimal("100"),
            current_price=Decimal("95"),
            side="long",
            high_since_entry=Decimal("100"),
        )
        assert signal is not None
        assert signal.metadata["exit_type"] == "stop_loss"

    def test_stop_loss_just_above_threshold(self):
        """亏损略小于止损线时不触发止损（边界值）。"""
        strategy = _make_exit_strategy(stop_loss="0.05")
        # 亏损 4.99% < 5%
        signal = strategy.check_exit(
            symbol="BTCUSDT",
            entry_price=Decimal("100"),
            current_price=Decimal("95.01"),
            side="long",
            high_since_entry=Decimal("100"),
        )
        # 不应触发止损（可能触发其他出场条件）
        if signal is not None:
            assert signal.metadata.get("exit_type") != "stop_loss"


# ──────────────────────────── 止盈测试 ────────────────────────────


class TestTakeProfit:
    """止盈触发测试"""

    def test_long_take_profit_triggered(self):
        """多头持仓盈利超过止盈线，触发止盈。"""
        strategy = _make_exit_strategy(take_profit="0.10")
        # 入场价100，当前价111（盈利11% > 10%止盈线）
        signal = strategy.check_exit(
            symbol="BTCUSDT",
            entry_price=Decimal("100"),
            current_price=Decimal("111"),
            side="long",
            high_since_entry=Decimal("111"),
        )
        assert signal is not None
        assert signal.side == "sell"
        assert signal.metadata["exit_type"] == "take_profit"
        assert signal.strength == 0.8

    def test_short_take_profit_triggered(self):
        """空头持仓盈利超过止盈线，触发止盈。"""
        strategy = _make_exit_strategy(take_profit="0.10")
        # 入场价100，当前价89（空头盈利11% > 10%止盈线）
        signal = strategy.check_exit(
            symbol="BTCUSDT",
            entry_price=Decimal("100"),
            current_price=Decimal("89"),
            side="short",
            high_since_entry=Decimal("89"),
        )
        assert signal is not None
        assert signal.side == "buy"
        assert signal.metadata["exit_type"] == "take_profit"

    def test_take_profit_exact_threshold(self):
        """盈利恰好等于止盈线时触发止盈（边界值）。"""
        strategy = _make_exit_strategy(take_profit="0.10")
        signal = strategy.check_exit(
            symbol="BTCUSDT",
            entry_price=Decimal("100"),
            current_price=Decimal("110"),
            side="long",
            high_since_entry=Decimal("110"),
        )
        assert signal is not None
        assert signal.metadata["exit_type"] == "take_profit"

    def test_take_profit_just_below_threshold(self):
        """盈利略小于止盈线时不触发止盈（边界值）。"""
        strategy = _make_exit_strategy(take_profit="0.10")
        # 盈利 9.99% < 10%
        signal = strategy.check_exit(
            symbol="BTCUSDT",
            entry_price=Decimal("100"),
            current_price=Decimal("109.99"),
            side="long",
            high_since_entry=Decimal("109.99"),
        )
        if signal is not None:
            assert signal.metadata.get("exit_type") != "take_profit"


# ──────────────────────────── 移动止损测试 ────────────────────────────


class TestTrailingStop:
    """移动止损触发测试"""

    def test_long_trailing_stop_triggered(self):
        """多头从最高点回撤超过移动止损线，触发移动止损。"""
        strategy = _make_exit_strategy(trailing_stop="0.03")
        # 最高点110，当前价106.7（回撤3% = 3%移动止损线）
        signal = strategy.check_exit(
            symbol="BTCUSDT",
            entry_price=Decimal("100"),
            current_price=Decimal("106.7"),
            side="long",
            high_since_entry=Decimal("110"),
        )
        assert signal is not None
        assert signal.metadata["exit_type"] == "trailing_stop"
        assert signal.strength == 0.9

    def test_short_trailing_stop_triggered(self):
        """空头从最低点反弹超过移动止损线，触发移动止损。"""
        strategy = _make_exit_strategy(trailing_stop="0.03")
        # 最低点90，当前价92.7（反弹3% = 3%移动止损线）
        signal = strategy.check_exit(
            symbol="BTCUSDT",
            entry_price=Decimal("100"),
            current_price=Decimal("92.7"),
            side="short",
            high_since_entry=Decimal("90"),
        )
        assert signal is not None
        assert signal.metadata["exit_type"] == "trailing_stop"

    def test_trailing_stop_not_triggered_below_threshold(self):
        """回撤未达移动止损线时不触发。"""
        strategy = _make_exit_strategy(trailing_stop="0.03")
        # 最高点110，当前价107.5（回撤2.27% < 3%）
        signal = strategy.check_exit(
            symbol="BTCUSDT",
            entry_price=Decimal("100"),
            current_price=Decimal("107.5"),
            side="long",
            high_since_entry=Decimal("110"),
        )
        if signal is not None:
            assert signal.metadata.get("exit_type") != "trailing_stop"

    def test_trailing_stop_uses_high_since_entry(self):
        """移动止损使用入场后最高价，而非入场价。"""
        strategy = _make_exit_strategy(
            stop_loss="0.20",  # 大止损，避免先触发止损
            take_profit="0.50",  # 大止盈
            trailing_stop="0.05",
        )
        # 入场价100，最高点120，当前价114（从最高点回撤5%）
        signal = strategy.check_exit(
            symbol="BTCUSDT",
            entry_price=Decimal("100"),
            current_price=Decimal("114"),
            side="long",
            high_since_entry=Decimal("120"),
        )
        assert signal is not None
        assert signal.metadata["exit_type"] == "trailing_stop"


# ──────────────────────────── 不触发场景 ────────────────────────────


class TestNoTrigger:
    """不触发出场的场景"""

    def test_profit_below_take_profit_no_exit(self):
        """盈利未达止盈线且无亏损，不触发任何出场。"""
        strategy = _make_exit_strategy(
            stop_loss="0.05",
            take_profit="0.10",
            trailing_stop="0.03",
        )
        # 入场价100，当前价103（盈利3%，未达止盈，无止损/移动止损）
        signal = strategy.check_exit(
            symbol="BTCUSDT",
            entry_price=Decimal("100"),
            current_price=Decimal("103"),
            side="long",
            high_since_entry=Decimal("103"),
        )
        assert signal is None

    def test_loss_below_stop_loss_no_exit(self):
        """亏损未达止损线，不触发止损。"""
        strategy = _make_exit_strategy(stop_loss="0.05")
        # 入场价100，当前价97（亏损3% < 5%止损线）
        signal = strategy.check_exit(
            symbol="BTCUSDT",
            entry_price=Decimal("100"),
            current_price=Decimal("97"),
            side="long",
            high_since_entry=Decimal("100"),
        )
        # 不应触发止损（可能不触发任何出场）
        if signal is not None:
            assert signal.metadata.get("exit_type") != "stop_loss"

    def test_flat_position_returns_none(self):
        """平仓状态不触发出场。"""
        strategy = _make_exit_strategy()
        # 使用 side="flat" 不在 long/short 分支中，应返回 None
        # 注意：FixedExitStrategy.check_exit 只处理 long/short
        # 传入 side="flat" 会走到最后返回 None
        signal = strategy.check_exit(
            symbol="BTCUSDT",
            entry_price=Decimal("100"),
            current_price=Decimal("90"),
            side="flat",
            high_since_entry=Decimal("100"),
        )
        assert signal is None


# ──────────────────────────── 边界值测试 ────────────────────────────


class TestBoundaryValues:
    """边界值测试"""

    def test_zero_entry_price_returns_none(self):
        """入场价为零不崩溃，返回 None。"""
        strategy = _make_exit_strategy()
        signal = strategy.check_exit(
            symbol="BTCUSDT",
            entry_price=Decimal("0"),
            current_price=Decimal("100"),
            side="long",
            high_since_entry=Decimal("100"),
        )
        assert signal is None

    def test_zero_current_price_returns_none(self):
        """当前价为零不崩溃，返回 None。"""
        strategy = _make_exit_strategy()
        signal = strategy.check_exit(
            symbol="BTCUSDT",
            entry_price=Decimal("100"),
            current_price=Decimal("0"),
            side="long",
            high_since_entry=Decimal("100"),
        )
        assert signal is None

    def test_negative_entry_price_returns_none(self):
        """负入场价不崩溃，返回 None。"""
        strategy = _make_exit_strategy()
        signal = strategy.check_exit(
            symbol="BTCUSDT",
            entry_price=Decimal("-100"),
            current_price=Decimal("100"),
            side="long",
            high_since_entry=Decimal("100"),
        )
        assert signal is None

    def test_stop_loss_pct_boundary_zero(self):
        """止损百分比为0时抛出异常。"""
        with pytest.raises(ValueError, match="止损百分比"):
            FixedExitStrategy(stop_loss_pct=Decimal("0"))

    def test_stop_loss_pct_boundary_one(self):
        """止损百分比为1时抛出异常。"""
        with pytest.raises(ValueError, match="止损百分比"):
            FixedExitStrategy(stop_loss_pct=Decimal("1"))

    def test_take_profit_pct_boundary_zero(self):
        """止盈百分比为0时抛出异常。"""
        with pytest.raises(ValueError, match="止盈百分比"):
            FixedExitStrategy(take_profit_pct=Decimal("0"))

    def test_trailing_stop_pct_boundary_zero(self):
        """移动止损百分比为0时抛出异常。"""
        with pytest.raises(ValueError, match="移动止损百分比"):
            FixedExitStrategy(trailing_stop_pct=Decimal("0"))

    def test_trailing_stop_pct_boundary_one(self):
        """移动止损百分比为1时抛出异常。"""
        with pytest.raises(ValueError, match="移动止损百分比"):
            FixedExitStrategy(trailing_stop_pct=Decimal("1"))

    def test_high_since_entry_zero_no_trailing_stop(self):
        """入场后最高价为零时不触发移动止损。"""
        strategy = _make_exit_strategy(trailing_stop="0.03")
        signal = strategy.check_exit(
            symbol="BTCUSDT",
            entry_price=Decimal("100"),
            current_price=Decimal("95"),
            side="long",
            high_since_entry=Decimal("0"),
        )
        # high_since_entry=0 且 <= entry_price，不触发移动止损
        if signal is not None:
            assert signal.metadata.get("exit_type") != "trailing_stop"


# ──────────────────────────── 优先级测试 ────────────────────────────


class TestExitPriority:
    """出场优先级测试"""

    def test_stop_loss_before_take_profit(self):
        """止损优先于止盈（当同时满足时）。"""
        # 极端情况：止损5%，止盈10%
        # 当前亏损6% → 应触发止损而非止盈
        strategy = _make_exit_strategy(stop_loss="0.05", take_profit="0.10")
        signal = strategy.check_exit(
            symbol="BTCUSDT",
            entry_price=Decimal("100"),
            current_price=Decimal("94"),
            side="long",
            high_since_entry=Decimal("105"),
        )
        assert signal is not None
        assert signal.metadata["exit_type"] == "stop_loss"

    def test_take_profit_before_trailing_stop(self):
        """止盈优先于移动止损。"""
        strategy = _make_exit_strategy(
            stop_loss="0.50",
            take_profit="0.10",
            trailing_stop="0.03",
        )
        # 入场价100，当前价112（盈利12% > 10%止盈）
        # 最高点115，从最高点回撤2.6% < 3%移动止损
        # 但止盈已触发
        signal = strategy.check_exit(
            symbol="BTCUSDT",
            entry_price=Decimal("100"),
            current_price=Decimal("112"),
            side="long",
            high_since_entry=Decimal("115"),
        )
        assert signal is not None
        assert signal.metadata["exit_type"] == "take_profit"


# ──────────────────────────── ExitBrain 影子层测试 ────────────────────────────


class TestExitBrain:
    """ExitBrain 影子层测试"""

    def test_high_volatility_profit_suggests_exit(self):
        """高波动率 + 盈利时建议止盈。"""
        brain = ExitBrain()
        pos = _make_position(side="long", entry_price="100", quantity="10")
        # 修改 unrealized_pnl 模拟盈利
        pos = pos.model_copy(update={"unrealized_pnl": Decimal("60")})

        signal = brain.suggest_exit(
            symbol="BTCUSDT",
            position=pos,
            market_data={"volatility": 0.05, "volume_ratio": 1.0, "holding_seconds": 3600},
        )
        assert signal is not None
        assert signal.metadata.get("shadow") is True

    def test_long_holding_low_profit_suggests_exit(self):
        """长时间持仓 + 微利时建议出场。"""
        brain = ExitBrain()
        pos = _make_position(side="long", entry_price="100", quantity="10")
        pos = pos.model_copy(update={"unrealized_pnl": Decimal("10")})

        signal = brain.suggest_exit(
            symbol="BTCUSDT",
            position=pos,
            market_data={"volatility": 0.01, "volume_ratio": 1.0, "holding_seconds": 100000},
        )
        assert signal is not None

    def test_large_profit_suggests_partial_exit(self):
        """大幅盈利时建议部分止盈。"""
        brain = ExitBrain()
        pos = _make_position(side="long", entry_price="100", quantity="10")
        pos = pos.model_copy(update={"unrealized_pnl": Decimal("200")})

        signal = brain.suggest_exit(
            symbol="BTCUSDT",
            position=pos,
            market_data={"volatility": 0.01, "volume_ratio": 1.0, "holding_seconds": 3600},
        )
        assert signal is not None

    def test_flat_position_no_suggestion(self):
        """平仓状态不产生建议。"""
        brain = ExitBrain()
        pos = _make_position(side="flat", entry_price="0", quantity="0")

        signal = brain.suggest_exit(
            symbol="BTCUSDT",
            position=pos,
            market_data={},
        )
        assert signal is None

    def test_no_reason_no_suggestion(self):
        """无触发条件时不产生建议。"""
        brain = ExitBrain()
        pos = _make_position(side="long", entry_price="100", quantity="10")
        pos = pos.model_copy(update={"unrealized_pnl": Decimal("5")})

        signal = brain.suggest_exit(
            symbol="BTCUSDT",
            position=pos,
            market_data={"volatility": 0.01, "volume_ratio": 1.0, "holding_seconds": 3600},
        )
        # 微利（0.5%）+ 低波动 + 短持仓 → 不触发
        assert signal is None
