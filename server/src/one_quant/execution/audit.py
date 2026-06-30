"""不可变审计日志 — 纳秒戳/状态快照，只增不改"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from typing import Any

from one_quant.infra.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class AuditRecord:
    """审计记录（不可变）"""

    record_id: str
    event_type: str  # order.submit / order.fill / risk.decision / system.state_change
    source: str  # 策略名 / 风控规则名 / 系统
    data: dict[str, Any]
    state_snapshot: dict[str, Any]  # 当前状态快照
    timestamp_ns: int
    trace_id: str = ""


class AuditLog:
    """不可变审计日志。

    设计原则：
    - 只增不改：所有记录追加写入，永不修改或删除
    - 纳秒精度：每条记录带纳秒时间戳
    - 状态快照：每条记录附带当时的状态快照，支持确定性回放
    - 全链路追踪：通过 trace_id 关联上下游

    存储：当前内存实现，生产环境应写入 PostgreSQL 或 append-only 文件。
    """

    def __init__(self) -> None:
        self._records: list[AuditRecord] = []
        self._counter = 0

    def record(
        self,
        event_type: str,
        source: str,
        data: dict[str, Any],
        state_snapshot: dict[str, Any] | None = None,
        trace_id: str = "",
    ) -> AuditRecord:
        """追加审计记录。

        Args:
            event_type: 事件类型
            source: 事件来源
            data: 事件数据
            state_snapshot: 当前状态快照
            trace_id: 关联追踪 ID

        Returns:
            创建的审计记录
        """
        self._counter += 1
        rec = AuditRecord(
            record_id=f"AUDIT-{self._counter:012d}",
            event_type=event_type,
            source=source,
            data=data,
            state_snapshot=state_snapshot or {},
            timestamp_ns=time.time_ns(),
            trace_id=trace_id,
        )
        self._records.append(rec)

        logger.debug(
            "审计记录: %s %s/%s",
            rec.record_id,
            event_type,
            source,
        )
        return rec

    def query(
        self,
        event_type: str | None = None,
        source: str | None = None,
        start_ns: int = 0,
        end_ns: int = 0,
        limit: int = 100,
    ) -> list[AuditRecord]:
        """查询审计记录。

        Args:
            event_type: 过滤事件类型
            source: 过滤来源
            start_ns: 开始时间
            end_ns: 结束时间
            limit: 最大返回数

        Returns:
            匹配的审计记录
        """
        results: list[AuditRecord] = []
        for rec in reversed(self._records):  # 最新的在前
            if event_type and rec.event_type != event_type:
                continue
            if source and rec.source != source:
                continue
            if start_ns and rec.timestamp_ns < start_ns:
                continue
            if end_ns and rec.timestamp_ns > end_ns:
                continue
            results.append(rec)
            if len(results) >= limit:
                break
        return results

    def export_jsonl(self, filepath: str) -> int:
        """导出为 JSONL 格式（只增不改，可追加写入）"""
        count = 0
        with open(filepath, "a", encoding="utf-8") as f:
            for rec in self._records:
                f.write(json.dumps(asdict(rec), default=str, ensure_ascii=False) + "\n")
                count += 1
        return count

    @property
    def count(self) -> int:
        return len(self._records)
