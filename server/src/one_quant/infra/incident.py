"""事故管理 — 创建/解决/复盘，归档进机构记忆

事故生命周期：
open → investigating → identified → resolved → post_mortem

复盘结果归档进机构记忆（喂回 LLM），形成闭环。
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Awaitable

from one_quant.infra.logging import get_logger

logger = get_logger(__name__)


class Severity(str, Enum):
    """事故严重级别"""
    P0 = "P0"  # 全面停机，资金风险
    P1 = "P1"  # 部分功能不可用
    P2 = "P2"  # 非关键功能异常
    P3 = "P3"  # 轻微异常


class IncidentStatus(str, Enum):
    """事故状态"""
    OPEN = "open"
    INVESTIGATING = "investigating"
    IDENTIFIED = "identified"
    RESOLVED = "resolved"
    POST_MORTEM = "post_mortem"
    CLOSED = "closed"


@dataclass
class Incident:
    """事故记录"""
    incident_id: str
    title: str
    severity: Severity
    description: str
    status: IncidentStatus = IncidentStatus.OPEN
    created_at: int = 0
    updated_at: int = 0
    resolved_at: int = 0
    resolution: str = ""
    root_cause: str = ""
    impact: str = ""
    timeline: list[dict[str, Any]] = field(default_factory=list)
    action_items: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PostMortem:
    """事后复盘"""
    incident_id: str
    summary: str
    root_cause: str
    timeline: list[dict[str, Any]]
    what_went_well: list[str]
    what_went_wrong: list[str]
    action_items: list[str]
    lessons_learned: list[str]
    created_at: int = 0


class IncidentManager:
    """事故管理器。

    职责：
    - 创建和跟踪事故
    - 管理事故生命周期
    - 事后复盘并归档进机构记忆
    - 复盘结果喂回 LLM，形成闭环
    """

    def __init__(self) -> None:
        self._incidents: dict[str, Incident] = {}
        self._post_mortems: dict[str, PostMortem] = {}

        # 机构记忆归档回调（由上层注入）
        self._archive_fn: Callable[[dict[str, Any]], Awaitable[None]] | None = None

    def set_archive_fn(self, fn: Callable[[dict[str, Any]], Awaitable[None]]) -> None:
        """注入机构记忆归档函数。"""
        self._archive_fn = fn

    # ── 事故创建 ──────────────────────────────────────────────────

    def create_incident(
        self,
        title: str,
        severity: str,
        description: str,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """创建事故。

        Args:
            title: 事故标题
            severity: 严重级别 (P0/P1/P2/P3)
            description: 事故描述
            tags: 标签列表
            metadata: 附加元数据

        Returns:
            事故 ID
        """
        incident_id = f"INC-{uuid.uuid4().hex[:8].upper()}"
        now = time.time_ns()

        incident = Incident(
            incident_id=incident_id,
            title=title,
            severity=Severity(severity),
            description=description,
            created_at=now,
            updated_at=now,
            tags=tags or [],
            metadata=metadata or {},
            timeline=[
                {
                    "time": now,
                    "event": "事故创建",
                    "detail": description,
                }
            ],
        )

        self._incidents[incident_id] = incident
        logger.warning("事故创建: %s [%s] %s", incident_id, severity, title)

        return incident_id

    # ── 事故更新 ──────────────────────────────────────────────────

    def update_status(self, incident_id: str, status: str, detail: str = "") -> bool:
        """更新事故状态。

        Args:
            incident_id: 事故 ID
            status: 新状态
            detail: 更新说明

        Returns:
            是否更新成功
        """
        incident = self._incidents.get(incident_id)
        if not incident:
            logger.error("事故不存在: %s", incident_id)
            return False

        old_status = incident.status.value
        incident.status = IncidentStatus(status)
        incident.updated_at = time.time_ns()
        incident.timeline.append({
            "time": time.time_ns(),
            "event": f"状态变更: {old_status} → {status}",
            "detail": detail,
        })

        logger.info("事故状态更新: %s %s → %s", incident_id, old_status, status)
        return True

    def add_timeline_event(self, incident_id: str, event: str, detail: str = "") -> bool:
        """添加时间线事件。"""
        incident = self._incidents.get(incident_id)
        if not incident:
            return False

        incident.timeline.append({
            "time": time.time_ns(),
            "event": event,
            "detail": detail,
        })
        incident.updated_at = time.time_ns()
        return True

    # ── 事故解决 ──────────────────────────────────────────────────

    def resolve_incident(self, incident_id: str, resolution: str) -> None:
        """解决事故。

        Args:
            incident_id: 事故 ID
            resolution: 解决方案描述
        """
        incident = self._incidents.get(incident_id)
        if not incident:
            logger.error("事故不存在: %s", incident_id)
            return

        incident.status = IncidentStatus.RESOLVED
        incident.resolution = resolution
        incident.resolved_at = time.time_ns()
        incident.updated_at = time.time_ns()
        incident.timeline.append({
            "time": time.time_ns(),
            "event": "事故解决",
            "detail": resolution,
        })

        # 计算解决时间
        duration_sec = (incident.resolved_at - incident.created_at) / 1e9
        logger.info("事故已解决: %s (耗时 %.1fs)", incident_id, duration_sec)

    # ── 事后复盘 ──────────────────────────────────────────────────

    async def post_mortem(self, incident_id: str) -> dict[str, Any]:
        """事后复盘。

        复盘内容：
        1. 事故摘要
        2. 根因分析
        3. 时间线回顾
        4. 做得好的 / 做得差的
        5. 改进行动项
        6. 经验教训

        复盘结果归档进机构记忆（喂回 LLM）。

        Args:
            incident_id: 事故 ID

        Returns:
            复盘结果
        """
        incident = self._incidents.get(incident_id)
        if not incident:
            logger.error("事故不存在: %s", incident_id)
            return {"error": "事故不存在"}

        # 计算关键指标
        duration_sec = 0
        if incident.resolved_at > 0 and incident.created_at > 0:
            duration_sec = (incident.resolved_at - incident.created_at) / 1e9

        mttr = duration_sec  # 平均恢复时间

        pm = PostMortem(
            incident_id=incident_id,
            summary=f"[{incident.severity.value}] {incident.title}",
            root_cause=incident.root_cause or "待分析",
            timeline=incident.timeline,
            what_went_well=[],
            what_went_wrong=[],
            action_items=incident.action_items,
            lessons_learned=[],
            created_at=time.time_ns(),
        )

        self._post_mortems[incident_id] = pm

        # 更新事故状态
        incident.status = IncidentStatus.POST_MORTEM
        incident.updated_at = time.time_ns()

        # 构建复盘结果
        result = {
            "incident_id": incident_id,
            "title": incident.title,
            "severity": incident.severity.value,
            "duration_sec": round(duration_sec, 1),
            "mttr_sec": round(mttr, 1),
            "summary": pm.summary,
            "root_cause": pm.root_cause,
            "timeline": [
                {
                    "time": t["time"],
                    "event": t["event"],
                    "detail": t["detail"],
                }
                for t in pm.timeline
            ],
            "what_went_well": pm.what_went_well,
            "what_went_wrong": pm.what_went_wrong,
            "action_items": pm.action_items,
            "lessons_learned": pm.lessons_learned,
            "resolution": incident.resolution,
            "tags": incident.tags,
        }

        # 归档进机构记忆（喂回 LLM）
        if self._archive_fn:
            try:
                await self._archive_fn({
                    "type": "post_mortem",
                    "incident_id": incident_id,
                    "data": result,
                })
                logger.info("复盘已归档进机构记忆: %s", incident_id)
            except Exception:
                logger.exception("复盘归档失败: %s", incident_id)

        logger.info("事后复盘完成: %s", incident_id)
        return result

    # ── 查询接口 ──────────────────────────────────────────────────

    def get_incident(self, incident_id: str) -> dict[str, Any] | None:
        """获取事故详情。"""
        incident = self._incidents.get(incident_id)
        if not incident:
            return None

        return {
            "incident_id": incident.incident_id,
            "title": incident.title,
            "severity": incident.severity.value,
            "status": incident.status.value,
            "description": incident.description,
            "resolution": incident.resolution,
            "root_cause": incident.root_cause,
            "created_at": incident.created_at,
            "updated_at": incident.updated_at,
            "resolved_at": incident.resolved_at,
            "timeline": incident.timeline,
            "action_items": incident.action_items,
            "tags": incident.tags,
        }

    def list_incidents(
        self,
        status: str | None = None,
        severity: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """列出事故。"""
        incidents = list(self._incidents.values())

        if status:
            incidents = [i for i in incidents if i.status.value == status]
        if severity:
            incidents = [i for i in incidents if i.severity.value == severity]

        # 按创建时间倒序
        incidents.sort(key=lambda i: i.created_at, reverse=True)

        return [
            {
                "incident_id": i.incident_id,
                "title": i.title,
                "severity": i.severity.value,
                "status": i.status.value,
                "created_at": i.created_at,
                "resolved_at": i.resolved_at,
            }
            for i in incidents[:limit]
        ]

    @property
    def stats(self) -> dict[str, Any]:
        """获取事故统计。"""
        total = len(self._incidents)
        open_count = sum(1 for i in self._incidents.values() if i.status in (IncidentStatus.OPEN, IncidentStatus.INVESTIGATING))
        resolved = sum(1 for i in self._incidents.values() if i.status in (IncidentStatus.RESOLVED, IncidentStatus.POST_MORTEM))

        # 计算平均恢复时间
        resolved_incidents = [i for i in self._incidents.values() if i.resolved_at > 0]
        avg_mttr = 0
        if resolved_incidents:
            total_time = sum((i.resolved_at - i.created_at) / 1e9 for i in resolved_incidents)
            avg_mttr = total_time / len(resolved_incidents)

        return {
            "total": total,
            "open": open_count,
            "resolved": resolved,
            "avg_mttr_sec": round(avg_mttr, 1),
            "post_mortems": len(self._post_mortems),
        }
