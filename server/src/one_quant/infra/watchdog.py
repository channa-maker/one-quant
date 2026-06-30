"""看门狗 — 全进程心跳 + 崩溃拉起 + 死锁检测"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable

from one_quant.infra.logging import get_logger

logger = get_logger(__name__)

HealthCheckFn = Callable[[], Awaitable[bool]]


@dataclass
class ProcessHealth:
    """进程健康状态"""
    name: str
    last_heartbeat_ns: int = 0
    consecutive_failures: int = 0
    status: str = "unknown"  # healthy / degraded / dead
    restart_count: int = 0


class Watchdog:
    """看门狗监控器。

    监控所有子进程的健康状态：
    - 心跳超时 → 告警
    - 连续失败 → 重启
    - 死锁检测 → 强制重启
    """

    def __init__(
        self,
        heartbeat_timeout_sec: float = 30,
        max_failures: int = 3,
    ) -> None:
        self._timeout = heartbeat_timeout_sec
        self._max_failures = max_failures
        self._processes: dict[str, ProcessHealth] = {}
        self._check_fns: dict[str, HealthCheckFn] = {}
        self._restart_fns: dict[str, Callable[[], Awaitable[None]]] = {}
        self._running = False
        self._monitor_task: asyncio.Task[None] | None = None

    def register(
        self,
        name: str,
        health_check: HealthCheckFn,
        restart_fn: Callable[[], Awaitable[None]],
    ) -> None:
        """注册监控进程"""
        self._processes[name] = ProcessHealth(name=name)
        self._check_fns[name] = health_check
        self._restart_fns[name] = restart_fn
        logger.info("看门狗注册进程: %s", name)

    def heartbeat(self, name: str) -> None:
        """进程上报心跳"""
        proc = self._processes.get(name)
        if proc:
            proc.last_heartbeat_ns = time.time_ns()
            proc.consecutive_failures = 0
            proc.status = "healthy"

    async def start(self) -> None:
        """启动监控"""
        self._running = True
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        logger.info("看门狗已启动")

    async def stop(self) -> None:
        """停止监控"""
        self._running = False
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass

    async def _monitor_loop(self) -> None:
        """监控主循环"""
        while self._running:
            await asyncio.sleep(5)  # 每 5 秒检查一次
            now = time.time_ns()

            for name, proc in self._processes.items():
                # 心跳超时检查
                age_sec = (now - proc.last_heartbeat_ns) / 1e9 if proc.last_heartbeat_ns > 0 else float('inf')

                if age_sec > self._timeout:
                    proc.consecutive_failures += 1
                    proc.status = "degraded" if proc.consecutive_failures < self._max_failures else "dead"
                    logger.warning(
                        "进程心跳超时: %s (%.1fs, 连续失败 %d)",
                        name, age_sec, proc.consecutive_failures,
                    )

                # 健康检查
                check_fn = self._check_fns.get(name)
                if check_fn:
                    try:
                        healthy = await check_fn()
                        if not healthy:
                            proc.consecutive_failures += 1
                    except Exception:
                        proc.consecutive_failures += 1
                        logger.exception("健康检查异常: %s", name)

                # 连续失败 → 重启
                if proc.consecutive_failures >= self._max_failures:
                    restart_fn = self._restart_fns.get(name)
                    if restart_fn:
                        logger.error("触发重启: %s (连续失败 %d 次)", name, proc.consecutive_failures)
                        try:
                            await restart_fn()
                            proc.restart_count += 1
                            proc.consecutive_failures = 0
                            proc.status = "healthy"
                        except Exception:
                            logger.exception("重启失败: %s", name)

    @property
    def status(self) -> dict[str, dict[str, Any]]:
        return {
            name: {
                "status": proc.status,
                "failures": proc.consecutive_failures,
                "restarts": proc.restart_count,
                "last_heartbeat_age_sec": round((time.time_ns() - proc.last_heartbeat_ns) / 1e9, 1) if proc.last_heartbeat_ns > 0 else -1,
            }
            for name, proc in self._processes.items()
        }
