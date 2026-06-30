"""P0/P1 故障处置 Runbook — 标准化应急响应"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from one_quant.infra.logging import get_logger

logger = get_logger(__name__)


class Severity(str, Enum):
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


# ── 预定义 Runbook ──────────────────────────────────────────────────

RUNBOOKS: dict[str, Runbook] = {
    "exchange_down": Runbook(
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
    "risk_halt": Runbook(
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
    "data_gap": Runbook(
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
    "db_down": Runbook(
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


def get_runbook(incident_type: str) -> Runbook | None:
    """获取预定义 Runbook"""
    return RUNBOOKS.get(incident_type)


def list_runbooks() -> list[dict[str, Any]]:
    """列出所有 Runbook"""
    return [
        {"id": rb.incident_id, "title": rb.title_zh, "severity": rb.severity.value}
        for rb in RUNBOOKS.values()
    ]
