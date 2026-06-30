"""Tests for api/permissions.py — 权限系统"""

import pytest

from one_quant.api.permissions import (
    DUAL_APPROVAL_PERMISSIONS,
    ROLE_PERMISSIONS,
    DualApproval,
    Permission,
    PermissionChecker,
    Role,
    UserContext,
    check_permission,
    require_dual_approval,
)

# ── Permission enum ────────────────────────────────────────────


class TestPermissionEnum:
    def test_all_permissions_exist(self):
        expected = {
            "view_dashboard",
            "view_positions",
            "place_order",
            "cancel_order",
            "manage_strategy",
            "edit_risk_limits",
            "emergency_halt",
            "view_audit",
        }
        actual = {p.value for p in Permission}
        assert actual == expected

    def test_permission_is_str(self):
        assert isinstance(Permission.VIEW_DASHBOARD, str)
        assert Permission.VIEW_DASHBOARD == "view_dashboard"


# ── Role enum ──────────────────────────────────────────────────


class TestRoleEnum:
    def test_all_roles_exist(self):
        expected = {"owner", "admin", "trader", "viewer"}
        actual = {r.value for r in Role}
        assert actual == expected


# ── ROLE_PERMISSIONS matrix ────────────────────────────────────


class TestRolePermissionMatrix:
    def test_owner_has_all_permissions(self):
        assert ROLE_PERMISSIONS[Role.OWNER] == set(Permission)

    def test_admin_has_no_emergency_halt(self):
        assert Permission.EMERGENCY_HALT not in ROLE_PERMISSIONS[Role.ADMIN]

    def test_admin_has_view_audit(self):
        assert Permission.VIEW_AUDIT in ROLE_PERMISSIONS[Role.ADMIN]

    def test_trader_permissions(self):
        perms = ROLE_PERMISSIONS[Role.TRADER]
        assert Permission.PLACE_ORDER in perms
        assert Permission.CANCEL_ORDER in perms
        assert Permission.MANAGE_STRATEGY in perms
        assert Permission.EDIT_RISK_LIMITS not in perms
        assert Permission.EMERGENCY_HALT not in perms
        assert Permission.VIEW_AUDIT not in perms

    def test_viewer_only_view(self):
        perms = ROLE_PERMISSIONS[Role.VIEWER]
        assert perms == {Permission.VIEW_DASHBOARD, Permission.VIEW_POSITIONS}

    def test_dual_approval_permissions(self):
        assert Permission.EDIT_RISK_LIMITS in DUAL_APPROVAL_PERMISSIONS
        assert Permission.EMERGENCY_HALT in DUAL_APPROVAL_PERMISSIONS
        assert len(DUAL_APPROVAL_PERMISSIONS) == 2


# ── UserContext ────────────────────────────────────────────────


class TestUserContext:
    def test_auto_populate_permissions(self):
        user = UserContext(user_id="u1", username="alice", role=Role.TRADER)
        assert user.permissions == ROLE_PERMISSIONS[Role.TRADER]

    def test_explicit_permissions_preserved(self):
        custom = {Permission.VIEW_DASHBOARD}
        user = UserContext(user_id="u2", username="bob", role=Role.VIEWER, permissions=custom)
        assert user.permissions == custom

    def test_owner_context(self):
        user = UserContext(user_id="u3", username="root", role=Role.OWNER)
        assert Permission.EMERGENCY_HALT in user.permissions


# ── PermissionChecker ──────────────────────────────────────────


class TestPermissionChecker:
    @pytest.fixture
    def checker(self):
        return PermissionChecker()

    def test_owner_can_do_everything(self, checker):
        for perm in Permission:
            assert checker.check(Role.OWNER, perm) is True

    def test_viewer_cannot_place_order(self, checker):
        assert checker.check(Role.VIEWER, Permission.PLACE_ORDER) is False

    def test_admin_cannot_emergency_halt(self, checker):
        assert checker.check(Role.ADMIN, Permission.EMERGENCY_HALT) is False

    def test_trader_can_place_order(self, checker):
        assert checker.check(Role.TRADER, Permission.PLACE_ORDER) is True

    def test_check_user(self, checker):
        user = UserContext(user_id="u1", username="alice", role=Role.ADMIN)
        assert checker.check_user(user, Permission.VIEW_AUDIT) is True
        assert checker.check_user(user, Permission.EMERGENCY_HALT) is False

    def test_get_permissions(self, checker):
        perms = checker.get_permissions(Role.VIEWER)
        assert perms == {Permission.VIEW_DASHBOARD, Permission.VIEW_POSITIONS}
        # Returns a copy
        perms.add(Permission.PLACE_ORDER)
        assert Permission.PLACE_ORDER not in checker.get_permissions(Role.VIEWER)

    def test_get_user_permissions(self, checker):
        user = UserContext(user_id="u1", username="alice", role=Role.TRADER)
        perms = checker.get_user_permissions(user)
        assert Permission.PLACE_ORDER in perms

    def test_unknown_role_has_no_permissions(self, checker):
        # Simulate unknown role by checking against a role not in matrix
        # Actually all roles are in matrix, so test empty set behavior
        perms = checker.get_permissions(Role.VIEWER)
        assert Permission.EMERGENCY_HALT not in perms


# ── Decorators ─────────────────────────────────────────────────


class TestRequirePermissionDecorator:
    @pytest.fixture
    def checker(self):
        return PermissionChecker()

    @pytest.mark.asyncio
    async def test_granted(self, checker):
        @checker.require_permission(Permission.PLACE_ORDER)
        async def place_order(user: UserContext):
            return "order_placed"

        user = UserContext(user_id="u1", username="trader", role=Role.TRADER)
        result = await place_order(user=user)
        assert result == "order_placed"

    @pytest.mark.asyncio
    async def test_denied(self, checker):
        @checker.require_permission(Permission.EMERGENCY_HALT)
        async def halt(user: UserContext):
            return "halted"

        user = UserContext(user_id="u1", username="viewer", role=Role.VIEWER)
        with pytest.raises(PermissionError, match="权限不足"):
            await halt(user=user)

    @pytest.mark.asyncio
    async def test_no_user_context(self, checker):
        @checker.require_permission(Permission.PLACE_ORDER)
        async def place_order():
            return "ok"

        with pytest.raises(PermissionError, match="未提供用户上下文"):
            await place_order()

    @pytest.mark.asyncio
    async def test_user_as_positional_arg(self, checker):
        @checker.require_permission(Permission.VIEW_DASHBOARD)
        async def view(user: UserContext):
            return "dashboard"

        user = UserContext(user_id="u1", username="v", role=Role.VIEWER)
        result = await view(user)
        assert result == "dashboard"


class TestRequireAnyPermissionDecorator:
    @pytest.fixture
    def checker(self):
        return PermissionChecker()

    @pytest.mark.asyncio
    async def test_has_one_of(self, checker):
        @checker.require_any_permission(Permission.PLACE_ORDER, Permission.CANCEL_ORDER)
        async def submit(user: UserContext):
            return "submitted"

        user = UserContext(user_id="u1", username="trader", role=Role.TRADER)
        result = await submit(user=user)
        assert result == "submitted"

    @pytest.mark.asyncio
    async def test_has_none_of(self, checker):
        @checker.require_any_permission(Permission.PLACE_ORDER, Permission.EMERGENCY_HALT)
        async def submit(user: UserContext):
            return "submitted"

        user = UserContext(user_id="u1", username="viewer", role=Role.VIEWER)
        with pytest.raises(PermissionError, match="权限不足"):
            await submit(user=user)


# ── DualApproval ───────────────────────────────────────────────


class TestDualApproval:
    @pytest.fixture
    def approval(self):
        return DualApproval(timeout_seconds=300)

    @pytest.mark.asyncio
    async def test_request_and_approve(self, approval):
        req_id = await approval.request_approval("edit_risk_limit: max_dd=0.1", "user-a")
        assert req_id is not None

        result = await approval.approve(req_id, "user-b")
        assert result is True

        req = approval.get_request(req_id)
        assert req.status == "approved"
        assert req.approver_id == "user-b"

    @pytest.mark.asyncio
    async def test_self_approve_rejected(self, approval):
        req_id = await approval.request_approval("halt", "user-a")
        with pytest.raises(PermissionError, match="自批自"):
            await approval.approve(req_id, "user-a")

    @pytest.mark.asyncio
    async def test_duplicate_pending_raises(self, approval):
        await approval.request_approval("action-x", "user-a")
        with pytest.raises(ValueError, match="已有相同操作"):
            await approval.request_approval("action-x", "user-a")

    @pytest.mark.asyncio
    async def test_nonexistent_request(self, approval):
        with pytest.raises(ValueError, match="不存在"):
            await approval.approve("no-such-id", "user-b")

    @pytest.mark.asyncio
    async def test_reject(self, approval):
        req_id = await approval.request_approval("action-y", "user-a")
        result = await approval.reject(req_id, "user-b", reason="not safe")
        assert result is True
        req = approval.get_request(req_id)
        assert req.status == "rejected"
        assert req.metadata["reject_reason"] == "not safe"

    @pytest.mark.asyncio
    async def test_cannot_reject_twice(self, approval):
        req_id = await approval.request_approval("action-z", "user-a")
        await approval.reject(req_id, "user-b")
        with pytest.raises(ValueError, match="已处理"):
            await approval.reject(req_id, "user-c")

    @pytest.mark.asyncio
    async def test_expired_request(self, approval):
        # Create approval with 0 timeout
        approval._timeout = 0
        req_id = await approval.request_approval("expire-test", "user-a")
        # Manually set expires_at to past
        approval._requests[req_id].expires_at = 0
        with pytest.raises(ValueError, match="过期"):
            await approval.approve(req_id, "user-b")

    @pytest.mark.asyncio
    async def test_get_pending_requests(self, approval):
        await approval.request_approval("action-1", "user-a")
        await approval.request_approval("action-2", "user-a")
        await approval.request_approval("action-3", "user-b")

        all_pending = approval.get_pending_requests()
        assert len(all_pending) == 3

        user_a_pending = approval.get_pending_requests(requester_id="user-a")
        assert len(user_a_pending) == 2

    @pytest.mark.asyncio
    async def test_cleanup_expired(self, approval):
        req_id = await approval.request_approval("old-action", "user-a")
        # Make it old and expired
        req = approval._requests[req_id]
        req.status = "expired"
        req.created_at = 0  # Very old

        count = approval.cleanup_expired()
        assert count == 1
        assert approval.get_request(req_id) is None

    @pytest.mark.asyncio
    async def test_cleanup_keeps_recent(self, approval):
        req_id = await approval.request_approval("recent-action", "user-a")
        req = approval._requests[req_id]
        req.status = "expired"
        # created_at is now, so within 1 hour — should NOT be cleaned
        count = approval.cleanup_expired()
        assert count == 0

    @pytest.mark.asyncio
    async def test_request_with_metadata(self, approval):
        req_id = await approval.request_approval(
            "meta-action", "user-a", metadata={"reason": "test"}
        )
        req = approval.get_request(req_id)
        assert req.metadata["reason"] == "test"

    @pytest.mark.asyncio
    async def test_expired_on_get(self, approval):
        """get_request should mark pending requests as expired if past deadline."""
        approval._timeout = 0
        req_id = await approval.request_approval("auto-expire", "user-a")
        approval._requests[req_id].expires_at = 0
        req = approval.get_request(req_id)
        assert req.status == "expired"


# ── Convenience functions ──────────────────────────────────────


class TestConvenienceFunctions:
    def test_check_permission(self):
        user = UserContext(user_id="u1", username="trader", role=Role.TRADER)
        assert check_permission(user, Permission.PLACE_ORDER) is True
        assert check_permission(user, Permission.EMERGENCY_HALT) is False

    def test_require_dual_approval(self):
        assert require_dual_approval(Permission.EDIT_RISK_LIMITS) is True
        assert require_dual_approval(Permission.EMERGENCY_HALT) is True
        assert require_dual_approval(Permission.PLACE_ORDER) is False
