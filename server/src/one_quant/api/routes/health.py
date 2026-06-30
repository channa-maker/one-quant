"""
ONE量化 - 健康检查路由

提供 K8s liveness/readiness 探针端点，无需鉴权。
- /health — 快速存活检查（liveness）
- /health/ready — 完整就绪检查（readiness）
- /health/detail — 详细健康报告
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from one_quant.infra.healthcheck import HealthChecker, HealthStatus

router = APIRouter()

# 服务启动时间
_start_time = time.time()

# 全局健康检查器实例（由 lifespan 初始化）
_health_checker: HealthChecker | None = None


def init_health_checker(
    db_engine: Any = None,
    redis_client: Any = None,
    event_bus: Any = None,
    exchange_clients: dict[str, Any] | None = None,
) -> HealthChecker:
    """初始化健康检查器。

    由应用 lifespan 调用，注入各组件依赖。

    Args:
        db_engine: SQLAlchemy 异步引擎。
        redis_client: Redis 异步客户端。
        event_bus: EventBus 实例。
        exchange_clients: 交易所适配器字典。

    Returns:
        HealthChecker 实例。
    """
    global _health_checker
    _health_checker = HealthChecker(
        db_engine=db_engine,
        redis_client=redis_client,
        event_bus=event_bus,
        exchange_clients=exchange_clients,
    )
    return _health_checker


@router.get("")
async def health_check() -> dict[str, Any]:
    """K8s liveness 探针 — 快速存活检查。

    仅检查服务进程是否存活，不依赖外部组件。
    任何情况返回 200 表示进程存活。

    Returns:
        服务存活状态。
    """
    return {
        "success": True,
        "data": {
            "status": "alive",
            "uptime_seconds": round(time.time() - _start_time, 2),
        },
        "error": None,
        "meta": None,
    }


@router.get("/ready")
async def readiness_check(request: Request) -> JSONResponse:
    """K8s readiness 探针 — 完整就绪检查。

    检测数据库、Redis、EventBus 等核心组件。
    全部正常返回 200，异常返回 503（K8s 会摘除流量）。

    Returns:
        就绪状态及各组件健康信息。
    """
    checker = _health_checker
    if checker is None:
        # 未初始化时从 app.state 获取组件
        checker = HealthChecker(
            db_engine=getattr(request.app.state, "db_engine", None),
            redis_client=getattr(request.app.state, "redis_client", None),
            event_bus=getattr(request.app.state, "event_bus", None),
        )

    health = await checker.full_check()

    status_code = 200 if health.status == HealthStatus.HEALTHY else 503
    return JSONResponse(
        status_code=status_code,
        content={
            "success": health.status == HealthStatus.HEALTHY,
            "data": health.to_dict(),
            "error": None if health.status == HealthStatus.HEALTHY else "组件异常",
            "meta": None,
        },
    )


@router.get("/detail")
async def health_detail(request: Request) -> JSONResponse:
    """详细健康报告（供运维排查使用）。

    返回所有组件的详细状态、延迟、错误信息。
    非 K8s 探针用途，仅供人工排查。

    Returns:
        详细健康报告。
    """
    checker = _health_checker
    if checker is None:
        checker = HealthChecker(
            db_engine=getattr(request.app.state, "db_engine", None),
            redis_client=getattr(request.app.state, "redis_client", None),
            event_bus=getattr(request.app.state, "event_bus", None),
        )

    health = await checker.full_check()

    status_code = 200 if health.status != HealthStatus.UNHEALTHY else 503
    return JSONResponse(
        status_code=status_code,
        content={
            "success": True,
            "data": health.to_dict(),
            "error": None,
            "meta": {
                "checker_initialized": _health_checker is not None,
                "service_start_time": _start_time,
            },
        },
    )
