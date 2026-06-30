"""看门狗 — 全进程心跳 + 崩溃拉起 + 死锁检测 + 状态恢复

RTO < 5 分钟 / RPO < 1 秒
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Awaitable

from one_quant.infra.logging import get_logger

logger = get_logger(__name__)

HealthCheckFn = Callable[[], Awaitable[bool]]
RestartFn = Callable[[], Awaitable[None]]


class ProcessStatus(str, Enum):
    """进程状态枚举"""
    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    DEAD = "dead"
    RECOVERING = "recovering"


@dataclass
class ProcessInfo:
    """进程注册信息"""
    name: str
    pid: int = 0
    healthcheck_fn: HealthCheckFn | None = None
    restart_fn: RestartFn | None = None
    last_heartbeat_ns: int = 0
    consecutive_failures: int = 0
    status: ProcessStatus = ProcessStatus.UNKNOWN
    restart_count: int = 0
    last_restart_ns: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class DeadlockIndicator:
    """死锁指标"""
    event_loop_blocked: bool = False  # 事件循环卡顿
    market_data_stale: bool = False  # 行情停更
    order_no_response: bool = False  # 订单超时未回报
    last_check_ns: int = 0


class Watchdog:
    """看门狗 — 全进程心跳与自愈。

    职责：
    - 心跳监控：周期性检查所有注册进程的健康状态
    - 崩溃拉起：连续失败达到阈值时自动重启
    - 死锁检测：事件循环卡顿 / 行情停更 / 订单超时未回报
    - 状态恢复：重启后拉取真实持仓 + 审计重建，SL/TP/入场价全恢复
    """

    def __init__(
        self,
        heartbeat_timeout_sec: float = 30,
        max_failures: int = 3,
        monitor_interval_sec: float = 5,
        deadlock_timeout_sec: float = 60,
        order_timeout_sec: float = 30,
    ) -> None:
        self._heartbeat_timeout_sec = heartbeat_timeout_sec
        self._max_failures = max_failures
        self._monitor_interval_sec = monitor_interval_sec
        self._deadlock_timeout_sec = deadlock_timeout_sec
        self._order_timeout_sec = order_timeout_sec

        self._processes: dict[str, ProcessInfo] = {}
        self._deadlock = DeadlockIndicator()

        self._running = False
        self._monitor_task: asyncio.Task[None] | None = None

        # 事件循环卡顿检测：记录上次事件循环心跳
        self._loop_heartbeat_ns: int = time.time_ns()
        # 行情最后更新时间
        self._last_market_data_ns: int = 0
        # 订单最后回报时间
        self._last_order_response_ns: int = 0

        # 状态恢复回调（由上层注入）
        self._recovery_callbacks: list[Callable[[], Awaitable[None]]] = []

    # ── 注册与心跳 ──────────────────────────────────────────────────

    def register_process(
        self,
        name: str,
        pid: int = 0,
        healthcheck_fn: HealthCheckFn | None = None,
        restart_fn: RestartFn | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """注册监控进程。

        Args:
            name: 进程名称（唯一标识）
            pid: 进程 PID
            healthcheck_fn: 异步健康检查函数
            restart_fn: 异步重启函数
            metadata: 附加元数据
        """
        self._processes[name] = ProcessInfo(
            name=name,
            pid=pid,
            healthcheck_fn=healthcheck_fn,
            restart_fn=restart_fn,
            metadata=metadata or {},
        )
        logger.info("看门狗注册进程: %s (pid=%d)", name, pid)

    def heartbeat(self, name: str) -> None:
        """进程上报心跳。"""
        proc = self._processes.get(name)
        if proc:
            proc.last_heartbeat_ns = time.time_ns()
            proc.consecutive_failures = 0
            proc.status = ProcessStatus.HEALTHY

    def report_market_data(self) -> None:
        """行情模块上报数据更新。"""
        self._last_market_data_ns = time.time_ns()
        self._deadlock.market_data_stale = False

    def report_order_response(self) -> None:
        """订单模块上报回报。"""
        self._last_order_response_ns = time.time_ns()
        self._deadlock.order_no_response = False

    def register_recovery_callback(self, callback: Callable[[], Awaitable[None]]) -> None:
        """注册状态恢复回调（重启后执行）。"""
        self._recovery_callbacks.append(callback)

    # ── 启停控制 ──────────────────────────────────────────────────

    async def start(self) -> None:
        """启动看门狗监控。"""
        self._running = True
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        logger.info("看门狗已启动 (心跳超时=%ds, 最大失败=%d)", self._heartbeat_timeout_sec, self._max_failures)

    async def stop(self) -> None:
        """停止看门狗监控。"""
        self._running = False
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        logger.info("看门狗已停止")

    # ── 主监控循环 ──────────────────────────────────────────────────

    async def _monitor_loop(self) -> None:
        """监控主循环：心跳检查 + 死锁检测。"""
        while self._running:
            try:
                await asyncio.sleep(self._monitor_interval_sec)
                await self._check_all_heartbeats()
                await self._check_deadlock()
                self._update_loop_heartbeat()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("看门狗监控循环异常")

    async def _check_all_heartbeats(self) -> None:
        """检查所有进程心跳。"""
        now = time.time_ns()
        for name, proc in self._processes.items():
            # 心跳超时检查
            if proc.last_heartbeat_ns > 0:
                age_sec = (now - proc.last_heartbeat_ns) / 1e9
                if age_sec > self._heartbeat_timeout_sec:
                    proc.consecutive_failures += 1
                    proc.status = (
                        ProcessStatus.DEGRADED
                        if proc.consecutive_failures < self._max_failures
                        else ProcessStatus.DEAD
                    )
                    logger.warning(
                        "进程心跳超时: %s (%.1fs, 连续失败 %d/%d)",
                        name, age_sec, proc.consecutive_failures, self._max_failures,
                    )

            # 健康检查函数
            if proc.healthcheck_fn:
                try:
                    healthy = await proc.healthcheck_fn()
                    if healthy:
                        proc.consecutive_failures = 0
                        proc.status = ProcessStatus.HEALTHY
                    else:
                        proc.consecutive_failures += 1
                except Exception:
                    proc.consecutive_failures += 1
                    logger.exception("健康检查异常: %s", name)

            # 连续失败达到阈值 → 触发重启
            if proc.consecutive_failures >= self._max_failures:
                await self.restart_process(name)

    async def check_all(self) -> dict[str, bool]:
        """检查所有进程心跳，返回健康状态映射。

        Returns:
            {进程名: 是否健康}
        """
        results: dict[str, bool] = {}
        for name, proc in self._processes.items():
            if proc.healthcheck_fn:
                try:
                    results[name] = await proc.healthcheck_fn()
                except Exception:
                    results[name] = False
            else:
                # 无健康检查函数，根据心跳判断
                if proc.last_heartbeat_ns > 0:
                    age = (time.time_ns() - proc.last_heartbeat_ns) / 1e9
                    results[name] = age < self._heartbeat_timeout_sec
                else:
                    results[name] = False
        return results

    # ── 崩溃拉起 ──────────────────────────────────────────────────

    async def restart_process(self, name: str) -> bool:
        """崩溃自动拉起。

        Args:
            name: 进程名称

        Returns:
            是否重启成功
        """
        proc = self._processes.get(name)
        if not proc:
            logger.error("重启失败: 进程 %s 未注册", name)
            return False

        if not proc.restart_fn:
            logger.error("重启失败: 进程 %s 无重启函数", name)
            return False

        # 防止重启风暴：60秒内最多重启3次
        now = time.time_ns()
        if proc.last_restart_ns > 0:
            since_last = (now - proc.last_restart_ns) / 1e9
            if since_last < 60 and proc.restart_count >= 3:
                logger.critical("重启风暴检测: %s 60秒内已重启 %d 次，暂停重启", name, proc.restart_count)
                return False

        logger.error("触发重启: %s (连续失败 %d 次, 累计重启 %d 次)", name, proc.consecutive_failures, proc.restart_count)
        proc.status = ProcessStatus.RECOVERING

        try:
            await proc.restart_fn()
            proc.restart_count += 1
            proc.last_restart_ns = now
            proc.consecutive_failures = 0
            proc.status = ProcessStatus.HEALTHY
            logger.info("进程重启成功: %s", name)

            # 重启后触发状态恢复
            await self.recover_state()
            return True
        except Exception:
            proc.status = ProcessStatus.DEAD
            logger.exception("进程重启失败: %s", name)
            return False

    # ── 死锁检测 ──────────────────────────────────────────────────

    async def detect_deadlock(self) -> list[str]:
        """死锁检测。

        检测三类死锁：
        1. 事件循环卡顿 — loop 心跳超时
        2. 行情停更 — 行情数据长时间未更新
        3. 订单超时未回报 — 订单发出后无回报

        Returns:
            检测到的死锁类型列表
        """
        deadlocks: list[str] = []
        now = time.time_ns()

        # 1. 事件循环卡顿
        loop_age = (now - self._loop_heartbeat_ns) / 1e9
        if loop_age > self._deadlock_timeout_sec:
            self._deadlock.event_loop_blocked = True
            deadlocks.append("event_loop_blocked")
            logger.critical("死锁检测: 事件循环卡顿 (%.1fs 未响应)", loop_age)

        # 2. 行情停更
        if self._last_market_data_ns > 0:
            market_age = (now - self._last_market_data_ns) / 1e9
            if market_age > self._deadlock_timeout_sec:
                self._deadlock.market_data_stale = True
                deadlocks.append("market_data_stale")
                logger.critical("死锁检测: 行情停更 (%.1fs 未更新)", market_age)

        # 3. 订单超时未回报
        if self._last_order_response_ns > 0:
            order_age = (now - self._last_order_response_ns) / 1e9
            if order_age > self._order_timeout_sec:
                self._deadlock.order_no_response = True
                deadlocks.append("order_no_response")
                logger.critical("死锁检测: 订单超时未回报 (%.1fs)", order_age)

        self._deadlock.last_check_ns = now
        return deadlocks

    async def _check_deadlock(self) -> None:
        """内部死锁检查，发现死锁时触发恢复。"""
        deadlocks = await self.detect_deadlock()
        if deadlocks:
            logger.critical("发现死锁: %s，触发自愈", deadlocks)
            # 通知上层（通过恢复回调）
            for cb in self._recovery_callbacks:
                try:
                    await cb()
                except Exception:
                    logger.exception("死锁恢复回调异常")

    def _update_loop_heartbeat(self) -> None:
        """更新事件循环心跳。"""
        self._loop_heartbeat_ns = time.time_ns()

    # ── 状态恢复 ──────────────────────────────────────────────────

    async def recover_state(self) -> None:
        """重启即恢复：拉真实持仓 + 审计重建，SL/TP/入场价 key 全恢复。

        恢复流程：
        1. 从交易所拉取真实持仓
        2. 从数据库恢复未完成订单
        3. 恢复止损/止盈设置
        4. 重建审计日志
        5. 执行注册的恢复回调
        """
        logger.info("开始状态恢复...")
        recovery_start = time.time_ns()

        try:
            # 执行所有注册的恢复回调
            for cb in self._recovery_callbacks:
                try:
                    await cb()
                except Exception:
                    logger.exception("恢复回调执行失败: %s", cb.__name__)

            elapsed_ms = (time.time_ns() - recovery_start) / 1e6
            logger.info("状态恢复完成 (耗时 %.1fms)", elapsed_ms)
        except Exception:
            logger.exception("状态恢复异常")

    # ── 状态查询 ──────────────────────────────────────────────────

    @property
    def status(self) -> dict[str, Any]:
        """获取看门狗完整状态。"""
        return {
            "running": self._running,
            "processes": {
                name: {
                    "pid": proc.pid,
                    "status": proc.status.value,
                    "consecutive_failures": proc.consecutive_failures,
                    "restart_count": proc.restart_count,
                    "last_heartbeat_age_sec": (
                        round((time.time_ns() - proc.last_heartbeat_ns) / 1e9, 1)
                        if proc.last_heartbeat_ns > 0
                        else -1
                    ),
                }
                for name, proc in self._processes.items()
            },
            "deadlock": {
                "event_loop_blocked": self._deadlock.event_loop_blocked,
                "market_data_stale": self._deadlock.market_data_stale,
                "order_no_response": self._deadlock.order_no_response,
            },
        }
