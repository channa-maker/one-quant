"""
ONE量化 - FastAPI 应用工厂

创建并配置 FastAPI 应用实例，挂载中间件、路由、异常处理器。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from one_quant.api.routes import api_router
from one_quant.api.ws_hub import ws_router
from one_quant.infra.config import get_settings
from one_quant.infra.event_bus import InMemoryEventBus, RedisEventBus
from one_quant.infra.logging import get_logger

logger = get_logger(__name__)

# 全局资源引用，由 lifespan 管理
event_bus_instance: InMemoryEventBus | RedisEventBus | None = None
db_engine: Any | None = None


# ──────────── 鉴权中间件 ────────────


async def auth_middleware(request: Request, call_next):
    """JWT 鉴权中间件。

    白名单路径（如健康检查、文档）直接放行；
    其余路径必须携带合法 Bearer Token。
    """
    # 白名单路径，无需鉴权
    whitelist = {"/docs", "/openapi.json", "/redoc"}
    if request.url.path in whitelist or request.url.path.startswith("/api/v1/health"):
        return await call_next(request)

    # 提取 Authorization 头
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return JSONResponse(
            status_code=401,
            content={"code": 401, "message": "未提供认证凭据"},
        )

    token = auth_header.removeprefix("Bearer ").strip()
    if not token:
        return JSONResponse(
            status_code=401,
            content={"code": 401, "message": "认证凭据为空"},
        )

    # JWT 验证
    try:
        import jwt

        settings = get_settings()
        payload = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
        )
        # 将解析出的用户信息挂到 request.state 供下游使用
        request.state.user = payload
    except jwt.ExpiredSignatureError:
        return JSONResponse(
            status_code=401,
            content={"code": 401, "message": "认证凭据已过期"},
        )
    except jwt.InvalidTokenError:
        return JSONResponse(
            status_code=401,
            content={"code": 401, "message": "无效的认证凭据"},
        )

    return await call_next(request)


# ──────────── 生命周期管理 ────────────


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """应用生命周期管理。

    启动时初始化 EventBus、数据库连接池等；
    关闭时优雅释放资源。
    """
    global event_bus_instance, db_engine

    settings = get_settings()

    # ── 初始化 EventBus ──
    logger.info("初始化 EventBus...")
    if settings.ENV == "prod":
        # 生产环境使用 Redis 事件总线
        event_bus_instance = RedisEventBus(
            redis_url=settings.redis.REDIS_URL,
            max_queue_size=10_000,
        )
    else:
        # 开发/测试环境使用内存事件总线
        event_bus_instance = InMemoryEventBus(max_queue_size=10_000)
    await event_bus_instance.start()
    logger.info("EventBus 已启动 (%s)", type(event_bus_instance).__name__)

    # ── 初始化数据库连接池 ──
    logger.info("初始化数据库连接池...")
    try:
        import sqlalchemy as sa
        from sqlalchemy.ext.asyncio import create_async_engine

        db_engine = create_async_engine(
            settings.database.DATABASE_URL,
            pool_size=10,
            max_overflow=20,
            pool_recycle=3600,
            echo=settings.DEBUG,
        )
        # 验证连接可用
        async with db_engine.connect() as conn:
            await conn.execute(sa.text("SELECT 1"))
        logger.info("数据库连接池已初始化")
    except Exception as exc:
        logger.warning("数据库连接池初始化失败（降级为无数据库模式）: %s", exc)
        db_engine = None

    # ── 初始化健康检查器 ──
    logger.info("初始化健康检查器...")
    from one_quant.api.routes.health import init_health_checker

    init_health_checker(
        db_engine=db_engine,
        event_bus=event_bus_instance,
    )

    # 将资源挂到 app.state 供路由使用
    app.state.event_bus = event_bus_instance
    app.state.db_engine = db_engine

    logger.info("ONE量化 API 启动完成")
    yield

    # ── 释放资源 ──
    logger.info("ONE量化 API 关闭中...")

    # 关闭数据库连接池
    if db_engine is not None:
        logger.info("关闭数据库连接池...")
        await db_engine.dispose()
        db_engine = None

    # 停止 EventBus
    if event_bus_instance is not None:
        logger.info("停止 EventBus...")
        await event_bus_instance.stop()
        event_bus_instance = None

    logger.info("ONE量化 API 已关闭")


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

    # 鉴权中间件
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
