"""
ONE量化 - OKX 交易所适配器

实现 ExchangeAdapter ABC，对接 OKX v5 REST API。
支持现货和合约的下单、撤单、持仓查询。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

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

OKX_API_BASE = "https://www.okx.com"


class OKXAdapter(ExchangeAdapter):
    """OKX 交易所适配器。

    使用 OKX v5 REST API，支持现货和合约。

    Attributes:
        name: 交易所名称。
        supported_markets: 支持的市场类型。
    """

    name = "okx"
    supported_markets = {Market.SPOT, Market.FUTURES, Market.OPTION}

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        passphrase: str,
    ) -> None:
        """初始化 OKX 适配器。

        Args:
            api_key: API Key。
            api_secret: API Secret。
            passphrase: API Passphrase。
        """
        self._api_key = api_key
        self._api_secret = api_secret
        self._passphrase = passphrase
        self._client: httpx.AsyncClient | None = None
        self._rate_limiter = RateLimiter("okx", max_tokens=10, refill_rate=1.0)

    def _sign(self, timestamp: str, method: str, path: str, body: str = "") -> str:
        """生成 OKX 签名。"""
        message = timestamp + method.upper() + path + body
        mac = hmac.new(
            self._api_secret.encode(),
            message.encode(),
            hashlib.sha256,
        )
        return base64.b64encode(mac.digest()).decode()

    def _headers(self, method: str, path: str, body: str = "") -> dict[str, str]:
        """生成认证头。"""
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        sign = self._sign(timestamp, method, path, body)
        return {
            "OK-ACCESS-KEY": self._api_key,
            "OK-ACCESS-SIGN": sign,
            "OK-ACCESS-TIMESTAMP": timestamp,
            "OK-ACCESS-PASSPHRASE": self._passphrase,
            "Content-Type": "application/json",
        }

    async def connect(self) -> None:
        """建立 HTTP 连接。"""
        self._client = httpx.AsyncClient(
            base_url=OKX_API_BASE,
            timeout=10.0,
        )
        logger.info("OKX 适配器已连接")

    async def disconnect(self) -> None:
        """关闭连接。"""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        logger.info("OKX 适配器已断开")

    async def submit_order(self, order: Order) -> str:
        """提交订单到 OKX。

        Args:
            order: 统一订单对象。

        Returns:
            OKX 订单 ID。
        """
        async with self._rate_limiter:
            body = {
                "instId": order.symbol,
                "tdMode": "cash",
                "side": order.side,
                "ordType": order.order_type,
                "sz": str(order.quantity),
                "clOrdId": order.client_order_id,
            }

            if order.price is not None:
                body["px"] = str(order.price)

            body_str = json.dumps(body)
            headers = self._headers("POST", "/api/v5/trade/order", body_str)

            assert self._client is not None
            resp = await self._client.post(
                "/api/v5/trade/order",
                content=body_str,
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()

            if data.get("code") != "0":
                raise Exception(f"OKX 下单失败: {data}")

            order_id = data["data"][0].get("ordId", "")
            logger.info("OKX 下单成功: %s → ordId=%s", order.client_order_id[:8], order_id)
            return order_id

    async def cancel_order(self, order_id: str, symbol: str) -> bool:
        """撤销订单。"""
        async with self._rate_limiter:
            body = {"instId": symbol, "ordId": order_id}
            body_str = json.dumps(body)
            headers = self._headers("POST", "/api/v5/trade/cancel-order", body_str)

            assert self._client is not None
            try:
                resp = await self._client.post(
                    "/api/v5/trade/cancel-order",
                    content=body_str,
                    headers=headers,
                )
                resp.raise_for_status()
                data = resp.json()
                return data.get("code") == "0"
            except Exception as exc:
                logger.warning("OKX 撤单失败: %s - %s", order_id, exc)
                return False

    async def get_positions(self) -> list[PositionState]:
        """查询持仓。"""
        async with self._rate_limiter:
            headers = self._headers("GET", "/api/v5/account/positions")

            assert self._client is not None
            resp = await self._client.get(
                "/api/v5/account/positions",
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()

            positions = []
            for pos in data.get("data", []):
                qty = Decimal(pos.get("pos", "0"))
                if qty == 0:
                    continue
                positions.append(
                    PositionState(
                        symbol=pos["instId"],
                        market=Market.FUTURES,
                        side="long" if qty > 0 else "short",
                        quantity=abs(qty),
                        entry_price=Decimal(pos.get("avgPx", "0")),
                        unrealized_pnl=Decimal(pos.get("upl", "0")),
                        realized_pnl=Decimal("0"),
                        timestamp_ns=time.time_ns(),
                    )
                )

            return positions

    async def get_ticker(self, symbol: str) -> Ticker:
        """查询行情。"""
        async with self._rate_limiter:
            assert self._client is not None
            resp = await self._client.get(
                "/api/v5/market/ticker",
                params={"instId": symbol},
            )
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
                timestamp_ns=int(data.get("ts", "0")) * 1_000_000,
            )
