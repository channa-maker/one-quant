"""认证路由 — 登录签发 JWT。

最小实现:单管理员账户(环境变量配置),供机构内部平台起步使用。
后续接入用户表/RBAC 时替换 `_verify_credentials` 即可,签发逻辑不变。

安全要点:
  - 恒定时间比较(secrets.compare_digest)防时序侧信道
  - 默认密码(未配置)时拒绝一切登录,防止裸奔上线
  - 失败统一返回"用户名或密码错误",不区分哪个错
"""

from __future__ import annotations

import logging
import secrets
import time
from typing import Any

import jwt
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from one_quant.infra.config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter()

# 未配置密码时的哨兵值:保持与真实密码比较的恒定时间行为
_UNSET_SENTINEL = "\x00__unset__\x00"


class LoginRequest(BaseModel):
    """登录请求体"""

    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


def _verify_credentials(username: str, password: str) -> bool:
    """校验凭据(恒定时间比较)。

    ADMIN_PASSWORD 未配置时一律拒绝——禁止默认口令上线。
    """
    settings = get_settings()
    expect_user = getattr(settings, "ADMIN_USERNAME", "admin")
    expect_pass = getattr(settings, "ADMIN_PASSWORD", None) or _UNSET_SENTINEL

    user_ok = secrets.compare_digest(username.encode(), str(expect_user).encode())
    pass_ok = secrets.compare_digest(password.encode(), str(expect_pass).encode())
    if expect_pass == _UNSET_SENTINEL:
        # 未配置管理员密码:恒定时间走完比较后仍拒绝
        return False
    return user_ok and pass_ok


@router.post("/login")
async def login(body: LoginRequest) -> JSONResponse:
    """登录并签发 JWT。

    成功:{success: true, data: {access_token, token_type, expires_in, username, role}}
    失败:401,统一文案不泄露细节。
    """
    if not _verify_credentials(body.username, body.password):
        logger.warning("登录失败: username=%s", body.username)
        return JSONResponse(
            status_code=401,
            content={"success": False, "data": None, "error": "用户名或密码错误"},
        )

    settings = get_settings()
    now = int(time.time())
    expires_in = settings.JWT_EXPIRE_MINUTES * 60
    payload: dict[str, Any] = {
        "sub": body.username,
        "role": "owner",
        "iat": now,
        "exp": now + expires_in,
    }
    token = jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    logger.info("登录成功: username=%s", body.username)
    return JSONResponse(
        content={
            "success": True,
            "data": {
                "access_token": token,
                "token_type": "bearer",
                "expires_in": expires_in,
                "username": body.username,
                "role": "owner",
            },
            "error": None,
        }
    )


@router.get("/me")
async def me() -> dict[str, Any]:
    """占位:当前用户信息(需鉴权,中间件已挂 request.state.user)。"""
    return {"success": True, "data": {"role": "owner"}, "error": None}
