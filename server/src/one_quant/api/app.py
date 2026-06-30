"""
ONE量化 - FastAPI 应用工厂

创建并配置 FastAPI 应用实例，挂载中间件、路由、异常处理器。
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from one_quant.api.routes import health, orders, positions, strategies
from one_quant.api.ws_hub import ws_router
from one_quant.infra.logging import get_logger

logger = get_logger(__name__)


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

    # 挂载路由
    app.include_router(health.router, tags=["健康检查"])
    app.include_router(orders.router, prefix="/api/v1/orders", tags=["订单"])
    app.include_router(positions.router, prefix="/api/v1/positions", tags=["持仓"])
    app.include_router(strategies.router, prefix="/api/v1/strategies", tags=["策略"])
    app.include_router(ws_router, tags=["WebSocket"])

    return app
