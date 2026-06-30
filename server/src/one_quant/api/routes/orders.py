"""
ONE量化 - 订单路由

提供订单提交、查询、撤销接口。所有写接口需鉴权。
接入 OMS（订单管理系统）和四层风控引擎。
"""

from __future__ import annotations

import time
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from one_quant.core.types import Market, Order
from one_quant.execution.oms import OrderManager
from one_quant.risk.engine import RiskEngine

router = APIRouter()


# ──────────────────── 请求/响应模型 ────────────────────


class SubmitOrderRequest(BaseModel):
    """提交订单请求"""

    symbol: str = Field(description="标的符号")
    market: Market = Field(description="市场类型")
    side: Literal["buy", "sell"] = Field(description="买卖方向")
    order_type: Literal["limit", "market", "stop_limit", "stop_market"] = Field(
        description="订单类型"
    )
    quantity: Decimal = Field(gt=0, description="委托数量")
    price: Decimal | None = Field(default=None, description="委托价格（市价单可不填）")
    stop_price: Decimal | None = Field(default=None, description="触发价格")
    exchange: str = Field(description="交易所名称")


class OrderResponse(BaseModel):
    """订单响应"""

    client_order_id: str
    symbol: str
    market: Market
    side: str
    order_type: str
    quantity: Decimal
    price: Decimal | None
    status: str
    exchange: str


# ──────────────────── 辅助：从 app.state 获取 OMS 与风控 ────────────────────


def _get_oms(request: Request) -> OrderManager:
    """从应用状态获取或创建 OMS 实例。"""
    if not hasattr(request.app.state, "oms"):
        # 首次使用时创建 OMS，挂到 app.state
        event_bus = getattr(request.app.state, "event_bus", None)
        if event_bus is None:
            raise HTTPException(status_code=503, detail="EventBus 未初始化")
        request.app.state.oms = OrderManager(event_bus=event_bus)
    return request.app.state.oms


def _get_risk_engine(request: Request) -> RiskEngine:
    """从应用状态获取或创建风控引擎实例。"""
    if not hasattr(request.app.state, "risk_engine"):
        request.app.state.risk_engine = RiskEngine()
    return request.app.state.risk_engine


# ──────────────────── 路由 ────────────────────


@router.post("/", response_model=dict[str, Any])
async def submit_order(req: SubmitOrderRequest, request: Request) -> dict[str, Any]:
    """提交订单。

    订单经过四层风控检查后提交到 OMS。
    """
    oms = _get_oms(request)
    risk_engine = _get_risk_engine(request)

    # 构建统一订单对象
    order = Order(
        client_order_id="",  # OMS 创建时会生成 UUID
        symbol=req.symbol,
        market=req.market,
        side=req.side,
        order_type=req.order_type,
        quantity=req.quantity,
        price=req.price,
        stop_price=req.stop_price,
        status="pending",
        exchange=req.exchange,
        timestamp_ns=time.time_ns(),
    )

    # 获取当前持仓用于风控检查
    positions = oms.get_all_positions()

    # 执行四层风控检查
    risk_result = risk_engine.check(
        order=order,
        positions=positions,
        latest_price=req.price,
    )

    if risk_result.decision.value != "APPROVE":
        raise HTTPException(
            status_code=403,
            detail={
                "code": 403,
                "message": f"风控拒绝: {risk_result.reason}",
                "decision": risk_result.decision.value,
                "rule": risk_result.rule_name,
            },
        )

    # 风控通过，通过 OMS 创建订单
    from one_quant.core.types import Signal

    signal = Signal(
        symbol=req.symbol,
        market=req.market,
        side=req.side,
        strength=1.0,
        strategy_name="manual",
        reason="手动下单",
        timestamp_ns=time.time_ns(),
    )

    created_order = oms.create_order_from_signal(
        signal=signal,
        order_type=req.order_type,
        price=req.price,
        quantity=req.quantity,
        exchange=req.exchange,
    )

    return {
        "success": True,
        "data": {
            "client_order_id": created_order.client_order_id,
            "symbol": created_order.symbol,
            "market": created_order.market.value,
            "side": created_order.side,
            "order_type": created_order.order_type,
            "quantity": str(created_order.quantity),
            "price": str(created_order.price) if created_order.price else None,
            "status": created_order.status,
            "exchange": created_order.exchange,
        },
        "error": None,
        "meta": {"risk_decision": risk_result.decision.value},
    }


@router.get("/{order_id}", response_model=dict[str, Any])
async def get_order(order_id: str, request: Request) -> dict[str, Any]:
    """查询订单状态。"""
    oms = _get_oms(request)
    order = oms.get_order(order_id)

    if order is None:
        raise HTTPException(status_code=404, detail=f"订单 '{order_id}' 未找到")

    return {
        "success": True,
        "data": {
            "client_order_id": order.client_order_id,
            "symbol": order.symbol,
            "market": order.market.value,
            "side": order.side,
            "order_type": order.order_type,
            "quantity": str(order.quantity),
            "price": str(order.price) if order.price else None,
            "stop_price": str(order.stop_price) if order.stop_price else None,
            "status": order.status,
            "exchange": order.exchange,
        },
        "error": None,
        "meta": None,
    }


@router.delete("/{order_id}", response_model=dict[str, Any])
async def cancel_order(order_id: str, request: Request) -> dict[str, Any]:
    """撤销订单。

    通过 OMS 更新订单状态为已撤销。
    """
    oms = _get_oms(request)

    # 先查询订单是否存在
    order = oms.get_order(order_id)
    if order is None:
        raise HTTPException(status_code=404, detail=f"订单 '{order_id}' 未找到")

    # 只有待提交/部分成交的订单可撤销
    if order.status not in ("pending", "submitted", "partial"):
        raise HTTPException(
            status_code=400,
            detail=f"订单状态为 '{order.status}'，无法撤销",
        )

    # 更新订单状态为已撤销
    updated = oms.update_order_status(order_id, "cancelled")
    if updated is None:
        raise HTTPException(status_code=500, detail="撤单失败")

    return {
        "success": True,
        "data": {
            "client_order_id": updated.client_order_id,
            "symbol": updated.symbol,
            "status": updated.status,
        },
        "error": None,
        "meta": None,
    }
