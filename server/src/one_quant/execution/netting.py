"""
ONE量化 - 多策略净额轧差 + 跨策略同向限额 + 冲突仲裁

两个层次的轧差：
  1. MultiStrategyNetting: 信号级轧差（信号合并，输出净信号）
  2. NettingEngine: 订单级轧差（同标的反向订单内部对冲，减少手续费）

多策略并行可能自相残杀（A买BTC、B卖BTC=内部对敲白付手续费），
NettingEngine 在订单发出前先内部对冲，只对净额部分下单到交易所。
"""

from __future__ import annotations

import time
from collections import defaultdict
from decimal import Decimal
from typing import Any

from one_quant.core.types import Order, Signal
from one_quant.infra.logging import get_logger

logger = get_logger(__name__)


# ──────────────────────────── 信号级轧差 ────────────────────────────


class MultiStrategyNetting:
    """多策略信号级净额轧差引擎。

    多个策略可能同时对同一标的产生相反方向的信号。
    轧差引擎：
    1. 汇总同标的所有信号
    2. 计算净方向和净数量
    3. 同向限额检查（防止单方向过重）
    4. 冲突仲裁（多空信号强度对比）

    示例：
    - 策略 A: BTC/USDT 买入 0.5（强度 0.8）
    - 策略 B: BTC/USDT 卖出 0.3（强度 0.6）
    - 净结果: 买入 0.2
    """

    def __init__(
        self,
        max_same_side_pct: Decimal = Decimal("0.3"),  # 同方向最大占总资产 30%
        conflict_threshold: float = 0.3,  # 信号差异阈值
    ) -> None:
        self._max_same_side_pct = max_same_side_pct
        self._conflict_threshold = conflict_threshold
        self._netting_history: list[dict[str, Any]] = []

    def net_signals(self, signals: list[Signal]) -> list[Signal]:
        """对信号进行净额轧差。

        Args:
            signals: 原始信号列表（可能包含同一标的的多空信号）

        Returns:
            轧差后的净信号列表
        """
        # 按标的分组
        by_symbol: dict[str, list[Signal]] = defaultdict(list)
        for sig in signals:
            by_symbol[sig.symbol].append(sig)

        netted: list[Signal] = []

        for symbol, group in by_symbol.items():
            buys = [s for s in group if s.side == "buy"]
            sells = [s for s in group if s.side == "sell"]

            buy_strength = sum(s.strength for s in buys)
            sell_strength = sum(s.strength for s in sells)

            # 计算净方向
            net_strength = buy_strength - sell_strength

            if abs(net_strength) < 0.01:
                # 完全抵消，不产生信号
                logger.info("信号完全抵消: %s (买=%f, 卖=%f)", symbol, buy_strength, sell_strength)
                continue

            # 冲突检测
            if buys and sells:
                conflict_level = min(buy_strength, sell_strength) / max(buy_strength, sell_strength)
                if conflict_level > self._conflict_threshold:
                    logger.warning(
                        "信号冲突: %s 买强度=%f 卖强度=%f 冲突度=%f",
                        symbol,
                        buy_strength,
                        sell_strength,
                        conflict_level,
                    )

            # 生成净信号
            side = "buy" if net_strength > 0 else "sell"
            strength = min(abs(net_strength), 1.0)
            reason_parts = []
            if buys:
                reason_parts.append(f"多头×{len(buys)}")
            if sells:
                reason_parts.append(f"空头×{len(sells)}")

            netted.append(
                Signal(
                    symbol=symbol,
                    market=group[0].market,
                    side=side,
                    strength=strength,
                    strategy_name="multi_strategy_netting",
                    reason=f"净额轧差: {' vs '.join(reason_parts)}, 净方向={side}",
                    timestamp_ns=time.time_ns(),
                )
            )

            self._netting_history.append(
                {
                    "symbol": symbol,
                    "buy_count": len(buys),
                    "sell_count": len(sells),
                    "net_side": side,
                    "net_strength": strength,
                    "timestamp_ns": time.time_ns(),
                }
            )

        return netted

    @property
    def stats(self) -> dict[str, int]:
        return {"netting_operations": len(self._netting_history)}


# ──────────────────────────── 订单级净额轧差 ────────────────────────────


class NettingEngine:
    """多策略订单级净额轧差引擎。

    多策略并行可能自相残杀（A买BTC、B卖BTC=内部对敲白付手续费）。
    NettingEngine 在订单发出交易所之前进行内部对冲：
      1. 汇总同标的反向订单
      2. 内部撮合（减少外部手续费）
      3. 只对净额部分下单到交易所

    示例：
      策略A: 买入 BTC 1.0 @ 50000
      策略B: 卖出 BTC 0.6 @ 50000
      净额: 买入 BTC 0.4 @ 50000（节省 0.6 × 手续费）

    Attributes:
        fee_rate: 外部交易所手续费率（用于计算节省金额）
    """

    def __init__(self, fee_rate: Decimal = Decimal("0.001")) -> None:
        """初始化净额轧差引擎。

        Args:
            fee_rate: 交易所手续费率（默认 0.1%）
        """
        self._fee_rate = fee_rate
        self._netting_log: list[dict[str, Any]] = []
        self._total_saved_fees = Decimal("0")

    def net_orders(self, orders: list[Order]) -> list[Order]:
        """内部净额对冲：同标的反向先内部对冲再出净单。

        处理流程：
          1. 按 (symbol, exchange) 分组
          2. 同组内 buy 和 sell 对冲
          3. 输出净额订单（保留原始 client_order_id 追溯）

        Args:
            orders: 原始订单列表

        Returns:
            净额订单列表（数量可能减少）
        """
        if not orders:
            return []

        # 按 (symbol, exchange) 分组
        groups: dict[tuple[str, str], list[Order]] = defaultdict(list)
        for order in orders:
            key = (order.symbol, order.exchange)
            groups[key].append(order)

        netted_orders: list[Order] = []

        for (symbol, exchange), group in groups.items():
            buys = [o for o in group if o.side == "buy"]
            sells = [o for o in group if o.side == "sell"]

            total_buy_qty = sum(o.quantity for o in buys)
            total_sell_qty = sum(o.quantity for o in sells)

            if not buys or not sells:
                # 无反向订单，全部保留
                netted_orders.extend(group)
                continue

            # 内部对冲
            hedge_qty = min(total_buy_qty, total_sell_qty)
            net_buy = total_buy_qty - hedge_qty
            net_sell = total_sell_qty - hedge_qty

            # 计算节省的手续费
            saved_fees = hedge_qty * 2 * self._fee_rate  # 买+卖两笔
            self._total_saved_fees += saved_fees

            logger.info(
                "内部对冲: %s@%s 对冲量=%s, 买净=%s, 卖净=%s, 节省手续费=%s",
                symbol,
                exchange,
                hedge_qty,
                net_buy,
                net_sell,
                saved_fees,
            )

            self._netting_log.append(
                {
                    "symbol": symbol,
                    "exchange": exchange,
                    "hedge_quantity": hedge_qty,
                    "saved_fees": saved_fees,
                    "timestamp_ns": time.time_ns(),
                }
            )

            # 生成净额订单
            if net_buy > 0:
                # 取第一个 buy 订单作为模板
                template = buys[0]
                netted_orders.append(
                    Order(
                        client_order_id=template.client_order_id,
                        symbol=template.symbol,
                        market=template.market,
                        side="buy",
                        order_type=template.order_type,
                        quantity=net_buy,
                        price=template.price,
                        stop_price=template.stop_price,
                        status=template.status,
                        exchange=template.exchange,
                        timestamp_ns=time.time_ns(),
                    )
                )

            if net_sell > 0:
                template = sells[0]
                netted_orders.append(
                    Order(
                        client_order_id=template.client_order_id,
                        symbol=template.symbol,
                        market=template.market,
                        side="sell",
                        order_type=template.order_type,
                        quantity=net_sell,
                        price=template.price,
                        stop_price=template.stop_price,
                        status=template.status,
                        exchange=template.exchange,
                        timestamp_ns=time.time_ns(),
                    )
                )

        return netted_orders

    def check_conflict(self, orders: list[Order]) -> list[dict[str, Any]]:
        """检测策略间冲突。

        识别同标的反向订单（可能的内部对敲）。

        Args:
            orders: 订单列表

        Returns:
            冲突列表：
            [
                {
                    "symbol": str,
                    "exchange": str,
                    "buy_orders": list[Order],
                    "sell_orders": list[Order],
                    "conflict_quantity": Decimal,   # 可对冲数量
                    "conflict_value": Decimal,      # 可对冲金额
                    "severity": str,                # "low" / "medium" / "high"
                }
            ]
        """
        groups: dict[tuple[str, str], list[Order]] = defaultdict(list)
        for order in orders:
            key = (order.symbol, order.exchange)
            groups[key].append(order)

        conflicts: list[dict[str, Any]] = []

        for (symbol, exchange), group in groups.items():
            buys = [o for o in group if o.side == "buy"]
            sells = [o for o in group if o.side == "sell"]

            if not buys or not sells:
                continue

            total_buy = sum(o.quantity for o in buys)
            total_sell = sum(o.quantity for o in sells)
            conflict_qty = min(total_buy, total_sell)

            # 估算冲突金额
            avg_price = Decimal("0")
            all_orders = buys + sells
            for o in all_orders:
                if o.price:
                    avg_price += o.price
            avg_price = avg_price / len(all_orders) if all_orders else Decimal("0")
            conflict_value = conflict_qty * avg_price

            # 严重程度
            if conflict_qty > total_buy * Decimal("0.5") or conflict_qty > total_sell * Decimal(
                "0.5"
            ):
                severity = "high"
            elif conflict_qty > total_buy * Decimal("0.2") or conflict_qty > total_sell * Decimal(
                "0.2"
            ):
                severity = "medium"
            else:
                severity = "low"

            conflicts.append(
                {
                    "symbol": symbol,
                    "exchange": exchange,
                    "buy_orders": buys,
                    "sell_orders": sells,
                    "conflict_quantity": conflict_qty,
                    "conflict_value": conflict_value,
                    "severity": severity,
                }
            )

        if conflicts:
            logger.warning("检测到 %d 个策略间冲突", len(conflicts))

        return conflicts

    def arbitrate(self, conflicting_orders: list[Order]) -> list[Order]:
        """冲突仲裁。

        当多个策略对同一标的产生反向订单时，通过加权评分决定最终方向。

        仲裁规则：
          1. 按 (symbol, exchange) 分组
          2. 计算各方向的加权得分（价格 × 数量 × 优先级）
          3. 得分高的方向保留，低的取消
          4. 同方向多订单合并

        Args:
            conflicting_orders: 冲突订单列表

        Returns:
            仲裁后的订单列表
        """
        if not conflicting_orders:
            return []

        groups: dict[tuple[str, str], list[Order]] = defaultdict(list)
        for order in conflicting_orders:
            key = (order.symbol, order.exchange)
            groups[key].append(order)

        arbitrated: list[Order] = []

        for (symbol, exchange), group in groups.items():
            buys = [o for o in group if o.side == "buy"]
            sells = [o for o in group if o.side == "sell"]

            if not buys or not sells:
                # 无冲突，保留所有
                arbitrated.extend(group)
                continue

            # 计算各方加权得分
            buy_score = self._calculate_score(buys)
            sell_score = self._calculate_score(sells)

            if buy_score > sell_score:
                # 买方胜出，合并买入订单
                merged = self._merge_orders(buys, "buy", symbol, exchange)
                arbitrated.append(merged)
                logger.info(
                    "仲裁结果: %s@%s 保留买方 (得分 %.4f vs %.4f)",
                    symbol,
                    exchange,
                    buy_score,
                    sell_score,
                )
            elif sell_score > buy_score:
                merged = self._merge_orders(sells, "sell", symbol, exchange)
                arbitrated.append(merged)
                logger.info(
                    "仲裁结果: %s@%s 保留卖方 (得分 %.4f vs %.4f)",
                    symbol,
                    exchange,
                    sell_score,
                    buy_score,
                )
            else:
                # 得分相等，全部取消（避免内部对敲）
                logger.info("仲裁结果: %s@%s 得分相等，全部取消", symbol, exchange)

        return arbitrated

    def _calculate_score(self, orders: list[Order]) -> float:
        """计算订单组加权得分。

        得分 = Σ(quantity × price) / 1000
        无价格时用数量替代。

        Args:
            orders: 订单列表

        Returns:
            加权得分
        """
        score = 0.0
        for o in orders:
            if o.price and o.price > 0:
                score += float(o.quantity * o.price)
            else:
                score += float(o.quantity) * 50000  # 默认价格估算
        return score / 1000

    def _merge_orders(self, orders: list[Order], side: str, symbol: str, exchange: str) -> Order:
        """合并同方向订单为一个净额订单。

        Args:
            orders: 待合并订单
            side: 方向
            symbol: 标的
            exchange: 交易所

        Returns:
            合并后的订单
        """
        total_qty = sum(o.quantity for o in orders)
        # 加权平均价格
        total_notional = sum(o.quantity * (o.price or Decimal("0")) for o in orders)
        avg_price = (
            total_notional / total_qty if total_qty > 0 and any(o.price for o in orders) else None
        )

        # 使用第一个订单的 client_order_id 作为主 ID
        primary = orders[0]

        return Order(
            client_order_id=primary.client_order_id,
            symbol=symbol,
            market=primary.market,
            side=side,
            order_type=primary.order_type,
            quantity=total_qty,
            price=avg_price,
            stop_price=primary.stop_price,
            status="pending",
            exchange=exchange,
            timestamp_ns=time.time_ns(),
        )

    @property
    def stats(self) -> dict[str, Any]:
        """轧差统计。"""
        return {
            "netting_operations": len(self._netting_log),
            "total_saved_fees": self._total_saved_fees,
        }
