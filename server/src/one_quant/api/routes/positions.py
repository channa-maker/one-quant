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
    """查询所有当前持仓。"""
    # TODO: 从持仓管理器查询
    return {
        "success": True,
        "data": [],
        "error": None,
        "meta": {"total": 0},
    }
