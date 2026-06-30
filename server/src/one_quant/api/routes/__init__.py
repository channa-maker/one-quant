"""API 路由注册"""

from fastapi import APIRouter
from one_quant.api.routes.health import router as health_router
from one_quant.api.routes.orders import router as orders_router
from one_quant.api.routes.positions import router as positions_router
from one_quant.api.routes.strategies import router as strategies_router

api_router = APIRouter()
api_router.include_router(health_router, prefix="/health", tags=["健康检查"])
api_router.include_router(orders_router, prefix="/orders", tags=["订单"])
api_router.include_router(positions_router, prefix="/positions", tags=["持仓"])
api_router.include_router(strategies_router, prefix="/strategies", tags=["策略"])
