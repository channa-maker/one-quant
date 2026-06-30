"""
ONE量化 - 策略管理路由

查询策略列表、启停策略、查看策略表现。
数据来源：策略注册表（one_quant.strategy.registry）。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from one_quant.strategy.registry import STRATEGY_REGISTRY

router = APIRouter()


class StrategyToggleRequest(BaseModel):
    """策略启停请求"""

    enabled: bool = Field(description="是否启用")


def _strategy_to_dict(name: str, cls: type) -> dict[str, Any]:
    """将策略类转换为 API 响应字典。"""
    return {
        "name": name,
        "enabled": getattr(cls, "enabled", False),
        "class": cls.__name__,
        "module": cls.__module__,
    }


@router.get("/")
async def list_strategies() -> dict[str, Any]:
    """查询所有已注册策略。

    Returns:
        策略列表，包含名称、状态、统计信息。
    """
    strategies = []
    enabled_count = 0

    for name in STRATEGY_REGISTRY.list_keys():
        cls = STRATEGY_REGISTRY.get(name)
        if cls is not None:
            info = _strategy_to_dict(name, cls)
            strategies.append(info)
            if info["enabled"]:
                enabled_count += 1

    return {
        "success": True,
        "data": strategies,
        "error": None,
        "meta": {"total": len(strategies), "enabled": enabled_count},
    }


@router.get("/{strategy_name}")
async def get_strategy(strategy_name: str) -> dict[str, Any]:
    """查询指定策略详情。

    Args:
        strategy_name: 策略名称。

    Returns:
        策略详情。
    """
    cls = STRATEGY_REGISTRY.get(strategy_name)
    if cls is None:
        raise HTTPException(
            status_code=404,
            detail=f"策略 '{strategy_name}' 未找到",
        )

    info = _strategy_to_dict(strategy_name, cls)

    # 尝试获取策略类的额外属性
    for attr in ("description", "version", "author"):
        if hasattr(cls, attr):
            info[attr] = getattr(cls, attr)

    return {
        "success": True,
        "data": info,
        "error": None,
        "meta": None,
    }


@router.post("/{strategy_name}/toggle")
async def toggle_strategy(strategy_name: str, req: StrategyToggleRequest) -> dict[str, Any]:
    """启停策略。

    修改策略类的 enabled 类属性。

    Args:
        strategy_name: 策略名称。
        req: 启停请求。

    Returns:
        操作结果。
    """
    cls = STRATEGY_REGISTRY.get(strategy_name)
    if cls is None:
        raise HTTPException(
            status_code=404,
            detail=f"策略 '{strategy_name}' 未找到",
        )

    # 修改策略类的 enabled 属性
    old_enabled = getattr(cls, "enabled", False)
    cls.enabled = req.enabled  # type: ignore[attr-defined]

    return {
        "success": True,
        "data": {
            "strategy_name": strategy_name,
            "enabled": req.enabled,
            "previous_enabled": old_enabled,
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
    cls = STRATEGY_REGISTRY.get(strategy_name)
    if cls is None:
        raise HTTPException(
            status_code=404,
            detail=f"策略 '{strategy_name}' 未找到",
        )

    # 尝试从策略类获取统计信息
    stats: dict[str, Any] = {
        "strategy_name": strategy_name,
        "signal_count": 0,
        "win_rate": 0.0,
        "total_pnl": "0",
        "sharpe_ratio": 0.0,
    }

    # 如果策略类有 stats 属性，使用它
    if hasattr(cls, "stats") and isinstance(cls.stats, dict):
        stats.update(cls.stats)

    return {
        "success": True,
        "data": stats,
        "error": None,
        "meta": None,
    }
