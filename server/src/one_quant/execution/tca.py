"""TCA 交易成本分析 — 事后执行质量评估"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from one_quant.core.types import Fill
from one_quant.infra.logging import get_logger

logger = get_logger(__name__)


@dataclass
class TCAReport:
    """TCA 分析报告"""
    symbol: str
    side: str
    total_quantity: Decimal
    avg_fill_price: Decimal
    arrival_price: Decimal  # 下单时市场价
    vwap_price: Decimal  # 成交量加权均价
    implementation_shortfall: Decimal  # 实施缺口
    slippage_bps: float  # 滑点（基点）
    fill_rate: float  # 成交率
    fill_count: int
    total_commission: Decimal
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp_ns: int = 0

    def __post_init__(self) -> None:
        if self.timestamp_ns == 0:
            self.timestamp_ns = time.time_ns()


class TransactionCostAnalyzer:
    """交易成本分析器。

    事后评估执行质量：
    - 实施缺口 (Implementation Shortfall): 理想 vs 实际成本差异
    - VWAP 偏差: 成交均价 vs 市场 VWAP
    - 滑点归因: 市场冲击 + 时机成本 + 价差成本
    """

    def analyze(
        self,
        fills: list[Fill],
        arrival_price: Decimal,
        market_vwap: Decimal | None = None,
    ) -> TCAReport:
        """分析一组成交的执行质量

        Args:
            fills: 成交记录列表
            arrival_price: 下单时市场价
            market_vwap: 市场 VWAP（可选）

        Returns:
            TCA 报告
        """
        if not fills:
            return TCAReport(
                symbol="", side="", total_quantity=Decimal("0"),
                avg_fill_price=Decimal("0"), arrival_price=arrival_price,
                vwap_price=Decimal("0"), implementation_shortfall=Decimal("0"),
                slippage_bps=0, fill_rate=0, fill_count=0,
                total_commission=Decimal("0"),
            )

        total_qty = sum(f.quantity for f in fills)
        total_notional = sum(f.price * f.quantity for f in fills)
        avg_price = total_notional / total_qty if total_qty > 0 else Decimal("0")
        total_commission = sum(f.fee for f in fills)

        # VWAP
        vwap = market_vwap if market_vwap else avg_price

        # 实施缺口
        side_sign = Decimal("1") if fills[0].side == "buy" else Decimal("-1")
        shortfall = (avg_price - arrival_price) * side_sign * total_qty

        # 滑点（基点）
        slippage_bps = float((avg_price - arrival_price) / arrival_price * 10000) if arrival_price > 0 else 0

        return TCAReport(
            symbol=fills[0].symbol,
            side=fills[0].side,
            total_quantity=total_qty,
            avg_fill_price=avg_price,
            arrival_price=arrival_price,
            vwap_price=vwap,
            implementation_shortfall=shortfall,
            slippage_bps=slippage_bps,
            fill_rate=1.0,
            fill_count=len(fills),
            total_commission=total_commission,
        )
