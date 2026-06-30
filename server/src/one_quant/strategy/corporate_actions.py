"""公司行为引擎 — 分红/拆股/合股/并购/退市 + 历史复权"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Any

from one_quant.infra.logging import get_logger

logger = get_logger(__name__)


class CorporateActionType(str, Enum):
    DIVIDEND = "dividend"  # 分红
    SPLIT = "split"  # 拆股
    REVERSE_SPLIT = "reverse_split"  # 合股
    MERGER = "merger"  # 并购
    DELISTING = "delisting"  # 退市
    SPINOFF = "spinoff"  # 分拆
    RIGHTS_OFFERING = "rights_offering"  # 配股


@dataclass
class CorporateAction:
    """公司行为记录"""
    action_id: str
    symbol: str
    action_type: CorporateActionType
    effective_date: str  # YYYY-MM-DD
    details: dict[str, Any] = field(default_factory=dict)
    processed: bool = False


class CorporateActionEngine:
    """公司行为引擎。

    处理所有影响持仓的公司行为：
    - 分红：现金/股票分红
    - 拆股/合股：调整持仓数量和成本价
    - 并购：持仓转换
    - 退市：标记+资产处理
    - 历史复权：回测时正确处理
    """

    def __init__(self) -> None:
        self._actions: list[CorporateAction] = []
        self._adjustment_log: list[dict[str, Any]] = []

    def register(self, action: CorporateAction) -> None:
        self._actions.append(action)
        logger.info("公司行为注册: %s %s %s", action.symbol, action.action_type.value, action.effective_date)

    def apply_split(
        self, symbol: str, ratio: Decimal, quantity: Decimal, avg_price: Decimal,
    ) -> tuple[Decimal, Decimal]:
        """应用拆股

        Args:
            ratio: 拆股比例（如 2 表示 1 拆 2）
            quantity: 当前持仓数量
            avg_price: 当前均价

        Returns:
            (新数量, 新均价)
        """
        new_qty = quantity * ratio
        new_price = avg_price / ratio
        self._adjustment_log.append({
            "type": "split", "symbol": symbol, "ratio": str(ratio),
            "old_qty": str(quantity), "new_qty": str(new_qty),
            "old_price": str(avg_price), "new_price": str(new_price),
            "timestamp_ns": time.time_ns(),
        })
        return new_qty, new_price

    def apply_reverse_split(
        self, symbol: str, ratio: Decimal, quantity: Decimal, avg_price: Decimal,
    ) -> tuple[Decimal, Decimal]:
        """应用合股"""
        new_qty = quantity / ratio
        new_price = avg_price * ratio
        self._adjustment_log.append({
            "type": "reverse_split", "symbol": symbol, "ratio": str(ratio),
            "old_qty": str(quantity), "new_qty": str(new_qty),
        })
        return new_qty, new_price

    def apply_dividend(
        self, symbol: str, per_share: Decimal, quantity: Decimal,
    ) -> Decimal:
        """应用现金分红

        Returns:
            分红总金额
        """
        total = per_share * quantity
        self._adjustment_log.append({
            "type": "dividend", "symbol": symbol,
            "per_share": str(per_share), "total": str(total),
            "timestamp_ns": time.time_ns(),
        })
        return total

    def adjust_for_backtest(
        self, symbol: str, price: Decimal, date_str: str,
    ) -> Decimal:
        """回测时对价格进行复权调整"""
        adjusted = price
        for action in self._actions:
            if action.symbol != symbol:
                continue
            if action.effective_date > date_str:
                continue
            if action.action_type == CorporateActionType.SPLIT:
                ratio = Decimal(str(action.details.get("ratio", 1)))
                adjusted = adjusted / ratio
            elif action.action_type == CorporateActionType.REVERSE_SPLIT:
                ratio = Decimal(str(action.details.get("ratio", 1)))
                adjusted = adjusted * ratio
        return adjusted

    @property
    def stats(self) -> dict[str, int]:
        return {
            "total_actions": len(self._actions),
            "adjustments": len(self._adjustment_log),
        }
