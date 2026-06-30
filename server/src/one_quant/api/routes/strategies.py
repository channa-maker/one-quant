"""
ONE量化 - 策略管理路由

查询策略列表、启停策略、查看策略表现。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter()


class StrategyToggleRequest(BaseModel):
    """策略启停请求"""

    enabled: bool = Field(description="是否启用")


@router.get("/")
async def list_strategies() -> dict[str, Any]:
    """查询所有已注册策略。

    Returns:
        策略列表，包含名称、状态、统计信息。
    """
    # TODO: 从策略注册表查询
    return {
        "success": True,
        "data": [],
        "error": None,
        "meta": {"total": 0, "enabled": 0},
    }


@router.get("/{strategy_name}")
async def get_strategy(strategy_name: str) -> dict[str, Any]:
    """查询指定策略详情。

    Args:
        strategy_name: 策略名称。

    Returns:
        策略详情。
    """
    # TODO: 从注册表查询
    raise HTTPException(status_code=404, detail=f"策略 '{strategy_name}' 未找到")


@router.post("/{strategy_name}/toggle")
async def toggle_strategy(
    strategy_name: str, req: StrategyToggleRequest
) -> dict[str, Any]:
    """启停策略。

    Args:
        strategy_name: 策略名称。
        req: 启停请求。

    Returns:
        操作结果。
    """
    # TODO: 从注册表获取策略并修改 enabled 状态
    return {
        "success": True,
        "data": {
            "strategy_name": strategy_name,
            "enabled": req.enabled,
        },
        "error": None,
        "meta": None,
    }


@router.get("/{strategy_name}/stats")
async def get_strategy_stats(strategy_name: str) -> dict[str, Any]:
    """查询策略表现统计。

    Args:
        strategy_name: 策略名称。

    Returns:
        策略统计信息（信号数、胜率、盈亏等）。
    """
    return {
        "success": True,
        "data": {
            "strategy_name": strategy_name,
            "signal_count": 0,
            "win_rate": 0.0,
            "total_pnl": "0",
            "sharpe_ratio": 0.0,
        },
        "error": None,
        "meta": None,
    }
