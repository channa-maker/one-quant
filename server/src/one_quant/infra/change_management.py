"""灾备与变更管理 — RTO/RPO + 发布窗口 + 回滚预案"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from one_quant.infra.logging import get_logger

logger = get_logger(__name__)


class ChangeType(str, Enum):
    HOTFIX = "hotfix"
    FEATURE = "feature"
    INFRA = "infra"
    CONFIG = "config"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class ChangeRequest:
    """变更请求"""
    change_id: str
    title: str
    change_type: ChangeType
    risk_level: RiskLevel
    description: str
    rollback_plan: str
    scheduled_window: str = ""  # 发布窗口
    approved_by: str = ""
    executed_at: int = 0
    rolled_back: bool = False


class ChangeManager:
    """变更管理器。

    - 发布窗口管理（低波动时段）
    - 高波动事件变更冻结
    - 回滚预案
    - RTO/RPO 追踪
    """

    # 发布窗口：UTC 02:00-06:00（亚洲凌晨，欧美收盘后）
    RELEASE_WINDOWS = ["02:00-06:00 UTC"]

    def __init__(self) -> None:
        self._changes: list[ChangeRequest] = []
        self._freeze_until: int = 0  # 冻结截止时间戳

    def submit(self, change: ChangeRequest) -> str:
        """提交变更请求"""
        self._changes.append(change)
        logger.info("变更请求已提交: %s %s", change.change_id, change.title)
        return change.change_id

    def approve(self, change_id: str, approver: str) -> bool:
        for c in self._changes:
            if c.change_id == change_id:
                c.approved_by = approver
                logger.info("变更已审批: %s by %s", change_id, approver)
                return True
        return False

    def freeze(self, duration_sec: int = 3600, reason: str = "") -> None:
        """变更冻结（高波动事件期间）"""
        self._freeze_until = time.time() + duration_sec
        logger.warning("变更冻结: %d 秒 (原因: %s)", duration_sec, reason)

    def is_frozen(self) -> bool:
        return time.time() < self._freeze_until

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "total_changes": len(self._changes),
            "frozen": self.is_frozen(),
            "release_windows": self.RELEASE_WINDOWS,
        }


@dataclass
class DRMetrics:
    """灾备指标"""
    rto_target_sec: int = 300  # RTO < 5 分钟
    rpo_target_sec: int = 1  # RPO < 1 秒
    last_backup_ts: int = 0
    last_restore_test_ts: int = 0
    backup_success: bool = False
