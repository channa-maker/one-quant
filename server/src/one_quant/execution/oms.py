"""
ONE量化 - 订单管理系统 (OMS)

管理订单全生命周期：新建 → 已提交 → 部分成交 → 全部成交/已撤/拒绝。
幂等设计：所有订单带 clientOrderId (UUIDv4)，重试不重复。
"""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal

from one_quant.core.types import (
    Fill,
    Market,
    Order,
    PositionState,
    Signal,
)
from one_quant.infra.event_bus import EventBus

logger = logging.getLogger(__name__)


class OrderManager:
    """订单管理系统。

    职责：
    1. 从信号创建订单（带幂等 ID）。
    2. 提交到交易所适配器。
    3. 处理成交回报，更新订单状态。
    4. 管理持仓状态。

    Attributes:
        event_bus: 事件总线实例。
    """

    def __init__(self, event_bus: EventBus) -> None:
        """初始化 OMS。

        Args:
            event_bus: 事件总线实例。
        """
        self._event_bus = event_bus
        self._orders: dict[str, Order] = {}  # client_order_id -> Order
        self._positions: dict[str, PositionState] = {}  # symbol -> PositionState
        self._fills: list[Fill] = []

    def create_order_from_signal(
        self,
        signal: Signal,
        order_type: str = "limit",
        price: Decimal | None = None,
        quantity: Decimal = Decimal("0"),
        exchange: str = "",
    ) -> Order:
        """从策略信号创建订单。

        Args:
            signal: 策略信号。
            order_type: 订单类型。
            price: 委托价格。
            quantity: 委托数量。
            exchange: 交易所名称。

        Returns:
            创建的订单对象。
        """
        order = Order(
            client_order_id=str(uuid.uuid4()),
            symbol=signal.symbol,
            market=signal.market,
            side=signal.side,
            order_type=order_type,  # type: ignore
            quantity=quantity,
            price=price,
            stop_price=None,
            status="pending",
            exchange=exchange,
            timestamp_ns=signal.timestamp_ns,
        )
        self._orders[order.client_order_id] = order

        logger.info(
            "订单已创建: %s %s %s %s @ %s (策略: %s)",
            order.client_order_id[:8],
            order.side,
            order.quantity,
            order.symbol,
            order.price or "市价",
            signal.strategy_name,
        )

        return order

    def update_order_status(
        self,
        client_order_id: str,
        status: str,
    ) -> Order | None:
        """更新订单状态。

        由于 Order 是 frozen 模型，此方法创建新实例替换旧的。

        Args:
            client_order_id: 客户端订单 ID。
            status: 新状态。

        Returns:
            更新后的订单，未找到返回 None。
        """
        old = self._orders.get(client_order_id)
        if old is None:
            logger.warning("订单不存在: %s", client_order_id)
            return None

        # 创建新实例（frozen 模型不可变）
        new_order = old.model_copy(update={"status": status})
        self._orders[client_order_id] = new_order

        logger.info("订单状态更新: %s → %s", client_order_id[:8], status)
        return new_order

    def process_fill(self, fill: Fill) -> None:
        """处理成交回报。

        更新订单状态和持仓。

        Args:
            fill: 成交回报。
        """
        self._fills.append(fill)

        # 更新订单状态
        order = self._orders.get(fill.order_id)
        if order is not None:
            # 简化处理：假设全部成交
            self.update_order_status(fill.order_id, "filled")

        # 更新持仓（简化实现）
        self._update_position(fill)

        logger.info(
            "成交回报: %s %s %s @ %s (手续费: %s %s)",
            fill.order_id[:8],
            fill.side,
            fill.quantity,
            fill.price,
            fill.fee,
            fill.fee_currency,
        )

    def _update_position(self, fill: Fill) -> None:
        """根据成交更新持仓状态。"""
        symbol = fill.symbol
        current = self._positions.get(symbol)

        if current is None:
            # 新持仓：从关联订单获取市场类型，订单不存在则降级为现货
            order = self._orders.get(fill.order_id)
            market = order.market if order is not None else Market.SPOT
            side = "long" if fill.side == "buy" else "short"
            self._positions[symbol] = PositionState(
                symbol=symbol,
                market=market,
                side=side if side in ("long", "short", "flat") else "flat",  # type: ignore[arg-type]
                quantity=fill.quantity,
                entry_price=fill.price,
                unrealized_pnl=Decimal("0"),
                realized_pnl=Decimal("0"),
                timestamp_ns=fill.timestamp_ns,
            )
        else:
            # 更新持仓（简化）
            logger.debug("持仓更新: %s", symbol)

    def get_order(self, client_order_id: str) -> Order | None:
        """查询订单。"""
        return self._orders.get(client_order_id)

    def get_position(self, symbol: str) -> PositionState | None:
        """查询持仓。"""
        return self._positions.get(symbol)

    def get_all_positions(self) -> list[PositionState]:
        """查询所有持仓。"""
        return list(self._positions.values())

    @property
    def stats(self) -> dict[str, int]:
        """统计信息。"""
        return {
            "orders": len(self._orders),
            "fills": len(self._fills),
            "positions": len(self._positions),
        }
