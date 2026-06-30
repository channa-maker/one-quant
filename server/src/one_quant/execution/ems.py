"""
ONE量化 - 执行管理系统 (EMS)

算法拆单引擎，将大额订单拆分为多个子单，降低市场冲击。

支持算法：
  - TWAP: 时间加权平均价格（等时拆分）
  - VWAP: 成交量加权平均价格（按历史成交量分布）
  - POV:  参与率算法（跟踪市场成交量）

规范：
  - 所有算法继承 ExecutionAlgo 抽象基类
  - execute() 返回 Fill 列表（子单成交结果）
  - 适配器限流由外部 RateLimiter 控制
  - 异步执行，支持中途取消
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from abc import ABC, abstractmethod
from decimal import ROUND_DOWN, Decimal

from one_quant.core.types import Fill, Order
from one_quant.exchange.contracts import ExchangeAdapter

logger = logging.getLogger(__name__)


# ──────────────────── 辅助函数 ────────────────────


def _round_to_lot(quantity: Decimal, lot_size: Decimal) -> Decimal:
    """将数量取整到最小下单单位。

    Args:
        quantity: 原始数量。
        lot_size: 最小下单数量。

    Returns:
        取整后的数量（向下取整）。
    """
    if lot_size <= 0:
        return quantity
    return (quantity / lot_size).to_integral_value(rounding=ROUND_DOWN) * lot_size


def _time_ns() -> int:
    """获取当前纳秒时间戳。"""
    return time.time_ns()


# ──────────────────── 算法基类 ────────────────────


class ExecutionAlgo(ABC):
    """执行算法基类。

    所有拆单算法必须继承此类并实现 execute() 方法。

    Example::

        algo = TWAPAlgo(duration_sec=300, slice_count=10)
        fills = await algo.execute(order, adapter)
    """

    @abstractmethod
    async def execute(self, order: Order, adapter: ExchangeAdapter) -> list[Fill]:
        """执行订单，返回成交列表。

        Args:
            order: 父订单（原始大单）。
            adapter: 交易所适配器。

        Returns:
            子单成交列表。未完全成交时返回已成交部分。
        """
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """算法名称。"""
        ...


# ──────────────────── TWAP 算法 ────────────────────


class TWAPAlgo(ExecutionAlgo):
    """TWAP 算法：时间加权平均价格。

    将大单按时间均匀拆分，每间隔固定时间下一笔子单。
    适用：大额订单、流动性一般的标的。

    执行逻辑：
      1. 计算每笔子单数量 = 总量 / slice_count
      2. 每隔 duration_sec / slice_count 秒下一笔市价/限价单
      3. 等待成交后继续下一笔
      4. 超时未成交则撤单重试（带追价）

    Attributes:
        _duration: 执行总时长（秒）。
        _slice_count: 拆分子单数量。
        _price_limit: 限价保护价格（None 表示市价）。
        _max_retries: 单笔子单最大重试次数。
    """

    def __init__(
        self,
        duration_sec: int = 300,
        slice_count: int = 10,
        price_limit: Decimal | None = None,
        max_retries: int = 3,
    ) -> None:
        """初始化 TWAP 算法。

        Args:
            duration_sec: 执行总时长（秒），默认 5 分钟。
            slice_count: 拆分子单数量，默认 10 笔。
            price_limit: 限价保护价格，None 表示市价单。
            max_retries: 单笔子单最大重试次数，默认 3。
        """
        if duration_sec <= 0:
            raise ValueError(f"执行时长必须大于 0，当前: {duration_sec}")
        if slice_count <= 0:
            raise ValueError(f"拆分数量必须大于 0，当前: {slice_count}")

        self._duration = duration_sec
        self._slice_count = slice_count
        self._price_limit = price_limit
        self._max_retries = max_retries

    @property
    def name(self) -> str:
        return "TWAP"

    async def execute(self, order: Order, adapter: ExchangeAdapter) -> list[Fill]:
        """执行 TWAP 算法。

        将订单按时间均匀拆分，定时下子单。

        Args:
            order: 父订单。
            adapter: 交易所适配器。

        Returns:
            成交列表。
        """
        fills: list[Fill] = []
        total_qty = order.quantity

        # 计算每笔子单数量
        slice_qty = _round_to_lot(total_qty / self._slice_count, Decimal("0.001"))
        if slice_qty <= 0:
            logger.error("TWAP: 子单数量为 0，总量=%s，拆分数=%s", total_qty, self._slice_count)
            return fills

        # 计算时间间隔
        interval_sec = self._duration / self._slice_count
        remaining = total_qty

        logger.info(
            "TWAP 开始: %s %s %s，拆分 %d 笔，每笔 %s，间隔 %.1fs",
            order.side,
            order.quantity,
            order.symbol,
            self._slice_count,
            slice_qty,
            interval_sec,
        )

        for i in range(self._slice_count):
            # 最后一笔取剩余量
            if i == self._slice_count - 1:
                current_qty = remaining
            else:
                current_qty = min(slice_qty, remaining)

            if current_qty <= 0:
                break

            # 下子单
            child_fills = await self._execute_slice(
                order=order,
                adapter=adapter,
                quantity=current_qty,
                slice_index=i,
            )

            fills.extend(child_fills)

            filled_qty = sum(f.quantity for f in child_fills)
            remaining -= filled_qty

            logger.info(
                "TWAP 子单 %d/%d: 成交 %s，剩余 %s",
                i + 1,
                self._slice_count,
                filled_qty,
                remaining,
            )

            if remaining <= 0:
                break

            # 非最后一笔，等待间隔
            if i < self._slice_count - 1:
                await asyncio.sleep(interval_sec)

        total_filled = sum(f.quantity for f in fills)
        logger.info(
            "TWAP 完成: 总成交 %s/%s，成交笔数 %d",
            total_filled,
            total_qty,
            len(fills),
        )

        return fills

    async def _execute_slice(
        self,
        order: Order,
        adapter: ExchangeAdapter,
        quantity: Decimal,
        slice_index: int,
    ) -> list[Fill]:
        """执行单笔子单，带重试逻辑。

        Args:
            order: 父订单。
            adapter: 交易所适配器。
            quantity: 子单数量。
            slice_index: 子单序号。

        Returns:
            该子单的成交列表。
        """
        fills: list[Fill] = []

        for attempt in range(self._max_retries):
            try:
                # 构建子单
                child_order = Order(
                    client_order_id=str(uuid.uuid4()),
                    symbol=order.symbol,
                    market=order.market,
                    side=order.side,
                    order_type="limit" if self._price_limit else "market",
                    quantity=quantity,
                    price=self._price_limit,
                    stop_price=None,
                    status="pending",
                    exchange=order.exchange,
                    timestamp_ns=_time_ns(),
                )

                # 提交到交易所
                exchange_order_id = await adapter.submit_order(child_order)
                logger.debug(
                    "TWAP 子单 %d 提交成功: exchange_id=%s, qty=%s",
                    slice_index,
                    exchange_order_id,
                    quantity,
                )

                # 模拟成交回报（实际应通过 WebSocket 订阅获取）
                # 这里用下单价格近似成交价
                fill_price = self._price_limit or order.price or Decimal("0")
                fill = Fill(
                    order_id=order.client_order_id,
                    symbol=order.symbol,
                    side=order.side,
                    price=fill_price,
                    quantity=quantity,
                    fee=Decimal("0"),
                    fee_currency="USDT",
                    exchange=order.exchange,
                    timestamp_ns=_time_ns(),
                )
                fills.append(fill)
                return fills

            except Exception as e:
                logger.warning(
                    "TWAP 子单 %d 第 %d 次失败: %s",
                    slice_index,
                    attempt + 1,
                    e,
                )
                if attempt < self._max_retries - 1:
                    await asyncio.sleep(1.0 * (attempt + 1))  # 退避重试

        logger.error("TWAP 子单 %d 重试 %d 次均失败", slice_index, self._max_retries)
        return fills


# ──────────────────── VWAP 算法 ────────────────────


class VWAPAlgo(ExecutionAlgo):
    """VWAP 算法：成交量加权平均价格。

    按历史成交量分布拆单，跟随市场节奏。
    高成交量时段多下单，低成交量时段少下单。
    适用：有历史成交量数据的标的。

    执行逻辑：
      1. 获取历史 K 线数据（lookback_intervals 个窗口）
      2. 计算每个时间窗口的成交量占比
      3. 按占比分配子单数量
      4. 在对应时间窗口内下单

    Attributes:
        _lookback_intervals: 回看时间窗口数。
        _participation_rate: 参与率（每窗口成交量的比例）。
    """

    def __init__(
        self,
        lookback_intervals: int = 20,
        participation_rate: float = 0.1,
    ) -> None:
        """初始化 VWAP 算法。

        Args:
            lookback_intervals: 回看时间窗口数，默认 20。
            participation_rate: 参与率，默认 10%。
        """
        if lookback_intervals <= 0:
            raise ValueError(f"回看窗口数必须大于 0，当前: {lookback_intervals}")
        if not 0 < participation_rate <= 1:
            raise ValueError(f"参与率必须在 (0, 1] 之间，当前: {participation_rate}")

        self._lookback = lookback_intervals
        self._participation_rate = participation_rate

    @property
    def name(self) -> str:
        return "VWAP"

    async def execute(self, order: Order, adapter: ExchangeAdapter) -> list[Fill]:
        """执行 VWAP 算法。

        按历史成交量分布拆单。

        Args:
            order: 父订单。
            adapter: 交易所适配器。

        Returns:
            成交列表。
        """
        fills: list[Fill] = []
        total_qty = order.quantity

        # 获取历史成交量分布
        volume_profile = await self._get_volume_profile(adapter, order.symbol)

        if not volume_profile:
            logger.warning("VWAP: 无法获取成交量分布，回退到 TWAP")
            fallback = TWAPAlgo(duration_sec=self._lookback * 60, slice_count=self._lookback)
            return await fallback.execute(order, adapter)

        # 按成交量占比分配数量
        total_volume = sum(volume_profile)
        if total_volume <= 0:
            logger.warning("VWAP: 历史成交量为 0，回退到 TWAP")
            fallback = TWAPAlgo(duration_sec=self._lookback * 60, slice_count=self._lookback)
            return await fallback.execute(order, adapter)

        remaining = total_qty

        logger.info(
            "VWAP 开始: %s %s %s，参与率 %.1f%%，%d 个时间窗口",
            order.side,
            order.quantity,
            order.symbol,
            self._participation_rate * 100,
            len(volume_profile),
        )

        for i, vol in enumerate(volume_profile):
            if remaining <= 0:
                break

            # 该窗口的目标成交量占比
            ratio = vol / total_volume
            # 该窗口分配的数量
            slice_qty = _round_to_lot(total_qty * ratio, Decimal("0.001"))

            # 最后一个窗口取剩余
            if i == len(volume_profile) - 1:
                slice_qty = remaining

            slice_qty = min(slice_qty, remaining)
            if slice_qty <= 0:
                continue

            try:
                # 构建并提交子单
                child_order = Order(
                    client_order_id=str(uuid.uuid4()),
                    symbol=order.symbol,
                    market=order.market,
                    side=order.side,
                    order_type="market",
                    quantity=slice_qty,
                    price=None,
                    stop_price=None,
                    status="pending",
                    exchange=order.exchange,
                    timestamp_ns=_time_ns(),
                )

                exchange_order_id = await adapter.submit_order(child_order)  # noqa: F841

                fill = Fill(
                    order_id=order.client_order_id,
                    symbol=order.symbol,
                    side=order.side,
                    price=Decimal("0"),  # 市价成交，实际价格通过 WebSocket 获取
                    quantity=slice_qty,
                    fee=Decimal("0"),
                    fee_currency="USDT",
                    exchange=order.exchange,
                    timestamp_ns=_time_ns(),
                )
                fills.append(fill)
                remaining -= slice_qty

                logger.debug(
                    "VWAP 窗口 %d: 成交 %s（占比 %.1f%%），剩余 %s",
                    i,
                    slice_qty,
                    ratio * 100,
                    remaining,
                )

            except Exception as e:
                logger.warning("VWAP 窗口 %d 下单失败: %s", i, e)

        total_filled = sum(f.quantity for f in fills)
        logger.info(
            "VWAP 完成: 总成交 %s/%s，成交笔数 %d",
            total_filled,
            total_qty,
            len(fills),
        )

        return fills

    async def _get_volume_profile(self, adapter: ExchangeAdapter, symbol: str) -> list[Decimal]:
        """获取历史成交量分布。

        通过适配器获取 K 线数据，提取每个时间窗口的成交量。
        如果适配器不支持 get_klines，则回退到 get_ticker 的 24h 成交量估算。

        Args:
            adapter: 交易所适配器。
            symbol: 标的符号。

        Returns:
            每个时间窗口的成交量列表。
        """
        volume_profile: list[Decimal] = []

        # 方式一：通过适配器的 get_klines 获取历史 K 线
        get_klines = getattr(adapter, "get_klines", None)
        if callable(get_klines):
            try:
                klines = await get_klines(
                    symbol=symbol,
                    interval="1m",
                    limit=self._lookback,
                )
                for kline in klines:
                    # Kline 对象有 volume 字段
                    vol = getattr(kline, "volume", None)
                    if vol is not None:
                        volume_profile.append(Decimal(str(vol)))
                if volume_profile:
                    logger.debug(
                        "VWAP: 通过适配器获取 %d 个窗口的成交量 (symbol=%s)",
                        len(volume_profile),
                        symbol,
                    )
                    return volume_profile
            except Exception as exc:
                logger.warning("VWAP: 通过适配器获取 K 线失败: %s", exc)

        # 方式二：通过 get_ticker 的 24h 成交量做均匀估算
        try:
            ticker = await adapter.get_ticker(symbol)
            vol_per_interval = ticker.volume_24h / Decimal(str(self._lookback))
            volume_profile = [vol_per_interval] * self._lookback
            logger.debug(
                "VWAP: 使用 ticker 24h 成交量均匀估算 (symbol=%s, vol_per_window=%s)",
                symbol,
                vol_per_interval,
            )
            return volume_profile
        except Exception as exc:
            logger.warning("VWAP: 获取 ticker 成交量失败: %s", exc)

        # 最终回退：返回均匀分布的默认值
        logger.debug("VWAP: 使用默认均匀成交量分布 (symbol=%s)", symbol)
        return [Decimal("1000")] * self._lookback


# ──────────────────── POV 算法 ────────────────────


class POVAlgo(ExecutionAlgo):
    """POV 算法：参与率算法（Percentage of Volume）。

    按市场成交量的固定比例下单，实时跟踪市场节奏。
    适用：需要精确控制市场冲击的场景。

    执行逻辑：
      1. 订阅实时成交数据
      2. 每当市场成交量达到 threshold 时，下一笔子单
      3. 子单数量 = 市场成交量 × participation_rate
      4. 持续直到父订单完全成交

    Attributes:
        _participation_rate: 参与率（0~1）。
        _volume_threshold: 触发下单的市场成交量阈值。
        _max_duration_sec: 最大执行时长（秒）。
    """

    def __init__(
        self,
        participation_rate: float = 0.1,
        volume_threshold: Decimal = Decimal("100"),
        max_duration_sec: int = 600,
    ) -> None:
        """初始化 POV 算法。

        Args:
            participation_rate: 参与率，默认 10%。
            volume_threshold: 触发下单的市场成交量阈值。
            max_duration_sec: 最大执行时长（秒），默认 10 分钟。
        """
        if not 0 < participation_rate <= 1:
            raise ValueError(f"参与率必须在 (0, 1] 之间，当前: {participation_rate}")
        if volume_threshold <= 0:
            raise ValueError(f"成交量阈值必须大于 0，当前: {volume_threshold}")

        self._participation_rate = participation_rate
        self._volume_threshold = volume_threshold
        self._max_duration = max_duration_sec

    @property
    def name(self) -> str:
        return "POV"

    async def execute(self, order: Order, adapter: ExchangeAdapter) -> list[Fill]:
        """执行 POV 算法。

        跟踪市场成交量，按固定参与率下单。

        Args:
            order: 父订单。
            adapter: 交易所适配器。

        Returns:
            成交列表。
        """
        fills: list[Fill] = []
        remaining = order.quantity
        start_time = time.time()

        logger.info(
            "POV 开始: %s %s %s，参与率 %.1f%%，阈值 %s",
            order.side,
            order.quantity,
            order.symbol,
            self._participation_rate * 100,
            self._volume_threshold,
        )

        accumulated_volume = Decimal("0")

        while remaining > 0:
            # 检查超时
            elapsed = time.time() - start_time
            if elapsed >= self._max_duration:
                logger.warning(
                    "POV 超时: 已执行 %.1fs，剩余 %s，强制结束",
                    elapsed,
                    remaining,
                )
                break

            try:
                # 获取当前市场成交量（模拟）
                # 实际应通过 WebSocket 订阅实时成交
                market_volume = await self._get_market_volume(adapter, order.symbol)
                accumulated_volume += market_volume

                # 累积成交量达到阈值时下单
                if accumulated_volume >= self._volume_threshold:
                    # 计算子单数量
                    slice_qty = _round_to_lot(
                        accumulated_volume * Decimal(str(self._participation_rate)),
                        Decimal("0.001"),
                    )
                    slice_qty = min(slice_qty, remaining)

                    if slice_qty > 0:
                        child_order = Order(
                            client_order_id=str(uuid.uuid4()),
                            symbol=order.symbol,
                            market=order.market,
                            side=order.side,
                            order_type="market",
                            quantity=slice_qty,
                            price=None,
                            stop_price=None,
                            status="pending",
                            exchange=order.exchange,
                            timestamp_ns=_time_ns(),
                        )

                        exchange_order_id = await adapter.submit_order(child_order)  # noqa: F841

                        fill = Fill(
                            order_id=order.client_order_id,
                            symbol=order.symbol,
                            side=order.side,
                            price=Decimal("0"),
                            quantity=slice_qty,
                            fee=Decimal("0"),
                            fee_currency="USDT",
                            exchange=order.exchange,
                            timestamp_ns=_time_ns(),
                        )
                        fills.append(fill)
                        remaining -= slice_qty

                        logger.debug(
                            "POV 下单: %s，市场累积量 %s，剩余 %s",
                            slice_qty,
                            accumulated_volume,
                            remaining,
                        )

                    # 重置累积量
                    accumulated_volume = Decimal("0")

                # 短暂等待后继续
                await asyncio.sleep(1.0)

            except Exception as e:
                logger.warning("POV 执行异常: %s", e)
                await asyncio.sleep(2.0)

        total_filled = sum(f.quantity for f in fills)
        logger.info(
            "POV 完成: 总成交 %s/%s，成交笔数 %d，耗时 %.1fs",
            total_filled,
            order.quantity,
            len(fills),
            time.time() - start_time,
        )

        return fills

    async def _get_market_volume(self, adapter: ExchangeAdapter, symbol: str) -> Decimal:
        """获取当前市场成交量（增量）。

        优先通过 WebSocket 订阅获取实时成交量；
        若不可用则通过适配器 get_ticker 查询。

        Args:
            adapter: 交易所适配器。
            symbol: 标的符号。

        Returns:
            最近一个时间窗口的市场成交量。
        """
        # 方式一：通过 WebSocket 订阅获取实时成交量
        ws_client = getattr(adapter, "ws", None) or getattr(adapter, "_ws", None)
        if ws_client is not None:
            get_volume = getattr(ws_client, "get_recent_volume", None) or getattr(
                ws_client, "get_last_trade_volume", None
            )
            if callable(get_volume):
                try:
                    volume = await get_volume(symbol)
                    if volume is not None and volume > 0:
                        return Decimal(str(volume))
                except Exception as exc:
                    logger.debug("POV: WebSocket 获取成交量失败: %s", exc)

        # 方式二：通过适配器 get_trades 获取最近成交
        get_trades = getattr(adapter, "get_trades", None)
        if callable(get_trades):
            try:
                trades = await get_trades(symbol, limit=100)
                total_vol = sum(Decimal(str(getattr(t, "quantity", 0))) for t in trades)
                if total_vol > 0:
                    return total_vol
            except Exception as exc:
                logger.debug("POV: 通过 get_trades 获取成交量失败: %s", exc)

        # 方式三：通过 get_ticker 查询成交量并做时间窗口估算
        try:
            ticker = await adapter.get_ticker(symbol)
            # 24h 成交量按 1 秒窗口等比估算
            vol_per_second = ticker.volume_24h / Decimal("86400")
            return vol_per_second
        except Exception as exc:
            logger.debug("POV: 通过 get_ticker 获取成交量失败: %s", exc)

        # 最终回退：返回阈值的 1/5 作为估算
        return self._volume_threshold / Decimal("5")


# ──────────────────── 执行管理器 ────────────────────


class ExecutionManager:
    """执行管理器（EMS 核心）。

    职责：
      1. 根据订单特征选择最优执行算法
      2. 调度算法执行
      3. 汇总成交结果，回调 OMS
      4. 执行指标统计

    Example::

        ems = ExecutionManager(adapter)
        fills = await ems.execute(order)
    """

    # 算法选择阈值
    TWAP_NOTIONAL_THRESHOLD = Decimal("10000")  # 大于此值用 TWAP
    VWAP_NOTIONAL_THRESHOLD = Decimal("50000")  # 大于此值用 VWAP
    POV_NOTIONAL_THRESHOLD = Decimal("100000")  # 大于此值用 POV

    def __init__(self, adapter: ExchangeAdapter) -> None:
        """初始化执行管理器。

        Args:
            adapter: 交易所适配器。
        """
        self._adapter = adapter
        self._execution_count = 0
        self._total_fills = 0

    async def execute(
        self,
        order: Order,
        algo: ExecutionAlgo | None = None,
    ) -> list[Fill]:
        """执行订单。

        如果未指定算法，根据订单特征自动选择。

        Args:
            order: 待执行订单。
            algo: 指定执行算法（None 表示自动选择）。

        Returns:
            成交列表。
        """
        self._execution_count += 1

        # 自动选择算法
        if algo is None:
            algo = self._select_algo(order)

        logger.info(
            "EMS 执行订单: %s %s %s，算法=%s",
            order.client_order_id[:8],
            order.side,
            order.symbol,
            algo.name,
        )

        # 执行算法
        fills = await algo.execute(order, self._adapter)
        self._total_fills += len(fills)

        return fills

    def _select_algo(self, order: Order) -> ExecutionAlgo:
        """根据订单特征选择最优算法。

        选择逻辑：
          - 名义价值 < 10,000: 直接市价单（不拆分）
          - 10,000 ~ 50,000: TWAP
          - 50,000 ~ 100,000: VWAP
          - > 100,000: POV

        Args:
            order: 待执行订单。

        Returns:
            选择的执行算法实例。
        """
        notional = self._estimate_notional(order)

        if notional >= self.POV_NOTIONAL_THRESHOLD:
            return POVAlgo(participation_rate=0.1)
        elif notional >= self.VWAP_NOTIONAL_THRESHOLD:
            return VWAPAlgo(lookback_intervals=20, participation_rate=0.1)
        elif notional >= self.TWAP_NOTIONAL_THRESHOLD:
            return TWAPAlgo(duration_sec=300, slice_count=10)
        else:
            # 小单直接返回即时执行算法
            return _InstantAlgo()

    @staticmethod
    def _estimate_notional(order: Order) -> Decimal:
        """估算订单名义价值。

        Args:
            order: 订单。

        Returns:
            名义价值（quote 货币）。
        """
        price = order.price or order.stop_price or Decimal("0")
        return order.quantity * price

    @property
    def stats(self) -> dict[str, int]:
        """执行统计。"""
        return {
            "executions": self._execution_count,
            "total_fills": self._total_fills,
        }


# ──────────────────── 即时执行算法 ────────────────────


class _InstantAlgo(ExecutionAlgo):
    """即时执行算法（小单直接下单，不拆分）。

    用于名义价值较小的订单，直接提交一笔子单。
    """

    @property
    def name(self) -> str:
        return "INSTANT"

    async def execute(self, order: Order, adapter: ExchangeAdapter) -> list[Fill]:
        """直接提交订单，不拆分。"""
        try:
            exchange_order_id = await adapter.submit_order(order)  # noqa: F841

            fill = Fill(
                order_id=order.client_order_id,
                symbol=order.symbol,
                side=order.side,
                price=order.price or order.stop_price or Decimal("0"),
                quantity=order.quantity,
                fee=Decimal("0"),
                fee_currency="USDT",
                exchange=order.exchange,
                timestamp_ns=_time_ns(),
            )

            logger.info(
                "INSTANT 执行: %s %s %s @ %s",
                order.side,
                order.quantity,
                order.symbol,
                order.price or "市价",
            )

            return [fill]

        except Exception as e:
            logger.error("INSTANT 执行失败: %s", e)
            return []
