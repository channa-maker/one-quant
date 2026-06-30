"""
ONE量化 - 持仓路由

查询当前持仓、历史持仓、盈亏统计。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

router = APIRouter()


@router.get("/")
async def list_positions() -> dict[str, Any]:
    """查询所有当前持仓。

    Returns:
        持仓列表，包含每个持仓的详细信息。
    """
    # TODO: 从 OMS 持仓管理器查询真实数据
    return {
        "success": True,
        "data": [],
        "error": None,
        "meta": {
            "total": 0,
            "total_unrealized_pnl": "0",
            "total_realized_pnl": "0",
        },
    }


@router.get("/{symbol}")
async def get_position(symbol: str) -> dict[str, Any]:
    """查询指定标的的持仓。

    Args:
        symbol: 标的符号。

    Returns:
        持仓详情。
    """
    # TODO: 从 OMS 查询
    return {
        "success": True,
        "data": None,
        "error": None,
        "meta": None,
    }


@router.get("/summary/pnl")
async def get_pnl_summary() -> dict[str, Any]:
    """查询盈亏汇总。

    Returns:
        总未实现盈亏、总已实现盈亏、各持仓明细。
    """
    return {
        "success": True,
        "data": {
            "total_unrealized_pnl": "0",
            "total_realized_pnl": "0",
            "total_equity": "0",
            "positions": [],
        },
        "error": None,
        "meta": None,
    }
