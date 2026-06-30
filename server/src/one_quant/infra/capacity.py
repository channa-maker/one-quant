"""容量管理 — 行情吞吐 / 存储增长 / LLM 成本

定期检查系统容量指标，提前预警瓶颈。
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from one_quant.infra.logging import get_logger

logger = get_logger(__name__)


@dataclass
class CapacityThreshold:
    """容量阈值"""

    warning: float = 0.0  # 告警阈值
    critical: float = 0.0  # 严重阈值
    unit: str = ""


@dataclass
class CapacityMetric:
    """容量指标"""

    name: str
    current: float = 0.0
    threshold: CapacityThreshold = field(default_factory=CapacityThreshold)
    status: str = "ok"  # ok / warning / critical
    detail: str = ""
    measured_at: int = 0


class CapacityManager:
    """容量管理器。

    监控维度：
    1. 行情吞吐 — tick/s、L2 更新频率、延迟
    2. 存储增长 — tick/L2 数据体量、磁盘使用率
    3. LLM 成本 — 按月评估 API 调用费用
    4. 连接池 — DB/Redis 连接数使用率
    5. 内存 — 进程内存使用
    """

    def __init__(self) -> None:
        self._metrics: dict[str, CapacityMetric] = {}
        self._history: list[dict[str, Any]] = []

        # 外部注入的数据源
        self._tick_rate_fn: Callable[[], Awaitable[float]] | None = None
        self._storage_fn: Callable[[], Awaitable[dict[str, Any]]] | None = None
        self._llm_cost_fn: Callable[[], Awaitable[dict[str, Any]]] | None = None
        self._notify_fn: Callable[[str, str, str], Awaitable[None]] | None = None

    # ── 依赖注入 ──────────────────────────────────────────────────

    def set_tick_rate_fn(self, fn: Callable[[], Awaitable[float]]) -> None:
        """注入行情吞吐查询函数。"""
        self._tick_rate_fn = fn

    def set_storage_fn(self, fn: Callable[[], Awaitable[dict[str, Any]]]) -> None:
        """注入存储查询函数。"""
        self._storage_fn = fn

    def set_llm_cost_fn(self, fn: Callable[[], Awaitable[dict[str, Any]]]) -> None:
        """注入LLM成本查询函数。"""
        self._llm_cost_fn = fn

    def set_notifier(self, fn: Callable[[str, str, str], Awaitable[None]]) -> None:
        """注入通知函数。"""
        self._notify_fn = fn

    # ── 行情吞吐检查 ──────────────────────────────────────────────

    async def check_data_throughput(self) -> dict[str, Any]:
        """行情吞吐检查。

        检查项：
        - tick/s 吞吐量
        - L2 盘口更新频率
        - 行情延迟（本地时间 - 交易所时间）

        Returns:
            吞吐检查结果
        """
        result: dict[str, Any] = {
            "checked_at": time.time_ns(),
            "metrics": {},
            "status": "ok",
        }

        # tick/s 检查
        if self._tick_rate_fn:
            try:
                tick_rate = await self._tick_rate_fn()
                tick_metric = CapacityMetric(
                    name="tick_rate",
                    current=tick_rate,
                    threshold=CapacityThreshold(warning=1000, critical=5000, unit="tick/s"),
                    measured_at=time.time_ns(),
                )

                if tick_rate > tick_metric.threshold.critical:
                    tick_metric.status = "critical"
                    tick_metric.detail = (
                        f"tick/s 超过严重阈值: {tick_rate:.0f} > {tick_metric.threshold.critical}"
                    )
                    result["status"] = "critical"
                elif tick_rate > tick_metric.threshold.warning:
                    tick_metric.status = "warning"
                    tick_metric.detail = (
                        f"tick/s 超过告警阈值: {tick_rate:.0f} > {tick_metric.threshold.warning}"
                    )
                    if result["status"] != "critical":
                        result["status"] = "warning"

                result["metrics"]["tick_rate"] = {
                    "current": tick_rate,
                    "unit": "tick/s",
                    "status": tick_metric.status,
                }
                self._metrics["tick_rate"] = tick_metric

            except Exception:
                logger.exception("行情吞吐检查异常")
                result["metrics"]["tick_rate"] = {"error": "查询失败"}

        # 行情延迟检查（由上层数据源提供）
        result["metrics"]["latency"] = {
            "note": "延迟数据需由行情模块上报",
            "threshold_ms": {"warning": 100, "critical": 500},
        }

        # 通知
        if result["status"] in ("warning", "critical") and self._notify_fn:
            await self._notify_fn(
                f"行情吞吐告警: {result['status']}",
                f"tick/s: {result['metrics'].get('tick_rate', {}).get('current', 'N/A')}",
                level=result["status"],
            )

        return result

    # ── 存储增长评估 ──────────────────────────────────────────────

    async def check_storage_growth(self) -> dict[str, Any]:
        """存储增长评估。

        tick/L2 数据体量大，需要持续监控：
        - 数据库大小
        - 磁盘使用率
        - 预计满盘时间

        Returns:
            存储检查结果
        """
        result: dict[str, Any] = {
            "checked_at": time.time_ns(),
            "metrics": {},
            "status": "ok",
        }

        if self._storage_fn:
            try:
                storage = await self._storage_fn()

                # 数据库大小
                db_size_gb = storage.get("db_size_gb", 0)
                disk_used_pct = storage.get("disk_used_pct", 0)
                days_until_full = storage.get("days_until_full", -1)

                disk_metric = CapacityMetric(
                    name="disk_usage",
                    current=disk_used_pct,
                    threshold=CapacityThreshold(warning=70, critical=90, unit="%"),
                    measured_at=time.time_ns(),
                )

                if disk_used_pct > disk_metric.threshold.critical:
                    disk_metric.status = "critical"
                    disk_metric.detail = f"磁盘使用率超过严重阈值: {disk_used_pct:.1f}%"
                    result["status"] = "critical"
                elif disk_used_pct > disk_metric.threshold.warning:
                    disk_metric.status = "warning"
                    disk_metric.detail = f"磁盘使用率超过告警阈值: {disk_used_pct:.1f}%"
                    if result["status"] != "critical":
                        result["status"] = "warning"

                result["metrics"] = {
                    "db_size_gb": db_size_gb,
                    "disk_used_pct": disk_used_pct,
                    "days_until_full": days_until_full,
                    "status": disk_metric.status,
                }
                self._metrics["disk_usage"] = disk_metric

                # 预计满盘告警
                if 0 < days_until_full < 7:
                    result["status"] = "critical" if days_until_full < 3 else "warning"
                    result["metrics"]["alert"] = f"预计 {days_until_full:.0f} 天后磁盘满"

            except Exception:
                logger.exception("存储检查异常")
                result["metrics"] = {"error": "查询失败"}

        # 通知
        if result["status"] in ("warning", "critical") and self._notify_fn:
            await self._notify_fn(
                f"存储告警: {result['status']}",
                f"磁盘使用: {result['metrics'].get('disk_used_pct', 'N/A')}%\n"
                f"预计满盘: {result['metrics'].get('days_until_full', 'N/A')} 天",
                level=result["status"],
            )

        return result

    # ── LLM 成本评估 ──────────────────────────────────────────────

    async def check_llm_cost(self) -> dict[str, Any]:
        """LLM 成本按月评估。

        监控维度：
        - 本月 API 调用次数
        - 本月费用（USD）
        - 日均费用
        - 预计月底总费用

        Returns:
            LLM 成本检查结果
        """
        result: dict[str, Any] = {
            "checked_at": time.time_ns(),
            "metrics": {},
            "status": "ok",
        }

        if self._llm_cost_fn:
            try:
                cost = await self._llm_cost_fn()

                monthly_cost = cost.get("monthly_cost_usd", 0)
                daily_budget = cost.get("daily_budget_usd", 50)
                days_in_month = cost.get("days_in_month", 30)
                day_of_month = cost.get("day_of_month", 1)

                # 日均费用
                daily_avg = monthly_cost / day_of_month if day_of_month > 0 else 0

                # 预计月底总费用
                projected = daily_avg * days_in_month

                cost_metric = CapacityMetric(
                    name="llm_cost",
                    current=monthly_cost,
                    threshold=CapacityThreshold(
                        warning=daily_budget * days_in_month * 0.8,
                        critical=daily_budget * days_in_month,
                        unit="USD",
                    ),
                    measured_at=time.time_ns(),
                )

                if projected > cost_metric.threshold.critical:
                    cost_metric.status = "critical"
                    cost_metric.detail = f"预计月底费用超过预算: ${projected:.2f}"
                    result["status"] = "critical"
                elif projected > cost_metric.threshold.warning:
                    cost_metric.status = "warning"
                    cost_metric.detail = f"预计月底费用接近预算: ${projected:.2f}"
                    if result["status"] != "critical":
                        result["status"] = "warning"

                result["metrics"] = {
                    "monthly_cost_usd": round(monthly_cost, 2),
                    "daily_avg_usd": round(daily_avg, 2),
                    "projected_monthly_usd": round(projected, 2),
                    "daily_budget_usd": daily_budget,
                    "status": cost_metric.status,
                }
                self._metrics["llm_cost"] = cost_metric

            except Exception:
                logger.exception("LLM成本检查异常")
                result["metrics"] = {"error": "查询失败"}

        # 通知
        if result["status"] in ("warning", "critical") and self._notify_fn:
            await self._notify_fn(
                f"LLM成本告警: {result['status']}",
                f"本月费用: ${result['metrics'].get('monthly_cost_usd', 'N/A')}\n"
                f"预计月底: ${result['metrics'].get('projected_monthly_usd', 'N/A')}",
                level=result["status"],
            )

        return result

    # ── 综合容量报告 ──────────────────────────────────────────────

    async def full_check(self) -> dict[str, Any]:
        """执行完整容量检查。

        Returns:
            综合容量报告
        """
        report: dict[str, Any] = {
            "checked_at": time.time_ns(),
            "sections": {},
            "overall_status": "ok",
        }

        # 并行执行所有检查
        throughput, storage, llm_cost = await asyncio.gather(
            self.check_data_throughput(),
            self.check_storage_growth(),
            self.check_llm_cost(),
            return_exceptions=True,
        )

        if isinstance(throughput, dict):
            report["sections"]["throughput"] = throughput
            if throughput.get("status") == "critical":
                report["overall_status"] = "critical"
            elif throughput.get("status") == "warning" and report["overall_status"] != "critical":
                report["overall_status"] = "warning"
        else:
            report["sections"]["throughput"] = {"error": str(throughput)}

        if isinstance(storage, dict):
            report["sections"]["storage"] = storage
            if storage.get("status") == "critical":
                report["overall_status"] = "critical"
            elif storage.get("status") == "warning" and report["overall_status"] != "critical":
                report["overall_status"] = "warning"
        else:
            report["sections"]["storage"] = {"error": str(storage)}

        if isinstance(llm_cost, dict):
            report["sections"]["llm_cost"] = llm_cost
            if llm_cost.get("status") == "critical":
                report["overall_status"] = "critical"
            elif llm_cost.get("status") == "warning" and report["overall_status"] != "critical":
                report["overall_status"] = "warning"
        else:
            report["sections"]["llm_cost"] = {"error": str(llm_cost)}

        # 记录历史
        self._history.append(
            {
                "time": time.time_ns(),
                "overall_status": report["overall_status"],
            }
        )

        return report

    # ── 状态查询 ──────────────────────────────────────────────────

    @property
    def current_metrics(self) -> dict[str, Any]:
        """获取当前容量指标。"""
        return {
            name: {
                "current": m.current,
                "status": m.status,
                "detail": m.detail,
                "threshold": {
                    "warning": m.threshold.warning,
                    "critical": m.threshold.critical,
                    "unit": m.threshold.unit,
                },
            }
            for name, m in self._metrics.items()
        }

    @property
    def history(self) -> list[dict[str, Any]]:
        """获取检查历史。"""
        return self._history[-100:]  # 最近 100 条
