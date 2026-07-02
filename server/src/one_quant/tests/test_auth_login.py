"""登录端点测试:签发/拒绝/白名单。"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from one_quant.api.app import create_app
from one_quant.infra.config import get_settings


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> AsyncClient:
    monkeypatch.setenv("ONE_ADMIN_PASSWORD", "test-pass-123")
    get_settings.cache_clear()
    app = create_app()
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


class TestLogin:
    @pytest.mark.asyncio
    async def test_login_success_returns_token(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/v1/auth/login", json={"username": "admin", "password": "test-pass-123"}
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["access_token"]
        assert data["token_type"] == "bearer"

    @pytest.mark.asyncio
    async def test_login_wrong_password_401(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/v1/auth/login", json={"username": "admin", "password": "wrong"}
        )
        assert resp.status_code == 401
        assert resp.json()["error"] == "用户名或密码错误"

    @pytest.mark.asyncio
    async def test_login_no_password_configured_rejects(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("ONE_ADMIN_PASSWORD", raising=False)
        get_settings.cache_clear()
        app = create_app()
        c = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
        resp = await c.post(
            "/api/v1/auth/login", json={"username": "admin", "password": "anything"}
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_token_grants_access(self, client: AsyncClient) -> None:
        login = await client.post(
            "/api/v1/auth/login", json={"username": "admin", "password": "test-pass-123"}
        )
        token = login.json()["data"]["access_token"]
        resp = await client.get("/api/v1/positions/", headers={"Authorization": f"Bearer {token}"})
        # 鉴权通过即非 401(业务依赖不可用时可能 503,不属于鉴权范畴)
        assert resp.status_code != 401
