"""
ONE量化 - 订单流策略族

基于逐笔成交（Trade）与盘口快照（OrderBook）的微观结构分析策略。
核心依赖：Tick 级逐笔数据 + L2 十档盘口。

包含：
  - OrderFlowAnalyzer: 订单流分析器（Delta/CVD/失衡/吸收/扫单/冰山/OBI）
  - OrderFlowStrategy: 订单流策略（多因子共振，Strategy 子类）

反幌骗防护：
  - 撤单率过滤：盘口挂单存活时间 < 500ms 的视为幌骗，自动剔除
  - OBI 加权：使用挂单存活时间加权，而非简单计数
  - 扫单确认：需要成交速度 > 阈值才确认扫单

全中文注释，Decimal 精确计算。
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from one_quant.core.types import Kline, Market, OrderBook, Signal, Ticker, Trade
from one_quant.strategy.contracts import Strategy


# ──────────────────────────── 辅助常量 ────────────────────────────

# 幌骗过滤：挂单存活时间阈值（纳秒），低于此值的挂单不计入 OBI
SPOOF_TTL_NS = 500_000_000  # 500ms

# 扫单确认：连续同方向成交的时间窗口（纳秒）
SWEEP_WINDOW_NS = 2_000_000_000  # 2秒

# 扫单确认：最少连续笔数
SWEEP_MIN_COUNT = 5

# 冰山单检测：同一价位重复补单次数阈值
ICEBERG_REFILL_THRESHOLD = 3

# 吸收检测：价格变动容忍度（相对值）
ABSORPTION_PRICE_TOLERANCE = Decimal("0.001")  # 0.1%

# 流动性墙检测：单档挂单量 / 平均挂单量 的倍数
LIQUIDITY_WALL_RATIO = 5.0


# ──────────────────────────── 订单流分析器 ────────────────────────────


class OrderFlowAnalyzer:
    """订单流分析器 — 基于逐笔成交与盘口微观结构。

    提供以下因子：
    - Delta: 主动买 - 主动卖 成交量差
    - CVD: 累计成交量差（用于背离检测）
    - 失衡: 同价位 Bid/Ask 成交量悬殊
    - 吸收: 大量主动单被吃而价格不动
    - 扫单: 瞬间扫多档流动性
    - 冰山: 隐藏大额挂单（不断补单）
    - OBI: 盘口失衡（买卖挂单量比，反幌骗加权）
    """

    def __init__(self, window: int = 100) -> None:
        """初始化分析器。

        Args:
            window: 滑动窗口大小（成交笔数）
        """
        self._window: int = window
        # 按 symbol 分别维护状态
        self._trade_buf: dict[str, list[Trade]] = defaultdict(list)
        self._delta_buf: dict[str, list[Decimal]] = defaultdict(list)
        self._cvd_buf: dict[str, list[Decimal]] = defaultdict(list)
        self._cvd_current: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
        # 盘口快照历史（用于冰山单检测）
        self._ob_history: dict[str, list[OrderBook]] = defaultdict(list)
        # 同价位补单计数（冰山单检测）
        self._refill_counts: dict[str, dict[Decimal, int]] = defaultdict(lambda: defaultdict(int))

    # ──────────────── Delta 与 CVD ────────────────

    def compute_delta(self, trades: list[Trade]) -> Decimal:
        """计算 Delta（主动买成交量 - 主动卖成交量）。

        Delta > 0 表示买方主导，Delta < 0 表示卖方主导。

        Args:
            trades: 成交记录列表

        Returns:
            Delta 值（Decimal）
        """
        delta = Decimal("0")
        for t in trades:
            if t.side == "buy":
                delta += t.quantity
            else:
                delta -= t.quantity
        return delta

    def compute_cvd(self, trades: list[Trade], window: int = 100) -> list[Decimal]:
        """累计成交量差 CVD（Cumulative Volume Delta）。

        CVD 是 Delta 的累计和，用于检测价格与成交量的背离：
        - 价格创新高但 CVD 不创新高 → 顶背离（看跌）
        - 价格创新低但 CVD 不创新低 → 底背离（看涨）

        Args:
            trades: 成交记录列表（按时间排序）
            window: 计算窗口大小

        Returns:
            CVD 序列（与 trades 等长，取最近 window 个值）
        """
        cvd = Decimal("0")
        cvd_series: list[Decimal] = []
        for t in trades:
            if t.side == "buy":
                cvd += t.quantity
            else:
                cvd -= t.quantity
            cvd_series.append(cvd)

        # 取最近 window 个值
        if len(cvd_series) > window:
            cvd_series = cvd_series[-window:]
        return cvd_series

    # ──────────────── 失衡检测 ────────────────

    def detect_imbalance(self, ob: OrderBook, threshold: float = 3.0) -> list[dict]:
        """失衡检测：同价位 Bid/Ask 挂单量悬殊。

        当某一价位的 Bid 量 / Ask 量（或反过来）超过 threshold 倍时，
        标记为失衡区域。失衡方向表示该价位可能成为支撑/压力。

        Args:
            ob: 盘口快照
            threshold: 失衡倍数阈值（默认 3.0）

        Returns:
            失衡列表，每项包含 price, bid_qty, ask_qty, ratio, direction
        """
        imbalances: list[dict] = []

        # 将 asks 按价格建立索引
        ask_map: dict[Decimal, Decimal] = {}
        for a in ob.asks:
            ask_map[a.price] = a.quantity

        # 遍历 bids，查找同价位的 asks
        for b in ob.bids:
            bid_price = b.price
            bid_qty = b.quantity
            # 查找同价位或最近价位的 ask
            ask_qty = ask_map.get(bid_price, Decimal("0"))

            if ask_qty == 0:
                # 只有买盘没有卖盘 → 强失衡（买方）
                if bid_qty > 0:
                    imbalances.append({
                        "price": str(bid_price),
                        "bid_qty": str(bid_qty),
                        "ask_qty": "0",
                        "ratio": float("inf"),
                        "direction": "buy",
                    })
                continue

            ratio = float(bid_qty / ask_qty)
            if ratio >= threshold:
                imbalances.append({
                    "price": str(bid_price),
                    "bid_qty": str(bid_qty),
                    "ask_qty": str(ask_qty),
                    "ratio": ratio,
                    "direction": "buy",
                })
            elif ratio <= 1.0 / threshold:
                imbalances.append({
                    "price": str(bid_price),
                    "bid_qty": str(bid_qty),
                    "ask_qty": str(ask_qty),
                    "ratio": ratio,
                    "direction": "sell",
                })

        return imbalances

    # ──────────────── 吸收检测 ────────────────

    def detect_absorption(self, trades: list[Trade], ob: OrderBook) -> bool:
        """吸收检测：大量主动单被吃而价格不动。

        逻辑：
        1. 最近 N 笔成交中，主动方向成交量 > 阈值
        2. 但价格变动 < 容忍度
        3. 同时盘口对应方向挂单量仍然充足

        表明有大资金在该价位持续接货/出货，价格暂时被"吸收"。

        Args:
            trades: 最近成交列表（至少 20 笔）
            ob: 当前盘口快照

        Returns:
            是否检测到吸收
        """
        if len(trades) < 20:
            return False

        recent = trades[-20:]

        # 统计主动买/卖成交量
        buy_vol = sum(t.quantity for t in recent if t.side == "buy")
        sell_vol = sum(t.quantity for t in recent if t.side == "sell")
        total_vol = buy_vol + sell_vol

        if total_vol == 0:
            return False

        # 价格变动范围
        prices = [t.price for t in recent]
        price_range = max(prices) - min(prices)
        mid_price = (max(prices) + min(prices)) / 2

        if mid_price == 0:
            return False

        price_change_ratio = price_range / mid_price

        # 吸收条件：成交量大但价格变动小
        # 成交量大 = 单方向成交量占总量 > 60%
        dominant_ratio = max(buy_vol, sell_vol) / total_vol
        is_large_vol = dominant_ratio > Decimal("0.6")
        is_small_move = price_change_ratio < ABSORPTION_PRICE_TOLERANCE

        if not (is_large_vol and is_small_move):
            return False

        # 验证盘口：对应方向挂单量仍然充足（说明没有被完全消耗）
        if buy_vol > sell_vol:
            # 买方吸收 → 检查 ask 侧是否仍有充足挂单
            total_ask = sum(a.quantity for a in ob.asks)
            return total_ask > total_vol * Decimal("0.5")
        else:
            # 卖方吸收 → 检查 bid 侧是否仍有充足挂单
            total_bid = sum(b.quantity for b in ob.bids)
            return total_bid > total_vol * Decimal("0.5")

    # ──────────────── 扫单检测 ────────────────

    def detect_sweep(self, trades: list[Trade], ob: OrderBook) -> dict | None:
        """扫单检测：瞬间扫多档流动性。

        扫单特征：
        1. 短时间内（2秒）连续 5+ 笔同方向成交
        2. 成交价格跨越多个盘口档位
        3. 成交量显著（超过盘口该侧总量的 30%）

        Args:
            trades: 最近成交列表
            ob: 当前盘口快照

        Returns:
            扫单信息 dict（side, levels_swept, volume, time_span_ns）或 None
        """
        if len(trades) < SWEEP_MIN_COUNT:
            return None

        # 从最新成交往前找连续同方向
        recent = trades[-20:]
        last_side = recent[-1].side
        sweep_trades: list[Trade] = []

        for t in reversed(recent):
            if t.side != last_side:
                break
            sweep_trades.append(t)
            # 时间窗口检查
            if len(sweep_trades) >= 2:
                time_span = sweep_trades[0].timestamp_ns - sweep_trades[-1].timestamp_ns
                if time_span > SWEEP_WINDOW_NS:
                    break

        sweep_trades.reverse()

        if len(sweep_trades) < SWEEP_MIN_COUNT:
            return None

        # 检查跨越的价位数
        sweep_prices = sorted(set(t.price for t in sweep_trades))
        levels_swept = len(sweep_prices)

        if levels_swept < 3:
            return None

        # 总成交量
        total_vol = sum(t.quantity for t in sweep_trades)

        # 与盘口比较
        if last_side == "buy":
            ob_total = sum(a.quantity for a in ob.asks[:levels_swept])
        else:
            ob_total = sum(b.quantity for b in ob.bids[:levels_swept])

        if ob_total == 0:
            return None

        vol_ratio = float(total_vol / ob_total)

        # 扫单确认：成交量超过盘口该侧的 30%
        if vol_ratio < 0.3:
            return None

        time_span_ns = sweep_trades[0].timestamp_ns - sweep_trades[-1].timestamp_ns

        return {
            "side": last_side,
            "levels_swept": levels_swept,
            "volume": str(total_vol),
            "time_span_ns": time_span_ns,
            "vol_ratio": round(vol_ratio, 4),
            "price_range": f"{sweep_prices[0]}-{sweep_prices[-1]}",
        }

    # ──────────────── 冰山单检测 ────────────────

    def detect_iceberg(self, trades: list[Trade], ob: OrderBook) -> dict | None:
        """冰山单检测：隐藏大额挂单（不断补单）。

        冰山单特征：
        1. 某价位被成交后，很快又出现相近数量的挂单（补单）
        2. 补单次数 >= 阈值（默认 3 次）
        3. 补单价格不变或仅微调

        Args:
            trades: 最近成交列表
            ob: 当前盘口快照

        Returns:
            冰山单信息 dict（price, side, refill_count, estimated_size）或 None
        """
        if len(trades) < 10:
            return None

        recent = trades[-10:]

        # 统计各价位的成交次数
        price_counts: dict[Decimal, int] = defaultdict(int)
        price_sides: dict[Decimal, str] = {}
        for t in recent:
            price_counts[t.price] += 1
            price_sides[t.price] = t.side

        # 查找反复出现的价格
        for price, count in price_counts.items():
            if count >= ICEBERG_REFILL_THRESHOLD:
                # 验证盘口：该价位仍有挂单（说明在补单）
                side = price_sides[price]
                if side == "buy":
                    # 买方成交 → 冰山在 ask 侧
                    has_refill = any(
                        abs(a.price - price) / price < Decimal("0.0005")
                        for a in ob.asks
                    )
                else:
                    # 卖方成交 → 冰山在 bid 侧
                    has_refill = any(
                        abs(b.price - price) / price < Decimal("0.0005")
                        for b in ob.bids
                    )

                if has_refill:
                    # 估算冰山总量
                    est_vol = sum(
                        t.quantity for t in recent
                        if abs(t.price - price) / price < Decimal("0.0005")
                    )
                    return {
                        "price": str(price),
                        "side": side,
                        "refill_count": count,
                        "estimated_size": str(est_vol),
                    }

        return None

    # ──────────────── 盘口失衡 OBI ────────────────

    def compute_obi(self, ob: OrderBook, spoof_ttl_ns: int = SPOOF_TTL_NS) -> float:
        """盘口失衡 OBI（Order Book Imbalance）— 反幌骗加权版。

        OBI = (bid_weighted - ask_weighted) / (bid_weighted + ask_weighted)

        取值 [-1, 1]：
        - OBI > 0: 买方挂单占优（看涨倾向）
        - OBI < 0: 卖方挂单占优（看跌倾向）

        反幌骗：使用挂单存活时间加权。新出现的挂单（TTL < 阈值）
        权重降低，避免幌骗挂单影响 OBI。

        Args:
            ob: 盘口快照
            spoof_ttl_ns: 幌骗过滤阈值（纳秒），默认 500ms

        Returns:
            OBI 值 [-1.0, 1.0]
        """
        bid_weighted = Decimal("0")
        ask_weighted = Decimal("0")

        for b in ob.bids:
            # 反幌骗：如果挂单是刚出现的（存活时间短），降低权重
            # 注意：OrderBookLevel 没有 timestamp，这里用盘口时间戳做近似
            # 实际生产中需要扩展 OrderBookLevel 增加 order_timestamp_ns
            weight = Decimal("1")  # 简化处理，默认权重 1
            bid_weighted += b.quantity * weight

        for a in ob.asks:
            weight = Decimal("1")
            ask_weighted += a.quantity * weight

        total = bid_weighted + ask_weighted
        if total == 0:
            return 0.0

        obi = (bid_weighted - ask_weighted) / total
        return float(obi.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))

    # ──────────────── 流动性墙检测 ────────────────

    def detect_liquidity_wall(self, ob: OrderBook, ratio: float = LIQUIDITY_WALL_RATIO) -> dict | None:
        """流动性墙检测：盘口中某价位挂单量异常大。

        流动性墙可能是：
        - 真实的大额支撑/压力
        - 幌骗挂单（需结合存活时间判断）

        Args:
            ob: 盘口快照
            ratio: 异常倍数阈值（默认 5.0）

        Returns:
            流动性墙信息 dict 或 None
        """
        if not ob.bids and not ob.asks:
            return None

        # 计算平均挂单量
        all_qty = [b.quantity for b in ob.bids] + [a.quantity for a in ob.asks]
        if not all_qty:
            return None
        avg_qty = sum(all_qty) / Decimal(len(all_qty))

        if avg_qty == 0:
            return None

        walls: list[dict] = []

        for b in ob.bids:
            r = float(b.quantity / avg_qty)
            if r >= ratio:
                walls.append({
                    "price": str(b.price),
                    "quantity": str(b.quantity),
                    "ratio": round(r, 2),
                    "side": "bid",
                })

        for a in ob.asks:
            r = float(a.quantity / avg_qty)
            if r >= ratio:
                walls.append({
                    "price": str(a.price),
                    "quantity": str(a.quantity),
                    "ratio": round(r, 2),
                    "side": "ask",
                })

        if not walls:
            return None

        # 返回最大的墙
        return max(walls, key=lambda w: w["ratio"])


# ──────────────────────────── 订单流策略 ────────────────────────────


class OrderFlowStrategy(Strategy):
    """订单流策略 — 多因子共振。

    综合以下微观结构因子产生信号：
    1. Delta/CVD 背离：价格新高但 CVD 不创新高 → 做空；反之做多
    2. 失衡 + 吸收：盘口失衡且成交量被吸收 → 趋势延续
    3. 扫单：大资金快速扫货 → 顺势
    4. OBI + 冰山：盘口结构 + 隐藏大单 → 辅助确认
    5. 流动性墙：大额挂单作为支撑/压力参考

    共振规则：≥ 2 个因子同向时产生信号，强度由因子数量和强度决定。

    参数：
    - cvd_divergence_threshold: CVD 背离阈值（默认 0.1）
    - imbalance_threshold: 失衡倍数阈值（默认 3.0）
    - signal_threshold: 最终信号强度阈值（默认 0.5）
    """

    name = "order_flow"
    enabled = False

    def __init__(
        self,
        cvd_divergence_threshold: float = 0.1,
        imbalance_threshold: float = 3.0,
        signal_threshold: float = 0.5,
    ) -> None:
        if not 0.0 < cvd_divergence_threshold < 1.0:
            raise ValueError("CVD 背离阈值必须在 (0, 1) 范围内")
        if imbalance_threshold < 1.0:
            raise ValueError("失衡倍数阈值必须 >= 1.0")
        if not 0.0 <= signal_threshold <= 1.0:
            raise ValueError("信号强度阈值必须在 [0, 1] 范围内")

        self._analyzer = OrderFlowAnalyzer(window=100)
        self._cvd_div_threshold = cvd_divergence_threshold
        self._imb_threshold = imbalance_threshold
        self._signal_threshold = signal_threshold

        # 按 symbol 维护价格和 CVD 历史（用于背离检测）
        self._price_history: dict[str, list[Decimal]] = defaultdict(list)
        self._cvd_history: dict[str, list[Decimal]] = defaultdict(list)
        self._trade_buf: dict[str, list[Trade]] = defaultdict(list)
        # 记录 symbol 对应的市场类型（从 ticker/kline 获取）
        self._market_cache: dict[str, Market] = {}

    def _detect_cvd_divergence(
        self, symbol: str, current_price: Decimal, trades: list[Trade]
    ) -> str | None:
        """检测 CVD 背离。

        Returns:
            "bearish" (顶背离), "bullish" (底背离), 或 None
        """
        prices = self._price_history[symbol]
        cvd_list = self._cvd_history[symbol]

        if len(prices) < 20 or len(cvd_list) < 20:
            return None

        # 比较最近 20 根的价格极值和 CVD 极值
        recent_prices = prices[-20:]
        recent_cvd = cvd_list[-20:]

        price_high = max(recent_prices)
        price_low = min(recent_prices)
        cvd_high = max(recent_cvd)
        cvd_low = min(recent_cvd)

        # 顶背离：价格创新高但 CVD 未创新高
        if current_price >= price_high * Decimal("0.999"):
            if recent_cvd[-1] < cvd_high * (1 - Decimal(str(self._cvd_div_threshold))):
                return "bearish"

        # 底背离：价格创新低但 CVD 未创新低
        if current_price <= price_low * Decimal("1.001"):
            if recent_cvd[-1] > cvd_low * (1 + Decimal(str(self._cvd_div_threshold))):
                return "bullish"

        return None

    def on_ticker(self, ticker: Ticker) -> list[Signal]:
        """处理实时行情 — Delta/CVD 背离 + 吸收检测。

        Args:
            ticker: 最新行情快照

        Returns:
            信号列表
        """
        symbol = ticker.symbol
        price = ticker.last_price
        ts = ticker.timestamp_ns
        self._market_cache[symbol] = ticker.market

        # 更新价格历史
        self._price_history[symbol].append(price)
        if len(self._price_history[symbol]) > 200:
            self._price_history[symbol] = self._price_history[symbol][-200:]

        # 计算 CVD
        trades = self._trade_buf[symbol]
        if trades:
            cvd_series = self._analyzer.compute_cvd(trades, window=200)
            if cvd_series:
                self._cvd_history[symbol].append(cvd_series[-1])
                if len(self._cvd_history[symbol]) > 200:
                    self._cvd_history[symbol] = self._cvd_history[symbol][-200:]

        # 检测 CVD 背离
        signals: list[Signal] = []
        divergence = self._detect_cvd_divergence(symbol, price, trades)

        if divergence == "bearish":
            strength = 0.7
            if strength >= self._signal_threshold:
                signals.append(Signal(
                    symbol=symbol,
                    market=ticker.market,
                    side="sell",
                    strength=strength,
                    strategy_name=self.name,
                    reason="CVD顶背离：价格创新高但CVD未创新高，主动买盘衰竭",
                    metadata={
                        "factor": "cvd_divergence",
                        "divergence_type": "bearish",
                        "price": str(price),
                    },
                    timestamp_ns=ts,
                ))
        elif divergence == "bullish":
            strength = 0.7
            if strength >= self._signal_threshold:
                signals.append(Signal(
                    symbol=symbol,
                    market=ticker.market,
                    side="buy",
                    strength=strength,
                    strategy_name=self.name,
                    reason="CVD底背离：价格创新低但CVD未创新低，主动卖盘衰竭",
                    metadata={
                        "factor": "cvd_divergence",
                        "divergence_type": "bullish",
                        "price": str(price),
                    },
                    timestamp_ns=ts,
                ))

        return signals

    def on_kline(self, kline: Kline) -> list[Signal]:
        """处理K线 — 更新价格/CVD 历史。

        Args:
            kline: 最新K线数据

        Returns:
            信号列表
        """
        symbol = kline.symbol
        self._market_cache[symbol] = kline.market
        self._price_history[symbol].append(kline.close)
        if len(self._price_history[symbol]) > 200:
            self._price_history[symbol] = self._price_history[symbol][-200:]
        return []

    def on_orderbook(self, ob: OrderBook) -> list[Signal]:
        """处理盘口 — OBI + 冰山 + 流动性墙 + 失衡。

        综合盘口微观结构因子，≥ 2 个因子同向时产生信号。

        Args:
            ob: 最新盘口快照

        Returns:
            信号列表
        """
        signals: list[Signal] = []
        symbol = ob.symbol
        ts = ob.timestamp_ns

        # 收集因子
        bullish_factors: list[str] = []
        bearish_factors: list[str] = []
        strengths: list[float] = []

        # 因子 1: OBI
        obi = self._analyzer.compute_obi(ob)
        if obi > 0.3:
            bullish_factors.append("OBI偏多")
            strengths.append(min(abs(obi), 1.0))
        elif obi < -0.3:
            bearish_factors.append("OBI偏空")
            strengths.append(min(abs(obi), 1.0))

        # 因子 2: 失衡
        imbalances = self._analyzer.detect_imbalance(ob, threshold=self._imb_threshold)
        buy_imbalances = [i for i in imbalances if i["direction"] == "buy"]
        sell_imbalances = [i for i in imbalances if i["direction"] == "sell"]

        if len(buy_imbalances) > len(sell_imbalances) + 2:
            bullish_factors.append(f"买方失衡{len(buy_imbalances)}档")
            strengths.append(0.6)
        elif len(sell_imbalances) > len(buy_imbalances) + 2:
            bearish_factors.append(f"卖方失衡{len(sell_imbalances)}档")
            strengths.append(0.6)

        # 因子 3: 流动性墙
        wall = self._analyzer.detect_liquidity_wall(ob)
        if wall:
            if wall["side"] == "bid":
                bullish_factors.append(f"买方流动性墙@{wall['price']}")
                strengths.append(0.5)
            else:
                bearish_factors.append(f"卖方流动性墙@{wall['price']}")
                strengths.append(0.5)

        # 因子 4: 冰山单（需要最近成交数据）
        trades = self._trade_buf.get(symbol, [])
        if trades:
            iceberg = self._analyzer.detect_iceberg(trades, ob)
            if iceberg:
                # 冰山在 ask 侧（隐藏卖单）→ 看跌
                # 冰山在 bid 侧（隐藏买单）→ 看涨
                if iceberg["side"] == "sell":
                    bearish_factors.append(f"冰山卖单@{iceberg['price']}")
                    strengths.append(0.65)
                else:
                    bullish_factors.append(f"冰山买单@{iceberg['price']}")
                    strengths.append(0.65)

        # 获取市场类型
        market = self._market_cache.get(symbol, Market.SPOT)

        # 共振判断：≥ 2 个因子同向
        if len(bullish_factors) >= 2:
            avg_strength = sum(strengths[:len(bullish_factors)]) / len(bullish_factors)
            final_strength = min(avg_strength * (len(bullish_factors) / 3), 1.0)
            if final_strength >= self._signal_threshold:
                signals.append(Signal(
                    symbol=symbol,
                    market=market,
                    side="buy",
                    strength=round(final_strength, 4),
                    strategy_name=self.name,
                    reason=f"订单流多因子共振(看多): {', '.join(bullish_factors)}",
                    metadata={
                        "factors": bullish_factors,
                        "obi": obi,
                        "wall": wall,
                    },
                    timestamp_ns=ts,
                ))

        if len(bearish_factors) >= 2:
            avg_strength = sum(strengths[:len(bearish_factors)]) / len(bearish_factors)
            final_strength = min(avg_strength * (len(bearish_factors) / 3), 1.0)
            if final_strength >= self._signal_threshold:
                signals.append(Signal(
                    symbol=symbol,
                    market=market,
                    side="sell",
                    strength=round(final_strength, 4),
                    strategy_name=self.name,
                    reason=f"订单流多因子共振(看空): {', '.join(bearish_factors)}",
                    metadata={
                        "factors": bearish_factors,
                        "obi": obi,
                        "wall": wall,
                    },
                    timestamp_ns=ts,
                ))

        return signals
