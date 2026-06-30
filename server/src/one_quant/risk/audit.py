"""
ONE量化 - 不可变风控审计日志

只增不改，不可变。每条记录包含：
  - 纳秒时间戳
  - 策略 ID
  - 订单 ID
  - 决策（四态）
  - 触发规则
  - 状态快照（当时持仓/敞口/回撤）

设计原则：
  - append-only：只有 record()，没有 update/delete
  - 线程安全：使用锁保护写操作
  - 查询支持：按时间范围和策略 ID 过滤
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any

from one_quant.core.types import Order
from one_quant.risk.contracts import RiskCheckResult

logger = logging.getLogger(__name__)


class RiskAuditLog:
    """风控决策审计日志。

    只增不改，不可变。每条记录包含：
    - 纳秒时间戳
    - 策略 ID
    - 订单 ID
    - 决策（四态）
    - 触发规则
    - 状态快照（当时持仓/敞口/回撤）

    支持内存存储和文件持久化两种模式。
    """

    def __init__(self, persist_path: Path | str | None = None) -> None:
        """初始化审计日志。

        Args:
            persist_path: 日志持久化文件路径。None 则仅内存存储。
        """
        self._records: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self._persist_path: Path | None = Path(persist_path) if persist_path else None

    def record(
        self,
        decision: RiskCheckResult,
        order: Order | None,
        snapshot: dict[str, Any],
        strategy_id: str | None = None,
    ) -> None:
        """记录一条审计日志。

        Args:
            decision: 风控检查结果。
            order: 待检查订单（可为 None，如 halt_all 场景）。
            snapshot: 当时状态快照（持仓/敞口/回撤等）。
            strategy_id: 策略 ID。可选。
        """
        entry = {
            "timestamp_ns": decision.timestamp_ns,
            "strategy_id": strategy_id,
            "order_id": order.client_order_id if order else None,
            "symbol": order.symbol if order else None,
            "decision": decision.decision.value,
            "rule_name": decision.rule_name,
            "reason": decision.reason,
            "snapshot": snapshot,
        }

        with self._lock:
            self._records.append(entry)

        # 持久化
        if self._persist_path is not None:
            try:
                with open(self._persist_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
            except OSError as e:
                logger.error("审计日志持久化失败: %s", e)

        logger.info(
            "审计: decision=%s rule=%s order=%s",
            decision.decision.value,
            decision.rule_name,
            order.client_order_id if order else "N/A",
        )

    def query(
        self,
        start_time: int,
        end_time: int,
        strategy_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """查询审计日志。

        Args:
            start_time: 起始时间（纳秒时间戳，包含）。
            end_time: 结束时间（纳秒时间戳，包含）。
            strategy_id: 策略 ID 过滤。None 表示不过滤。

        Returns:
            符合条件的审计记录列表。
        """
        with self._lock:
            results = []
            for entry in self._records:
                ts = entry["timestamp_ns"]
                if ts < start_time or ts > end_time:
                    continue
                if strategy_id is not None and entry["strategy_id"] != strategy_id:
                    continue
                results.append(entry)
            return results

    @property
    def count(self) -> int:
        """当前记录总数。"""
        return len(self._records)

    def clear(self) -> None:
        """清空内存记录（仅用于测试）。"""
        with self._lock:
            self._records.clear()
