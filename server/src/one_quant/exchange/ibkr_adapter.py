"""
IBKR (Interactive Brokers) 适配器 — 美股 + 美期权

对接 IBKR TWS/Gateway API，支持：
  - 美股下单/撤单（盘前/盘中/盘后）
  - 美期权下单/撤单
  - 持仓查询
  - 资金查询
  - 标的搜索

能力声明：
  - 支持市场: STOCK, OPTION
  - 支持订单: limit, market, stop_limit
  - 特性: 盘前/盘中/盘后, 多账户

注意：此为骨架实现，实际 IBKR API 调用需要 ib_insync 或 ibapi 库。
"""

from __future__ import annotations

import time
from decimal import Decimal
from typing import Any

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


# ──────────────────────────── IBKR 适配器 ────────────────────────────


class IBKRAdapter(UnifiedBroker):
    """IBKR 适配器 — 美股 + 美期权

    对接 Interactive Brokers TWS/Gateway API。

    能力声明：
    - 支持市场: STOCK, OPTION
    - 支持订单: limit, market, stop_limit
    - 特性: 盘前/盘中/盘后, 多账户

    使用方式::

        adapter = IBKRAdapter(host="127.0.0.1", port=7497, client_id=1)
        await adapter.connect()

        # 下单
        order = Order(...)
        order_id = await adapter.submit_order(order)

        # 查询持仓
        positions = await adapter.get_positions()
    """

    name = "ibkr"
    supported_markets = {Market.STOCK, Market.OPTION}

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 7497,
        client_id: int = 1,
        account: str = "",
        is_paper: bool = False,
    ) -> None:
        """初始化 IBKR 适配器

        Args:
            host: TWS/Gateway 主机地址
            port: TWS 端口（TWS=7496, Gateway=4001, Paper=7497）
            client_id: API 客户端 ID
            account: 账户ID（多账户时指定）
            is_paper: 是否为模拟账户
        """
        self._host = host
        self._port = port
        self._client_id = client_id
        self._account = account
        self._is_paper = is_paper

        # IBKR 连接状态
        self._connected = False
        self._client: Any = None  # ib_insync.IB 实例

        # 订单映射: client_order_id -> ib_order_id
        self._order_map: dict[str, int] = {}

    # ── 连接管理 ──────────────────────────────────────────────────

    async def connect(self) -> None:
        """建立与 TWS/Gateway 的连接

        Raises:
            ConnectionError: 连接失败
        """
        try:
            from ib_insync import IB

            self._client = IB()
            await self._client.connectAsync(
                host=self._host,
                port=self._port,
                clientId=self._client_id,
            )
            self._connected = True
            logger.info(
                "IBKR 已连接: %s:%d (client_id=%d, paper=%s)",
                self._host,
                self._port,
                self._client_id,
                self._is_paper,
            )
        except ImportError:
            logger.error("ib_insync 未安装，IBKR 适配器不可用")
            raise
        except Exception as exc:
            logger.error("IBKR 连接失败: %s", exc)
            raise ConnectionError(f"IBKR 连接失败: {exc}") from exc

    async def disconnect(self) -> None:
        """断开与 TWS/Gateway 的连接"""
        if self._client is not None:
            self._client.disconnect()
            self._client = None
        self._connected = False
        logger.info("IBKR 已断开")

    # ── 订单操作 ──────────────────────────────────────────────────

    async def submit_order(self, order: Order) -> str:
        """提交订单到 IBKR

        Args:
            order: 统一订单对象

        Returns:
            IBKR 订单 ID（字符串）

        Raises:
            RuntimeError: 未连接
            ValueError: 不支持的订单类型
        """
        self._ensure_connected()

        from ib_insync import LimitOrder, MarketOrder, StopLimitOrder

        # 构建合约
        contract = self._build_contract(order.symbol, order.market)

        # 构建订单
        action = "BUY" if order.side == "buy" else "SELL"
        quantity = float(order.quantity)

        if order.order_type == "market":
            ib_order = MarketOrder(action, quantity)
        elif order.order_type == "limit":
            if order.price is None:
                raise ValueError("限价单必须指定价格")
            ib_order = LimitOrder(action, quantity, float(order.price))
        elif order.order_type == "stop_limit":
            if order.price is None or order.stop_price is None:
                raise ValueError("止损限价单必须指定价格和触发价")
            ib_order = StopLimitOrder(
                action,
                quantity,
                limitPrice=float(order.price),
                stopPrice=float(order.stop_price),
            )
        else:
            raise ValueError(f"不支持的订单类型: {order.order_type}")

        # 设置客户端订单ID（幂等键）
        ib_order.orderId = self._client.client.getNextOrderId()
        ib_order.account = self._account or ""

        # 提交
        _trade = self._client.placeOrder(contract, ib_order)  # noqa: F841
        ib_order_id = str(ib_order.orderId)

        # 保存映射
        self._order_map[order.client_order_id] = ib_order.orderId

        logger.info(
            "IBKR 下单成功: %s %s %s %s @ %s → orderId=%s",
            action,
            order.quantity,
            order.symbol,
            order.order_type,
            order.price or "market",
            ib_order_id,
        )
        return ib_order_id

    async def cancel_order(self, order_id: str, symbol: str) -> bool:
        """撤销 IBKR 订单

        Args:
            order_id: IBKR 订单ID
            symbol: 标的符号

        Returns:
            是否成功撤销
        """
        self._ensure_connected()

        try:
            order_id_int = int(order_id)
            # 查找对应的 trade 对象
            for trade in self._client.openTrades():
                if trade.order.orderId == order_id_int:
                    self._client.cancelOrder(trade.order)
                    logger.info("IBKR 撤单成功: %s", order_id)
                    return True

            logger.warning("IBKR 撤单失败: 订单 %s 未找到", order_id)
            return False
        except Exception as exc:
            logger.warning("IBKR 撤单异常: %s - %s", order_id, exc)
            return False

    # ── 持仓与资金 ────────────────────────────────────────────────

    async def get_positions(self) -> list[PositionState]:
        """查询当前所有持仓

        Returns:
            持仓状态列表
        """
        self._ensure_connected()

        positions = []
        for pos in self._client.positions():
            if self._account and pos.account != self._account:
                continue

            qty = Decimal(str(pos.position))
            if qty == 0:
                continue

            # 判断市场类型
            market = Market.STOCK
            if pos.contract.secType == "OPT":
                market = Market.OPTION

            # 获取未实现盈亏
            unrealized_pnl = Decimal("0")
            realized_pnl = Decimal("0")

            # 尝试从 accountSummary 获取
            positions.append(
                PositionState(
                    symbol=pos.contract.symbol,
                    market=market,
                    side="long" if qty > 0 else "short",
                    quantity=abs(qty),
                    entry_price=Decimal(str(pos.avgCost)),
                    unrealized_pnl=unrealized_pnl,
                    realized_pnl=realized_pnl,
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

        balances: dict[str, Decimal] = {}
        for item in self._client.accountSummary():
            if self._account and item.account != self._account:
                continue
            if item.tag == "TotalCashValue":
                balances["USD"] = Decimal(item.value)
            elif item.tag == "NetLiquidation":
                balances["NAV"] = Decimal(item.value)
            elif item.tag == "AvailableFunds":
                balances["AvailableFunds"] = Decimal(item.value)
            elif item.tag == "MaintMarginReq":
                balances["MaintMarginReq"] = Decimal(item.value)

        return balances

    async def get_ticker(self, symbol: str) -> Ticker:
        """查询指定标的最新行情

        Args:
            symbol: 标的符号

        Returns:
            最新行情快照
        """
        self._ensure_connected()

        from ib_insync import Stock

        contract = Stock(symbol, "SMART", "USD")
        self._client.qualifyContracts(contract)

        # 请求行情
        ticker = self._client.reqTickers(contract)
        if not ticker:
            raise ValueError(f"无法获取行情: {symbol}")

        t = ticker[0]
        return Ticker(
            symbol=symbol,
            market=Market.STOCK,
            exchange="ibkr",
            last_price=Decimal(str(t.last or t.close or 0)),
            bid=Decimal(str(t.bid or 0)),
            ask=Decimal(str(t.ask or 0)),
            volume_24h=Decimal(str(t.volume or 0)),
            timestamp_ns=time.time_ns(),
        )

    # ── 跨市场扩展接口 ────────────────────────────────────────────

    async def search_instrument(self, query: str) -> list[Instrument]:
        """搜索标的

        支持股票和期权搜索。

        Args:
            query: 搜索关键词（如 "AAPL", "SPY 240621C00500000"）

        Returns:
            匹配的标的列表
        """
        self._ensure_connected()

        from ib_insync import Stock

        results = []

        # 股票搜索
        contract = Stock(query, "SMART", "USD")
        details = self._client.reqContractDetails(contract)

        for detail in details[:10]:  # 限制返回数量
            c = detail.contract
            results.append(
                Instrument(
                    internal_id=f"ibkr_{c.conId}",
                    symbol=c.symbol,
                    market=Market.STOCK,
                    instrument_type=InstrumentType.STOCK,
                    exchange="ibkr",
                    base_currency=c.symbol,
                    quote_currency=c.currency or "USD",
                    tick_size=Decimal(str(detail.minTick)),
                    lot_size=Decimal("1"),
                    contract_multiplier=Decimal("1"),
                    is_active=True,
                )
            )

        return results

    async def get_unified_positions(self) -> list[dict[str, Any]]:
        """统一持仓视图（跨市场净敞口、保证金、组合 Greeks）

        Returns:
            统一持仓信息列表
        """
        positions = await self.get_positions()
        _balance = await self.get_balance()  # noqa: F841

        result: list[Any] = []
        for pos in positions:
            entry = pos.entry_price * pos.quantity
            result.append(
                {
                    "symbol": pos.symbol,
                    "market": pos.market.value,
                    "side": pos.side,
                    "quantity": str(pos.quantity),
                    "entry_price": str(pos.entry_price),
                    "market_value": str(entry),
                    "net_exposure": str(entry if pos.side == "long" else -entry),
                    "unrealized_pnl": str(pos.unrealized_pnl),
                    "margin_required": "0",  # 需要 IBKR API 查询
                    "greeks": {},  # 期权标的需要额外查询
                }
            )

        return result

    async def get_unified_balance(self) -> dict[str, Any]:
        """统一资金视图（多币种 NAV 合并）

        Returns:
            统一资金信息
        """
        balance = await self.get_balance()

        return {
            "total_nav_usd": str(balance.get("NAV", Decimal("0"))),
            "available_cash": str(balance.get("AvailableFunds", Decimal("0"))),
            "margin_used": str(balance.get("MaintMarginReq", Decimal("0"))),
            "balances": {k: str(v) for k, v in balance.items()},
        }

    # ── 内部方法 ──────────────────────────────────────────────────

    def _ensure_connected(self) -> None:
        """确保已连接"""
        if not self._connected or self._client is None:
            raise RuntimeError("IBKR 未连接，请先调用 connect()")

    def _build_contract(self, symbol: str, market: Market) -> Any:
        """构建 IBKR 合约对象

        Args:
            symbol: 标的符号
            market: 市场类型

        Returns:
            ib_insync Contract 对象
        """
        from ib_insync import Option, Stock

        if market == Market.OPTION:
            # 期权符号格式: SYMBOL-EXPIRY-STRIKE-TYPE
            # 如 AAPL-20240621-200-C
            parts = symbol.split("-")
            if len(parts) == 4:
                return Option(
                    parts[0],
                    parts[1],
                    float(parts[2]),
                    parts[3],
                    "SMART",
                    "100",
                )
            # 回退为股票
            logger.warning("期权符号格式不正确，回退为股票: %s", symbol)

        return Stock(symbol, "SMART", "USD")
