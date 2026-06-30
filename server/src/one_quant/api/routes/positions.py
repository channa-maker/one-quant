"""
ONE量化 - 持仓路由

查询当前持仓、历史持仓、盈亏统计。
数据来源：OMS 持仓管理器。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

from one_quant.execution.oms import OrderManager

router = APIRouter()


def _get_oms(request: Request) -> OrderManager:
    """从应用状态获取 OMS 实例。"""
    if not hasattr(request.app.state, "oms"):
        event_bus = getattr(request.app.state, "event_bus", None)
        if event_bus is None:
            raise HTTPException(status_code=503, detail="EventBus 未初始化")
        request.app.state.oms = OrderManager(event_bus=event_bus)
    return request.app.state.oms


@router.get("/")
async def list_positions(request: Request) -> dict[str, Any]:
    """查询所有当前持仓。

    Returns:
        持仓列表，包含每个持仓的详细信息。
    """
    oms = _get_oms(request)
    positions = oms.get_all_positions()

    position_list = []
    total_unrealized = 0
    total_realized = 0

    for pos in positions:
        position_list.append({
            "symbol": pos.symbol,
            "market": pos.market.value,
            "side": pos.side,
            "quantity": str(pos.quantity),
            "entry_price": str(pos.entry_price),
            "unrealized_pnl": str(pos.unrealized_pnl),
            "realized_pnl": str(pos.realized_pnl),
        })
        total_unrealized += float(pos.unrealized_pnl)
        total_realized += float(pos.realized_pnl)

    return {
        "success": True,
        "data": position_list,
        "error": None,
        "meta": {
            "total": len(position_list),
            "total_unrealized_pnl": str(total_unrealized),
            "total_realized_pnl": str(total_realized),
        },
    }


@router.get("/summary/pnl")
async def get_pnl_summary(request: Request) -> dict[str, Any]:
    """查询盈亏汇总。

    Returns:
        总未实现盈亏、总已实现盈亏、各持仓明细。
    """
    oms = _get_oms(request)
    positions = oms.get_all_positions()

    total_unrealized = 0.0
    total_realized = 0.0
    position_details = []

    for pos in positions:
        total_unrealized += float(pos.unrealized_pnl)
        total_realized += float(pos.realized_pnl)
        position_details.append({
            "symbol": pos.symbol,
            "side": pos.side,
            "quantity": str(pos.quantity),
            "entry_price": str(pos.entry_price),
            "unrealized_pnl": str(pos.unrealized_pnl),
            "realized_pnl": str(pos.realized_pnl),
        })

    total_equity = total_unrealized + total_realized

    return {
        "success": True,
        "data": {
            "total_unrealized_pnl": str(total_unrealized),
            "total_realized_pnl": str(total_realized),
            "total_equity": str(total_equity),
            "positions": position_details,
        },
        "error": None,
        "meta": None,
    }


@router.get("/{symbol}")
async def get_position(symbol: str, request: Request) -> dict[str, Any]:
    """查询指定标的的持仓。

    Args:
        symbol: 标的符号。

    Returns:
        持仓详情。
    """
    oms = _get_oms(request)
    pos = oms.get_position(symbol)

    if pos is None:
        return {
            "success": True,
            "data": None,
            "error": None,
            "meta": None,
        }

    return {
        "success": True,
        "data": {
            "symbol": pos.symbol,
            "market": pos.market.value,
            "side": pos.side,
            "quantity": str(pos.quantity),
            "entry_price": str(pos.entry_price),
            "unrealized_pnl": str(pos.unrealized_pnl),
            "realized_pnl": str(pos.realized_pnl),
        },
        "error": None,
        "meta": None,
    }
