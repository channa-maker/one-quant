"""
模型治理 — 枚举定义
"""

from enum import StrEnum


class ModelStatus(StrEnum):
    """模型生命周期状态"""

    DRAFT = "draft"  # 草稿：刚创建，未提交验证
    VALIDATION = "validation"  # 验证中：已提交独立验证
    APPROVED = "approved"  # 已审批：通过验证和审批
    LIVE = "live"  # 上线：正在生产环境运行
    RETIRED = "retired"  # 退役：已下线


class ApprovalAction(StrEnum):
    """审批动作"""

    APPROVE = "approve"  # 通过
    REJECT = "reject"  # 拒回
    REQUEST_CHANGES = "request_changes"  # 要求修改


class DriftType(StrEnum):
    """漂移类型"""

    DATA_DRIFT = "data_drift"  # 输入数据分布漂移
    CONCEPT_DRIFT = "concept_drift"  # 概念漂移（输入输出关系变化）
    PERFORMANCE_DRIFT = "performance_drift"  # 性能漂移（准确率下降等）


class AlertSeverity(StrEnum):
    """告警严重度"""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
