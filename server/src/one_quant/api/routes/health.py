"""
ONE量化 - 健康检查路由

公开端点，无需鉴权。
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter

router = APIRouter()

# 服务启动时间
_start_time = time.time()


@router.get("/health")
async def health_check() -> dict[str, Any]:
    """健康检查端点。

    Returns:
        服务状态信息。
    """
    return {
        "success": True,
        "data": {
            "status": "healthy",
            "uptime_seconds": round(time.time() - _start_time, 2),
        },
        "error": None,
        "meta": None,
    }
