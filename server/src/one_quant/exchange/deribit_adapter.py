"""
Deribit 期权适配器 — 加密期权主力流动性

对接 Deribit API v2，支持：
  - BTC/ETH 期权下单/撤单
  - 期权持仓查询（含 Greeks）
  - 期权行情（IV、Greeks、盘口）
  - 期权链查询

能力声明：
  - 支持市场: OPTION
  - 支持订单: limit, market
  - 特性: 组合保证金, 实时 Greeks

注意：此为骨架实现，实际 Deribit API 调用需要 deribit 库或 HTTP 封装。
"""

from __future__ import annotations

import time
from decimal import Decimal
from typing import Any

import httpx

from one_quant.core.types import (
    Instrument,
    InstrumentType,
    Market,
    Order,
    PositionState,
    Ticker,
)
from one_quant.exchange.unified_broker import UnifiedBroker
from one_quant.infra.logging import get_logger

logger = get_logger(__name__)

# Deribit API 基础地址
DERIBIT_API_BASE = "https://www.deribit.com/api/v2"
DERIBIT_TEST_API_BASE = "https://test.deribit.com/api/v2"


class DeribitAdapter(UnifiedBroker):
    """Deribit 适配器 — 加密期权主力流动性

    对接 Deribit API v2，支持 BTC/ETH 期权交易。

    能力声明：
    - 支持市场: OPTION
    - 支持订单: limit, market
    - 特性: 组合保证金, 实时 Greeks

    使用方式::

        adapter = DeribitAdapter(client_id="xxx", client_secret="yyy")
        await adapter.connect()

        # 下单
        order = Order(...)
        order_id = await adapter.submit_order(order)

        # 查询持仓（含 Greeks）
        positions = await adapter.get_positions()
    """

    name = "deribit"
    supported_markets = {Market.OPTION}

    def __init__(
        self,
        client_id: str = "",
        client_secret: str = "",
        is_test: bool = False,
    ) -> None:
        """初始化 Deribit 适配器

        Args:
            client_id: Deribit API client_id
            client_secret: Deribit API client_secret
            is_test: 是否使用测试网
        """
        self._client_id = client_id
        self._client_secret = client_secret
        self._base_url = DERIBIT_TEST_API_BASE if is_test else DERIBIT_API_BASE
        self._is_test = is_test

        self._connected = False
        self._client: httpx.AsyncClient | None = None
        self._access_token: str | None = None
        self._refresh_token: str | None = None

    # ── 连接管理 ──────────────────────────────────────────────────

    async def connect(self) -> None:
        """建立与 Deribit API 的连接并完成鉴权

        Raises:
            ConnectionError: 连接或鉴权失败
        """
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=15.0,
        )

        # 获取 access_token
        if self._client_id and self._client_secret:
            await self._authenticate()
        else:
            logger.warning("Deribit 未提供凭证，仅限公开 API")

        self._connected = True
        logger.info(
            "Deribit 已连接: %s (test=%s)",
            self._base_url,
            self._is_test,
        )

    async def disconnect(self) -> None:
        """断开连接"""
        if self._access_token:
            await self._logout()
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        self._connected = False
        self._access_token = None
        self._refresh_token = None
        logger.info("Deribit 已断开")

    async def _authenticate(self) -> None:
        """OAuth2 鉴权"""
        assert self._client is not None
        resp = await self._client.post(
            "/public/auth",
            json={
                "grant_type": "client_credentials",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
            },
        )
        resp.raise_for_status()
        data = resp.json().get("result", {})
        self._access_token = data.get("access_token")
        self._refresh_token = data.get("refresh_token")
        logger.info("Deribit 鉴权成功")

    async def _logout(self) -> None:
        """注销"""
        assert self._client is not None
        try:
            await self._client.get(
                "/private/logout",
                headers=self._auth_headers(),
            )
        except Exception:
            pass

    def _auth_headers(self) -> dict[str, str]:
        """构建鉴权头"""
        if self._access_token:
            return {"Authorization": f"Bearer {self._access_token}"}
        return {}

    # ── 订单操作 ──────────────────────────────────────────────────

    async def submit_order(self, order: Order) -> str:
        """提交期权订单到 Deribit

        Args:
            order: 统一订单对象

        Returns:
            Deribit 订单 ID

        Raises:
            RuntimeError: 未连接
            ValueError: 不支持的订单类型
        """
        self._ensure_connected()

        # 映射订单类型
        if order.order_type == "market":
            order_type = "market"
        elif order.order_type == "limit":
            order_type = "limit"
        else:
            raise ValueError(f"Deribit 不支持的订单类型: {order.order_type}")

        # Deribit 使用 instrument_name 格式: BTC-30JUN24-70000-C
        instrument_name = self._normalize_instrument_name(order.symbol)

        params: dict[str, Any] = {
            "instrument_name": instrument_name,
            "amount": str(order.quantity),
            "type": order_type,
            "direction": "buy" if order.side == "buy" else "sell",
        }

        if order.order_type == "limit" and order.price is not None:
            params["price"] = str(order.price)

        result = await self._private_post(
            "private/buy" if order.side == "buy" else "private/sell", params
        )

        order_id = str(result.get("order", {}).get("order_id", ""))
        logger.info(
            "Deribit 下单成功: %s %s %s → orderId=%s",
            order.side,
            order.quantity,
            instrument_name,
            order_id,
        )
        return order_id

    async def cancel_order(self, order_id: str, symbol: str) -> bool:
        """撤销 Deribit 订单

        Args:
            order_id: Deribit 订单ID
            symbol: 标的符号

        Returns:
            是否成功撤销
        """
        self._ensure_connected()

        try:
            await self._private_post(
                "private/cancel",
                {"order_id": order_id},
            )
            logger.info("Deribit 撤单成功: %s", order_id)
            return True
        except Exception as exc:
            logger.warning("Deribit 撤单失败: %s - %s", order_id, exc)
            return False

    # ── 持仓与资金 ────────────────────────────────────────────────

    async def get_positions(self) -> list[PositionState]:
        """查询当前所有期权持仓

        Returns:
            持仓状态列表（含 Greeks）
        """
        self._ensure_connected()

        result = await self._private_get(
            "private/get_positions",
            {"kind": "option"},
        )

        positions = []
        for pos in result:
            qty = Decimal(str(pos.get("size", 0)))
            if qty == 0:
                continue

            direction = pos.get("direction", "buy")
            side = "long" if direction == "buy" else "short"

            positions.append(
                PositionState(
                    symbol=pos.get("instrument_name", ""),
                    market=Market.OPTION,
                    side=side if side in ("long", "short", "flat") else "flat",  # type: ignore[arg-type]
                    quantity=abs(qty),
                    entry_price=Decimal(str(pos.get("average_price", 0))),
                    unrealized_pnl=Decimal(str(pos.get("floating_profit_loss", 0))),
                    realized_pnl=Decimal(str(pos.get("realized_profit_loss", 0))),
                    timestamp_ns=time.time_ns(),
                )
            )

        return positions

    async def get_balance(self) -> dict[str, Decimal]:
        """查询资金余额

        Returns:
            币种 -> 余额 的映射
        """
        self._ensure_connected()

        result = await self._private_get(
            "private/get_account_summary",
            {"currency": "BTC"},
        )

        balances: dict[str, Decimal] = {}
        if result:
            balances["BTC"] = Decimal(str(result.get("balance", 0)))
            balances["BTC_equity"] = Decimal(str(result.get("equity", 0)))
            balances["BTC_available"] = Decimal(str(result.get("available_funds", 0)))
            balances["BTC_margin"] = Decimal(str(result.get("margin_balance", 0)))

        # 也查询 ETH
        result_eth = await self._private_get(
            "private/get_account_summary",
            {"currency": "ETH"},
        )
        if result_eth:
            balances["ETH"] = Decimal(str(result_eth.get("balance", 0)))
            balances["ETH_equity"] = Decimal(str(result_eth.get("equity", 0)))

        return balances

    async def get_ticker(self, symbol: str) -> Ticker:
        """查询期权最新行情

        Args:
            symbol: 标的符号（Deribit instrument_name 格式）

        Returns:
            最新行情快照
        """
        self._ensure_connected()

        instrument_name = self._normalize_instrument_name(symbol)
        result = await self._public_get(
            "public/ticker",
            {"instrument_name": instrument_name},
        )

        return Ticker(
            symbol=instrument_name,
            market=Market.OPTION,
            exchange="deribit",
            last_price=Decimal(str(result.get("last_price", 0))),
            bid=Decimal(str(result.get("best_bid_price", 0))),
            ask=Decimal(str(result.get("best_ask_price", 0))),
            volume_24h=Decimal(str(result.get("stats", {}).get("volume", 0))),
            timestamp_ns=time.time_ns(),
        )

    # ── 跨市场扩展接口 ────────────────────────────────────────────

    async def search_instrument(self, query: str) -> list[Instrument]:
        """搜索期权标的

        Args:
            query: 搜索关键词（如 "BTC", "ETH-30JUN24"）

        Returns:
            匹配的期权标的列表
        """
        self._ensure_connected()

        # 获取所有可用期权
        currency = query.split("-")[0].upper() if "-" in query else query.upper()
        result = await self._public_get(
            "public/get_instruments",
            {"currency": currency, "kind": "option", "expired": False},
        )

        instruments = []
        for item in (result or [])[:50]:  # 限制返回数量
            name = item.get("instrument_name", "")
            # 简单匹配
            if query.upper() not in name.upper():
                continue

            instruments.append(
                Instrument(
                    internal_id=f"deribit_{name}",
                    symbol=name,
                    market=Market.OPTION,
                    instrument_type=InstrumentType.OPTION,
                    exchange="deribit",
                    base_currency=item.get("base_currency", ""),
                    quote_currency="USD",
                    tick_size=Decimal(str(item.get("tick_size", 0.0001))),
                    lot_size=Decimal(str(item.get("contract_size", 1))),
                    contract_multiplier=Decimal(str(item.get("contract_size", 1))),
                    is_active=True,
                )
            )

        return instruments

    async def get_unified_positions(self) -> list[dict[str, Any]]:
        """统一持仓视图（含期权 Greeks）

        Returns:
            统一持仓信息列表
        """
        positions = await self.get_positions()

        # 获取期权持仓的 Greeks
        result = []
        for pos in positions:
            greeks: dict[str, str] = {}
            try:
                ticker_data = await self._public_get(
                    "public/ticker",
                    {"instrument_name": pos.symbol},
                )
                if ticker_data:
                    greeks = {
                        "delta": str(ticker_data.get("greeks", {}).get("delta", 0)),
                        "gamma": str(ticker_data.get("greeks", {}).get("gamma", 0)),
                        "theta": str(ticker_data.get("greeks", {}).get("theta", 0)),
                        "vega": str(ticker_data.get("greeks", {}).get("vega", 0)),
                        "iv": str(ticker_data.get("mark_iv", 0)),
                    }
            except Exception:
                pass

            entry = pos.entry_price * pos.quantity
            result.append(
                {
                    "symbol": pos.symbol,
                    "market": Market.OPTION.value,
                    "side": pos.side,
                    "quantity": str(pos.quantity),
                    "entry_price": str(pos.entry_price),
                    "market_value": str(entry),
                    "net_exposure": str(entry * (Decimal(str(greeks.get("delta", "0"))))),
                    "unrealized_pnl": str(pos.unrealized_pnl),
                    "margin_required": "0",  # 需查询 account_summary
                    "greeks": greeks,
                }
            )

        return result

    async def get_unified_balance(self) -> dict[str, Any]:
        """统一资金视图（多币种 NAV 合并）

        Returns:
            统一资金信息
        """
        balance = await self.get_balance()

        # 将 BTC/ETH 合并为 USD 等值（需要实时价格，这里简化）
        total_btc = balance.get("BTC_equity", Decimal("0"))
        total_eth = balance.get("ETH_equity", Decimal("0"))

        return {
            "total_nav_usd": str(total_btc + total_eth),  # 简化，需乘以价格
            "available_cash": str(balance.get("BTC_available", Decimal("0"))),
            "margin_used": str(balance.get("BTC_margin", Decimal("0"))),
            "balances": {k: str(v) for k, v in balance.items()},
        }

    # ── 内部方法 ──────────────────────────────────────────────────

    def _ensure_connected(self) -> None:
        """确保已连接"""
        if not self._connected or self._client is None:
            raise RuntimeError("Deribit 未连接，请先调用 connect()")

    async def _public_get(self, path: str, params: dict[str, Any]) -> Any:
        """发送公开 API GET 请求"""
        assert self._client is not None
        resp = await self._client.get(f"/{path}", params=params)
        resp.raise_for_status()
        return resp.json().get("result")

    async def _private_get(self, path: str, params: dict[str, Any]) -> Any:
        """发送私有 API GET 请求"""
        assert self._client is not None
        resp = await self._client.get(
            f"/{path}",
            params=params,
            headers=self._auth_headers(),
        )
        resp.raise_for_status()
        return resp.json().get("result")

    async def _private_post(self, path: str, params: dict[str, Any]) -> Any:
        """发送私有 API POST 请求"""
        assert self._client is not None
        resp = await self._client.post(
            f"/{path}",
            json=params,
            headers=self._auth_headers(),
        )
        resp.raise_for_status()
        return resp.json().get("result")

    @staticmethod
    def _normalize_instrument_name(symbol: str) -> str:
        """标准化 Deribit 期权合约名称

        Deribit 格式: BTC-30JUN24-70000-C
        """
        # 如果已经是标准格式，直接返回
        if "-" in symbol and len(symbol.split("-")) >= 4:
            return symbol.upper()
        # 否则原样返回
        return symbol
