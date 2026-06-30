"""
ONE量化 - 订单路由

提供订单提交、查询、撤销接口。所有写接口需鉴权（TODO: 接入认证中间件）。
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from one_quant.core.types import Market

router = APIRouter()


# ──────────────────── 请求/响应模型 ────────────────────


class SubmitOrderRequest(BaseModel):
    """提交订单请求"""

    symbol: str = Field(description="标的符号")
    market: Market = Field(description="市场类型")
    side: Literal["buy", "sell"] = Field(description="买卖方向")
    order_type: Literal["limit", "market", "stop_limit", "stop_market"] = Field(
        description="订单类型"
    )
    quantity: Decimal = Field(gt=0, description="委托数量")
    price: Decimal | None = Field(default=None, description="委托价格（市价单可不填）")
    stop_price: Decimal | None = Field(default=None, description="触发价格")
    exchange: str = Field(description="交易所名称")


class OrderResponse(BaseModel):
    """订单响应"""

    client_order_id: str
    symbol: str
    market: Market
    side: str
    order_type: str
    quantity: Decimal
    price: Decimal | None
    status: str
    exchange: str


# ──────────────────── 路由 ────────────────────


@router.post("/", response_model=dict[str, Any])
async def submit_order(req: SubmitOrderRequest) -> dict[str, Any]:
    """提交订单。

    订单经过四层风控检查后提交到交易所。
    """
    # TODO: 接入 OMS + 风控引擎
    raise HTTPException(status_code=501, detail="订单提交功能尚未实现")


@router.get("/{order_id}", response_model=dict[str, Any])
async def get_order(order_id: str) -> dict[str, Any]:
    """查询订单状态。"""
    # TODO: 从 OMS 查询
    raise HTTPException(status_code=501, detail="订单查询功能尚未实现")


@router.delete("/{order_id}", response_model=dict[str, Any])
async def cancel_order(order_id: str) -> dict[str, Any]:
    """撤销订单。"""
    # TODO: 接入 OMS 撤单
    raise HTTPException(status_code=501, detail="订单撤销功能尚未实现")
