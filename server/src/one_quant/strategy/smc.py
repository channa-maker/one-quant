"""
ONE量化 - SMC (Smart Money Concepts) 策略族

基于市场结构（Market Structure）的机构级策略框架。
SMC 核心概念：BOS/CHoCH、Order Block、Fair Value Gap、流动性池。

包含：
  - SMCAnalyzer: SMC 结构分析器（BOS/CHoCH/OB/FVG/流动性）
  - SmartMoneyIndex: 聪明钱指数（经典 SMI + SMC 结构线）
  - SMCStrategy: SMC 策略（基于市场结构，Strategy 子类）

全中文注释，Decimal 精确计算。
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from one_quant.core.types import Kline, Market, Signal, Ticker
from one_quant.strategy.contracts import Strategy

# ──────────────────────────── SMC 结构分析器 ────────────────────────────


class SMCAnalyzer:
    """SMC 结构分析器。

    提供以下结构因子：
    - BOS: Break of Structure（市场结构破坏）
    - CHoCH: Change of Character（趋势转换信号）
    - Order Block: 订单块（机构挂单区域）
    - Fair Value Gap (FVG): 公允价值缺口（价格不平衡区域）
    - 流动性池: 等高/等低点止损聚集区
    - 流动性猎杀: 假突破扫止损后反转
    - 溢价/折价区: 基于近期波段的价格位置判断
    """

    # 结构检测参数
    SWING_LOOKBACK = 5  # Swing 高低点回看K线数
    OB_LOOKBACK = 20  # Order Block 搜索范围
    FVG_MIN_GAP_RATIO = 0.001  # FVG 最小缺口比例（占价格的 0.1%）
    LIQUIDITY_TOLERANCE = Decimal("0.002")  # 等高/等低点容差（0.2%）

    def __init__(self) -> None:
        # 按 symbol 维护结构状态
        self._trend: dict[str, str] = {}  # "bullish" / "bearish"
        self._last_bos: dict[str, dict | None] = {}
        self._last_choch: dict[str, dict | None] = {}

    # ──────────────── Swing 高低点识别 ────────────────

    def _find_swing_highs(self, highs: list[Decimal], lookback: int = SWING_LOOKBACK) -> list[dict]:
        """识别 Swing 高点（局部极值）。

        Swing 高点定义：某根K线的 high 是前后 lookback 根K线中最高的。

        Args:
            highs: 最高价序列（按时间排序）
            lookback: 回看/前瞻K线数

        Returns:
            Swing 高点列表 [{index, price}]
        """
        swings: list[dict] = []
        for i in range(lookback, len(highs) - lookback):
            is_highest = all(
                highs[i] >= highs[j] for j in range(i - lookback, i + lookback + 1) if j != i
            )
            if is_highest:
                swings.append({"index": i, "price": highs[i]})
        return swings

    def _find_swing_lows(self, lows: list[Decimal], lookback: int = SWING_LOOKBACK) -> list[dict]:
        """识别 Swing 低点（局部极值）。

        Args:
            lows: 最低价序列
            lookback: 回看/前瞻K线数

        Returns:
            Swing 低点列表 [{index, price}]
        """
        swings: list[dict] = []
        for i in range(lookback, len(lows) - lookback):
            is_lowest = all(
                lows[i] <= lows[j] for j in range(i - lookback, i + lookback + 1) if j != i
            )
            if is_lowest:
                swings.append({"index": i, "price": lows[i]})
        return swings

    # ──────────────── BOS 市场结构破坏 ────────────────

    def detect_bos(self, highs: list[Decimal], lows: list[Decimal]) -> dict | None:
        """BOS（Break of Structure）— 市场结构破坏。

        BOS 发生在趋势延续时：
        - 上升趋势中，价格突破前一个 Swing 高点 → Bullish BOS
        - 下降趋势中，价格跌破前一个 Swing 低点 → Bearish BOS

        BOS 不改变趋势方向，而是确认趋势延续。

        Args:
            highs: 最高价序列
            lows: 最低价序列

        Returns:
            BOS 信息 dict（type, price, swing_price, index）或 None
        """
        if len(highs) < 15 or len(lows) < 15:
            return None

        swing_highs = self._find_swing_highs(highs)
        swing_lows = self._find_swing_lows(lows)

        if len(swing_highs) < 2 or len(swing_lows) < 2:
            return None

        current_high = highs[-1]
        current_low = lows[-1]

        # Bullish BOS：最新 high 突破前一个 Swing 高点
        prev_sh = swing_highs[-2]  # 倒数第二个（前一个确认的）
        if current_high > prev_sh["price"]:
            return {
                "type": "bullish_bos",
                "price": str(current_high),
                "swing_price": str(prev_sh["price"]),
                "index": len(highs) - 1,
                "swing_index": prev_sh["index"],
            }

        # Bearish BOS：最新 low 跌破前一个 Swing 低点
        prev_sl = swing_lows[-2]
        if current_low < prev_sl["price"]:
            return {
                "type": "bearish_bos",
                "price": str(current_low),
                "swing_price": str(prev_sl["price"]),
                "index": len(lows) - 1,
                "swing_index": prev_sl["index"],
            }

        return None

    # ──────────────── CHoCH 趋势转换 ────────────────

    def detect_choch(self, highs: list[Decimal], lows: list[Decimal], trend: str) -> dict | None:
        """CHoCH（Change of Character）— 趋势转换信号。

        CHoCH 发生在趋势反转时：
        - 上升趋势中，价格跌破最近的 Swing 低点 → Bearish CHoCH（趋势可能转空）
        - 下降趋势中，价格突破最近的 Swing 高点 → Bullish CHoCH（趋势可能转多）

        与 BOS 的区别：BOS 确认趋势延续，CHoCH 预示趋势反转。

        Args:
            highs: 最高价序列
            lows: 最低价序列
            trend: 当前趋势方向（"bullish" 或 "bearish"）

        Returns:
            CHoCH 信息 dict 或 None
        """
        if len(highs) < 15 or len(lows) < 15:
            return None

        swing_highs = self._find_swing_highs(highs)
        swing_lows = self._find_swing_lows(lows)

        current_high = highs[-1]
        current_low = lows[-1]

        if trend == "bullish" and swing_lows:
            # 上升趋势中，跌破最近 Swing 低点 → 看跌 CHoCH
            last_sl = swing_lows[-1]
            if current_low < last_sl["price"]:
                return {
                    "type": "bearish_choch",
                    "price": str(current_low),
                    "swing_price": str(last_sl["price"]),
                    "index": len(lows) - 1,
                    "swing_index": last_sl["index"],
                    "prev_trend": trend,
                }

        elif trend == "bearish" and swing_highs:
            # 下降趋势中，突破最近 Swing 高点 → 看涨 CHoCH
            last_sh = swing_highs[-1]
            if current_high > last_sh["price"]:
                return {
                    "type": "bullish_choch",
                    "price": str(current_high),
                    "swing_price": str(last_sh["price"]),
                    "index": len(highs) - 1,
                    "swing_index": last_sh["index"],
                    "prev_trend": trend,
                }

        return None

    # ──────────────── Order Block 订单块 ────────────────

    def find_order_blocks(self, klines: list[Kline]) -> list[dict]:
        """Order Block 订单块识别。

        Order Block 是机构大额挂单区域，表现为：
        - Bullish OB: 一根或连续多根看跌K线之后紧接一根强势看涨K线（吞没），
          看跌K线的区域即为看涨 OB（支撑）
        - Bearish OB: 一根或连续多根看涨K线之后紧接一根强势看跌K线（吞没），
          看涨K线的区域即为看跌 OB（压力）

        Args:
            klines: K线序列

        Returns:
            Order Block 列表 [{type, top, bottom, index, strength}]
        """
        if len(klines) < 5:
            return []

        order_blocks: list[dict] = []

        for i in range(2, len(klines) - 1):
            k = klines[i]
            k_prev = klines[i - 1]
            k_next = klines[i + 1]

            body_prev = k_prev.close - k_prev.open
            _body = k.close - k.open  # noqa: F841
            body_next = k_next.close - k_next.open

            # Bullish OB: 前一根看跌 + 当前根被下一根强势吞没看涨
            if body_prev < 0 and body_next > 0:
                # 吞没条件：下一根的实体完全覆盖当前根
                if k_next.close > k.open and k_next.open < k.close:
                    ob_top = max(k.open, k.close)
                    ob_bottom = min(k.open, k.close)
                    # OB 强度 = 吞没K线实体大小 / 当前价格
                    strength = float(abs(body_next) / k_next.close) if k_next.close > 0 else 0
                    order_blocks.append(
                        {
                            "type": "bullish_ob",
                            "top": str(ob_top),
                            "bottom": str(ob_bottom),
                            "index": i,
                            "strength": min(strength * 100, 1.0),  # 归一化
                            "volume": str(k.volume),
                        }
                    )

            # Bearish OB: 前一根看涨 + 当前根被下一根强势吞没看跌
            elif body_prev > 0 and body_next < 0:
                if k_next.close < k.open and k_next.open > k.close:
                    ob_top = max(k.open, k.close)
                    ob_bottom = min(k.open, k.close)
                    strength = float(abs(body_next) / k_next.close) if k_next.close > 0 else 0
                    order_blocks.append(
                        {
                            "type": "bearish_ob",
                            "top": str(ob_top),
                            "bottom": str(ob_bottom),
                            "index": i,
                            "strength": min(strength * 100, 1.0),
                            "volume": str(k.volume),
                        }
                    )

        # 只保留最近的 OB（最多 10 个）
        return order_blocks[-10:]

    # ──────────────── Fair Value Gap (FVG) ────────────────

    def find_fvg(self, klines: list[Kline]) -> list[dict]:
        """Fair Value Gap 公允价值缺口识别。

        FVG 是三根K线之间形成的价格缺口：
        - Bullish FVG: 第 3 根K线的 low > 第 1 根K线的 high（向上缺口）
          → 价格可能回补到第 1 根 high 附近
        - Bearish FVG: 第 3 根K线的 high < 第 1 根K线的 low（向下缺口）
          → 价格可能回补到第 1 根 low 附近

        Args:
            klines: K线序列

        Returns:
            FVG 列表 [{type, top, bottom, index, gap_size, gap_ratio}]
        """
        if len(klines) < 3:
            return []

        fvgs: list[dict] = []

        for i in range(2, len(klines)):
            k1 = klines[i - 2]  # 第 1 根
            # k2 = klines[i - 1]  # 第 2 根（中间根）
            k3 = klines[i]  # 第 3 根

            # Bullish FVG: 第 3 根 low > 第 1 根 high
            if k3.low > k1.high:
                gap = k3.low - k1.high
                gap_ratio = float(gap / k1.high) if k1.high > 0 else 0
                if gap_ratio >= self.FVG_MIN_GAP_RATIO:
                    fvgs.append(
                        {
                            "type": "bullish_fvg",
                            "top": str(k3.low),
                            "bottom": str(k1.high),
                            "index": i,
                            "gap_size": str(gap),
                            "gap_ratio": round(gap_ratio, 6),
                        }
                    )

            # Bearish FVG: 第 3 根 high < 第 1 根 low
            elif k3.high < k1.low:
                gap = k1.low - k3.high
                gap_ratio = float(gap / k1.low) if k1.low > 0 else 0
                if gap_ratio >= self.FVG_MIN_GAP_RATIO:
                    fvgs.append(
                        {
                            "type": "bearish_fvg",
                            "top": str(k1.low),
                            "bottom": str(k3.high),
                            "index": i,
                            "gap_size": str(gap),
                            "gap_ratio": round(gap_ratio, 6),
                        }
                    )

        # 只保留最近的 FVG（最多 10 个）
        return fvgs[-10:]

    # ──────────────── 流动性池 ────────────────

    def find_liquidity_pools(self, highs: list[Decimal], lows: list[Decimal]) -> list[dict]:
        """流动性池识别：等高/等低点止损聚集区。

        流动性池特征：
        - 多个 Swing 高点聚集在同一价位（等高点）→ 止损单堆积在上方
        - 多个 Swing 低点聚集在同一价位（等低点）→ 止损单堆积在下方
        - 机构会猎杀这些流动性（扫止损后反转）

        Args:
            highs: 最高价序列
            lows: 最低价序列

        Returns:
            流动性池列表 [{type, price, touch_count, indices}]
        """
        swing_highs = self._find_swing_highs(highs)
        swing_lows = self._find_swing_lows(lows)

        pools: list[dict] = []

        # 查找等高点（高点聚集）
        used_highs: set[int] = set()
        for i, sh in enumerate(swing_highs):
            if i in used_highs:
                continue
            cluster = [sh]
            used_highs.add(i)
            for j in range(i + 1, len(swing_highs)):
                if j in used_highs:
                    continue
                # 价格接近（在容差范围内）
                if (
                    abs(swing_highs[j]["price"] - sh["price"]) / sh["price"]
                    < self.LIQUIDITY_TOLERANCE
                ):
                    cluster.append(swing_highs[j])
                    used_highs.add(j)

            if len(cluster) >= 2:
                avg_price = sum(c["price"] for c in cluster) / Decimal(len(cluster))
                pools.append(
                    {
                        "type": "sell_side_liquidity",  # 止损在高点上方（做空者的止损）
                        "price": str(avg_price),
                        "touch_count": len(cluster),
                        "indices": [c["index"] for c in cluster],
                    }
                )

        # 查找等低点（低点聚集）
        used_lows: set[int] = set()
        for i, sl in enumerate(swing_lows):
            if i in used_lows:
                continue
            cluster = [sl]
            used_lows.add(i)
            for j in range(i + 1, len(swing_lows)):
                if j in used_lows:
                    continue
                if (
                    abs(swing_lows[j]["price"] - sl["price"]) / sl["price"]
                    < self.LIQUIDITY_TOLERANCE
                ):
                    cluster.append(swing_lows[j])
                    used_lows.add(j)

            if len(cluster) >= 2:
                avg_price = sum(c["price"] for c in cluster) / Decimal(len(cluster))
                pools.append(
                    {
                        "type": "buy_side_liquidity",  # 止损在低点下方（做多者的止损）
                        "price": str(avg_price),
                        "touch_count": len(cluster),
                        "indices": [c["index"] for c in cluster],
                    }
                )

        return pools

    # ──────────────── 流动性猎杀 ────────────────

    def detect_liquidity_grab(self, klines: list[Kline], pools: list[dict]) -> dict | None:
        """流动性猎杀检测：假突破扫止损后反转。

        流动性猎杀特征：
        1. 价格突破流动性池价位（扫止损）
        2. 随后快速反转回到池价位内
        3. 反转K线形成吞没或长影线

        Args:
            klines: K线序列
            pools: 流动性池列表（来自 find_liquidity_pools）

        Returns:
            猎杀信息 dict 或 None
        """
        if len(klines) < 3 or not pools:
            return None

        k_current = klines[-1]
        k_prev = klines[-2]

        for pool in pools:
            pool_price = Decimal(pool["price"])

            if pool["type"] == "sell_side_liquidity":
                # 做空止损在上方被扫 → 价格先突破高点再回落
                if k_prev.high > pool_price and k_current.close < pool_price:
                    # 长上影线或吞没确认反转
                    upper_wick = k_prev.high - max(k_prev.open, k_prev.close)
                    body = abs(k_prev.close - k_prev.open)
                    if body == 0 or upper_wick > body:
                        return {
                            "type": "sell_side_grab",
                            "pool_price": str(pool_price),
                            "grab_high": str(k_prev.high),
                            "close": str(k_current.close),
                            "reversal_strength": float(
                                (k_prev.high - k_current.close) / k_current.close
                            )
                            if k_current.close > 0
                            else 0,
                            "signal": "bullish",  # 扫完上方止损 → 做多
                        }

            elif pool["type"] == "buy_side_liquidity":
                # 做多止损在下方被扫 → 价格先跌破低点再反弹
                if k_prev.low < pool_price and k_current.close > pool_price:
                    lower_wick = min(k_prev.open, k_prev.close) - k_prev.low
                    body = abs(k_prev.close - k_prev.open)
                    if body == 0 or lower_wick > body:
                        return {
                            "type": "buy_side_grab",
                            "pool_price": str(pool_price),
                            "grab_low": str(k_prev.low),
                            "close": str(k_current.close),
                            "reversal_strength": float(
                                (k_current.close - k_prev.low) / k_current.close
                            )
                            if k_current.close > 0
                            else 0,
                            "signal": "bearish",  # 扫完下方止损 → 做空
                        }

        return None

    # ──────────────── 溢价/折价区 ────────────────

    def premium_discount(self, klines: list[Kline]) -> str:
        """溢价/折价区判断。

        基于近期波段的 50% 回撤位（均衡价位）判断当前价格位置：
        - Premium（溢价区）：价格在均衡价位上方 → 卖出区域
        - Discount（折价区）：价格在均衡价位下方 → 买入区域
        - Equilibrium（均衡区）：价格接近均衡价位

        Args:
            klines: K线序列（至少 20 根）

        Returns:
            "premium" / "discount" / "equilibrium"
        """
        if len(klines) < 20:
            return "equilibrium"

        recent = klines[-20:]
        highest = max(k.high for k in recent)
        lowest = min(k.low for k in recent)

        if highest == lowest:
            return "equilibrium"

        # 50% 回撤位 = 均衡价位
        _equilibrium = (highest + lowest) / 2  # noqa: F841
        current = klines[-1].close

        # 计算当前价格在波段中的位置（0~1）
        position = (current - lowest) / (highest - lowest)

        if position > Decimal("0.6"):
            return "premium"
        elif position < Decimal("0.4"):
            return "discount"
        else:
            return "equilibrium"

    # ──────────────── 趋势管理 ────────────────

    def update_trend(self, symbol: str, highs: list[Decimal], lows: list[Decimal]) -> str:
        """更新并返回当前趋势。

        趋势判断逻辑：
        - 连续更高的高点 + 更高的低点 → bullish
        - 连续更低的高点 + 更低的低点 → bearish

        Args:
            symbol: 标的符号
            highs: 最高价序列
            lows: 最低价序列

        Returns:
            当前趋势方向 "bullish" / "bearish"
        """
        if len(highs) < 10 or len(lows) < 10:
            return self._trend.get(symbol, "bullish")

        swing_highs = self._find_swing_highs(highs)
        swing_lows = self._find_swing_lows(lows)

        if len(swing_highs) < 2 or len(swing_lows) < 2:
            return self._trend.get(symbol, "bullish")

        # 比较最近两个 swing 高点和低点
        higher_high = swing_highs[-1]["price"] > swing_highs[-2]["price"]
        higher_low = swing_lows[-1]["price"] > swing_lows[-2]["price"]
        lower_high = swing_highs[-1]["price"] < swing_highs[-2]["price"]
        lower_low = swing_lows[-1]["price"] < swing_lows[-2]["price"]

        if higher_high and higher_low:
            self._trend[symbol] = "bullish"
        elif lower_high and lower_low:
            self._trend[symbol] = "bearish"

        return self._trend.get(symbol, "bullish")


# ──────────────────────────── 聪明钱指数 ────────────────────────────


class SmartMoneyIndex:
    """聪明钱指数 — 两种实现。

    1. 经典 SMI：基于"早盘散户、尾盘机构"的假设，
       累计（尾盘涨幅 - 早盘涨幅）作为聪明钱指标。
    2. SMC 结构线：自动标注 BOS/CHoCH/OB/FVG 的可视化结构线。
    """

    def classic_smi(
        self,
        opens: list[Decimal],
        closes: list[Decimal],
        volumes: list[Decimal],
    ) -> list[Decimal]:
        """经典 Smart Money Index。

        原理：散户在早盘活跃（开盘方向），机构在尾盘活跃（收盘方向）。
        SMI = 累计(收盘变动 - 开盘变动)

        当 SMI 上升 → 聪明钱买入
        当 SMI 下降 → 聪明钱卖出

        Args:
            opens: 开盘价序列
            closes: 收盘价序列
            volumes: 成交量序列（用于加权）

        Returns:
            SMI 序列（与输入等长）
        """
        if len(opens) != len(closes) or len(opens) < 2:
            return []

        smi = Decimal("0")
        smi_series: list[Decimal] = [Decimal("0")]  # 第一根无意义

        for i in range(1, len(opens)):
            # 收盘变动（机构段）
            close_change = closes[i] - closes[i - 1]
            # 开盘变动（散户段）
            open_change = opens[i] - opens[i - 1]
            # SMI 累计差
            smi += close_change - open_change
            smi_series.append(smi)

        return smi_series

    def smc_structure_line(self, klines: list[Kline]) -> list[dict]:
        """SMC 结构线：自动标注 BOS/CHoCH/OB/FVG。

        综合分析K线序列，输出所有结构事件的时间线。

        Args:
            klines: K线序列

        Returns:
            结构事件列表 [{event_type, ...details}]
        """
        if len(klines) < 10:
            return []

        analyzer = SMCAnalyzer()
        highs = [k.high for k in klines]
        lows = [k.low for k in klines]

        events: list[dict] = []

        # 1. 更新趋势
        trend = analyzer.update_trend("auto", highs, lows)

        # 2. 检测 BOS
        bos = analyzer.detect_bos(highs, lows)
        if bos:
            bos["event"] = "BOS"
            events.append(bos)

        # 3. 检测 CHoCH
        choch = analyzer.detect_choch(highs, lows, trend)
        if choch:
            choch["event"] = "CHoCH"
            events.append(choch)

        # 4. 查找 Order Blocks
        obs = analyzer.find_order_blocks(klines)
        for ob in obs:
            ob["event"] = "OB"
            events.append(ob)

        # 5. 查找 FVG
        fvgs = analyzer.find_fvg(klines)
        for fvg in fvgs:
            fvg["event"] = "FVG"
            events.append(fvg)

        # 6. 查找流动性池
        pools = analyzer.find_liquidity_pools(highs, lows)
        for pool in pools:
            pool["event"] = "LIQUIDITY_POOL"
            events.append(pool)

        # 按 index 排序
        events.sort(key=lambda e: e.get("index", 0))

        return events


# ──────────────────────────── SMC 策略 ────────────────────────────


class SMCStrategy(Strategy):
    """SMC 策略 — 基于市场结构。

    信号逻辑：
    1. BOS/CHoCH → 确定趋势方向
    2. Order Block → 识别支撑/压力位
    3. FVG → 确定回补目标
    4. 流动性猎杀 → 反转信号
    5. 溢价/折价区 → 确认入场区域

    入场条件：
    - 趋势方向明确（BOS 确认）
    - 价格回踩 Order Block（支撑/压力）
    - 处于折价区（做多）或溢价区（做空）
    - 或：流动性猎杀 + CHoCH 反转信号

    参数：
    - ob_proximity_ratio: 价格接近 OB 的容差比例（默认 0.005 = 0.5%）
    - signal_threshold: 信号强度阈值（默认 0.5）
    """

    name = "smc"
    enabled = False

    def __init__(
        self,
        ob_proximity_ratio: float = 0.005,
        signal_threshold: float = 0.5,
    ) -> None:
        if not 0.0 < ob_proximity_ratio < 0.1:
            raise ValueError("OB 接近容差必须在 (0, 0.1) 范围内")
        if not 0.0 <= signal_threshold <= 1.0:
            raise ValueError("信号强度阈值必须在 [0, 1] 范围内")

        self._analyzer = SMCAnalyzer()
        self._smi = SmartMoneyIndex()
        self._ob_proximity = ob_proximity_ratio
        self._signal_threshold = signal_threshold

        # 按 symbol 维护K线缓冲
        self._kline_buf: dict[str, list[Kline]] = defaultdict(list)
        self._highs: dict[str, list[Decimal]] = defaultdict(list)
        self._lows: dict[str, list[Decimal]] = defaultdict(list)
        self._market_cache: dict[str, Market] = {}

    def _update_buffers(self, kline: Kline) -> None:
        """更新K线和高低点缓冲。"""
        symbol = kline.symbol
        self._market_cache[symbol] = kline.market

        self._kline_buf[symbol].append(kline)
        if len(self._kline_buf[symbol]) > 100:
            self._kline_buf[symbol] = self._kline_buf[symbol][-100:]

        self._highs[symbol].append(kline.high)
        if len(self._highs[symbol]) > 100:
            self._highs[symbol] = self._highs[symbol][-100:]

        self._lows[symbol].append(kline.low)
        if len(self._lows[symbol]) > 100:
            self._lows[symbol] = self._lows[symbol][-100:]

    def _check_ob_proximity(self, price: Decimal, obs: list[dict]) -> dict | None:
        """检查价格是否接近某个 Order Block。

        Args:
            price: 当前价格
            obs: Order Block 列表

        Returns:
            接近的 OB 信息或 None
        """
        for ob in obs:
            ob_top = Decimal(ob["top"])
            ob_bottom = Decimal(ob["bottom"])

            # 价格在 OB 区间内或接近
            in_zone = ob_bottom <= price <= ob_top
            near_zone = abs(price - ob_top) / ob_top < Decimal(str(self._ob_proximity)) or abs(
                price - ob_bottom
            ) / ob_bottom < Decimal(str(self._ob_proximity))

            if in_zone or near_zone:
                return ob
        return None

    def on_ticker(self, ticker: Ticker) -> list[Signal]:
        """处理实时行情 — 暂存最新价格。

        Args:
            ticker: 最新行情快照

        Returns:
            信号列表（SMC 主要在 K 线级别产生信号）
        """
        # SMC 策略主要基于K线结构，Ticker 级别不产生信号
        # 但会缓存市场类型
        self._market_cache[ticker.symbol] = ticker.market
        return []

    def on_kline(self, kline: Kline) -> list[Signal]:
        """处理K线 — SMC 核心信号逻辑。

        综合 BOS/CHoCH、Order Block、FVG、流动性猎杀产生信号。

        Args:
            kline: 最新K线数据

        Returns:
            信号列表
        """
        self._update_buffers(kline)

        symbol = kline.symbol
        price = kline.close
        ts = kline.timestamp_ns
        market = self._market_cache.get(symbol, Market.SPOT)
        signals: list[Signal] = []

        highs = self._highs[symbol]
        lows = self._lows[symbol]
        klines = self._kline_buf[symbol]

        if len(klines) < 15:
            return []

        # ── 1. 趋势判断 ──
        trend = self._analyzer.update_trend(symbol, highs, lows)

        # ── 2. BOS 检测 ──
        bos = self._analyzer.detect_bos(highs, lows)

        # ── 3. CHoCH 检测 ──
        choch = self._analyzer.detect_choch(highs, lows, trend)

        # ── 4. Order Block ──
        obs = self._analyzer.find_order_blocks(klines)
        near_ob = self._check_ob_proximity(price, obs)

        # ── 5. FVG ──
        fvgs = self._analyzer.find_fvg(klines)

        # ── 6. 流动性猎杀 ──
        pools = self._analyzer.find_liquidity_pools(highs, lows)
        liq_grab = self._analyzer.detect_liquidity_grab(klines, pools)

        # ── 7. 溢价/折价区 ──
        zone = self._analyzer.premium_discount(klines)

        # ── 信号合成 ──
        reasons: list[str] = []
        strength = 0.0

        # 场景 A: 趋势延续（BOS + OB 回踩）
        if bos and near_ob:
            if bos["type"] == "bullish_bos" and near_ob["type"] == "bullish_ob":
                if zone == "discount":
                    strength = 0.8
                    reasons.append("BOS确认上升趋势")
                    reasons.append(f"价格回踩看涨OB({near_ob['top']}-{near_ob['bottom']})")
                    reasons.append("处于折价区")
                else:
                    strength = 0.65
                    reasons.append("BOS确认上升趋势")
                    reasons.append("价格回踩看涨OB")

            elif bos["type"] == "bearish_bos" and near_ob["type"] == "bearish_ob":
                if zone == "premium":
                    strength = 0.8
                    reasons.append("BOS确认下降趋势")
                    reasons.append(f"价格回踩看跌OB({near_ob['top']}-{near_ob['bottom']})")
                    reasons.append("处于溢价区")
                else:
                    strength = 0.65
                    reasons.append("BOS确认下降趋势")
                    reasons.append("价格回踩看跌OB")

        # 场景 B: 趋势反转（CHoCH + 流动性猎杀）
        if liq_grab and choch:
            if liq_grab["signal"] == "bullish" and choch["type"] == "bullish_choch":
                strength = max(strength, 0.85)
                reasons.append("流动性猎杀(上方止损被扫)")
                reasons.append("CHoCH确认趋势反转(看涨)")

            elif liq_grab["signal"] == "bearish" and choch["type"] == "bearish_choch":
                strength = max(strength, 0.85)
                reasons.append("流动性猎杀(下方止损被扫)")
                reasons.append("CHoCH确认趋势反转(看跌)")

        # 场景 C: FVG 回补 + 趋势方向
        if fvgs and trend:
            latest_fvg = fvgs[-1]
            if latest_fvg["type"] == "bullish_fvg" and trend == "bullish":
                fvg_top = Decimal(latest_fvg["top"])
                fvg_bottom = Decimal(latest_fvg["bottom"])
                if fvg_bottom <= price <= fvg_top:
                    strength = max(strength, 0.6)
                    reasons.append(f"价格进入看涨FVG({fvg_top}-{fvg_bottom})")
                    reasons.append("趋势看涨，FVG回补做多")

            elif latest_fvg["type"] == "bearish_fvg" and trend == "bearish":
                fvg_top = Decimal(latest_fvg["top"])
                fvg_bottom = Decimal(latest_fvg["bottom"])
                if fvg_bottom <= price <= fvg_top:
                    strength = max(strength, 0.6)
                    reasons.append(f"价格进入看跌FVG({fvg_top}-{fvg_bottom})")
                    reasons.append("趋势看跌，FVG回补做空")

        # 纯 CHoCH 信号（无 OB/FVG 配合）
        if strength == 0 and choch:
            if choch["type"] == "bullish_choch" and zone == "discount":
                strength = 0.55
                reasons.append("CHoCH看涨反转")
                reasons.append("处于折价区")
            elif choch["type"] == "bearish_choch" and zone == "premium":
                strength = 0.55
                reasons.append("CHoCH看跌反转")
                reasons.append("处于溢价区")

        # 生成信号
        if strength >= self._signal_threshold and reasons:
            # 判断方向
            bullish_keywords = ["看涨", "上升", "bullish", "折价", "做多"]
            is_bullish = any(kw in r for r in reasons for kw in bullish_keywords)

            side: str = "buy" if is_bullish else "sell"

            signals.append(
                Signal(
                    symbol=symbol,
                    market=market,
                    side=side,
                    strength=round(strength, 4),
                    strategy_name=self.name,
                    reason="; ".join(reasons),
                    metadata={
                        "trend": trend,
                        "zone": zone,
                        "bos": bos,
                        "choch": choch,
                        "near_ob": near_ob,
                        "liq_grab": liq_grab,
                        "fvgs_count": len(fvgs),
                    },
                    timestamp_ns=ts,
                )
            )

        return signals
