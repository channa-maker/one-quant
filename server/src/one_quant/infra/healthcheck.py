"""健康检查 — Kubernetes liveness/readiness 探针

提供系统各组件的健康状态检测，支持：
- 数据库连接（PostgreSQL / TimescaleDB / ClickHouse）
- Redis 连接
- EventBus 状态
- 交易所连接

用于 K8s liveness/readiness 探针和监控告警。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from one_quant.infra.logging import get_logger

logger = get_logger("healthcheck")


# ──────────────────── 健康状态枚举 ────────────────────


class HealthStatus(str, Enum):
    """健康状态枚举。"""

    HEALTHY = "healthy"      # 正常
    DEGRADED = "degraded"    # 降级（部分组件异常但服务可用）
    UNHEALTHY = "unhealthy"  # 不可用（关键组件异常）


# ──────────────────── 组件检查结果 ────────────────────


@dataclass(frozen=True, slots=True)
class ComponentHealth:
    """单个组件的健康检查结果。

    Attributes:
        name: 组件名称。
        status: 健康状态。
        latency_ms: 检查耗时（毫秒）。
        message: 附加信息（如错误详情）。
    """

    name: str
    status: HealthStatus
    latency_ms: float = 0.0
    message: str = ""


@dataclass(frozen=True, slots=True)
class SystemHealth:
    """系统整体健康检查结果。

    Attributes:
        status: 整体健康状态。
        uptime_seconds: 服务运行时长（秒）。
        components: 各组件检查结果。
        timestamp: 检查时间戳。
    """

    status: HealthStatus
    uptime_seconds: float
    components: dict[str, ComponentHealth]
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        """转换为 API 响应字典。"""
        return {
            "status": self.status.value,
            "uptime_seconds": round(self.uptime_seconds, 2),
            "components": {
                name: {
                    "status": comp.status.value,
                    "latency_ms": round(comp.latency_ms, 2),
                    "message": comp.message,
                }
                for name, comp in self.components.items()
            },
            "timestamp": self.timestamp,
        }


# ──────────────────── 健康检查器 ────────────────────


class HealthChecker:
    """系统健康检查器。

    检测数据库、Redis、EventBus、交易所等核心组件的可用性。
    支持注入依赖实例，便于测试和不同环境的配置。

    Args:
        db_engine: SQLAlchemy 异步引擎（可选）。
        redis_client: Redis 异步客户端（可选）。
        event_bus: EventBus 实例（可选）。
        exchange_clients: 交易所适配器字典（可选）。
    """

    def __init__(
        self,
        db_engine: Any = None,
        redis_client: Any = None,
        event_bus: Any = None,
        exchange_clients: dict[str, Any] | None = None,
    ) -> None:
        self._db_engine = db_engine
        self._redis_client = redis_client
        self._event_bus = event_bus
        self._exchange_clients = exchange_clients or {}
        self._start_time = time.time()

    async def check_database(self) -> ComponentHealth:
        """数据库连接检查。

        执行 SELECT 1 验证连接可用性。

        Returns:
            数据库组件健康状态。
        """
        if self._db_engine is None:
            return ComponentHealth(
                name="database",
                status=HealthStatus.DEGRADED,
                message="数据库引擎未配置",
            )

        start = time.monotonic()
        try:
            import sqlalchemy as sa

            async with self._db_engine.connect() as conn:
                await conn.execute(sa.text("SELECT 1"))
            latency = (time.monotonic() - start) * 1000
            return ComponentHealth(
                name="database",
                status=HealthStatus.HEALTHY,
                latency_ms=latency,
                message="连接正常",
            )
        except Exception as exc:
            latency = (time.monotonic() - start) * 1000
            logger.error("数据库健康检查失败: %s", exc)
            return ComponentHealth(
                name="database",
                status=HealthStatus.UNHEALTHY,
                latency_ms=latency,
                message=f"连接失败: {exc}",
            )

    async def check_redis(self) -> ComponentHealth:
        """Redis 连接检查。

        执行 PING 命令验证连接可用性。

        Returns:
            Redis 组件健康状态。
        """
        if self._redis_client is None:
            return ComponentHealth(
                name="redis",
                status=HealthStatus.DEGRADED,
                message="Redis 客户端未配置",
            )

        start = time.monotonic()
        try:
            pong = await self._redis_client.ping()
            latency = (time.monotonic() - start) * 1000
            if pong:
                return ComponentHealth(
                    name="redis",
                    status=HealthStatus.HEALTHY,
                    latency_ms=latency,
                    message="连接正常",
                )
            else:
                return ComponentHealth(
                    name="redis",
                    status=HealthStatus.UNHEALTHY,
                    latency_ms=latency,
                    message="PING 响应异常",
                )
        except Exception as exc:
            latency = (time.monotonic() - start) * 1000
            logger.error("Redis 健康检查失败: %s", exc)
            return ComponentHealth(
                name="redis",
                status=HealthStatus.UNHEALTHY,
                latency_ms=latency,
                message=f"连接失败: {exc}",
            )

    async def check_event_bus(self) -> ComponentHealth:
        """EventBus 检查。

        验证 EventBus 实例是否存在且已启动。

        Returns:
            EventBus 组件健康状态。
        """
        if self._event_bus is None:
            return ComponentHealth(
                name="event_bus",
                status=HealthStatus.DEGRADED,
                message="EventBus 未配置",
            )

        start = time.monotonic()
        try:
            is_started = getattr(self._event_bus, "_started", False)
            latency = (time.monotonic() - start) * 1000
            if is_started:
                bus_type = type(self._event_bus).__name__
                return ComponentHealth(
                    name="event_bus",
                    status=HealthStatus.HEALTHY,
                    latency_ms=latency,
                    message=f"{bus_type} 运行中",
                )
            else:
                return ComponentHealth(
                    name="event_bus",
                    status=HealthStatus.UNHEALTHY,
                    latency_ms=latency,
                    message="EventBus 未启动",
                )
        except Exception as exc:
            latency = (time.monotonic() - start) * 1000
            logger.error("EventBus 健康检查失败: %s", exc)
            return ComponentHealth(
                name="event_bus",
                status=HealthStatus.UNHEALTHY,
                latency_ms=latency,
                message=f"检查异常: {exc}",
            )

    async def check_exchanges(self) -> dict[str, ComponentHealth]:
        """交易所连接检查。

        遍历所有已配置的交易所适配器，逐一检查连接状态。

        Returns:
            交易所名称到健康状态的映射。
        """
        if not self._exchange_clients:
            return {
                "exchanges": ComponentHealth(
                    name="exchanges",
                    status=HealthStatus.DEGRADED,
                    message="无交易所适配器配置",
                )
            }

        results: dict[str, ComponentHealth] = {}
        for name, client in self._exchange_clients.items():
            start = time.monotonic()
            try:
                # 尝试调用适配器的健康检查方法（如有）
                check_method = getattr(client, "health_check", None)
                if check_method and callable(check_method):
                    ok = await check_method()
                    latency = (time.monotonic() - start) * 1000
                    if ok:
                        results[name] = ComponentHealth(
                            name=name,
                            status=HealthStatus.HEALTHY,
                            latency_ms=latency,
                            message="连接正常",
                        )
                    else:
                        results[name] = ComponentHealth(
                            name=name,
                            status=HealthStatus.UNHEALTHY,
                            latency_ms=latency,
                            message="连接异常",
                        )
                else:
                    # 无 health_check 方法，仅检查实例是否存在
                    latency = (time.monotonic() - start) * 1000
                    results[name] = ComponentHealth(
                        name=name,
                        status=HealthStatus.HEALTHY,
                        latency_ms=latency,
                        message="适配器已加载",
                    )
            except Exception as exc:
                latency = (time.monotonic() - start) * 1000
                logger.error("交易所 %s 健康检查失败: %s", name, exc)
                results[name] = ComponentHealth(
                    name=name,
                    status=HealthStatus.UNHEALTHY,
                    latency_ms=latency,
                    message=f"检查异常: {exc}",
                )

        return results

    async def full_check(self) -> SystemHealth:
        """完整健康检查。

        检测所有组件，返回系统整体健康状态。
        判定规则：
        - 全部 HEALTHY → HEALTHY
        - 存在 UNHEALTHY 但无关键组件 → DEGRADED
        - 关键组件（数据库）UNHEALTHY → UNHEALTHY

        Returns:
            系统整体健康检查结果。
        """
        import asyncio

        # 并行执行所有检查
        db_health, redis_health, event_bus_health, exchange_results = (
            await asyncio.gather(
                self.check_database(),
                self.check_redis(),
                self.check_event_bus(),
                self.check_exchanges(),
            )
        )

        # 合并所有组件结果
        components: dict[str, ComponentHealth] = {
            "database": db_health,
            "redis": redis_health,
            "event_bus": event_bus_health,
        }
        components.update(exchange_results)

        # 判定整体状态
        has_unhealthy = any(
            c.status == HealthStatus.UNHEALTHY for c in components.values()
        )
        has_degraded = any(
            c.status == HealthStatus.DEGRADED for c in components.values()
        )

        # 数据库是关键组件，不可用则整体不可用
        if db_health.status == HealthStatus.UNHEALTHY:
            overall = HealthStatus.UNHEALTHY
        elif has_unhealthy:
            overall = HealthStatus.DEGRADED
        elif has_degraded:
            overall = HealthStatus.DEGRADED
        else:
            overall = HealthStatus.HEALTHY

        uptime = time.time() - self._start_time
        health = SystemHealth(
            status=overall,
            uptime_seconds=uptime,
            components=components,
        )

        if overall != HealthStatus.HEALTHY:
            unhealthy_names = [
                name for name, comp in components.items()
                if comp.status != HealthStatus.HEALTHY
            ]
            logger.warning("健康检查异常组件: %s, 整体状态: %s", unhealthy_names, overall.value)

        return health

    def update_db_engine(self, engine: Any) -> None:
        """更新数据库引擎引用。"""
        self._db_engine = engine

    def update_redis_client(self, client: Any) -> None:
        """更新 Redis 客户端引用。"""
        self._redis_client = client

    def update_event_bus(self, event_bus: Any) -> None:
        """更新 EventBus 引用。"""
        self._event_bus = event_bus

    def add_exchange_client(self, name: str, client: Any) -> None:
        """添加交易所适配器。"""
        self._exchange_clients[name] = client
