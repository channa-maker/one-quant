"""
统一券商抽象层 — 跨市场统一接口

桥接传统金融（IBKR 美股/美期权）与加密市场（币安/OKX/Deribit），
提供统一的下单/撤单/持仓/资金/标的操作接口。

设计原则：
  - 抽象层仅定义接口，不包含业务逻辑
  - 子类实现具体券商 API 交互
  - 支持插件扩展：新增券商只需实现 UnifiedBroker 子类
  - BrokerPool 管理适配器生命周期（惰性创建、用后释放）
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Any

from one_quant.core.types import (
    Instrument,
    Market,
    Order,
    PositionState,
    Ticker,
)
from one_quant.infra.logging import get_logger

logger = get_logger(__name__)


# ──────────────────────────── 统一券商抽象 ────────────────────────────


class UnifiedBroker(ABC):
    """统一券商抽象层

    所有券商适配器必须实现此接口。
    桥接 IBKR(美股/美期权) + 币安/OKX(加密) + Deribit(加密期权)。

    子类实现：
    - IBKRAdapter: 美股 + 美期权
    - DeribitAdapter: 加密期权
    - BinanceAdapter / OKXAdapter: 加密现货/合约

    Attributes:
        name: 券商名称（如 "ibkr", "binance", "deribit"）
        supported_markets: 支持的市场类型集合
    """

    name: str
    supported_markets: set[Market]

    # ── 连接管理 ──────────────────────────────────────────────────

    @abstractmethod
    async def connect(self) -> None:
        """建立与券商的连接

        包括 WebSocket 订阅连接和 REST API 鉴权。
        连接失败应抛出异常。
        """
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """断开与券商的连接

        优雅关闭所有连接，释放资源。
        """
        ...

    # ── 订单操作 ──────────────────────────────────────────────────

    @abstractmethod
    async def submit_order(self, order: Order) -> str:
        """提交订单

        Args:
            order: 统一订单对象

        Returns:
            券商分配的订单ID（字符串）

        Raises:
            券商相关异常：下单失败（余额不足、参数错误等）
        """
        ...

    @abstractmethod
    async def cancel_order(self, order_id: str, symbol: str) -> bool:
        """撤销订单

        Args:
            order_id: 券商订单ID
            symbol: 标的符号

        Returns:
            是否成功撤销。订单已成交或不存在时返回 False。
        """
        ...

    # ── 持仓与资金 ────────────────────────────────────────────────

    @abstractmethod
    async def get_positions(self) -> list[PositionState]:
        """查询当前所有持仓

        Returns:
            持仓状态列表。无持仓时返回空列表。
        """
        ...

    @abstractmethod
    async def get_balance(self) -> dict[str, Decimal]:
        """查询资金余额

        Returns:
            币种 -> 余额 的映射（如 {"USD": 50000, "BTC": 1.5}）
        """
        ...

    # ── 行情 ──────────────────────────────────────────────────────

    @abstractmethod
    async def get_ticker(self, symbol: str) -> Ticker:
        """查询指定标的最新行情

        Args:
            symbol: 标的符号

        Returns:
            最新行情快照
        """
        ...

    # ── 跨市场扩展接口 ────────────────────────────────────────────

    @abstractmethod
    async def search_instrument(self, query: str) -> list[Instrument]:
        """跨市场统一标的搜索

        支持多种标的格式：
        - 股票: AAPL, TSLA
        - 加密现货: BTC/USDT
        - 期权: BTC-30JUN24-70000-C
        - 永续合约: BTC-PERP

        Args:
            query: 搜索关键词或标的代码

        Returns:
            匹配的标的列表
        """
        ...

    @abstractmethod
    async def get_unified_positions(self) -> list[dict[str, Any]]:
        """统一持仓视图

        返回跨市场净敞口、保证金、组合 Greeks（如有期权）等信息。

        Returns:
            统一持仓信息列表，每项包含：
            - symbol: 标的符号
            - market: 市场类型
            - net_exposure: 净敞口
            - margin_required: 占用保证金
            - greeks: 期权 Greeks（非期权标的为空字典）
        """
        ...

    @abstractmethod
    async def get_unified_balance(self) -> dict[str, Any]:
        """统一资金视图

        合并多币种 NAV（Net Asset Value）。

        Returns:
            统一资金信息：
            - total_nav_usd: 总净值（美元）
            - available_cash: 可用现金
            - margin_used: 已用保证金
            - balances: 各币种余额明细
        """
        ...


# ──────────────────────────── 券商池 ────────────────────────────


class BrokerPool:
    """券商池 — 惰性创建、用后释放

    管理所有 UnifiedBroker 实例的生命周期。
    适配器按名称注册，按需获取。

    支持两种模式：
    1. 预注册模式：手动 register 适配器实例
    2. 工厂模式：注册工厂函数，惰性创建适配器

    Example::

        pool = BrokerPool()

        # 预注册模式
        pool.register("binance", BinanceAdapter(...))

        # 工厂模式（惰性创建）
        pool.register_factory("ibkr", lambda: IBKRAdapter(...))

        # 使用
        broker = pool.get_broker("ibkr")
        await broker.connect()
    """

    def __init__(self) -> None:
        self._brokers: dict[str, UnifiedBroker] = {}
        self._factories: dict[str, Any] = {}  # name -> factory callable
        self._connected: set[str] = set()

    def register(self, name: str, broker: UnifiedBroker) -> None:
        """注册适配器实例

        Args:
            name: 适配器名称
            broker: UnifiedBroker 子类实例
        """
        self._brokers[name] = broker
        logger.info(
            "券商已注册: %s (支持市场: %s)",
            name,
            {m.value for m in broker.supported_markets},
        )

    def register_factory(self, name: str, factory: Any) -> None:
        """注册适配器工厂函数（惰性创建）

        Args:
            name: 适配器名称
            factory: 返回 UnifiedBroker 实例的无参函数
        """
        self._factories[name] = factory
        logger.info("券商工厂已注册: %s", name)

    def get_broker(self, name: str) -> UnifiedBroker:
        """获取券商适配器

        如果已注册实例则直接返回，
        如果注册了工厂函数则惰性创建。

        Args:
            name: 适配器名称

        Returns:
            UnifiedBroker 实例

        Raises:
            KeyError: 适配器未注册
        """
        # 优先返回已创建的实例
        if name in self._brokers:
            return self._brokers[name]

        # 尝试惰性创建
        factory = self._factories.get(name)
        if factory is not None:
            broker = factory()
            self._brokers[name] = broker
            logger.info("券商惰性创建: %s", name)
            return broker

        available = sorted(set(self._brokers.keys()) | set(self._factories.keys()))
        available_str = ", ".join(available) or "(无)"
        raise KeyError(f"券商 '{name}' 未注册。可用: {available_str}")

    def release(self, name: str) -> None:
        """释放券商适配器

        断开连接并移除实例。
        工厂注册保留，下次 get_broker 时重新创建。

        Args:
            name: 适配器名称
        """
        if name in self._connected:
            self._connected.discard(name)

        if name in self._brokers:
            del self._brokers[name]
            logger.info("券商已释放: %s", name)

    async def connect_broker(self, name: str) -> None:
        """连接指定券商

        Args:
            name: 适配器名称
        """
        broker = self.get_broker(name)
        await broker.connect()
        self._connected.add(name)
        logger.info("券商已连接: %s", name)

    async def connect_all(self) -> None:
        """连接所有已注册的券商"""
        all_names = set(self._brokers.keys()) | set(self._factories.keys())
        for name in all_names:
            try:
                await self.connect_broker(name)
            except Exception:
                logger.exception("券商连接失败: %s", name)

    async def disconnect_all(self) -> None:
        """断开所有券商"""
        for name in list(self._connected):
            try:
                broker = self._brokers.get(name)
                if broker:
                    await broker.disconnect()
                self._connected.discard(name)
                logger.info("券商已断开: %s", name)
            except Exception:
                logger.exception("券商断开失败: %s", name)

    def get_by_market(self, market: Market) -> list[UnifiedBroker]:
        """按市场类型获取支持该市场的券商列表

        Args:
            market: 市场类型

        Returns:
            支持该市场的券商列表
        """
        # 确保工厂模式的券商也被考虑
        self._materialize_all()
        return [b for b in self._brokers.values() if market in b.supported_markets]

    def _materialize_all(self) -> None:
        """将所有工厂模式的券商实例化"""
        for name, factory in list(self._factories.items()):
            if name not in self._brokers:
                self._brokers[name] = factory()

    @property
    def stats(self) -> dict[str, Any]:
        """统计信息"""
        return {
            "total": len(self._brokers) + len(self._factories),
            "instantiated": len(self._brokers),
            "connected": len(self._connected),
            "brokers": sorted(set(self._brokers.keys()) | set(self._factories.keys())),
        }
