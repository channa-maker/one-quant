"""Runbook 管理器 — P0/P1 故障处置标准化应急响应

覆盖场景：
- 行情断线
- 交易所故障
- 数据库故障
- 熔断触发
- Redis 故障
- 策略异常
- 风控异常

每个 Runbook 含标准化步骤、自动执行能力、升级路径。
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from one_quant.infra.logging import get_logger

logger = get_logger(__name__)


class Severity(str, Enum):
    """事故严重级别"""

    P0 = "P0"  # 全面停机，资金风险
    P1 = "P1"  # 部分功能不可用
    P2 = "P2"  # 非关键功能异常


@dataclass
class RunbookStep:
    """Runbook 步骤"""

    step_id: str
    description_zh: str
    command: str = ""
    expected_result: str = ""
    auto_executable: bool = False
    auto_action: Callable[[], Awaitable[bool]] | None = None


@dataclass
class Runbook:
    """故障处置 Runbook"""

    incident_id: str
    severity: Severity
    title_zh: str
    steps: list[RunbookStep] = field(default_factory=list)
    escalation_path: list[str] = field(default_factory=list)
    created_at: int = 0
    resolved_at: int = 0
    status: str = "open"  # open / investigating / resolved


class RunbookManager:
    """Runbook 管理器。

    职责：
    - 存储和检索预定义 Runbook
    - 执行 Runbook 步骤（支持自动和手动）
    - 跟踪执行状态
    - 升级通知
    """

    # ── 预定义 Runbook ──────────────────────────────────────────────

    RUNBOOKS: dict[str, dict[str, Any]] = {
        "market_disconnect": {
            "title": "行情断线处置",
            "severity": "P1",
            "steps": [
                "1. 检查网络连通性 (ping/telnet 交易所 API)",
                "2. 检查交易所官方状态页",
                "3. 检查 WebSocket 连接状态",
                "4. 触发自动重连（指数退避 1s→2s→4s→...≤60s）",
                "5. 重连成功后拉取快照对齐",
                "6. 检测数据缺口并触发回补",
                "7. 如持续不可用，切换备用行情源",
                "8. 通知相关方",
            ],
            "escalation": "P1",
            "escalation_path": ["值班工程师", "数据工程师"],
            "auto_steps": [4, 5, 6, 7],
        },
        "exchange_down": {
            "title": "交易所故障处置",
            "severity": "P0",
            "steps": [
                "1. 确认交易所官方状态页和社交媒体",
                "2. 检查本地网络连通性",
                "3. 检查 API 限流状态 (429/418)",
                "4. 触发熔断器半开探测",
                "5. 评估现有持仓风险",
                "6. 如持续不可用，切换备用交易所",
                "7. 通知所有相关方（P0 升级）",
            ],
            "escalation": "P0",
            "escalation_path": ["值班工程师", "技术负责人", "CTO"],
            "auto_steps": [3, 4, 6],
        },
        "db_failure": {
            "title": "数据库故障处置",
            "severity": "P0",
            "steps": [
                "1. 检查 PostgreSQL/TimescaleDB 进程状态",
                "2. 检查磁盘空间和连接数",
                "3. 检查长事务和锁等待",
                "4. 尝试重启数据库服务",
                "5. 如主库不可用，切换到从库",
                "6. 恢复后执行数据一致性校验",
                "7. 检查备份状态",
                "8. 通知 DBA 和运维负责人",
            ],
            "escalation": "P0",
            "escalation_path": ["DBA", "运维负责人", "CTO"],
            "auto_steps": [4, 5, 6],
        },
        "circuit_breaker_triggered": {
            "title": "熔断触发处置",
            "severity": "P0",
            "steps": [
                "1. 确认熔断原因（回撤/频率/异常）",
                "2. 检查熔断器状态和触发条件",
                "3. 检查所有未平仓持仓",
                "4. 评估是否需要手动平仓",
                "5. 检查风控系统健康状态",
                "6. 修复根因",
                "7. 手动解除熔断（需审批）",
                "8. 恢复交易，监控 30 分钟",
            ],
            "escalation": "P0",
            "escalation_path": ["风控负责人", "CTO"],
            "auto_steps": [2, 3],
        },
        "redis_failure": {
            "title": "Redis 故障处置",
            "severity": "P1",
            "steps": [
                "1. 检查 Redis 进程状态",
                "2. 检查内存使用和连接数",
                "3. 切换到本地内存缓冲",
                "4. 触发 Redis 重连（指数退避）",
                "5. 重连成功后补发缓冲数据",
                "6. 检查数据一致性",
                "7. 通知运维负责人",
            ],
            "escalation": "P1",
            "escalation_path": ["运维负责人"],
            "auto_steps": [3, 4, 5],
        },
        "strategy_crash": {
            "title": "策略异常处置",
            "severity": "P1",
            "steps": [
                "1. 隔离崩溃策略（停止信号生成）",
                "2. 保留持仓（不自动平仓）",
                "3. 检查策略日志和异常堆栈",
                "4. 评估持仓风险",
                "5. 通知策略开发者",
                "6. 修复后重新上线（需审批）",
            ],
            "escalation": "P1",
            "escalation_path": ["策略开发者", "技术负责人"],
            "auto_steps": [1, 2],
        },
        "risk_failure": {
            "title": "风控异常处置",
            "severity": "P0",
            "steps": [
                "1. 立即触发全局熔断（停止所有新开仓）",
                "2. 保留现有持仓",
                "3. 检查风控系统日志",
                "4. 评估当前风险敞口",
                "5. 通知风控负责人和 CTO",
                "6. 修复风控系统",
                "7. 手动解除熔断（需 CTO 审批）",
                "8. 恢复交易，持续监控",
            ],
            "escalation": "P0",
            "escalation_path": ["风控负责人", "CTO"],
            "auto_steps": [1, 2],
        },
        "data_gap": {
            "title": "行情数据缺口处置",
            "severity": "P1",
            "steps": [
                "1. 检查数据质检告警日志",
                "2. 确认缺口时段和受影响标的",
                "3. 触发历史数据回补",
                "4. 验证回补数据完整性",
                "5. 重新计算受影响的因子和信号",
                "6. 通知数据工程师",
            ],
            "escalation": "P1",
            "escalation_path": ["数据工程师"],
            "auto_steps": [3, 4],
        },
    }

    def __init__(self) -> None:
        self._execution_history: list[dict[str, Any]] = []
        self._auto_action_map: dict[str, Callable[[], Awaitable[bool]]] = {}

    def register_auto_action(self, action_name: str, fn: Callable[[], Awaitable[bool]]) -> None:
        """注册自动执行动作。"""
        self._auto_action_map[action_name] = fn

    def get_runbook(self, incident_type: str) -> dict[str, Any] | None:
        """获取处置手册。

        Args:
            incident_type: 事件类型

        Returns:
            Runbook 内容，不存在返回 None
        """
        return self.RUNBOOKS.get(incident_type)

    def list_runbooks(self) -> list[dict[str, Any]]:
        """列出所有 Runbook。"""
        return [
            {
                "type": key,
                "title": rb["title"],
                "severity": rb["severity"],
                "step_count": len(rb["steps"]),
            }
            for key, rb in self.RUNBOOKS.items()
        ]

    async def execute_runbook(
        self,
        incident_type: str,
        context: dict[str, Any] | None = None,
    ) -> list[str]:
        """执行 Runbook 步骤。

        按步骤顺序执行：
        - auto_executable 步骤自动执行
        - 非自动步骤记录为待手动处理
        - 记录执行历史

        Args:
            incident_type: 事件类型
            context: 执行上下文

        Returns:
            执行结果日志
        """
        runbook = self.RUNBOOKS.get(incident_type)
        if not runbook:
            return [f"未找到 Runbook: {incident_type}"]

        context = context or {}
        results: list[str] = []
        started_at = time.time_ns()

        results.append(f"▶ 开始执行 Runbook: {runbook['title']} [{runbook['severity']}]")
        results.append(f"  升级路径: {' → '.join(runbook.get('escalation_path', []))}")

        auto_steps = set(runbook.get("auto_steps", []))

        for i, step in enumerate(runbook["steps"], 1):
            step_num = i
            is_auto = step_num in auto_steps

            if is_auto:
                results.append(f"  [{step_num}] 🔧 自动执行: {step}")
                # 尝试执行注册的自动动作
                action_name = f"{incident_type}_step_{step_num}"
                action_fn = self._auto_action_map.get(action_name)
                if action_fn:
                    try:
                        success = await action_fn()
                        results.append(f"       {'✅ 成功' if success else '❌ 失败'}")
                    except Exception as e:
                        results.append(f"       ❌ 异常: {e}")
                else:
                    results.append(f"       ⚠️ 自动动作未注册: {action_name}")
            else:
                results.append(f"  [{step_num}] 📋 手动执行: {step}")

        # 记录执行历史
        elapsed_ms = (time.time_ns() - started_at) / 1e6
        self._execution_history.append(
            {
                "incident_type": incident_type,
                "context": context,
                "results": results,
                "elapsed_ms": round(elapsed_ms, 1),
                "executed_at": started_at,
            }
        )

        results.append(f"▶ Runbook 执行完成 (耗时 {elapsed_ms:.1f}ms)")
        return results

    @property
    def execution_history(self) -> list[dict[str, Any]]:
        """获取执行历史。"""
        return self._execution_history[-50:]  # 最近 50 条


# ── 兼容旧接口 ──────────────────────────────────────────────────


@dataclass
class RunbookLegacy:
    """旧版 Runbook（兼容）"""

    incident_id: str
    severity: Severity
    title_zh: str
    steps: list[RunbookStep] = field(default_factory=list)
    escalation_path: list[str] = field(default_factory=list)
    created_at: int = 0
    resolved_at: int = 0
    status: str = "open"


RUNBOOKS: dict[str, RunbookLegacy] = {
    "exchange_down": RunbookLegacy(
        incident_id="RB-001",
        severity=Severity.P0,
        title_zh="交易所连接断开",
        steps=[
            RunbookStep("1", "检查交易所官方状态页", "curl -s https://www.binance.com/status"),
            RunbookStep("2", "检查本地网络连通性", "ping -c 3 api.binance.com"),
            RunbookStep("3", "确认 WebSocket 自动重连是否生效", auto_executable=True),
            RunbookStep("4", "如持续不可用，切换备用交易所", auto_executable=True),
            RunbookStep("5", "通知相关方"),
        ],
        escalation_path=["值班工程师", "技术负责人", "CTO"],
    ),
    "risk_halt": RunbookLegacy(
        incident_id="RB-002",
        severity=Severity.P0,
        title_zh="风控全局熔断触发",
        steps=[
            RunbookStep("1", "确认熔断原因（回撤/频率/异常）"),
            RunbookStep("2", "检查所有未平仓持仓"),
            RunbookStep("3", "评估是否需要手动平仓"),
            RunbookStep("4", "修复根因后，手动解除熔断"),
            RunbookStep("5", "恢复交易，监控 30 分钟"),
        ],
        escalation_path=["风控负责人", "CTO"],
    ),
    "data_gap": RunbookLegacy(
        incident_id="RB-003",
        severity=Severity.P1,
        title_zh="行情数据缺口",
        steps=[
            RunbookStep("1", "检查数据质检告警日志"),
            RunbookStep("2", "确认缺口时段和受影响标的"),
            RunbookStep("3", "触发历史数据回补", auto_executable=True),
            RunbookStep("4", "验证回补数据完整性"),
        ],
        escalation_path=["数据工程师"],
    ),
    "db_down": RunbookLegacy(
        incident_id="RB-004",
        severity=Severity.P0,
        title_zh="数据库不可用",
        steps=[
            RunbookStep("1", "检查 PostgreSQL/TimescaleDB 进程状态"),
            RunbookStep("2", "检查磁盘空间和连接数"),
            RunbookStep("3", "尝试重启数据库服务"),
            RunbookStep("4", "如主库不可用，切换到从库"),
            RunbookStep("5", "恢复后执行数据一致性校验"),
        ],
        escalation_path=["DBA", "运维负责人"],
    ),
}


def get_runbook(incident_type: str) -> RunbookLegacy | None:
    """获取预定义 Runbook（兼容旧接口）。"""
    return RUNBOOKS.get(incident_type)


def list_runbooks() -> list[dict[str, Any]]:
    """列出所有 Runbook（兼容旧接口）。"""
    return [
        {"id": rb.incident_id, "title": rb.title_zh, "severity": rb.severity.value}
        for rb in RUNBOOKS.values()
    ]
