"""
ONE量化 - 策略管理路由

查询策略列表、启停策略、查看策略表现。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

router = APIRouter()


@router.get("/")
async def list_strategies() -> dict[str, Any]:
    """查询所有已注册策略。"""
    # TODO: 从策略注册表查询
    return {
        "success": True,
        "data": [],
        "error": None,
        "meta": {"total": 0},
    }
