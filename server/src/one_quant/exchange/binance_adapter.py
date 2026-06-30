"""
ONE量化 - 币安交易所适配器

实现 ExchangeAdapter ABC，对接币安 REST API。
支持现货和合约（U本位）的下单、撤单、持仓查询。
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import time
from decimal import Decimal
from typing import Any
from urllib.parse import urlencode

import httpx

from one_quant.core.types import (
    Market,
    Order,
    PositionState,
    Ticker,
)
from one_quant.exchange.contracts import ExchangeAdapter
from one_quant.execution.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

# 币安 API 基础地址
BINANCE_API_BASE = "https://api.binance.com"
BINANCE_FUTURES_API_BASE = "https://fapi.binance.com"


class BinanceAdapter(ExchangeAdapter):
    """币安交易所适配器。

    支持现货和 U 本位合约的下单、撤单、持仓查询。
    内置客户端限流，防止 API 调用超限。

    Attributes:
        name: 交易所名称。
        supported_markets: 支持的市场类型。
    """

    name = "binance"
    supported_markets = {Market.SPOT, Market.FUTURES}

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        is_futures: bool = False,
    ) -> None:
        """初始化币安适配器。

        Args:
            api_key: API Key。
            api_secret: API Secret。
            is_futures: 是否使用合约 API。
        """
        self._api_key = api_key
        self._api_secret = api_secret
        self._base_url = BINANCE_FUTURES_API_BASE if is_futures else BINANCE_API_BASE
        self._is_futures = is_futures
        self._client: httpx.AsyncClient | None = None
        self._rate_limiter = RateLimiter("binance", max_tokens=10, refill_rate=1.0)

    async def connect(self) -> None:
        """建立 HTTP 连接。"""
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=10.0,
            headers={"X-MBX-APIKEY": self._api_key},
        )
        logger.info("币安适配器已连接: %s", self._base_url)

    async def disconnect(self) -> None:
        """关闭 HTTP 连接。"""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        logger.info("币安适配器已断开")

    def _sign(self, params: dict[str, Any]) -> dict[str, Any]:
        """生成签名。

        Args:
            params: 请求参数。

        Returns:
            带签名的请求参数。
        """
        params["timestamp"] = int(time.time() * 1000)
        query = urlencode(params)
        signature = hmac.new(
            self._api_secret.encode(),
            query.encode(),
            hashlib.sha256,
        ).hexdigest()
        params["signature"] = signature
        return params

    async def submit_order(self, order: Order) -> str:
        """提交订单到币安。

        Args:
            order: 统一订单对象。

        Returns:
            币安订单 ID（字符串）。

        Raises:
            Exception: 下单失败。
        """
        async with self._rate_limiter:
            params: dict[str, Any] = {
                "symbol": order.symbol,
                "side": order.side.upper(),
                "type": order.order_type.upper(),
                "quantity": str(order.quantity),
                "newClientOrderId": order.client_order_id,
            }

            if order.order_type == "limit":
                if order.price is None:
                    raise ValueError("限价单必须指定价格")
                params["price"] = str(order.price)
                params["timeInForce"] = "GTC"
            elif order.order_type in ("stop_limit", "stop_market"):
                if order.stop_price is not None:
                    params["stopPrice"] = str(order.stop_price)

            params = self._sign(params)

            assert self._client is not None
            resp = await self._client.post("/api/v3/order", params=params)
            resp.raise_for_status()
            data = resp.json()

            order_id = str(data.get("orderId", ""))
            logger.info("币安下单成功: %s → orderId=%s", order.client_order_id[:8], order_id)
            return order_id

    async def cancel_order(self, order_id: str, symbol: str) -> bool:
        """撤销订单。

        Args:
            order_id: 币安订单 ID。
            symbol: 标的符号。

        Returns:
            是否成功撤销。
        """
        async with self._rate_limiter:
            params = self._sign({"symbol": symbol, "orderId": order_id})

            assert self._client is not None
            try:
                resp = await self._client.delete("/api/v3/order", params=params)
                resp.raise_for_status()
                logger.info("币安撤单成功: %s", order_id)
                return True
            except Exception as exc:
                logger.warning("币安撤单失败: %s - %s", order_id, exc)
                return False

    async def get_positions(self) -> list[PositionState]:
        """查询当前持仓。

        Returns:
            持仓列表。
        """
        if not self._is_futures:
            # 现货无持仓概念，返回空
            return []

        async with self._rate_limiter:
            params = self._sign({})

            assert self._client is not None
            resp = await self._client.get("/fapi/v2/positionRisk", params=params)
            resp.raise_for_status()
            data = resp.json()

            positions = []
            for pos in data:
                qty = Decimal(pos.get("positionAmt", "0"))
                if qty == 0:
                    continue
                positions.append(
                    PositionState(
                        symbol=pos["symbol"],
                        market=Market.FUTURES,
                        side="long" if qty > 0 else "short",
                        quantity=abs(qty),
                        entry_price=Decimal(pos.get("entryPrice", "0")),
                        unrealized_pnl=Decimal(pos.get("unRealizedProfit", "0")),
                        realized_pnl=Decimal("0"),
                        timestamp_ns=time.time_ns(),
                    )
                )

            return positions

    async def get_ticker(self, symbol: str) -> Ticker:
        """查询最新行情。

        Args:
            symbol: 标的符号。

        Returns:
            行情快照。
        """
        async with self._rate_limiter:
            assert self._client is not None
            resp = await self._client.get(
                "/api/v3/ticker/bookTicker",
                params={"symbol": symbol},
            )
            resp.raise_for_status()
            data = resp.json()

            return Ticker(
                symbol=symbol,
                market=Market.SPOT,
                exchange="binance",
                last_price=Decimal(data.get("bidPrice", "0")),  # 近似
                bid=Decimal(data.get("bidPrice", "0")),
                ask=Decimal(data.get("askPrice", "0")),
                volume_24h=Decimal("0"),  # bookTicker 无成交量
                timestamp_ns=time.time_ns(),
            )
