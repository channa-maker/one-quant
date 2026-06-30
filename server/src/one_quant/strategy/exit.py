"""
ONE量化 - 出场系统

核心思想：
  出场系统分为两层：
  1. FixedExitStrategy（固定出场）：基于固定阈值的止损/止盈/移动止损，是主要出场逻辑
  2. ExitBrain（数据驱动出场）：基于持仓特征和市场数据的智能出场建议，影子模式运行

两层设计支持 A/B 测试：
  - 固定出场层始终生效，保证基本风控
  - 数据驱动层以影子模式运行，记录建议但不影响实际交易
  - 灰度成熟后可切换为主用出场逻辑

参数说明（FixedExitStrategy）：
  - stop_loss_pct: 止损百分比，如 0.05 表示 5% 亏损平仓（默认 5%）
  - take_profit_pct: 止盈百分比，如 0.10 表示 10% 盈利平仓（默认 10%）
  - trailing_stop_pct: 移动止损百分比，从最高点回撤此比例平仓（默认 3%）

适用场景：
  - 所有策略的出场保护层，与入场策略解耦
  - 趋势策略：移动止损可锁定利润
  - 反转策略：固定止损控制最大损失
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from one_quant.core.types import Market, PositionState, Signal


class FixedExitStrategy:
    """第一层：固定出场策略。

    基于固定阈值的三层出场机制：
    1. 止损：亏损达阈值自动平仓
    2. 止盈：盈利达阈值自动平仓
    3. 移动止损：从最高点回撤达阈值平仓

    优先级：止损 > 止盈 > 移动止损
    """

    def __init__(
        self,
        stop_loss_pct: Decimal = Decimal("0.05"),
        take_profit_pct: Decimal = Decimal("0.10"),
        trailing_stop_pct: Decimal = Decimal("0.03"),
    ) -> None:
        if stop_loss_pct <= 0 or stop_loss_pct >= 1:
            raise ValueError("止损百分比必须在 (0, 1) 范围内")
        if take_profit_pct <= 0:
            raise ValueError("止盈百分比必须为正数")
        if trailing_stop_pct <= 0 or trailing_stop_pct >= 1:
            raise ValueError("移动止损百分比必须在 (0, 1) 范围内")

        self.stop_loss_pct: Decimal = stop_loss_pct
        self.take_profit_pct: Decimal = take_profit_pct
        self.trailing_stop_pct: Decimal = trailing_stop_pct

    def check_exit(
        self,
        symbol: str,
        entry_price: Decimal,
        current_price: Decimal,
        side: str,
        high_since_entry: Decimal,
    ) -> Signal | None:
        """检查是否触发出场。

        三层出场逻辑（按优先级）：
        1. 止损：当前价格相对于入场价的亏损超过阈值
        2. 止盈：当前价格相对于入场价的盈利超过阈值
        3. 移动止损：当前价格从持仓期间最高点回撤超过阈值

        Args:
            symbol: 标的符号
            entry_price: 入场价格
            current_price: 当前价格
            side: 持仓方向（"long" 或 "short"）
            high_since_entry: 入场后的最高价格（多头）或最低价格（空头）

        Returns:
            出场信号，不触发返回 None
        """
        if entry_price <= 0 or current_price <= 0:
            return None

        # ── 多头持仓 ──
        if side == "long":
            pnl_pct = (current_price - entry_price) / entry_price

            # 1. 止损：亏损超过阈值
            if pnl_pct <= -self.stop_loss_pct:
                return Signal(
                    symbol=symbol,
                    market=Market.SPOT,  # market 由调用方在 metadata 中补充
                    side="sell",
                    strength=1.0,
                    strategy_name="fixed_exit",
                    reason=(
                        f"止损出场：多头入场价{entry_price:.4f}，当前价{current_price:.4f}，"
                        f"亏损{pnl_pct * 100:.2f}%，超过止损线{self.stop_loss_pct * 100:.1f}%"
                    ),
                    metadata={
                        "exit_type": "stop_loss",
                        "entry_price": str(entry_price),
                        "current_price": str(current_price),
                        "pnl_pct": str(pnl_pct),
                        "threshold": str(-self.stop_loss_pct),
                    },
                    timestamp_ns=0,  # 由调用方填充
                )

            # 2. 止盈：盈利超过阈值
            if pnl_pct >= self.take_profit_pct:
                return Signal(
                    symbol=symbol,
                    market=Market.SPOT,
                    side="sell",
                    strength=0.8,
                    strategy_name="fixed_exit",
                    reason=(
                        f"止盈出场：多头入场价{entry_price:.4f}，当前价{current_price:.4f}，"
                        f"盈利{pnl_pct * 100:.2f}%，达到止盈线{self.take_profit_pct * 100:.1f}%"
                    ),
                    metadata={
                        "exit_type": "take_profit",
                        "entry_price": str(entry_price),
                        "current_price": str(current_price),
                        "pnl_pct": str(pnl_pct),
                        "threshold": str(self.take_profit_pct),
                    },
                    timestamp_ns=0,
                )

            # 3. 移动止损：从最高点回撤
            if high_since_entry > 0 and high_since_entry > entry_price:
                drawdown = (high_since_entry - current_price) / high_since_entry
                if drawdown >= self.trailing_stop_pct:
                    return Signal(
                        symbol=symbol,
                        market=Market.SPOT,
                        side="sell",
                        strength=0.9,
                        strategy_name="fixed_exit",
                        reason=(
                            f"移动止损出场：多头最高价{high_since_entry:.4f}，"
                            f"当前价{current_price:.4f}，回撤{drawdown * 100:.2f}%，"
                            f"超过移动止损线{self.trailing_stop_pct * 100:.1f}%"
                        ),
                        metadata={
                            "exit_type": "trailing_stop",
                            "entry_price": str(entry_price),
                            "current_price": str(current_price),
                            "high_since_entry": str(high_since_entry),
                            "drawdown": str(drawdown),
                            "threshold": str(self.trailing_stop_pct),
                        },
                        timestamp_ns=0,
                    )

        # ── 空头持仓 ──
        elif side == "short":
            pnl_pct = (entry_price - current_price) / entry_price

            # 1. 止损
            if pnl_pct <= -self.stop_loss_pct:
                return Signal(
                    symbol=symbol,
                    market=Market.SPOT,
                    side="buy",
                    strength=1.0,
                    strategy_name="fixed_exit",
                    reason=(
                        f"止损出场：空头入场价{entry_price:.4f}，当前价{current_price:.4f}，"
                        f"亏损{pnl_pct * 100:.2f}%，超过止损线{self.stop_loss_pct * 100:.1f}%"
                    ),
                    metadata={
                        "exit_type": "stop_loss",
                        "entry_price": str(entry_price),
                        "current_price": str(current_price),
                        "pnl_pct": str(pnl_pct),
                        "threshold": str(-self.stop_loss_pct),
                    },
                    timestamp_ns=0,
                )

            # 2. 止盈
            if pnl_pct >= self.take_profit_pct:
                return Signal(
                    symbol=symbol,
                    market=Market.SPOT,
                    side="buy",
                    strength=0.8,
                    strategy_name="fixed_exit",
                    reason=(
                        f"止盈出场：空头入场价{entry_price:.4f}，当前价{current_price:.4f}，"
                        f"盈利{pnl_pct * 100:.2f}%，达到止盈线{self.take_profit_pct * 100:.1f}%"
                    ),
                    metadata={
                        "exit_type": "take_profit",
                        "entry_price": str(entry_price),
                        "current_price": str(current_price),
                        "pnl_pct": str(pnl_pct),
                        "threshold": str(self.take_profit_pct),
                    },
                    timestamp_ns=0,
                )

            # 3. 移动止损（空头：从最低点反弹）
            if high_since_entry > 0 and high_since_entry < entry_price:
                rebound = (current_price - high_since_entry) / high_since_entry
                if rebound >= self.trailing_stop_pct:
                    return Signal(
                        symbol=symbol,
                        market=Market.SPOT,
                        side="buy",
                        strength=0.9,
                        strategy_name="fixed_exit",
                        reason=(
                            f"移动止损出场：空头最低价{high_since_entry:.4f}，"
                            f"当前价{current_price:.4f}，反弹{rebound * 100:.2f}%，"
                            f"超过移动止损线{self.trailing_stop_pct * 100:.1f}%"
                        ),
                        metadata={
                            "exit_type": "trailing_stop",
                            "entry_price": str(entry_price),
                            "current_price": str(current_price),
                            "low_since_entry": str(high_since_entry),
                            "rebound": str(rebound),
                            "threshold": str(self.trailing_stop_pct),
                        },
                        timestamp_ns=0,
                    )

        return None


class ExitBrain:
    """第二层：数据驱动出场影子层。

    基于持仓特征（持仓时间、浮盈浮亏、波动率等）预测最优出场点。
    目前以影子模式运行：只输出建议，不影响实际交易。
    与固定出场层 A/B 测试，灰度成熟后再切换为主用出场逻辑。

    设计原则：
    - 只读旁路，不修改任何状态
    - 所有建议记录到日志，供回测分析
    - 建议通过 Signal 的 metadata 中标记 "shadow": True
    """

    def suggest_exit(
        self,
        symbol: str,
        position: PositionState,
        market_data: dict[str, Any],
    ) -> Signal | None:
        """建议出场（影子模式，不影响实际交易）。

        基于以下因素综合评估：
        1. 持仓盈亏比例
        2. 持仓时间（从 metadata 获取）
        3. 当前波动率（从 market_data 获取）
        4. 成交量变化

        Args:
            symbol: 标的符号
            position: 当前持仓状态
            market_data: 市场数据字典，可包含：
                - volatility: 当前波动率
                - volume_ratio: 成交量比率（当前/平均）
                - holding_seconds: 持仓时间（秒）
                - atr: ATR 值

        Returns:
            出场建议信号，无建议返回 None
        """
        if position.side == "flat" or position.quantity <= 0:
            return None

        entry_price = position.entry_price
        if entry_price <= 0:
            return None

        # 获取市场数据
        volatility: float = market_data.get("volatility", 0.0)
        volume_ratio: float = market_data.get("volume_ratio", 1.0)
        holding_seconds: float = market_data.get("holding_seconds", 0.0)

        # 计算盈亏比例
        if position.side == "long":
            pnl_pct = float(position.unrealized_pnl / (entry_price * position.quantity))
        else:  # short
            pnl_pct = float(position.unrealized_pnl / (entry_price * position.quantity))

        reasons: list[str] = []
        strength = 0.0

        # 规则 1：高波动率 + 盈利 → 建议止盈
        if volatility > 0.03 and pnl_pct > 0.05:
            reasons.append(f"高波动率({volatility:.2%})且盈利{pnl_pct:.2%}，建议锁定利润")
            strength = max(strength, 0.7)

        # 规则 2：长时间持仓 + 微利 → 建议出场（资金效率低）
        if holding_seconds > 86400 and 0 < pnl_pct < 0.02:
            reasons.append(f"持仓{holding_seconds / 3600:.1f}小时仅盈利{pnl_pct:.2%}，资金效率低")
            strength = max(strength, 0.5)

        # 规则 3：成交量萎缩 + 亏损 → 趋势可能反转
        if volume_ratio < 0.5 and pnl_pct < -0.02:
            reasons.append(f"成交量萎缩(比率{volume_ratio:.2f})且亏损{pnl_pct:.2%}，趋势可能反转")
            strength = max(strength, 0.6)

        # 规则 4：大幅盈利（> 15%）→ 建议部分止盈
        if pnl_pct > 0.15:
            reasons.append(f"大幅盈利{pnl_pct:.2%}，建议部分止盈保护利润")
            strength = max(strength, 0.8)

        if not reasons:
            return None

        side = "sell" if position.side == "long" else "buy"

        return Signal(
            symbol=symbol,
            market=position.market,
            side=side,
            strength=min(strength, 1.0),
            strategy_name="exit_brain_shadow",
            reason=f"[影子建议] {'; '.join(reasons)}",
            metadata={
                "shadow": True,
                "exit_type": "data_driven",
                "pnl_pct": str(pnl_pct),
                "volatility": str(volatility),
                "volume_ratio": str(volume_ratio),
                "holding_seconds": str(holding_seconds),
                "position_side": position.side,
                "position_qty": str(position.quantity),
                "entry_price": str(entry_price),
            },
            timestamp_ns=position.timestamp_ns,
        )
