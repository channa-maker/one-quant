"""变更管理 — RTO/RPO + 发布窗口 + 回滚预案 + 高波动冻结

职责：
- 发布窗口管理（低波动时段）
- 高波动事件变更冻结（CPI/FOMC/财报日/期权到期日）
- 变更审批流程
- 回滚预案与执行
- RTO/RPO 追踪
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from one_quant.infra.logging import get_logger

logger = get_logger(__name__)


class ChangeType(StrEnum):
    """变更类型"""

    HOTFIX = "hotfix"
    FEATURE = "feature"
    INFRA = "infra"
    CONFIG = "config"
    STRATEGY = "strategy"  # 策略参数变更


class RiskLevel(StrEnum):
    """风险等级"""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ChangeStatus(StrEnum):
    """变更状态"""

    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTING = "executing"
    EXECUTED = "executed"
    ROLLED_BACK = "rolled_back"
    FAILED = "failed"


@dataclass
class ChangeRequest:
    """变更请求"""

    change_id: str
    title: str
    change_type: ChangeType
    risk_level: RiskLevel
    description: str
    rollback_plan: str
    status: ChangeStatus = ChangeStatus.DRAFT
    scheduled_window: str = ""  # 发布窗口
    approved_by: str = ""
    rejected_by: str = ""
    executed_at: int = 0
    rolled_back_at: int = 0
    rolled_back: bool = False
    rollback_reason: str = ""
    created_at: int = 0
    updated_at: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class FreezeEvent:
    """冻结事件"""

    name: str
    start_time: int  # Unix 时间戳
    end_time: int
    reason: str = ""


class ChangeManager:
    """变更管理器。

    设计原则：
    - 高波动事件期间冻结所有变更
    - 变更需审批后才能执行
    - 所有变更必须有回滚预案
    - 回滚操作记录审计日志
    """

    # ── 高波动事件变更冻结 ──────────────────────────────────────
    FREEZE_EVENTS = ["CPI", "FOMC", "财报日", "期权到期日", "非农", "PCE"]

    # 发布窗口：UTC 02:00-06:00（亚洲凌晨，欧美收盘后）
    RELEASE_WINDOWS = ["02:00-06:00 UTC"]

    # 不同风险等级所需的审批级别
    APPROVAL_REQUIREMENTS: dict[RiskLevel, list[str]] = {
        RiskLevel.LOW: ["值班工程师"],
        RiskLevel.MEDIUM: ["技术负责人"],
        RiskLevel.HIGH: ["技术负责人", "CTO"],
        RiskLevel.CRITICAL: ["CTO", "CEO"],
    }

    def __init__(self) -> None:
        self._changes: list[ChangeRequest] = []
        self._freeze_events: list[FreezeEvent] = []
        self._freeze_until: int = 0  # 冻结截止时间戳
        self._freeze_reason: str = ""

        # 回滚执行回调
        self._rollback_fn: Callable[[str], Awaitable[bool]] | None = None

    def set_rollback_fn(self, fn: Callable[[str], Awaitable[bool]]) -> None:
        """注入回滚执行函数。"""
        self._rollback_fn = fn

    # ── 变更提交 ──────────────────────────────────────────────────

    def submit(self, change: ChangeRequest) -> str:
        """提交变更请求。

        Args:
            change: 变更请求

        Returns:
            变更 ID
        """
        change.created_at = time.time_ns()
        change.updated_at = time.time_ns()
        change.status = ChangeStatus.PENDING_APPROVAL
        self._changes.append(change)
        logger.info(
            "变更请求已提交: %s %s [%s/%s]",
            change.change_id,
            change.title,
            change.change_type.value,
            change.risk_level.value,
        )
        return change.change_id

    # ── 变更审批 ──────────────────────────────────────────────────

    def approve_change(self, change: dict[str, Any]) -> bool:
        """审批变更。

        Args:
            change: 变更数据（需包含 change_id 和 approver）

        Returns:
            是否审批成功
        """
        change_id = change.get("change_id", "")
        approver = change.get("approver", "")

        req = self._find_change(change_id)
        if not req:
            logger.error("变更不存在: %s", change_id)
            return False

        # 检查冻结期
        frozen, reason = self.is_freeze_period()
        if frozen:
            logger.warning("变更冻结期，拒绝审批: %s (原因: %s)", change_id, reason)
            return False

        # 检查审批权限
        required_approvers = self.APPROVAL_REQUIREMENTS.get(req.risk_level, [])
        if required_approvers and approver not in required_approvers:
            logger.warning("审批权限不足: %s 需要 %s", change_id, required_approvers)
            return False

        req.approved_by = approver
        req.status = ChangeStatus.APPROVED
        req.updated_at = time.time_ns()
        logger.info("变更已审批: %s by %s", change_id, approver)
        return True

    def reject_change(self, change_id: str, rejector: str, reason: str = "") -> bool:
        """拒绝变更。"""
        req = self._find_change(change_id)
        if not req:
            return False

        req.status = ChangeStatus.REJECTED
        req.rejected_by = rejector
        req.updated_at = time.time_ns()
        req.metadata["reject_reason"] = reason
        logger.info("变更已拒绝: %s by %s (原因: %s)", change_id, rejector, reason)
        return True

    # ── 变更执行 ──────────────────────────────────────────────────

    def execute_change(self, change_id: str) -> bool:
        """执行变更。

        Args:
            change_id: 变更 ID

        Returns:
            是否执行成功
        """
        req = self._find_change(change_id)
        if not req:
            return False

        if req.status != ChangeStatus.APPROVED:
            logger.warning("变更未审批，拒绝执行: %s (状态: %s)", change_id, req.status.value)
            return False

        # 检查冻结期
        frozen, reason = self.is_freeze_period()
        if frozen:
            logger.warning("变更冻结期，拒绝执行: %s (原因: %s)", change_id, reason)
            return False

        req.status = ChangeStatus.EXECUTING
        req.executed_at = time.time_ns()
        req.updated_at = time.time_ns()
        logger.info("变更开始执行: %s", change_id)
        return True

    def mark_executed(self, change_id: str, success: bool = True) -> bool:
        """标记变更执行完成。"""
        req = self._find_change(change_id)
        if not req:
            return False

        req.status = ChangeStatus.EXECUTED if success else ChangeStatus.FAILED
        req.updated_at = time.time_ns()
        return True

    # ── 变更回滚 ──────────────────────────────────────────────────

    def rollback(self, change_id: str, reason: str = "") -> bool:
        """回滚变更。

        Args:
            change_id: 变更 ID
            reason: 回滚原因

        Returns:
            是否回滚成功
        """
        req = self._find_change(change_id)
        if not req:
            logger.error("变更不存在: %s", change_id)
            return False

        if not req.rollback_plan:
            logger.error("变更无回滚预案: %s", change_id)
            return False

        req.status = ChangeStatus.ROLLED_BACK
        req.rolled_back = True
        req.rolled_back_at = time.time_ns()
        req.rollback_reason = reason
        req.updated_at = time.time_ns()

        logger.warning("变更已回滚: %s (原因: %s)", change_id, reason)
        return True

    async def execute_rollback(self, change_id: str, reason: str = "") -> bool:
        """执行回滚操作。

        Args:
            change_id: 变更 ID
            reason: 回滚原因

        Returns:
            是否回滚成功
        """
        req = self._find_change(change_id)
        if not req:
            return False

        if not self._rollback_fn:
            logger.error("回滚函数未注入: %s", change_id)
            return False

        try:
            success = await self._rollback_fn(change_id)
            if success:
                self.rollback(change_id, reason)
                logger.info("回滚执行成功: %s", change_id)
            else:
                logger.error("回滚执行失败: %s", change_id)
            return success
        except Exception:
            logger.exception("回滚执行异常: %s", change_id)
            return False

    # ── 变更冻结 ──────────────────────────────────────────────────

    def is_freeze_period(self) -> tuple[bool, str]:
        """检查是否在冻结期。

        检查两方面：
        1. 手动设置的冻结（freeze 方法）
        2. 预定义的高波动事件

        Returns:
            (是否冻结, 冻结原因)
        """
        now = time.time()

        # 1. 手动冻结
        if now < self._freeze_until:
            return True, self._freeze_reason or "手动冻结"

        # 2. 高波动事件
        for event in self._freeze_events:
            if event.start_time <= now <= event.end_time:
                return True, f"高波动事件: {event.name}"

        return False, ""

    def freeze(self, duration_sec: int = 3600, reason: str = "") -> None:
        """手动变更冻结。

        Args:
            duration_sec: 冻结时长(秒)
            reason: 冻结原因
        """
        self._freeze_until = time.time() + duration_sec
        self._freeze_reason = reason
        logger.warning("变更冻结: %d 秒 (原因: %s)", duration_sec, reason)

    def unfreeze(self) -> None:
        """解除变更冻结。"""
        self._freeze_until = 0
        self._freeze_reason = ""
        logger.info("变更冻结已解除")

    def add_freeze_event(self, event: FreezeEvent) -> None:
        """添加高波动冻结事件。

        Args:
            event: 冻结事件
        """
        self._freeze_events.append(event)
        logger.info("添加冻结事件: %s (%s ~ %s)", event.name, event.start_time, event.end_time)

    def check_freeze_events(self) -> list[dict[str, Any]]:
        """检查当前和即将到来的冻结事件。"""
        now = time.time()
        upcoming: list[dict[str, Any]] = []

        for event in self._freeze_events:
            if event.end_time < now:
                continue  # 已过期

            status = "active" if event.start_time <= now <= event.end_time else "upcoming"
            upcoming.append(
                {
                    "name": event.name,
                    "status": status,
                    "start_time": event.start_time,
                    "end_time": event.end_time,
                    "reason": event.reason,
                }
            )

        return upcoming

    # ── 查询接口 ──────────────────────────────────────────────────

    def _find_change(self, change_id: str) -> ChangeRequest | None:
        """查找变更请求。"""
        for c in self._changes:
            if c.change_id == change_id:
                return c
        return None

    def get_change(self, change_id: str) -> dict[str, Any] | None:
        """获取变更详情。"""
        req = self._find_change(change_id)
        if not req:
            return None

        return {
            "change_id": req.change_id,
            "title": req.title,
            "type": req.change_type.value,
            "risk_level": req.risk_level.value,
            "status": req.status.value,
            "description": req.description,
            "rollback_plan": req.rollback_plan,
            "approved_by": req.approved_by,
            "executed_at": req.executed_at,
            "rolled_back": req.rolled_back,
            "rollback_reason": req.rollback_reason,
            "created_at": req.created_at,
        }

    def list_changes(
        self,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """列出变更请求。"""
        changes = self._changes
        if status:
            changes = [c for c in changes if c.status.value == status]

        changes.sort(key=lambda c: c.created_at, reverse=True)

        return [
            {
                "change_id": c.change_id,
                "title": c.title,
                "type": c.change_type.value,
                "risk_level": c.risk_level.value,
                "status": c.status.value,
                "created_at": c.created_at,
            }
            for c in changes[:limit]
        ]

    @property
    def stats(self) -> dict[str, Any]:
        """获取变更管理统计。"""
        frozen, reason = self.is_freeze_period()
        return {
            "total_changes": len(self._changes),
            "pending_approval": sum(
                1 for c in self._changes if c.status == ChangeStatus.PENDING_APPROVAL
            ),
            "executed": sum(1 for c in self._changes if c.status == ChangeStatus.EXECUTED),
            "rolled_back": sum(1 for c in self._changes if c.status == ChangeStatus.ROLLED_BACK),
            "frozen": frozen,
            "freeze_reason": reason,
            "release_windows": self.RELEASE_WINDOWS,
            "freeze_events": self.FREEZE_EVENTS,
        }


# ── 灾备指标（兼容旧接口）──────────────────────────────────────


@dataclass
class DRMetrics:
    """灾备指标"""

    rto_target_sec: int = 300  # RTO < 5 分钟
    rpo_target_sec: int = 1  # RPO < 1 秒
    last_backup_ts: int = 0
    last_restore_test_ts: int = 0
    backup_success: bool = False
