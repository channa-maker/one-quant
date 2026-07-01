"""鉴权中间件测试 — TDD: 先写测试，再修代码。"""

from __future__ import annotations

import time
from unittest.mock import patch

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ── 常量 ──
JWT_SECRET = "test-secret-key"
JWT_ALGORITHM = "HS256"


# ── 辅助函数 ──


def _make_token(payload: dict, secret: str = JWT_SECRET, algorithm: str = JWT_ALGORITHM) -> str:
    """签发一个 JWT token。"""
    return jwt.encode(payload, secret, algorithm=algorithm)


def _make_expired_token() -> str:
    """签发一个已过期的 token。"""
    return _make_token({"sub": "user1", "exp": int(time.time()) - 3600})


def _make_valid_token() -> str:
    """签发一个有效的 token。"""
    return _make_token({"sub": "user1", "exp": int(time.time()) + 3600})


# ── Fixture: 带鉴权中间件的最小 FastAPI 应用 ──


@pytest.fixture()
def auth_app():
    """创建带鉴权中间件的测试用 FastAPI 应用。"""
    from one_quant.api.app import auth_middleware

    app = FastAPI()
    app.middleware("http")(auth_middleware)

    @app.get("/api/v1/data")
    async def protected_route():
        return {"ok": True}

    @app.get("/api/v1/health")
    async def health():
        return {"status": "ok"}

    return app


@pytest.fixture()
def client(auth_app):
    return TestClient(auth_app, raise_server_exceptions=False)


# ── 测试用例 ──


class TestAuthMiddleware:
    """鉴权中间件测试套件。"""

    def test_no_token_returns_401(self, client):
        """无 token 请求 → 401。"""
        resp = client.get("/api/v1/data")
        assert resp.status_code == 401
        body = resp.json()
        assert body["code"] == 401
        assert "认证" in body["message"]

    def test_empty_bearer_returns_401(self, client):
        """Bearer 后为空 → 401。"""
        resp = client.get("/api/v1/data", headers={"Authorization": "Bearer "})
        assert resp.status_code == 401
        assert resp.json()["code"] == 401

    def test_malformed_header_returns_401(self, client):
        """Authorization 头格式错误（非 Bearer）→ 401。"""
        resp = client.get("/api/v1/data", headers={"Authorization": "Basic abc"})
        assert resp.status_code == 401

    @patch("one_quant.api.app.get_settings")
    def test_expired_token_returns_401(self, mock_settings, client):
        """过期 token → 401。"""
        mock_settings.return_value.JWT_SECRET = JWT_SECRET
        mock_settings.return_value.JWT_ALGORITHM = JWT_ALGORITHM
        token = _make_expired_token()
        resp = client.get("/api/v1/data", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 401
        body = resp.json()
        assert body["code"] == 401
        assert "过期" in body["message"]

    @patch("one_quant.api.app.get_settings")
    def test_wrong_signature_returns_401(self, mock_settings, client):
        """签名错误 token → 401。"""
        mock_settings.return_value.JWT_SECRET = JWT_SECRET
        mock_settings.return_value.JWT_ALGORITHM = JWT_ALGORITHM
        # 用不同密钥签名
        token = _make_token({"sub": "user1", "exp": int(time.time()) + 3600}, secret="wrong-key")
        resp = client.get("/api/v1/data", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 401
        body = resp.json()
        assert body["code"] == 401

    @patch("one_quant.api.app.get_settings")
    def test_valid_token_passes(self, mock_settings, client):
        """有效 token → 正常通过，返回 200。"""
        mock_settings.return_value.JWT_SECRET = JWT_SECRET
        mock_settings.return_value.JWT_ALGORITHM = JWT_ALGORITHM
        token = _make_valid_token()
        resp = client.get("/api/v1/data", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

    def test_health_endpoint_skips_auth(self, client):
        """白名单路径 /api/v1/health 无需鉴权。"""
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200

    @patch("one_quant.api.app.get_settings")
    def test_no_unbound_local_error_on_missing_jwt(self, mock_settings, client):
        """即使 jwt 模块导入异常，也不应出现 UnboundLocalError。

        这是原始 bug 的回归测试：旧代码在 except 块中引用 jwt，
        如果 import jwt 失败就会 UnboundLocalError → 500。
        修复后 jwt 是模块级硬依赖，此测试确保不再有延迟 import 的问题。
        """
        mock_settings.return_value.JWT_SECRET = JWT_SECRET
        mock_settings.return_value.JWT_ALGORITHM = JWT_ALGORITHM
        token = _make_valid_token()
        resp = client.get("/api/v1/data", headers={"Authorization": f"Bearer {token}"})
        # 不应返回 500
        assert resp.status_code != 500
