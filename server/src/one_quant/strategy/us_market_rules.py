"""
美股交易机制校验引擎

包含所有美股硬规则检查器，这些规则是监管要求，不从 .env/DB 读取：
  - PDT (Pattern Day Trader) 日内交易规则
  - Reg-T 保证金要求
  - SSR (Short Sale Restriction) 卖空限制
  - Locate 借券定位
  - LULD (Limit Up/Limit Down) 限价带
  - 市场级熔断

规范：
  - 所有金额使用 Decimal 精确计算
  - 硬规则常量为类级属性，不从配置读取
  - 校验结果为 (bool, str) 元组，str 为中文说明
"""

from __future__ import annotations

import time
from collections import deque
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from one_quant.core.types import Order
from one_quant.infra.logging import get_logger

logger = get_logger(__name__)


# ──────────────────────────── PDT 检查 ────────────────────────────


class PDTChecker:
    """PDT (Pattern Day Trader) 检查

    SEC 规则：
    - 账户净值 < $25,000: 5 个交易日内 ≤ 3 次日内往返交易
    - 账户净值 ≥ $25,000: 不受限制
    - 日内往返定义：同一标的同日买入并卖出（或卖空并回补）

    硬规则：$25,000 阈值由 SEC/FINRA 规定，不从配置读取。
    """

    # FINRA 规定的 PDT 阈值（美元）
    PDT_THRESHOLD = Decimal("25000")
    # 滚动窗口天数
    ROLLING_DAYS = 5
    # 窗口内最大日内交易次数
    MAX_DAY_TRADES = 3

    def __init__(self, account_value: Decimal) -> None:
        """初始化 PDT 检查器

        Args:
            account_value: 账户当前净值（美元）
        """
        self._account_value = account_value
        self._day_trades: deque[dict[str, Any]] = deque()

    def check_pdt(self, symbol: str, side: str) -> tuple[bool, str]:
        """检查是否触发 PDT 规则

        Args:
            symbol: 标的符号
            side: 买卖方向 ("buy" / "sell")

        Returns:
            (是否允许交易, 中文说明)
        """
        # 账户 >= $25k，不受限制
        if self._account_value >= self.PDT_THRESHOLD:
            return True, "账户净值 >= $25,000，不受 PDT 限制"

        # 清理过期记录（5个交易日前）
        self._cleanup_old_trades()

        # 当前窗口内日内交易次数
        current_count = len(self._day_trades)

        if current_count >= self.MAX_DAY_TRADES:
            return (
                False,
                f"PDT 限制: 5个交易日内已有 {current_count} 次日内交易，"
                f"达到上限 {self.MAX_DAY_TRADES} 次。"
                f"账户净值 ${self._account_value} < $25,000",
            )

        remaining = self.MAX_DAY_TRADES - current_count
        return (
            True,
            f"PDT 检查通过: 剩余 {remaining} 次日内交易额度",
        )

    def record_day_trade(
        self, symbol: str, open_time: int, close_time: int
    ) -> None:
        """记录日内交易

        当同一标的在同一天内完成买入+卖出（或卖空+回补）时调用。

        Args:
            symbol: 标的符号
            open_time: 开仓时间戳（纳秒）
            close_time: 平仓时间戳（纳秒）
        """
        self._day_trades.append(
            {
                "symbol": symbol,
                "open_time": open_time,
                "close_time": close_time,
                "date": date.fromtimestamp(close_time / 1_000_000_000),
            }
        )
        logger.info(
            "PDT 日内交易记录: %s, 当前窗口内 %d 次",
            symbol,
            len(self._day_trades),
        )

    def update_account_value(self, account_value: Decimal) -> None:
        """更新账户净值（实时同步）"""
        self._account_value = account_value

    def _cleanup_old_trades(self) -> None:
        """清理超过滚动窗口的交易记录"""
        cutoff = date.today() - timedelta(days=self.ROLLING_DAYS * 2)  # 保守估计
        while self._day_trades and self._day_trades[0]["date"] < cutoff:
            self._day_trades.popleft()

    @property
    def is_pdt_account(self) -> bool:
        """是否为 PDT 账户（净值 >= $25k）"""
        return self._account_value >= self.PDT_THRESHOLD

    @property
    def day_trade_count(self) -> int:
        """当前窗口内日内交易次数"""
        self._cleanup_old_trades()
        return len(self._day_trades)


# ──────────────────────────── Reg-T 保证金 ────────────────────────────


class RegTMarginChecker:
    """Reg-T 保证金检查

    联储局 Regulation T 规定：
    - 初始保证金: 50%（买入时需有 50% 自有资金）
    - 维持保证金: 25%（持仓期间净值不低于 25%）

    硬规则：50%/25% 由联储局规定，不从配置读取。
    """

    # 初始保证金比例（联储局规定）
    INITIAL_MARGIN = Decimal("0.50")
    # 维持保证金比例（联储局规定）
    MAINTENANCE_MARGIN = Decimal("0.25")

    def check_initial_margin(
        self, order_value: Decimal, cash: Decimal
    ) -> tuple[bool, str]:
        """检查初始保证金

        Args:
            order_value: 订单总价值
            cash: 可用现金

        Returns:
            (是否满足保证金, 中文说明)
        """
        required = order_value * self.INITIAL_MARGIN
        if cash >= required:
            return (
                True,
                f"初始保证金检查通过: 需要 ${required}, 可用 ${cash}",
            )
        deficit = required - cash
        return (
            False,
            f"初始保证金不足: 需要 ${required} ({self.INITIAL_MARGIN * 100}%), "
            f"可用 ${cash}, 缺口 ${deficit}",
        )

    def check_maintenance_margin(
        self,
        positions: list[dict[str, Any]],
        equity: Decimal,
    ) -> tuple[bool, Decimal]:
        """检查维持保证金

        Args:
            positions: 持仓列表，每项含 market_value 字段
            equity: 账户净值

        Returns:
            (是否满足维持保证金, 缺口金额（负数表示安全余量）)
        """
        total_market_value = sum(
            abs(Decimal(str(p.get("market_value", 0)))) for p in positions
        )
        if total_market_value == 0:
            return True, Decimal("0")

        required = total_market_value * self.MAINTENANCE_MARGIN
        margin_excess = equity - required

        if margin_excess >= 0:
            return True, -margin_excess  # 负数表示安全余量

        # 触发追保
        logger.warning(
            "维持保证金不足: 净值 $%s, 需要 $%s, 缺口 $%s",
            equity,
            required,
            abs(margin_excess),
        )
        return False, abs(margin_excess)


# ──────────────────────────── SSR 卖空限制 ────────────────────────────


class SSRChecker:
    """卖空限制 (Short Sale Restriction / Alternative Uptick Rule)

    SEC 规则 201：
    - 当个股价格较前一日收盘价下跌 10% 时触发 SSR
    - SSR 状态持续至触发当日收盘及次日全天
    - SSR 期间卖空订单价格必须高于当前最优买价 (best bid)

    硬规则：10% 阈值由 SEC 规定，不从配置读取。
    """

    # SSR 触发阈值（SEC 规定 10%）
    SSR_DROP_THRESHOLD = Decimal("0.10")

    def __init__(self) -> None:
        # symbol -> SSR 状态信息
        self._ssr_status: dict[str, dict[str, Any]] = {}

    def update_price(self, symbol: str, current_price: Decimal, prev_close: Decimal) -> None:
        """更新价格并检查是否触发 SSR

        Args:
            symbol: 标的符号
            current_price: 当前价格
            prev_close: 前一日收盘价
        """
        if prev_close <= 0:
            return

        drop_pct = (prev_close - current_price) / prev_close
        if drop_pct >= self.SSR_DROP_THRESHOLD:
            self._ssr_status[symbol] = {
                "triggered_at": time.time_ns(),
                "drop_pct": str(drop_pct),
                "prev_close": str(prev_close),
                "trigger_price": str(current_price),
            }
            logger.info(
                "SSR 触发: %s, 跌幅 %.2f%%, 前收 $%s, 触发价 $%s",
                symbol,
                drop_pct * 100,
                prev_close,
                current_price,
            )

    def is_restricted(self, symbol: str) -> bool:
        """检查标的是否处于 SSR 状态

        SSR 在触发当日收盘后及次日全天有效。
        这里简化为检查是否在今日内触发过。

        Args:
            symbol: 标的符号

        Returns:
            是否处于 SSR 限制状态
        """
        status = self._ssr_status.get(symbol)
        if status is None:
            return False

        # SSR 持续到次日收盘，这里简化为 24 小时
        triggered_ns = status["triggered_at"]
        elapsed_hours = (time.time_ns() - triggered_ns) / (3600 * 1_000_000_000)
        return elapsed_hours < 24

    def validate_short_order(
        self, order: Order, best_bid: Decimal | None = None
    ) -> tuple[bool, str]:
        """验证卖空订单是否符合 SSR 规则

        SSR 期间：卖空价格必须高于最优买价 (best bid)

        Args:
            order: 订单对象
            best_bid: 当前最优买价（SSR 期间必填）

        Returns:
            (是否合法, 中文说明)
        """
        # 仅对卖空订单生效
        if order.side != "sell":
            return True, "非卖空订单，SSR 不适用"

        if not self.is_restricted(order.symbol):
            return True, "标的未处于 SSR 状态"

        # SSR 期间必须有价格（不能下市价卖空）
        if order.price is None:
            return (
                False,
                f"SSR 限制: {order.symbol} 处于卖空限制状态，"
                f"不允许市价卖空，必须指定高于最优买价的限价",
            )

        if best_bid is not None and order.price <= best_bid:
            return (
                False,
                f"SSR 限制: {order.symbol} 卖空价格 ${order.price} "
                f"必须高于最优买价 ${best_bid}",
            )

        return True, f"SSR 卖空订单验证通过: {order.symbol}"


# ──────────────────────────── 借券定位 ────────────────────────────


class LocateChecker:
    """借券定位检查 (Locate Requirement)

    SEC 规则 SHO (Regulation SHO)：
    - 卖空前必须确认可借券源（borrow availability）
    - 经纪商需提供 "locate" 确认
    - 未成功定位不得执行卖空

    此检查器为本地缓存层，实际 locate 需通过券商 API 获取。
    """

    def __init__(self) -> None:
        # symbol -> locate 信息
        self._locates: dict[str, dict[str, Any]] = {}

    def register_locate(
        self, symbol: str, quantity: Decimal, expiry_timestamp_ns: int
    ) -> None:
        """注册借券定位确认

        Args:
            symbol: 标的符号
            quantity: 可借数量
            expiry_timestamp_ns: 定位确认过期时间（纳秒）
        """
        self._locates[symbol] = {
            "quantity": quantity,
            "expiry_ns": expiry_timestamp_ns,
            "registered_at": time.time_ns(),
        }

    async def check_locate(
        self, symbol: str, quantity: Decimal = Decimal("0")
    ) -> tuple[bool, str]:
        """卖空前校验可借券源

        Args:
            symbol: 标的符号
            quantity: 需要借入的数量

        Returns:
            (是否可借, 中文说明)
        """
        locate = self._locates.get(symbol)
        if locate is None:
            return (
                False,
                f"无借券定位: {symbol} 未获取 locate 确认，不允许卖空",
            )

        # 检查是否过期
        now_ns = time.time_ns()
        if now_ns > locate["expiry_ns"]:
            del self._locates[symbol]
            return (
                False,
                f"借券定位已过期: {symbol}, 需重新获取 locate",
            )

        # 检查数量
        available = locate["quantity"]
        if quantity > 0 and quantity > available:
            return (
                False,
                f"借券数量不足: {symbol} 需要 {quantity}, 可借 {available}",
            )

        return (
            True,
            f"借券定位确认: {symbol}, 可借 {available}",
        )


# ──────────────────────────── LULD 限价带 ────────────────────────────


class LULDChecker:
    """LULD (Limit Up/Limit Down) 限价带检查

    SEC/NMS 规则：
    - 标的价格必须在参考价 ± 特定百分比范围内
    - Tier 1 标的（S&P 500 等）: ± 5%（开盘/收盘 30 分钟内 ± 10%）
    - Tier 2 标的（其他）: ± 10%（开盘/收盘 30 分钟内 ± 20%）
    - 价格超过限价带将触发交易暂停

    硬规则：百分比由 SEC/NMS 规定，不从配置读取。
    """

    # Tier 1 标的限价带百分比
    TIER1_PCT = Decimal("0.05")
    TIER1_OPEN_CLOSE_PCT = Decimal("0.10")
    # Tier 2 标的限价带百分比
    TIER2_PCT = Decimal("0.10")
    TIER2_OPEN_CLOSE_PCT = Decimal("0.20")

    def __init__(self) -> None:
        # symbol -> {"reference_price": Decimal, "tier": int}
        self._reference_prices: dict[str, dict[str, Any]] = {}

    def set_reference_price(
        self, symbol: str, reference_price: Decimal, tier: int = 1
    ) -> None:
        """设置参考价格（通常是前收盘价或开盘价）

        Args:
            symbol: 标的符号
            reference_price: 参考价格
            tier: 标的层级（1 或 2）
        """
        self._reference_prices[symbol] = {
            "reference_price": reference_price,
            "tier": tier,
        }

    def check_price_band(
        self,
        symbol: str,
        price: Decimal,
        is_open_close_period: bool = False,
    ) -> tuple[bool, str]:
        """检查价格是否在限价带内

        Args:
            symbol: 标的符号
            price: 待检查价格
            is_open_close_period: 是否处于开盘/收盘阶段（扩大限价带）

        Returns:
            (是否在限价带内, 中文说明)
        """
        ref_info = self._reference_prices.get(symbol)
        if ref_info is None:
            # 无参考价格，不执行 LULD 检查
            return True, f"无参考价格，LULD 检查跳过: {symbol}"

        ref_price = ref_info["reference_price"]
        tier = ref_info["tier"]

        if ref_price <= 0:
            return True, f"参考价格无效，LULD 检查跳过: {symbol}"

        # 根据层级和时段确定限价带百分比
        if tier == 1:
            pct = self.TIER1_OPEN_CLOSE_PCT if is_open_close_period else self.TIER1_PCT
            tier_name = "Tier 1"
        else:
            pct = self.TIER2_OPEN_CLOSE_PCT if is_open_close_period else self.TIER2_PCT
            tier_name = "Tier 2"

        upper = ref_price * (1 + pct)
        lower = ref_price * (1 - pct)

        if price > upper:
            return (
                False,
                f"LULD 限价带上限突破: {symbol} 价格 ${price} > 上限 ${upper} "
                f"(参考价 ${ref_price}, {tier_name}, ±{pct * 100}%)",
            )
        if price < lower:
            return (
                False,
                f"LULD 限价带下限突破: {symbol} 价格 ${price} < 下限 ${lower} "
                f"(参考价 ${ref_price}, {tier_name}, ±{pct * 100}%)",
            )

        return True, f"LULD 限价带检查通过: {symbol}"


# ──────────────────────────── 市场级熔断 ────────────────────────────


class MarketCircuitBreaker:
    """市场级熔断 (Market-Wide Circuit Breakers)

    SEC/NYSE 规则：
    - Level 1: S&P 500 较前日收盘跌 7% → 全市场暂停 15 分钟
    - Level 2: S&P 500 较前日收盘跌 13% → 全市场暂停 15 分钟
    - Level 3: S&P 500 较前日收盘跌 20% → 全市场收盘

    硬规则：7%/13%/20% 由 SEC/NYSE 规定，不从配置读取。
    """

    # 熔断阈值（由 SEC/NYSE 规定）
    LEVEL_1_DROP = Decimal("0.07")  # 7%
    LEVEL_2_DROP = Decimal("0.13")  # 13%
    LEVEL_3_DROP = Decimal("0.20")  # 20%

    def __init__(self) -> None:
        self._halt_active = False
        self._halt_level = 0
        self._halt_until_ns = 0
        self._sp500_prev_close: Decimal | None = None

    def set_sp500_prev_close(self, prev_close: Decimal) -> None:
        """设置 S&P 500 前日收盘价"""
        self._sp500_prev_close = prev_close

    def update_sp500_price(self, current_price: Decimal) -> int:
        """更新 S&P 500 价格并检查熔断

        Args:
            current_price: S&P 500 当前价格

        Returns:
            熔断级别（0=正常, 1/2/3=熔断级别）
        """
        if self._sp500_prev_close is None or self._sp500_prev_close <= 0:
            return 0

        drop_pct = (self._sp500_prev_close - current_price) / self._sp500_prev_close

        if drop_pct >= self.LEVEL_3_DROP:
            self._trigger_halt(3)
            return 3
        elif drop_pct >= self.LEVEL_2_DROP:
            self._trigger_halt(2)
            return 2
        elif drop_pct >= self.LEVEL_1_DROP:
            self._trigger_halt(1)
            return 1

        return 0

    def _trigger_halt(self, level: int) -> None:
        """触发熔断"""
        if self._halt_active and self._halt_level >= level:
            return  # 已在更高级别熔断中

        self._halt_active = True
        self._halt_level = level

        if level < 3:
            # Level 1/2: 暂停 15 分钟
            self._halt_until_ns = time.time_ns() + 15 * 60 * 1_000_000_000
            logger.warning(
                "市场熔断 Level %d 触发: S&P 500 跌幅达 %d%%, 暂停 15 分钟",
                level,
                level * 7 if level == 1 else 13,
            )
        else:
            # Level 3: 全天收盘
            self._halt_until_ns = 0  # 无限期
            logger.critical("市场熔断 Level 3 触发: S&P 500 跌幅达 20%, 全市场收盘")

    def check_market_halt(self) -> tuple[bool, int, str]:
        """检查全市场熔断状态

        Returns:
            (是否处于熔断, 熔断级别, 中文说明)
        """
        if not self._halt_active:
            return False, 0, "市场正常交易"

        # 检查是否已过暂停期
        if self._halt_until_ns > 0 and time.time_ns() > self._halt_until_ns:
            self._halt_active = False
            self._halt_level = 0
            return False, 0, "熔断暂停期已过，恢复交易"

        if self._halt_level == 3:
            return True, 3, "Level 3 熔断: 全市场收盘，禁止所有交易"

        return (
            True,
            self._halt_level,
            f"Level {self._halt_level} 熔断中: 全市场暂停交易",
        )


# ──────────────────────────── 综合规则引擎 ────────────────────────────


class USMarketRuleEngine:
    """美股规则引擎（集成所有检查器）

    按顺序执行所有校验：
    1. 市场熔断（最先检查，全市场级别）
    2. PDT 日内交易规则
    3. Reg-T 保证金检查
    4. SSR 卖空限制
    5. Locate 借券定位
    6. LULD 限价带

    使用方式::

        engine = USMarketRuleEngine(
            account_value=Decimal("30000"),
            cash=Decimal("15000"),
            positions=[...],
            equity=Decimal("30000"),
        )
        ok, reasons = engine.validate_order(order)
    """

    def __init__(
        self,
        account_value: Decimal,
        cash: Decimal,
        positions: list[dict[str, Any]],
        equity: Decimal,
    ) -> None:
        """初始化规则引擎

        Args:
            account_value: 账户净值（用于 PDT 判断）
            cash: 可用现金（用于保证金检查）
            positions: 当前持仓列表
            equity: 账户权益
        """
        self.pdt = PDTChecker(account_value)
        self.margin = RegTMarginChecker()
        self.ssr = SSRChecker()
        self.locate = LocateChecker()
        self.luld = LULDChecker()
        self.circuit_breaker = MarketCircuitBreaker()

        self._cash = cash
        self._positions = positions
        self._equity = equity

    def validate_order(
        self,
        order: Order,
        best_bid: Decimal | None = None,
    ) -> tuple[bool, list[str]]:
        """综合校验订单

        按优先级顺序检查所有规则，返回所有失败原因。

        Args:
            order: 订单对象
            best_bid: 当前最优买价（SSR 检查时需要）

        Returns:
            (是否通过所有检查, 失败原因列表)
        """
        failures: list[str] = []

        # 1. 市场熔断
        is_halted, level, msg = self.circuit_breaker.check_market_halt()
        if is_halted:
            failures.append(msg)
            # 熔断期间直接拒绝，不继续检查
            return False, failures

        # 2. PDT 检查（仅限买入或卖空触发日内往返的场景）
        if order.side == "buy":
            pdt_ok, pdt_msg = self.pdt.check_pdt(order.symbol, order.side)
            if not pdt_ok:
                failures.append(pdt_msg)

        # 3. Reg-T 保证金检查
        if order.price is not None:
            order_value = order.price * order.quantity
            margin_ok, margin_msg = self.margin.check_initial_margin(
                order_value, self._cash
            )
            if not margin_ok:
                failures.append(margin_msg)

        # 4. SSR 卖空限制
        if order.side == "sell":
            ssr_ok, ssr_msg = self.ssr.validate_short_order(order, best_bid)
            if not ssr_ok:
                failures.append(ssr_msg)

        # 5. Locate 借券定位（卖空时）
        # 注意：locate 是异步的，这里标记需要检查
        # 实际调用方应单独调用 locate.check_locate()

        # 6. LULD 限价带
        if order.price is not None:
            luld_ok, luld_msg = self.luld.check_price_band(order.symbol, order.price)
            if not luld_ok:
                failures.append(luld_msg)

        is_valid = len(failures) == 0
        if not is_valid:
            logger.warning(
                "订单校验失败: %s %s %s, 原因: %s",
                order.side,
                order.quantity,
                order.symbol,
                "; ".join(failures),
            )

        return is_valid, failures

    async def validate_order_async(
        self,
        order: Order,
        best_bid: Decimal | None = None,
    ) -> tuple[bool, list[str]]:
        """异步综合校验（包含 Locate 异步检查）

        Args:
            order: 订单对象
            best_bid: 当前最优买价

        Returns:
            (是否通过所有检查, 失败原因列表)
        """
        failures: list[str] = []

        # 同步检查
        is_valid, sync_failures = self.validate_order(order, best_bid)
        failures.extend(sync_failures)

        # 异步 Locate 检查（卖空时）
        if order.side == "sell" and is_valid:
            locate_ok, locate_msg = await self.locate.check_locate(
                order.symbol, order.quantity
            )
            if not locate_ok:
                failures.append(locate_msg)

        is_valid = len(failures) == 0
        return is_valid, failures
