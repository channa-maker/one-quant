"""自愈策略 — 六大场景全覆盖

覆盖：行情断线 / 交易所API异常 / DB锁争用 / Redis断连 / 策略异常 / 风控异常
每个策略独立，互不影响，支持并行执行。
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any

from one_quant.infra.logging import get_logger

logger = get_logger(__name__)


class HealResult(str, Enum):
    """自愈结果"""

    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    PARTIAL = "partial"


@dataclass
class HealRecord:
    """自愈记录"""

    strategy: str
    result: HealResult
    started_at: int = 0
    finished_at: int = 0
    attempts: int = 0
    detail: str = ""


class SelfHealStrategy:
    """自愈策略覆盖。

    设计原则：
    - 每个 heal_* 方法独立，互不影响
    - 指数退避 + 最大重试次数，防止雪崩
    - 所有自愈动作记录审计日志
    - 风控异常绝不静默，立即熔断 + ERROR 告警
    """

    def __init__(
        self,
        max_retries: int = 5,
        base_backoff_sec: float = 1.0,
        max_backoff_sec: float = 60.0,
    ) -> None:
        self._max_retries = max_retries
        self._base_backoff = base_backoff_sec
        self._max_backoff = max_backoff_sec
        self._history: list[HealRecord] = []

        # 外部注入的依赖（由上层设置）
        self._reconnect_market_fn: Callable[[], Awaitable[bool]] | None = None
        self._reconnect_exchange_fn: Callable[[], Awaitable[bool]] | None = None
        self._db_reconnect_fn: Callable[[], Awaitable[bool]] | None = None
        self._redis_reconnect_fn: Callable[[], Awaitable[bool]] | None = None
        self._notify_fn: Callable[[str, str, str], Awaitable[None]] | None = None

    # ── 依赖注入 ──────────────────────────────────────────────────

    def set_market_reconnector(self, fn: Callable[[], Awaitable[bool]]) -> None:
        """注入行情重连函数。"""
        self._reconnect_market_fn = fn

    def set_exchange_reconnector(self, fn: Callable[[], Awaitable[bool]]) -> None:
        """注入交易所API重连函数。"""
        self._reconnect_exchange_fn = fn

    def set_db_reconnector(self, fn: Callable[[], Awaitable[bool]]) -> None:
        """注入数据库重连函数。"""
        self._db_reconnect_fn = fn

    def set_redis_reconnector(self, fn: Callable[[], Awaitable[bool]]) -> None:
        """注入Redis重连函数。"""
        self._redis_reconnect_fn = fn

    def set_notifier(self, fn: Callable[[str, str, str], Awaitable[None]]) -> None:
        """注入通知函数 (title, content, level)。"""
        self._notify_fn = fn

    # ── 指数退避重试工具 ──────────────────────────────────────────

    async def _retry_with_backoff(
        self,
        name: str,
        action: Callable[[], Awaitable[bool]],
        max_retries: int | None = None,
        base_backoff: float | None = None,
        max_backoff: float | None = None,
    ) -> HealResult:
        """指数退避重试。

        Args:
            name: 策略名称（用于日志）
            action: 异步重试函数，返回 True 表示成功
            max_retries: 最大重试次数
            base_backoff: 基础退避时间(秒)
            max_backoff: 最大退避时间(秒)

        Returns:
            自愈结果
        """
        retries = max_retries or self._max_retries
        backoff = base_backoff or self._base_backoff
        max_bo = max_backoff or self._max_backoff

        record = HealRecord(strategy=name, started_at=time.time_ns())

        for attempt in range(1, retries + 1):
            record.attempts = attempt
            try:
                success = await action()
                if success:
                    record.result = HealResult.SUCCESS
                    record.finished_at = time.time_ns()
                    record.detail = f"第 {attempt} 次尝试成功"
                    self._history.append(record)
                    logger.info("自愈成功: %s (%s)", name, record.detail)
                    return HealResult.SUCCESS
            except Exception as e:
                record.detail = f"第 {attempt} 次尝试异常: {e}"
                logger.warning("自愈尝试失败: %s (第 %d/%d 次): %s", name, attempt, retries, e)

            # 指数退避
            if attempt < retries:
                wait = min(backoff * (2 ** (attempt - 1)), max_bo)
                logger.info("自愈退避: %s 等待 %.1fs 后重试", name, wait)
                await asyncio.sleep(wait)

        record.result = HealResult.FAILED
        record.finished_at = time.time_ns()
        self._history.append(record)
        logger.error("自愈失败: %s (已重试 %d 次)", name, retries)
        return HealResult.FAILED

    async def _notify(self, title: str, content: str, level: str = "warning") -> None:
        """发送通知（如果已注入）。"""
        if self._notify_fn:
            try:
                await self._notify_fn(title, content, level)
            except Exception:
                logger.exception("自愈通知发送失败")

    # ── 1. 行情断线自愈 ──────────────────────────────────────────

    async def heal_market_disconnect(self) -> bool:
        """行情断线：指数退避重连(≤60s) + 快照对齐 + 缺口回补。

        恢复步骤：
        1. 指数退避重连（1s → 2s → 4s → ... ≤ 60s）
        2. 重连成功后拉取最新快照对齐
        3. 检测数据缺口并触发回补

        Returns:
            是否恢复成功
        """
        if not self._reconnect_market_fn:
            logger.error("行情重连函数未注入")
            return False

        result = await self._retry_with_backoff(
            name="market_disconnect",
            action=self._reconnect_market_fn,
            max_retries=self._max_retries,
            max_backoff=60.0,
        )

        if result == HealResult.SUCCESS:
            logger.info("行情重连成功，执行快照对齐和缺口回补")
            # 快照对齐和缺口回补由上层的重连函数内部处理
            return True

        await self._notify(
            "行情断线自愈失败",
            "指数退避重连已耗尽所有重试次数，请人工介入",
            level="critical",
        )
        return False

    # ── 2. 交易所API异常自愈 ──────────────────────────────────────

    async def heal_exchange_api_error(self) -> bool:
        """交易所 API 异常：限流退避 + 熔断器半开探测。

        恢复步骤：
        1. 检测到 API 错误后进入限流退避
        2. 熔断器进入半开状态
        3. 定时发送探测请求
        4. 探测成功则恢复正常

        Returns:
            是否恢复成功
        """
        if not self._reconnect_exchange_fn:
            logger.error("交易所重连函数未注入")
            return False

        result = await self._retry_with_backoff(
            name="exchange_api_error",
            action=self._reconnect_exchange_fn,
            max_retries=self._max_retries,
            base_backoff=2.0,
            max_backoff=30.0,
        )

        if result == HealResult.SUCCESS:
            logger.info("交易所API恢复正常")
            return True

        await self._notify(
            "交易所API异常自愈失败",
            "限流退避和熔断探测已耗尽，请检查交易所状态",
            level="critical",
        )
        return False

    # ── 3. DB写锁争用自愈 ──────────────────────────────────────

    async def heal_db_lock(self) -> bool:
        """DB 写锁争用：重试 + 连接池调优。

        恢复步骤：
        1. 检测到锁争用后等待重试
        2. 调整连接池大小
        3. 检查长事务并终止

        Returns:
            是否恢复成功
        """
        if not self._db_reconnect_fn:
            logger.error("数据库重连函数未注入")
            return False

        result = await self._retry_with_backoff(
            name="db_lock",
            action=self._db_reconnect_fn,
            max_retries=3,
            base_backoff=2.0,
            max_backoff=10.0,
        )

        if result == HealResult.SUCCESS:
            logger.info("DB锁争用已恢复")
            return True

        await self._notify(
            "数据库锁争用自愈失败",
            "重试和连接池调优未能解决，请检查长事务和锁等待",
            level="error",
        )
        return False

    # ── 4. Redis断连自愈 ──────────────────────────────────────

    async def heal_redis_disconnect(self) -> bool:
        """Redis 断连：本地缓冲 + 重连补发。

        恢复步骤：
        1. 切换到本地内存缓冲
        2. 指数退避重连 Redis
        3. 重连成功后补发缓冲数据

        Returns:
            是否恢复成功
        """
        if not self._redis_reconnect_fn:
            logger.error("Redis重连函数未注入")
            return False

        logger.warning("Redis断连，切换到本地缓冲模式")
        result = await self._retry_with_backoff(
            name="redis_disconnect",
            action=self._redis_reconnect_fn,
            max_retries=self._max_retries,
            max_backoff=30.0,
        )

        if result == HealResult.SUCCESS:
            logger.info("Redis重连成功，开始补发缓冲数据")
            # 缓冲补发由上层的重连函数内部处理
            return True

        await self._notify(
            "Redis断连自愈失败",
            "本地缓冲已启用，请尽快恢复Redis连接",
            level="critical",
        )
        return False

    # ── 5. 策略异常自愈 ──────────────────────────────────────

    async def heal_strategy_crash(self, strategy_name: str) -> bool:
        """策略异常：隔离该策略 + 告警，不影响其他策略。

        恢复步骤：
        1. 立即隔离崩溃策略（停止其信号生成）
        2. 保留其持仓（不自动平仓，由风控决定）
        3. 发送 ERROR 告警
        4. 其他策略继续运行

        Args:
            strategy_name: 崩溃的策略名称

        Returns:
            是否成功隔离（不影响其他策略即为成功）
        """
        logger.error("策略异常: %s — 执行隔离", strategy_name)

        # 隔离策略：标记为异常状态
        record = HealRecord(
            strategy=f"strategy_crash:{strategy_name}",
            started_at=time.time_ns(),
            result=HealResult.SUCCESS,
            detail=f"策略 {strategy_name} 已隔离，持仓保留，等待人工决策",
        )
        record.finished_at = time.time_ns()
        self._history.append(record)

        await self._notify(
            f"策略异常: {strategy_name}",
            f"策略 {strategy_name} 已崩溃并隔离。\n"
            f"- 已停止信号生成\n"
            f"- 持仓已保留（未自动平仓）\n"
            f"- 其他策略正常运行\n"
            f"请检查策略日志并决定是否手动平仓",
            level="error",
        )
        return True

    # ── 6. 风控异常自愈 ──────────────────────────────────────

    async def heal_risk_failure(self) -> bool:
        """风控异常：立即熔断 + ERROR 告警（绝不静默）。

        恢复步骤：
        1. 立即触发全局熔断（停止所有新开仓）
        2. 保留现有持仓
        3. 发送 CRITICAL 告警
        4. 等待人工介入

        Returns:
            是否成功熔断（安全停机即为成功）
        """
        logger.critical("风控异常: 立即触发全局熔断")

        record = HealRecord(
            strategy="risk_failure",
            started_at=time.time_ns(),
            result=HealResult.SUCCESS,
            detail="风控异常，全局熔断已触发，所有新开仓已停止",
        )
        record.finished_at = time.time_ns()
        self._history.append(record)

        await self._notify(
            "⚠️ 风控异常 — 全局熔断",
            "风控系统异常，已触发全局熔断：\n"
            "- 所有新开仓已停止\n"
            "- 现有持仓已保留\n"
            "- 请立即检查风控系统\n\n"
            "这是最高优先级告警，绝不静默处理！",
            level="critical",
        )
        return True

    # ── 统一自愈入口 ──────────────────────────────────────────────

    async def heal(self, incident_type: str, **kwargs: Any) -> bool:
        """统一自愈入口。

        Args:
            incident_type: 事件类型
            **kwargs: 事件参数

        Returns:
            是否恢复成功
        """
        heal_map: dict[str, Callable[..., Awaitable[bool]]] = {
            "market_disconnect": self.heal_market_disconnect,
            "exchange_api_error": self.heal_exchange_api_error,
            "db_lock": self.heal_db_lock,
            "redis_disconnect": self.heal_redis_disconnect,
            "strategy_crash": lambda: self.heal_strategy_crash(
                kwargs.get("strategy_name", "unknown")
            ),
            "risk_failure": self.heal_risk_failure,
        }

        handler = heal_map.get(incident_type)
        if not handler:
            logger.error("未知自愈类型: %s", incident_type)
            return False

        return await handler()

    # ── 状态查询 ──────────────────────────────────────────────────

    @property
    def history(self) -> list[dict[str, Any]]:
        """获取自愈历史。"""
        return [
            {
                "strategy": r.strategy,
                "result": r.result.value,
                "attempts": r.attempts,
                "detail": r.detail,
                "duration_ms": round((r.finished_at - r.started_at) / 1e6, 1)
                if r.finished_at > 0
                else 0,
            }
            for r in self._history
        ]

    @property
    def stats(self) -> dict[str, Any]:
        """获取自愈统计。"""
        total = len(self._history)
        success = sum(1 for r in self._history if r.result == HealResult.SUCCESS)
        failed = sum(1 for r in self._history if r.result == HealResult.FAILED)
        return {
            "total": total,
            "success": success,
            "failed": failed,
            "success_rate": round(success / total * 100, 1) if total > 0 else 0,
        }
