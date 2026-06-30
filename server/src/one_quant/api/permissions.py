"""
ONE量化 · 权限系统
细粒度权限控制 · 角色矩阵 · 双人复核
"""

from __future__ import annotations

import uuid
import time
import asyncio
from enum import Enum
from functools import wraps
from typing import Callable, Any, Optional
from dataclasses import dataclass, field


# ── 权限枚举 ──────────────────────────────────────────────

class Permission(str, Enum):
    """细粒度权限"""
    VIEW_DASHBOARD = "view_dashboard"       # 查看总览
    VIEW_POSITIONS = "view_positions"       # 查看持仓
    PLACE_ORDER = "place_order"             # 下单
    CANCEL_ORDER = "cancel_order"           # 撤单
    MANAGE_STRATEGY = "manage_strategy"     # 管理策略
    EDIT_RISK_LIMITS = "edit_risk_limits"   # 编辑风控参数
    EMERGENCY_HALT = "emergency_halt"       # 紧急暂停
    VIEW_AUDIT = "view_audit"               # 查看审计日志


class Role(str, Enum):
    """角色"""
    OWNER = "owner"       # 所有者 - 全部权限
    ADMIN = "admin"       # 管理员 - 除紧急暂停和审计外全部
    TRADER = "trader"     # 交易员 - 查看+下单+撤单+策略
    VIEWER = "viewer"     # 观察者 - 仅查看


# ── 角色-权限矩阵 ─────────────────────────────────────────

ROLE_PERMISSIONS: dict[Role, set[Permission]] = {
    Role.OWNER: {p for p in Permission},  # 全部权限

    Role.ADMIN: {
        Permission.VIEW_DASHBOARD,
        Permission.VIEW_POSITIONS,
        Permission.PLACE_ORDER,
        Permission.CANCEL_ORDER,
        Permission.MANAGE_STRATEGY,
        Permission.EDIT_RISK_LIMITS,
        Permission.VIEW_AUDIT,
    },

    Role.TRADER: {
        Permission.VIEW_DASHBOARD,
        Permission.VIEW_POSITIONS,
        Permission.PLACE_ORDER,
        Permission.CANCEL_ORDER,
        Permission.MANAGE_STRATEGY,
    },

    Role.VIEWER: {
        Permission.VIEW_DASHBOARD,
        Permission.VIEW_POSITIONS,
    },
}


# ── 需要双人复核的权限 ────────────────────────────────────

DUAL_APPROVAL_PERMISSIONS: set[Permission] = {
    Permission.EDIT_RISK_LIMITS,
    Permission.EMERGENCY_HALT,
}


# ── 用户上下文 ────────────────────────────────────────────

@dataclass
class UserContext:
    """当前用户上下文"""
    user_id: str
    username: str
    role: Role
    permissions: set[Permission] = field(default_factory=set)

    def __post_init__(self):
        if not self.permissions:
            self.permissions = ROLE_PERMISSIONS.get(self.role, set())


# ── 权限检查器 ────────────────────────────────────────────

class PermissionChecker:
    """权限检查器"""

    def check(self, user_role: Role, required_permission: Permission) -> bool:
        """
        检查角色是否拥有指定权限
        
        Args:
            user_role: 用户角色
            required_permission: 需要的权限
            
        Returns:
            bool: 是否拥有权限
        """
        role_perms = ROLE_PERMISSIONS.get(user_role, set())
        return required_permission in role_perms

    def check_user(self, user: UserContext, required_permission: Permission) -> bool:
        """检查用户上下文是否拥有权限"""
        return required_permission in user.permissions

    def get_permissions(self, role: Role) -> set[Permission]:
        """获取角色的全部权限"""
        return ROLE_PERMISSIONS.get(role, set()).copy()

    def get_user_permissions(self, user: UserContext) -> set[Permission]:
        """获取用户的全部权限"""
        return user.permissions.copy()

    def require_permission(self, permission: Permission) -> Callable:
        """
        装饰器：要求特定权限
        
        用法:
            @checker.require_permission(Permission.PLACE_ORDER)
            async def place_order(user: UserContext, ...):
                ...
        """

        def decorator(func: Callable) -> Callable:
            @wraps(func)
            async def wrapper(*args: Any, **kwargs: Any) -> Any:
                # 从参数中提取 UserContext
                user = _extract_user_context(args, kwargs)
                if user is None:
                    raise PermissionError("未提供用户上下文")

                if not self.check_user(user, permission):
                    raise PermissionError(
                        f"权限不足：需要 {permission.value}，"
                        f"当前角色 {user.role.value} 无此权限"
                    )

                return await func(*args, **kwargs)

            return wrapper

        return decorator

    def require_any_permission(self, *permissions: Permission) -> Callable:
        """
        装饰器：要求拥有任一指定权限
        
        用法:
            @checker.require_any_permission(Permission.PLACE_ORDER, Permission.CANCEL_ORDER)
            async def submit_order(...):
                ...
        """
        perm_set = set(permissions)

        def decorator(func: Callable) -> Callable:
            @wraps(func)
            async def wrapper(*args: Any, **kwargs: Any) -> Any:
                user = _extract_user_context(args, kwargs)
                if user is None:
                    raise PermissionError("未提供用户上下文")

                if not (perm_set & user.permissions):
                    perm_names = ", ".join(p.value for p in permissions)
                    raise PermissionError(
                        f"权限不足：需要以下任一权限 [{perm_names}]，"
                        f"当前角色 {user.role.value} 无匹配权限"
                    )

                return await func(*args, **kwargs)

            return wrapper

        return decorator


def _extract_user_context(args: tuple, kwargs: dict) -> Optional[UserContext]:
    """从函数参数中提取 UserContext"""
    # 检查 kwargs
    for v in kwargs.values():
        if isinstance(v, UserContext):
            return v

    # 检查 args（跳过 self）
    for arg in args:
        if isinstance(arg, UserContext):
            return arg

    return None


# ── 双人复核系统 ──────────────────────────────────────────

@dataclass
class ApprovalRequest:
    """复核请求"""
    request_id: str
    action: str
    requester_id: str
    created_at: float
    expires_at: float
    status: str = "pending"   # pending / approved / rejected / expired
    approver_id: Optional[str] = None
    approved_at: Optional[float] = None
    metadata: dict = field(default_factory=dict)


class DualApproval:
    """
    双人复核（敏感操作）
    
    流程:
    1. 发起人调用 request_approval 发起请求
    2. 系统通知审批人
    3. 审批人调用 approve 完成审批
    4. 发起人收到审批结果后执行操作
    
    超时: 默认 5 分钟
    """

    def __init__(self, timeout_seconds: int = 300):
        self._timeout = timeout_seconds
        self._requests: dict[str, ApprovalRequest] = {}

    async def request_approval(
        self,
        action: str,
        requester_id: str,
        metadata: Optional[dict] = None,
    ) -> str:
        """
        发起复核请求
        
        Args:
            action: 操作描述（如 "edit_risk_limit: max_drawdown=0.1"）
            requester_id: 发起人 ID
            metadata: 附加信息
            
        Returns:
            str: 请求 ID
            
        Raises:
            ValueError: 如果已有相同操作的待审批请求
        """
        now = time.time()

        # 检查是否有重复的待审批请求
        for req in self._requests.values():
            if (
                req.action == action
                and req.requester_id == requester_id
                and req.status == "pending"
                and req.expires_at > now
            ):
                raise ValueError(
                    f"已有相同操作的待审批请求: {req.request_id}"
                )

        request_id = str(uuid.uuid4())
        request = ApprovalRequest(
            request_id=request_id,
            action=action,
            requester_id=requester_id,
            created_at=now,
            expires_at=now + self._timeout,
            metadata=metadata or {},
        )

        self._requests[request_id] = request

        # TODO: 发送通知给可审批的管理员
        # await notify_admins(request)

        return request_id

    async def approve(self, request_id: str, approver_id: str) -> bool:
        """
        审批复核请求
        
        Args:
            request_id: 请求 ID
            approver_id: 审批人 ID
            
        Returns:
            bool: 是否审批成功
            
        Raises:
            ValueError: 请求不存在或已过期
            PermissionError: 审批人与发起人相同（不允许自批自）
        """
        request = self._requests.get(request_id)
        if request is None:
            raise ValueError(f"复核请求不存在: {request_id}")

        if request.status != "pending":
            raise ValueError(f"请求已处理: {request.status}")

        if request.expires_at < time.time():
            request.status = "expired"
            raise ValueError("复核请求已过期")

        if request.requester_id == approver_id:
            raise PermissionError("不允许自批自，必须由其他管理员审批")

        now = time.time()
        request.status = "approved"
        request.approver_id = approver_id
        request.approved_at = now

        return True

    async def reject(self, request_id: str, approver_id: str, reason: str = "") -> bool:
        """拒绝复核请求"""
        request = self._requests.get(request_id)
        if request is None:
            raise ValueError(f"复核请求不存在: {request_id}")

        if request.status != "pending":
            raise ValueError(f"请求已处理: {request.status}")

        if request.requester_id == approver_id:
            raise PermissionError("不允许自批自")

        request.status = "rejected"
        request.approver_id = approver_id
        request.metadata["reject_reason"] = reason

        return True

    def get_request(self, request_id: str) -> Optional[ApprovalRequest]:
        """获取复核请求状态"""
        req = self._requests.get(request_id)
        # 检查是否过期
        if req and req.status == "pending" and req.expires_at < time.time():
            req.status = "expired"
        return req

    def get_pending_requests(self, requester_id: Optional[str] = None) -> list[ApprovalRequest]:
        """获取待审批请求列表"""
        now = time.time()
        results = []
        for req in self._requests.values():
            if req.status == "pending":
                if req.expires_at < now:
                    req.status = "expired"
                    continue
                if requester_id is None or req.requester_id == requester_id:
                    results.append(req)
        return results

    def cleanup_expired(self) -> int:
        """清理过期请求，返回清理数量"""
        now = time.time()
        expired_ids = [
            rid for rid, req in self._requests.items()
            if req.status in ("expired", "approved", "rejected")
            and (now - req.created_at) > 3600  # 1 小时后清理
        ]
        for rid in expired_ids:
            del self._requests[rid]
        return len(expired_ids)


# ── 全局实例 ──────────────────────────────────────────────

permission_checker = PermissionChecker()
dual_approval = DualApproval()


# ── 便捷函数 ──────────────────────────────────────────────

def check_permission(user: UserContext, permission: Permission) -> bool:
    """检查用户权限"""
    return permission_checker.check_user(user, permission)


def require_permission(permission: Permission) -> Callable:
    """装饰器：要求特定权限"""
    return permission_checker.require_permission(permission)


def require_dual_approval(permission: Permission) -> bool:
    """检查权限是否需要双人复核"""
    return permission in DUAL_APPROVAL_PERMISSIONS
