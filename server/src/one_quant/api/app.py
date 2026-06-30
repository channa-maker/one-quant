"""
ONE量化 - FastAPI 应用工厂

创建并配置 FastAPI 应用实例，挂载中间件、路由、异常处理器。
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from one_quant.api.routes import api_router
from one_quant.api.ws_hub import ws_router
from one_quant.infra.logging import get_logger

logger = get_logger(__name__)


# ──────────── 鉴权中间件骨架 ────────────


async def auth_middleware(request: Request, call_next):
    """鉴权中间件（骨架）。

    当前为透传模式，后续可接入 JWT / API Key 等验证逻辑。
    白名单路径（如健康检查、文档）直接放行。
    """
    # 白名单路径，无需鉴权
    whitelist = {"/docs", "/openapi.json", "/redoc"}
    if request.url.path in whitelist or request.url.path.startswith("/api/v1/health"):
        return await call_next(request)

    # TODO: 接入实际鉴权逻辑（JWT、API Key 等）
    # token = request.headers.get("Authorization")
    # if not token:
    #     return JSONResponse(status_code=401, content={"detail": "未提供认证凭据"})

    return await call_next(request)


# ──────────── 生命周期管理 ────────────


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """应用生命周期管理。

    启动时初始化 EventBus、注册表等；关闭时优雅释放资源。
    """
    logger.info("ONE量化 API 启动中...")
    # TODO: 初始化 EventBus、数据库连接池等
    yield
    logger.info("ONE量化 API 关闭中...")
    # TODO: 释放资源


# ──────────── 应用工厂 ────────────


def create_app() -> FastAPI:
    """创建 FastAPI 应用实例。

    Returns:
        配置完成的 FastAPI 应用。
    """
    app = FastAPI(
        title="ONE量化",
        description="机构级智能量化交易系统 API",
        version="0.1.0",
        docs_url="/docs",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # CORS 中间件
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # 生产环境应限制
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 鉴权中间件（骨架）
    app.middleware("http")(auth_middleware)

    # 全中文异常处理
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        """全局异常处理器，返回中文错误信息。"""
        logger.exception("未捕获异常: %s", exc)
        return JSONResponse(
            status_code=500,
            content={
                "code": 500,
                "message": "服务器内部错误，请稍后重试",
                "detail": str(exc),
            },
        )

    @app.exception_handler(404)
    async def not_found_handler(request: Request, exc):
        """404 异常处理器。"""
        return JSONResponse(
            status_code=404,
            content={
                "code": 404,
                "message": "请求的资源不存在",
            },
        )

    @app.exception_handler(422)
    async def validation_handler(request: Request, exc):
        """参数校验异常处理器。"""
        return JSONResponse(
            status_code=422,
            content={
                "code": 422,
                "message": "请求参数校验失败",
                "detail": str(exc),
            },
        )

    # 挂载路由
    app.include_router(api_router, prefix="/api/v1")
    app.include_router(ws_router, tags=["WebSocket"])

    return app
