"""OKX 交易适配器 — 下单/撤单/持仓/对账"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from datetime import UTC, datetime
from decimal import Decimal

import httpx

from one_quant.core.types import Market, Order, PositionState, Ticker
from one_quant.exchange.contracts import ExchangeAdapter
from one_quant.execution.rate_limiter import RateLimiter
from one_quant.infra.logging import get_logger

logger = get_logger(__name__)

OKX_REST = "https://www.okx.com"


class OKXTradingAdapter(ExchangeAdapter):
    """OKX 交易适配器。

    支持现货 + 合约的下单、撤单、持仓查询。
    """

    name = "okx"
    supported_markets = {Market.SPOT, Market.FUTURES}

    def __init__(
        self,
        api_key: str,
        secret: str,
        passphrase: str,
        testnet: bool = False,
    ) -> None:
        self._api_key = api_key
        self._secret = secret
        self._passphrase = passphrase
        self._base_url = "https://www.okx.com" if not testnet else "https://www.okx.com"
        self._client: httpx.AsyncClient | None = None
        self._limiter = RateLimiter("okx_trading", max_tokens=10, refill_rate=1.0)

    def _sign(self, timestamp: str, method: str, path: str, body: str = "") -> str:
        """OKX API 签名"""
        message = timestamp + method.upper() + path + body
        mac = hmac.new(self._secret.encode(), message.encode(), hashlib.sha256)
        return base64.b64encode(mac.digest()).decode()

    def _headers(self, method: str, path: str, body: str = "") -> dict[str, str]:
        ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        sign = self._sign(ts, method, path, body)
        return {
            "OK-ACCESS-KEY": self._api_key,
            "OK-ACCESS-SIGN": sign,
            "OK-ACCESS-TIMESTAMP": ts,
            "OK-ACCESS-PASSPHRASE": self._passphrase,
            "Content-Type": "application/json",
        }

    async def connect(self) -> None:
        self._client = httpx.AsyncClient(base_url=self._base_url, timeout=10)
        # 验证
        path = "/api/v5/account/balance"
        headers = self._headers("GET", path)
        resp = await self._client.get(path, headers=headers)
        resp.raise_for_status()
        logger.info("OKX 交易接口已连接")

    async def disconnect(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def submit_order(self, order: Order) -> str:
        await self._limiter.acquire()
        path = "/api/v5/trade/order"
        body_dict = {
            "instId": order.symbol.replace("/", "-"),
            "tdMode": "cash",
            "side": order.side,
            "ordType": order.order_type.replace("market", "market").replace("limit", "limit"),
            "sz": str(order.quantity),
            "clOrdId": order.client_order_id,
        }
        if order.price and order.order_type == "limit":
            body_dict["px"] = str(order.price)

        body = json.dumps(body_dict)
        headers = self._headers("POST", path, body)
        resp = await self._client.post(path, content=body, headers=headers)  # type: ignore
        resp.raise_for_status()
        data = resp.json().get("data", [{}])[0]
        exchange_id = data.get("ordId", "")
        logger.info("OKX 下单成功", client_id=order.client_order_id[:8], exchange_id=exchange_id)
        return exchange_id

    async def cancel_order(self, order_id: str, symbol: str) -> bool:
        await self._limiter.acquire()
        path = "/api/v5/trade/cancel-order"
        body = json.dumps({"instId": symbol.replace("/", "-"), "ordId": order_id})
        headers = self._headers("POST", path, body)
        try:
            resp = await self._client.post(path, content=body, headers=headers)  # type: ignore
            resp.raise_for_status()
            return True
        except Exception:
            logger.warning("OKX 撤单失败", order_id=order_id)
            return False

    async def get_positions(self) -> list[PositionState]:
        await self._limiter.acquire()
        path = "/api/v5/account/positions"
        headers = self._headers("GET", path)
        resp = await self._client.get(path, headers=headers)  # type: ignore
        resp.raise_for_status()

        positions = []
        for p in resp.json().get("data", []):
            qty = Decimal(p.get("pos", "0"))
            if qty == 0:
                continue
            positions.append(
                PositionState(
                    symbol=p.get("instId", "").replace("-", "/"),
                    market=Market.FUTURES,
                    side="long" if qty > 0 else "short",
                    quantity=abs(qty),
                    entry_price=Decimal(p.get("avgPx", "0")),
                    unrealized_pnl=Decimal(p.get("upl", "0")),
                    realized_pnl=Decimal("0"),
                    timestamp_ns=time.time_ns(),
                )
            )
        return positions

    async def get_ticker(self, symbol: str) -> Ticker:
        await self._limiter.acquire()
        inst_id = symbol.replace("/", "-")
        resp = await self._client.get("/api/v5/market/ticker", params={"instId": inst_id})
        resp.raise_for_status()
        data = resp.json().get("data", [{}])[0]
        return Ticker(
            symbol=symbol,
            market=Market.SPOT,
            exchange="okx",
            last_price=Decimal(data.get("last", "0")),
            bid=Decimal(data.get("bidPx", "0")),
            ask=Decimal(data.get("askPx", "0")),
            volume_24h=Decimal(data.get("vol24h", "0")),
            timestamp_ns=int(data.get("ts", time.time_ns() * 1_000_000)),
        )
