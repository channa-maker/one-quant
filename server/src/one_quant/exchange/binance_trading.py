"""币安交易适配器 — 下单/撤单/持仓/对账"""

from __future__ import annotations

import hashlib
import hmac
import time
import urllib.parse
from decimal import Decimal
from typing import Any

import httpx

from one_quant.core.types import Market, Order, PositionState, Ticker
from one_quant.exchange.contracts import ExchangeAdapter
from one_quant.execution.rate_limiter import RateLimiter
from one_quant.infra.logging import get_logger

logger = get_logger(__name__)

BINANCE_REST = "https://api.binance.com"
BINANCE_FUTURES_REST = "https://fapi.binance.com"


class BinanceTradingAdapter(ExchangeAdapter):
    """币安交易适配器。

    支持现货 + 合约的下单、撤单、持仓查询、对账。
    所有 API 调用经过限流器。
    """

    name = "binance"
    supported_markets = {Market.SPOT, Market.FUTURES}

    def __init__(
        self,
        api_key: str,
        secret: str,
        testnet: bool = False,
    ) -> None:
        self._api_key = api_key
        self._secret = secret
        self._testnet = testnet
        self._base_url = BINANCE_REST if not testnet else "https://testnet.binance.vision"
        self._futures_url = BINANCE_FUTURES_REST
        self._client: httpx.AsyncClient | None = None
        self._limiter = RateLimiter("binance_trading", max_tokens=10, refill_rate=1.0)

    async def connect(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=10,
            headers={"X-MBX-APIKEY": self._api_key},
        )
        # 验证连接
        resp = await self._client.get("/api/v3/account")
        resp.raise_for_status()
        logger.info("币安交易接口已连接", testnet=self._testnet)

    async def disconnect(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    def _sign(self, params: dict[str, Any]) -> dict[str, Any]:
        """签名请求"""
        params["timestamp"] = int(time.time() * 1000)
        query = urllib.parse.urlencode(params)
        signature = hmac.new(self._secret.encode(), query.encode(), hashlib.sha256).hexdigest()
        params["signature"] = signature
        return params

    async def submit_order(self, order: Order) -> str:
        await self._limiter.acquire()
        params: dict[str, Any] = {
            "symbol": order.symbol.replace("/", "").upper(),
            "side": order.side.upper(),
            "type": order.order_type.upper(),
            "quantity": str(order.quantity),
        }
        if order.price and order.order_type == "limit":
            params["price"] = str(order.price)
            params["timeInForce"] = "GTC"
        if order.stop_price:
            params["stopPrice"] = str(order.stop_price)
        params["newClientOrderId"] = order.client_order_id

        params = self._sign(params)
        resp = await self._client.post("/api/v3/order", params=params)  # type: ignore
        resp.raise_for_status()
        data = resp.json()
        exchange_id = str(data.get("orderId", ""))
        logger.info("币安下单成功", client_id=order.client_order_id[:8], exchange_id=exchange_id)
        return exchange_id

    async def cancel_order(self, order_id: str, symbol: str) -> bool:
        await self._limiter.acquire()
        params = self._sign(
            {
                "symbol": symbol.replace("/", "").upper(),
                "orderId": order_id,
            }
        )
        try:
            resp = await self._client.delete("/api/v3/order", params=params)  # type: ignore
            resp.raise_for_status()
            return True
        except Exception:
            logger.warning("币安撤单失败", order_id=order_id)
            return False

    async def get_positions(self) -> list[PositionState]:
        await self._limiter.acquire()
        params = self._sign({})
        resp = await self._client.get("/api/v3/account", params=params)  # type: ignore
        resp.raise_for_status()
        balances = resp.json().get("balances", [])

        positions = []
        for b in balances:
            free = Decimal(b.get("free", "0"))
            locked = Decimal(b.get("locked", "0"))
            total = free + locked
            if total > 0:
                positions.append(
                    PositionState(
                        symbol=b["asset"],
                        market=Market.SPOT,
                        side="long",
                        quantity=total,
                        entry_price=Decimal("0"),
                        unrealized_pnl=Decimal("0"),
                        realized_pnl=Decimal("0"),
                        timestamp_ns=time.time_ns(),
                    )
                )
        return positions

    async def get_ticker(self, symbol: str) -> Ticker:
        await self._limiter.acquire()
        resp = await self._client.get(
            "/api/v3/ticker/24hr",
            params={"symbol": symbol.replace("/", "").upper()},
        )
        resp.raise_for_status()
        data = resp.json()
        return Ticker(
            symbol=symbol,
            market=Market.SPOT,
            exchange="binance",
            last_price=Decimal(data["lastPrice"]),
            bid=Decimal(data.get("bidPrice", "0")),
            ask=Decimal(data.get("askPrice", "0")),
            volume_24h=Decimal(data["volume"]),
            timestamp_ns=time.time_ns(),
        )
