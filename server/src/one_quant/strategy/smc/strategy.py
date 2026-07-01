"""
SMC — SMC 策略
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import Any

from one_quant.core.types import Kline, Market, Signal, Ticker
from one_quant.strategy.contracts import Strategy
from one_quant.strategy.smc.analyzer import SMCAnalyzer
from one_quant.strategy.smc.smart_money import SmartMoneyIndex


class SMCStrategy(Strategy):
    """SMC 策略 — 基于市场结构。

    信号逻辑：
    1. BOS/CHoCH → 确定趋势方向
    2. Order Block → 识别支撑/压力位
    3. FVG → 确定回补目标
    4. 流动性猎杀 → 反转信号
    5. 溢价/折价区 → 确认入场区域
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

    def _check_ob_proximity(
        self, price: Decimal, obs: list[dict[str, Any]]
    ) -> dict[str, Any] | None:
        """检查价格是否接近某个 Order Block。"""
        for ob in obs:
            ob_top = Decimal(ob["top"])
            ob_bottom = Decimal(ob["bottom"])

            in_zone = ob_bottom <= price <= ob_top
            near_zone = abs(price - ob_top) / ob_top < Decimal(str(self._ob_proximity)) or abs(
                price - ob_bottom
            ) / ob_bottom < Decimal(str(self._ob_proximity))

            if in_zone or near_zone:
                return ob
        return None

    def on_ticker(self, ticker: Ticker) -> list[Signal]:
        """处理实时行情 — 暂存最新价格。"""
        self._market_cache[ticker.symbol] = ticker.market
        return []

    def on_kline(self, kline: Kline) -> list[Signal]:
        """处理K线 — SMC 核心信号逻辑。"""
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

        # 纯 CHoCH 信号
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
            bullish_keywords = ["看涨", "上升", "bullish", "折价", "做多"]
            is_bullish = any(kw in r for r in reasons for kw in bullish_keywords)

            side: str = "buy" if is_bullish else "sell"

            signals.append(
                Signal(
                    symbol=symbol,
                    market=market,
                    side=side if side in ("buy", "sell") else "buy",  # type: ignore[arg-type]
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
