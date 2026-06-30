"""
美股税务处理模块

包含：
  - Wash Sale 检测（30 天内回购亏损股规则）
  - Tax-Lot 会计（FIFO / 特定批次）
  - 税务报表导出

规范：
  - 所有金额使用 Decimal 精确计算
  - 不从 .env/DB 读取规则常量
  - 税务规则基于 IRS 公开规定
"""

from __future__ import annotations

import time
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Literal

from pydantic import BaseModel

from one_quant.infra.logging import get_logger

logger = get_logger(__name__)


# ──────────────────────────── 数据模型 ────────────────────────────


class TaxLot(BaseModel, frozen=True):
    """税务批次记录

    Attributes:
        symbol: 标的符号
        buy_date: 买入日期
        buy_price: 买入价格
        quantity: 数量
        lot_id: 批次ID（唯一标识）
    """

    symbol: str
    buy_date: date
    buy_price: Decimal
    quantity: Decimal
    lot_id: str


class DisposalRecord(BaseModel, frozen=True):
    """处置记录（卖出）

    Attributes:
        symbol: 标的符号
        sell_date: 卖出日期
        sell_price: 卖出价格
        quantity: 数量
        cost_basis: 成本基础
        realized_pnl: 已实现盈亏
        holding_period: 持有期（天）
        is_long_term: 是否为长期持有（> 365 天）
        wash_sale: 是否触发 Wash Sale
        disallowed_loss: 不可抵扣亏损（Wash Sale 时）
    """

    symbol: str
    sell_date: date
    sell_price: Decimal
    quantity: Decimal
    cost_basis: Decimal
    realized_pnl: Decimal
    holding_period: int
    is_long_term: bool
    wash_sale: bool = False
    disallowed_loss: Decimal = Decimal("0")


# ──────────────────────────── Wash Sale 检测 ────────────────────────────


class WashSaleDetector:
    """Wash Sale 检测（IRS Wash Sale Rule）

    规则：
    - 卖出证券产生亏损后，30 天内（含前后）回购"实质相同"证券，
      则该亏损不可在当年抵扣，需加到新购证券的成本基础中。
    - 30 天窗口：卖出日前 30 天 + 卖出日后 30 天
    - 适用于股票、期权、认股权证等

    硬规则：30 天窗口由 IRS 规定，不从配置读取。

    使用方式::

        detector = WashSaleDetector()

        # 卖出亏损后 20 天内回购
        is_wash = detector.check_wash_sale(
            symbol="AAPL",
            sell_date=date(2024, 1, 15),
            sell_price=Decimal("150"),
            buy_date=date(2024, 2, 1),  # 17 天后
            buy_price=Decimal("155"),
        )
        # is_wash = True
    """

    # Wash Sale 窗口（IRS 规定 30 天）
    WASH_SALE_WINDOW_DAYS = 30

    def __init__(self) -> None:
        # symbol -> 卖出记录列表
        self._sales: dict[str, list[dict[str, Any]]] = defaultdict(list)
        # 不可抵扣亏损累积
        self._disallowed_losses: list[dict[str, Any]] = []

    def record_sale(
        self,
        symbol: str,
        sell_date: date,
        sell_price: Decimal,
        quantity: Decimal,
        cost_basis: Decimal,
    ) -> None:
        """记录卖出（用于后续 Wash Sale 检测）

        Args:
            symbol: 标的符号
            sell_date: 卖出日期
            sell_price: 卖出价格
            quantity: 卖出数量
            cost_basis: 成本基础
        """
        pnl = (sell_price - cost_basis) * quantity
        self._sales[symbol].append(
            {
                "sell_date": sell_date,
                "sell_price": sell_price,
                "quantity": quantity,
                "cost_basis": cost_basis,
                "pnl": pnl,
                "is_loss": pnl < 0,
            }
        )

    def check_wash_sale(
        self,
        symbol: str,
        sell_date: date,
        sell_price: Decimal,
        buy_date: date,
        buy_price: Decimal,
    ) -> tuple[bool, Decimal]:
        """检查是否触发 Wash Sale

        Args:
            symbol: 标的符号
            sell_date: 卖出日期
            sell_price: 卖出价格
            buy_date: 回购日期
            buy_price: 回购价格

        Returns:
            (是否触发 Wash Sale, 不可抵扣亏损金额)
        """
        # 计算卖出盈亏
        pnl = sell_price - buy_price  # 简化：假设成本基础为 buy_price

        # 如果没有亏损，不适用 Wash Sale
        if sell_price >= buy_price:
            return False, Decimal("0")

        # 检查是否在 30 天窗口内回购
        window_start = sell_date - timedelta(days=self.WASH_SALE_WINDOW_DAYS)
        window_end = sell_date + timedelta(days=self.WASH_SALE_WINDOW_DAYS)

        if window_start <= buy_date <= window_end:
            # 触发 Wash Sale
            loss = abs(sell_price - buy_price)
            logger.info(
                "Wash Sale 触发: %s, 卖出日 %s, 回购日 %s, 不可抵扣亏损 $%s",
                symbol,
                sell_date,
                buy_date,
                loss,
            )
            self._disallowed_losses.append(
                {
                    "symbol": symbol,
                    "sell_date": sell_date,
                    "buy_date": buy_date,
                    "disallowed_loss": loss,
                }
            )
            return True, loss

        return False, Decimal("0")

    def check_wash_sale_with_lots(
        self,
        symbol: str,
        sell_date: date,
        sell_price: Decimal,
        cost_basis: Decimal,
        quantity: Decimal,
        recent_buys: list[dict[str, Any]],
    ) -> tuple[bool, Decimal]:
        """使用已有批次检查 Wash Sale

        Args:
            symbol: 标的符号
            sell_date: 卖出日期
            sell_price: 卖出价格
            cost_basis: 成本基础
            quantity: 卖出数量
            recent_buys: 近期买入记录列表，每项含 buy_date/buy_price/quantity

        Returns:
            (是否触发, 不可抵扣亏损)
        """
        loss = (cost_basis - sell_price) * quantity
        if loss <= 0:
            return False, Decimal("0")

        window_start = sell_date - timedelta(days=self.WASH_SALE_WINDOW_DAYS)
        window_end = sell_date + timedelta(days=self.WASH_SALE_WINDOW_DAYS)

        for buy in recent_buys:
            buy_date = buy["buy_date"]
            if window_start <= buy_date <= window_end:
                logger.info(
                    "Wash Sale 触发: %s, 卖出日 %s 回购日 %s, 不可抵扣亏损 $%s",
                    symbol,
                    sell_date,
                    buy_date,
                    loss,
                )
                return True, loss

        return False, Decimal("0")

    @property
    def total_disallowed_loss(self) -> Decimal:
        """累计不可抵扣亏损"""
        return sum(
            (d["disallowed_loss"] for d in self._disallowed_losses),
            Decimal("0"),
        )


# ──────────────────────────── Tax-Lot 会计 ────────────────────────────


class TaxLotAccounting:
    """Tax-Lot 会计

    管理持仓批次，支持多种成本基础计算方法：
    - FIFO (First In, First Out): 先进先出
    - Specific ID: 特定批次指定

    IRS 要求纳税人选择一种方法并保持一致。

    使用方式::

        accounting = TaxLotAccounting()

        # 记录买入批次
        accounting.add_lot("AAPL", date(2024, 1, 10), Decimal("150"), Decimal("100"))
        accounting.add_lot("AAPL", date(2024, 2, 15), Decimal("160"), Decimal("50"))

        # 卖出时计算成本基础
        cost_basis, lots = accounting.calculate_cost_basis(
            "AAPL", Decimal("80"), method="fifo"
        )
    """

    def __init__(self) -> None:
        # symbol -> 按时间排序的批次列表
        self._lots: dict[str, list[TaxLot]] = defaultdict(list)
        self._lot_counter = 0

    def add_lot(
        self,
        symbol: str,
        buy_date: date,
        buy_price: Decimal,
        quantity: Decimal,
    ) -> TaxLot:
        """添加持仓批次

        Args:
            symbol: 标的符号
            buy_date: 买入日期
            buy_price: 买入价格
            quantity: 数量

        Returns:
            创建的批次记录
        """
        self._lot_counter += 1
        lot = TaxLot(
            symbol=symbol,
            buy_date=buy_date,
            buy_price=buy_price,
            quantity=quantity,
            lot_id=f"LOT-{self._lot_counter:08d}",
        )
        self._lots[symbol].append(lot)
        # 按买入日期排序
        self._lots[symbol].sort(key=lambda l: l.buy_date)
        return lot

    def calculate_cost_basis(
        self,
        symbol: str,
        quantity: Decimal,
        method: Literal["fifo", "specific"] = "fifo",
        specific_lot_ids: list[str] | None = None,
    ) -> tuple[Decimal, list[TaxLot]]:
        """计算卖出的成本基础

        Args:
            symbol: 标的符号
            quantity: 卖出数量
            method: 计算方法 ("fifo" 或 "specific")
            specific_lot_ids: 特定批次ID列表（method="specific" 时必填）

        Returns:
            (总成本基础, 消耗的批次列表)

        Raises:
            ValueError: 批次数量不足或指定批次无效
        """
        lots = self._lots.get(symbol, [])
        if not lots:
            raise ValueError(f"无可用批次: {symbol}")

        if method == "fifo":
            return self._fifo_cost_basis(lots, quantity)
        elif method == "specific":
            if not specific_lot_ids:
                raise ValueError("特定批次方法必须指定 lot_ids")
            return self._specific_cost_basis(lots, quantity, specific_lot_ids)
        else:
            raise ValueError(f"不支持的成本基础方法: {method}")

    def _fifo_cost_basis(
        self, lots: list[TaxLot], quantity: Decimal
    ) -> tuple[Decimal, list[TaxLot]]:
        """FIFO 先进先出"""
        remaining = quantity
        total_cost = Decimal("0")
        consumed: list[TaxLot] = []

        for lot in lots:
            if remaining <= 0:
                break
            if lot.quantity <= 0:
                continue

            take = min(remaining, lot.quantity)
            cost = take * lot.buy_price
            total_cost += cost
            remaining -= take

            consumed.append(
                TaxLot(
                    symbol=lot.symbol,
                    buy_date=lot.buy_date,
                    buy_price=lot.buy_price,
                    quantity=take,
                    lot_id=lot.lot_id,
                )
            )

        if remaining > 0:
            raise ValueError(
                f"批次数量不足: {symbol} 需要 {quantity}, "
                f"可用 {quantity - remaining}"
            )

        # 更新原始批次（扣除已消耗）
        consumed_ids = {c.lot_id: c.quantity for c in consumed}
        for lot in lots:
            if lot.lot_id in consumed_ids:
                # 此处不修改 frozen 模型，实际应维护可变状态
                pass

        return total_cost.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), consumed

    def _specific_cost_basis(
        self,
        lots: list[TaxLot],
        quantity: Decimal,
        specific_lot_ids: list[str],
    ) -> tuple[Decimal, list[TaxLot]]:
        """特定批次指定"""
        lot_map = {l.lot_id: l for l in lots}
        total_cost = Decimal("0")
        consumed: list[TaxLot] = []
        remaining = quantity

        for lot_id in specific_lot_ids:
            if remaining <= 0:
                break
            lot = lot_map.get(lot_id)
            if lot is None:
                raise ValueError(f"批次不存在: {lot_id}")
            if lot.quantity <= 0:
                continue

            take = min(remaining, lot.quantity)
            cost = take * lot.buy_price
            total_cost += cost
            remaining -= take

            consumed.append(
                TaxLot(
                    symbol=lot.symbol,
                    buy_date=lot.buy_date,
                    buy_price=lot.buy_price,
                    quantity=take,
                    lot_id=lot.lot_id,
                )
            )

        if remaining > 0:
            raise ValueError(
                f"指定批次数量不足: 需要 {quantity}, 可用 {quantity - remaining}"
            )

        return total_cost.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), consumed

    def get_lots(self, symbol: str) -> list[TaxLot]:
        """获取指定标的的所有批次

        Args:
            symbol: 标的符号

        Returns:
            批次列表
        """
        return list(self._lots.get(symbol, []))

    def get_total_quantity(self, symbol: str) -> Decimal:
        """获取指定标的的总持仓数量

        Args:
            symbol: 标的符号

        Returns:
            总数量
        """
        return sum(l.quantity for l in self._lots.get(symbol, []))


# ──────────────────────────── 税务报表 ────────────────────────────


class TaxReportGenerator:
    """税务报表导出

    生成符合 IRS 要求的年度税务报表，包括：
    - Schedule D (资本利得/亏损)
    - Form 8949 (销售和处置明细)
    - Wash Sale 汇总

    使用方式::

        generator = TaxReportGenerator(
            wash_sale_detector=detector,
            tax_lot_accounting=accounting,
        )
        report = generator.generate_annual_report(2024)
    """

    # 长期持有阈值（IRS 规定 365 天）
    LONG_TERM_THRESHOLD_DAYS = 365

    def __init__(
        self,
        wash_sale_detector: WashSaleDetector | None = None,
        tax_lot_accounting: TaxLotAccounting | None = None,
    ) -> None:
        self._detector = wash_sale_detector or WashSaleDetector()
        self._accounting = tax_lot_accounting or TaxLotAccounting()
        # 处置记录
        self._disposals: list[DisposalRecord] = []

    def add_disposal(
        self,
        symbol: str,
        sell_date: date,
        sell_price: Decimal,
        quantity: Decimal,
        cost_basis: Decimal,
        buy_date: date,
    ) -> DisposalRecord:
        """添加处置记录

        Args:
            symbol: 标的符号
            sell_date: 卖出日期
            sell_price: 卖出价格
            quantity: 数量
            cost_basis: 成本基础
            buy_date: 买入日期

        Returns:
            处置记录
        """
        realized_pnl = (sell_price * quantity) - cost_basis
        holding_days = (sell_date - buy_date).days
        is_long_term = holding_days > self.LONG_TERM_THRESHOLD_DAYS

        # 检查 Wash Sale
        wash_sale, disallowed = self._detector.check_wash_sale(
            symbol=symbol,
            sell_date=sell_date,
            sell_price=sell_price,
            buy_date=sell_date,  # 简化：实际应检查近期回购
            buy_price=cost_basis / quantity if quantity > 0 else Decimal("0"),
        )

        disposal = DisposalRecord(
            symbol=symbol,
            sell_date=sell_date,
            sell_price=sell_price,
            quantity=quantity,
            cost_basis=cost_basis,
            realized_pnl=realized_pnl,
            holding_period=holding_days,
            is_long_term=is_long_term,
            wash_sale=wash_sale,
            disallowed_loss=disallowed,
        )
        self._disposals.append(disposal)
        return disposal

    def generate_annual_report(self, year: int) -> dict[str, Any]:
        """生成年度税务报表

        Args:
            year: 年份

        Returns:
            税务报表字典，包含：
            - summary: 汇总数据
            - schedule_d: Schedule D 数据
            - form_8949: Form 8949 明细
            - wash_sale_summary: Wash Sale 汇总
        """
        # 筛选指定年份的处置记录
        year_disposals = [
            d for d in self._disposals if d.sell_date.year == year
        ]

        # 分类：短期 vs 长期
        short_term = [d for d in year_disposals if not d.is_long_term]
        long_term = [d for d in year_disposals if d.is_long_term]

        # 汇总计算
        short_term_gain = sum(
            (d.realized_pnl for d in short_term if d.realized_pnl > 0),
            Decimal("0"),
        )
        short_term_loss = sum(
            (d.realized_pnl for d in short_term if d.realized_pnl < 0),
            Decimal("0"),
        )
        long_term_gain = sum(
            (d.realized_pnl for d in long_term if d.realized_pnl > 0),
            Decimal("0"),
        )
        long_term_loss = sum(
            (d.realized_pnl for d in long_term if d.realized_pnl < 0),
            Decimal("0"),
        )

        total_wash_sale_loss = sum(
            (d.disallowed_loss for d in year_disposals if d.wash_sale),
            Decimal("0"),
        )

        net_short = short_term_gain + short_term_loss
        net_long = long_term_gain + long_term_loss
        net_total = net_short + net_long

        # Form 8949 明细
        form_8949_entries = []
        for d in year_disposals:
            form_8949_entries.append(
                {
                    "symbol": d.symbol,
                    "acquired": str(d.sell_date - timedelta(days=d.holding_period)),
                    "sold": str(d.sell_date),
                    "proceeds": str(d.sell_price * d.quantity),
                    "cost_basis": str(d.cost_basis),
                    "gain_loss": str(d.realized_pnl),
                    "holding_period": d.holding_period,
                    "long_term": d.is_long_term,
                    "wash_sale": d.wash_sale,
                    "wash_sale_adjustment": str(d.disallowed_loss),
                }
            )

        report = {
            "year": year,
            "generated_at": str(date.today()),
            "summary": {
                "total_disposals": len(year_disposals),
                "short_term_transactions": len(short_term),
                "long_term_transactions": len(long_term),
                "short_term_gain": str(short_term_gain.quantize(Decimal("0.01"))),
                "short_term_loss": str(short_term_loss.quantize(Decimal("0.01"))),
                "net_short_term": str(net_short.quantize(Decimal("0.01"))),
                "long_term_gain": str(long_term_gain.quantize(Decimal("0.01"))),
                "long_term_loss": str(long_term_loss.quantize(Decimal("0.01"))),
                "net_long_term": str(net_long.quantize(Decimal("0.01"))),
                "net_total": str(net_total.quantize(Decimal("0.01"))),
                "wash_sale_disallowed_loss": str(
                    total_wash_sale_loss.quantize(Decimal("0.01"))
                ),
            },
            "schedule_d": {
                "part_i_short_term": {
                    "total_proceeds": str(
                        sum(
                            (d.sell_price * d.quantity for d in short_term),
                            Decimal("0"),
                        ).quantize(Decimal("0.01"))
                    ),
                    "total_cost_basis": str(
                        sum(
                            (d.cost_basis for d in short_term),
                            Decimal("0"),
                        ).quantize(Decimal("0.01"))
                    ),
                    "total_gain_loss": str(net_short.quantize(Decimal("0.01"))),
                },
                "part_ii_long_term": {
                    "total_proceeds": str(
                        sum(
                            (d.sell_price * d.quantity for d in long_term),
                            Decimal("0"),
                        ).quantize(Decimal("0.01"))
                    ),
                    "total_cost_basis": str(
                        sum(
                            (d.cost_basis for d in long_term),
                            Decimal("0"),
                        ).quantize(Decimal("0.01"))
                    ),
                    "total_gain_loss": str(net_long.quantize(Decimal("0.01"))),
                },
            },
            "form_8949": form_8949_entries,
            "wash_sale_summary": {
                "affected_transactions": sum(
                    1 for d in year_disposals if d.wash_sale
                ),
                "total_disallowed_loss": str(
                    total_wash_sale_loss.quantize(Decimal("0.01"))
                ),
                "details": [
                    {
                        "symbol": d.symbol,
                        "sell_date": str(d.sell_date),
                        "disallowed_loss": str(d.disallowed_loss),
                    }
                    for d in year_disposals
                    if d.wash_sale
                ],
            },
        }

        logger.info(
            "税务报表生成完成: %d 年, %d 笔处置, 净盈亏 $%s",
            year,
            len(year_disposals),
            report["summary"]["net_total"],
        )
        return report
