"""
公司行为引擎 — 分红/拆股/合股/并购/特别股息/退市 + 历史复权 + 期权调整

核心职责：
  1. 注册/查询公司行为事件
  2. 价格复权（前复权/后复权）
  3. 数量调整（拆股/合股）
  4. 期权合约调整（非标准合约）
  5. 历史价格批量复权
  6. 退市预警与强制平仓信号

规范：
  - 所有金额/数量使用 Decimal 精确计算
  - 不可变模型（frozen=True）保证线程安全
"""

from __future__ import annotations

import time
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel

from one_quant.core.types import Market, Signal
from one_quant.infra.logging import get_logger

logger = get_logger(__name__)


# ──────────────────────────── 枚举与模型 ────────────────────────────


class CorporateActionType(str, Enum):
    """公司行为类型"""

    DIVIDEND = "dividend"  # 分红（现金股息）
    SPLIT = "split"  # 拆股（如 1 拆 2）
    REVERSE_SPLIT = "reverse_split"  # 合股（如 2 合 1）
    MERGER = "merger"  # 并购
    SPECIAL_DIVIDEND = "special_dividend"  # 特别股息
    DELISTING = "delisting"  # 退市


class CorporateAction(BaseModel, frozen=True):
    """公司行为记录（不可变）

    Attributes:
        action_type: 行为类型
        symbol: 标的符号
        effective_date: 生效日期
        ratio: 拆股/合股比例（如 2:1 拆股 = Decimal('2')）
        dividend_amount: 每股分红金额（分红/特别股息时必填）
        new_symbol: 并购后新代码（并购时必填）
        metadata: 附加元数据（记录日、登记日等）
    """

    action_type: CorporateActionType
    symbol: str
    effective_date: date
    ratio: Decimal | None = None
    dividend_amount: Decimal | None = None
    new_symbol: str | None = None
    metadata: dict[str, Any] = {}


# ──────────────────────────── 公司行为引擎 ────────────────────────────


class CorporateActionEngine:
    """公司行为引擎

    管理所有影响持仓的公司行为，提供：
    - 事件注册与查询
    - 价格/数量/期权复权
    - 历史价格批量复权
    """

    def __init__(self) -> None:
        self._actions: list[CorporateAction] = []
        self._adjustment_log: list[dict[str, Any]] = []

    # ── 注册与查询 ────────────────────────────────────────────────

    def register_action(self, action: CorporateAction) -> None:
        """注册公司行为事件

        Args:
            action: 公司行为记录（不可变模型）
        """
        self._actions.append(action)
        logger.info(
            "公司行为注册: %s %s %s",
            action.symbol,
            action.action_type.value,
            action.effective_date,
        )

    def get_actions(
        self, symbol: str, start: date, end: date
    ) -> list[CorporateAction]:
        """查询指定标的在指定时段内的公司行为

        Args:
            symbol: 标的符号
            start: 起始日期（含）
            end: 结束日期（含）

        Returns:
            该时段内的公司行为列表，按生效日期排序
        """
        result = [
            a
            for a in self._actions
            if a.symbol == symbol and start <= a.effective_date <= end
        ]
        result.sort(key=lambda a: a.effective_date)
        return result

    # ── 价格复权 ──────────────────────────────────────────────────

    def adjust_price(
        self, price: Decimal, action: CorporateAction
    ) -> Decimal:
        """对单个价格进行复权调整

        拆股: price / ratio
        合股: price * ratio
        分红/特别股息: price - dividend_amount

        Args:
            price: 原始价格
            action: 公司行为事件

        Returns:
            调整后的价格（四舍五入到小数点后4位）
        """
        if action.action_type == CorporateActionType.SPLIT:
            if action.ratio is None or action.ratio <= 0:
                raise ValueError(f"拆股比例无效: {action.ratio}")
            adjusted = price / action.ratio

        elif action.action_type == CorporateActionType.REVERSE_SPLIT:
            if action.ratio is None or action.ratio <= 0:
                raise ValueError(f"合股比例无效: {action.ratio}")
            adjusted = price * action.ratio

        elif action.action_type in (
            CorporateActionType.DIVIDEND,
            CorporateActionType.SPECIAL_DIVIDEND,
        ):
            if action.dividend_amount is None:
                raise ValueError("分红金额未设置")
            adjusted = price - action.dividend_amount

        else:
            # 并购/退市不直接调整价格
            adjusted = price

        self._adjustment_log.append(
            {
                "type": "price_adjust",
                "action_type": action.action_type.value,
                "symbol": action.symbol,
                "original_price": str(price),
                "adjusted_price": str(adjusted),
                "timestamp_ns": time.time_ns(),
            }
        )
        return adjusted.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

    # ── 数量调整 ──────────────────────────────────────────────────

    def adjust_quantity(
        self, quantity: Decimal, action: CorporateAction
    ) -> Decimal:
        """对持仓数量进行调整（拆股/合股）

        拆股: quantity * ratio
        合股: quantity / ratio

        Args:
            quantity: 原始数量
            action: 公司行为事件

        Returns:
            调整后的数量（四舍五入到小数点后4位）
        """
        if action.action_type == CorporateActionType.SPLIT:
            if action.ratio is None or action.ratio <= 0:
                raise ValueError(f"拆股比例无效: {action.ratio}")
            adjusted = quantity * action.ratio

        elif action.action_type == CorporateActionType.REVERSE_SPLIT:
            if action.ratio is None or action.ratio <= 0:
                raise ValueError(f"合股比例无效: {action.ratio}")
            adjusted = quantity / action.ratio

        else:
            # 分红/并购/退市不改变数量
            adjusted = quantity

        self._adjustment_log.append(
            {
                "type": "quantity_adjust",
                "action_type": action.action_type.value,
                "symbol": action.symbol,
                "original_qty": str(quantity),
                "adjusted_qty": str(adjusted),
                "timestamp_ns": time.time_ns(),
            }
        )
        return adjusted.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

    # ── 期权调整 ──────────────────────────────────────────────────

    def adjust_option(
        self,
        strike: Decimal,
        multiplier: Decimal,
        action: CorporateAction,
    ) -> tuple[Decimal, Decimal]:
        """期权合约调整（非标准合约）

        拆股: strike / ratio, multiplier * ratio
        合股: strike * ratio, multiplier / ratio
        现金分红: strike - dividend_amount, multiplier 不变

        Args:
            strike: 行权价
            multiplier: 合约乘数（通常为 100）
            action: 公司行为事件

        Returns:
            (新行权价, 新合约乘数)
        """
        if action.action_type == CorporateActionType.SPLIT:
            if action.ratio is None or action.ratio <= 0:
                raise ValueError(f"拆股比例无效: {action.ratio}")
            new_strike = strike / action.ratio
            new_multiplier = multiplier * action.ratio

        elif action.action_type == CorporateActionType.REVERSE_SPLIT:
            if action.ratio is None or action.ratio <= 0:
                raise ValueError(f"合股比例无效: {action.ratio}")
            new_strike = strike * action.ratio
            new_multiplier = multiplier / action.ratio

        elif action.action_type in (
            CorporateActionType.DIVIDEND,
            CorporateActionType.SPECIAL_DIVIDEND,
        ):
            if action.dividend_amount is None:
                raise ValueError("分红金额未设置")
            new_strike = strike - action.dividend_amount
            new_multiplier = multiplier

        else:
            # 并购/退市不影响期权参数（由清算所处理）
            new_strike = strike
            new_multiplier = multiplier

        self._adjustment_log.append(
            {
                "type": "option_adjust",
                "action_type": action.action_type.value,
                "symbol": action.symbol,
                "original_strike": str(strike),
                "new_strike": str(new_strike),
                "original_multiplier": str(multiplier),
                "new_multiplier": str(new_multiplier),
                "timestamp_ns": time.time_ns(),
            }
        )
        return (
            new_strike.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            new_multiplier.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
        )

    # ── 历史价格批量复权 ──────────────────────────────────────────

    def get_price_history_adjusted(
        self,
        symbol: str,
        prices: list[dict[str, Any]],
        actions: list[CorporateAction],
        mode: Literal["forward", "backward"] = "forward",
    ) -> list[dict[str, Any]]:
        """历史价格复权（前复权/后复权）

        Args:
            symbol: 标的符号
            prices: 原始价格序列，每项含 date/ohlcv 字段
                    格式: [{"date": "2024-01-01", "open": ..., "high": ...,
                           "low": ..., "close": ..., "volume": ...}, ...]
            actions: 该标的的公司行为列表
            mode: "forward" 前复权（以最新价为基准往前调），
                  "backward" 后复权（以最早价为基准往后调）

        Returns:
            复权后的价格序列（结构同输入，金额为字符串）
        """
        if not prices or not actions:
            return prices

        # 按生效日期排序
        sorted_actions = sorted(actions, key=lambda a: a.effective_date)

        if mode == "forward":
            return self._forward_adjust(prices, sorted_actions)
        elif mode == "backward":
            return self._backward_adjust(prices, sorted_actions)
        else:
            raise ValueError(f"不支持的复权模式: {mode}，应为 'forward' 或 'backward'")

    def _forward_adjust(
        self,
        prices: list[dict[str, Any]],
        sorted_actions: list[CorporateAction],
    ) -> list[dict[str, Any]]:
        """前复权：以最新价格为基准，往前调整历史价格"""
        # 累计调整因子
        cumulative_ratio = Decimal("1")
        cumulative_dividend = Decimal("0")

        # 从最新到最旧累积调整
        for action in reversed(sorted_actions):
            if action.action_type == CorporateActionType.SPLIT:
                if action.ratio and action.ratio > 0:
                    cumulative_ratio *= action.ratio
            elif action.action_type == CorporateActionType.REVERSE_SPLIT:
                if action.ratio and action.ratio > 0:
                    cumulative_ratio /= action.ratio
            elif action.action_type in (
                CorporateActionType.DIVIDEND,
                CorporateActionType.SPECIAL_DIVIDEND,
            ):
                if action.dividend_amount:
                    cumulative_dividend += action.dividend_amount

        result = []
        for bar in prices:
            adjusted_bar = dict(bar)
            for field in ("open", "high", "low", "close"):
                if field in bar and bar[field] is not None:
                    raw = Decimal(str(bar[field]))
                    adjusted = (raw - cumulative_dividend) / cumulative_ratio
                    adjusted_bar[field] = str(
                        adjusted.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
                    )
            # 成交量反向调整（拆股后量变大）
            if "volume" in bar and bar["volume"] is not None:
                vol = Decimal(str(bar["volume"]))
                adjusted_vol = vol * cumulative_ratio
                adjusted_bar["volume"] = str(
                    adjusted_vol.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                )
            result.append(adjusted_bar)
        return result

    def _backward_adjust(
        self,
        prices: list[dict[str, Any]],
        sorted_actions: list[CorporateAction],
    ) -> list[dict[str, Any]]:
        """后复权：以最早价格为基准，往后调整历史价格"""
        adjustment_factor = Decimal("1")
        adjustment_dividend = Decimal("0")

        result = []
        action_idx = 0
        for bar in prices:
            # 检查是否有新的公司行为生效
            bar_date = str(bar.get("date", ""))
            while (
                action_idx < len(sorted_actions)
                and str(sorted_actions[action_idx].effective_date) <= bar_date
            ):
                act = sorted_actions[action_idx]
                if act.action_type == CorporateActionType.SPLIT:
                    if act.ratio and act.ratio > 0:
                        adjustment_factor /= act.ratio
                elif act.action_type == CorporateActionType.REVERSE_SPLIT:
                    if act.ratio and act.ratio > 0:
                        adjustment_factor *= act.ratio
                elif act.action_type in (
                    CorporateActionType.DIVIDEND,
                    CorporateActionType.SPECIAL_DIVIDEND,
                ):
                    if act.dividend_amount:
                        adjustment_dividend += act.dividend_amount
                action_idx += 1

            adjusted_bar = dict(bar)
            for field in ("open", "high", "low", "close"):
                if field in bar and bar[field] is not None:
                    raw = Decimal(str(bar[field]))
                    adjusted = raw / adjustment_factor + adjustment_dividend
                    adjusted_bar[field] = str(
                        adjusted.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
                    )
            result.append(adjusted_bar)
        return result

    @property
    def stats(self) -> dict[str, int]:
        """引擎统计"""
        return {
            "total_actions": len(self._actions),
            "adjustments": len(self._adjustment_log),
        }


# ──────────────────────────── 退市处理器 ────────────────────────────


class DelistingHandler:
    """退市处理器

    处理标的退市前的预警和强制平仓流程。

    使用方式::

        engine = CorporateActionEngine()
        handler = DelistingHandler(engine)

        # 注册退市事件
        engine.register_action(CorporateAction(
            action_type=CorporateActionType.DELISTING,
            symbol="XYZ",
            effective_date=date(2024, 6, 30),
        ))

        # 检查退市风险
        info = handler.check_delisting("XYZ")
        if info:
            signal = handler.force_close_position("XYZ")
    """

    def __init__(self, engine: CorporateActionEngine | None = None) -> None:
        self._engine = engine
        self._delisting_warnings: dict[str, dict[str, Any]] = {}

    def check_delisting(self, symbol: str) -> dict[str, Any] | None:
        """检查指定标的是否面临退市

        通过已注册的公司行为查询退市事件。

        Args:
            symbol: 标的符号

        Returns:
            退市信息字典，无退市风险时返回 None
        """
        if self._engine is None:
            return None

        today = date.today()
        # 查询未来 30 天内的退市事件
        future = date.fromordinal(today.toordinal() + 30)
        actions = self._engine.get_actions(symbol, today, future)

        delistings = [
            a for a in actions if a.action_type == CorporateActionType.DELISTING
        ]
        if not delistings:
            return None

        action = delistings[0]
        return {
            "symbol": symbol,
            "effective_date": str(action.effective_date),
            "metadata": action.metadata,
            "urgency": "high",
        }

    def force_close_position(self, symbol: str) -> Signal:
        """生成强制平仓信号

        当标的确认退市时，生成卖出信号强制平仓。

        Args:
            symbol: 标的符号

        Returns:
            强制卖出信号（strength=1.0，最高优先级）
        """
        logger.warning("触发退市强制平仓: %s", symbol)

        return Signal(
            symbol=symbol,
            market=Market.STOCK,
            side="sell",
            strength=1.0,
            strategy_name="delisting_handler",
            reason=f"标的 {symbol} 面临退市，强制平仓",
            metadata={"forced": True, "reason": "delisting"},
            timestamp_ns=time.time_ns(),
        )
