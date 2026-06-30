"""模拟盘 — 同代码同行情，仅撮合模拟"""

from __future__ import annotations

import time
import uuid
from decimal import Decimal
from typing import Any

from one_quant.core.types import Fill, Order
from one_quant.infra.logging import get_logger

logger = get_logger(__name__)


class PaperExchangeSimulator:
    """模拟交易所。

    与实盘共用同一策略代码和行情数据，仅撮合逻辑在本地模拟。
    用于：
    - 新策略灰度验证
    - 风控规则测试
    - 开发调试
    """

    def __init__(
        self,
        initial_balance: Decimal = Decimal("100000"),
        commission_rate: Decimal = Decimal("0.001"),
        slippage_bps: int = 5,
    ) -> None:
        self._balance = initial_balance
        self._commission_rate = commission_rate
        self._slippage_bps = slippage_bps
        self._positions: dict[str, dict[str, Any]] = {}
        self._open_orders: dict[str, Order] = {}
        self._fills: list[Fill] = []
        self._order_count = 0

    async def submit_order(self, order: Order) -> str:
        """提交订单到模拟撮合引擎。

        市价单立即撮合，限价单挂单等待。

        Returns:
            模拟交易所订单 ID
        """
        exchange_order_id = f"SIM-{uuid.uuid4().hex[:12]}"

        if order.order_type == "market":
            await self._match_market_order(order, exchange_order_id)
        else:
            self._open_orders[exchange_order_id] = order
            logger.info(
                "模拟限价单已挂单: %s %s %s @ %s",
                order.side,
                order.quantity,
                order.symbol,
                order.price,
            )

        self._order_count += 1
        return exchange_order_id

    async def _match_market_order(self, order: Order, exchange_id: str) -> None:
        """撮合市价单"""
        # 模拟滑点
        slippage_pct = Decimal(self._slippage_bps) / Decimal("10000")
        if order.price:
            fill_price = (
                order.price * (1 + slippage_pct)
                if order.side == "buy"
                else order.price * (1 - slippage_pct)
            )
        else:
            fill_price = Decimal("0")

        # 手续费
        notional = order.quantity * fill_price
        commission = notional * self._commission_rate

        # 扣除余额
        if order.side == "buy":
            self._balance -= notional + commission
        else:
            self._balance += notional - commission

        # 更新持仓
        self._update_position(order.symbol, order.side, order.quantity, fill_price)

        # 记录成交
        fill = Fill(
            order_id=order.client_order_id,
            symbol=order.symbol,
            side=order.side,
            price=fill_price,
            quantity=order.quantity,
            fee=commission,
            fee_currency="USDT",
            exchange="paper",
            timestamp_ns=time.time_ns(),
        )
        self._fills.append(fill)

        logger.info(
            "模拟成交: %s %s %s @ %s (手续费: %s)",
            order.side,
            order.quantity,
            order.symbol,
            fill_price,
            commission,
        )

    def _update_position(self, symbol: str, side: str, quantity: Decimal, price: Decimal) -> None:
        """更新持仓"""
        if symbol not in self._positions:
            self._positions[symbol] = {"quantity": Decimal("0"), "avg_price": Decimal("0")}

        pos = self._positions[symbol]
        if side == "buy":
            total_cost = pos["quantity"] * pos["avg_price"] + quantity * price
            pos["quantity"] += quantity
            pos["avg_price"] = total_cost / pos["quantity"] if pos["quantity"] > 0 else Decimal("0")
        else:
            pos["quantity"] -= quantity
            if pos["quantity"] <= 0:
                pos["quantity"] = Decimal("0")
                pos["avg_price"] = Decimal("0")

    async def cancel_order(self, exchange_order_id: str) -> bool:
        """撤销挂单"""
        if exchange_order_id in self._open_orders:
            del self._open_orders[exchange_order_id]
            return True
        return False

    def get_position(self, symbol: str) -> dict[str, Any]:
        """查询持仓"""
        return self._positions.get(symbol, {"quantity": Decimal("0"), "avg_price": Decimal("0")})

    def get_balance(self) -> Decimal:
        """查询余额"""
        return self._balance

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "balance": str(self._balance),
            "positions": len(self._positions),
            "open_orders": len(self._open_orders),
            "total_fills": len(self._fills),
            "total_orders": self._order_count,
        }
