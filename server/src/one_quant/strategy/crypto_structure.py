"""
ONE量化 - 加密专属结构分析

面向加密货币市场的专属分析框架，包含链上分析、衍生品结构、期权结构
和策略融合层。

包含：
  - OnChainAnalyzer: 链上分析（交易所净流/巨鲸活动/稳定币流向）
  - DerivativesStructure: 衍生品结构（资金费率/OI/清算热力图）
  - OptionStructure: 期权结构（Max Pain/GEX/PCR/IV偏斜）
  - StrategyFusion: 策略融合层（四层共振：订单流+SMC+ML+LLM）

全中文注释，Decimal 精确计算。
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

# ──────────────────────────── 链上分析 ────────────────────────────


class OnChainAnalyzer:
    """链上分析器。

    分析区块链上的资金流动，判断市场参与者行为：
    - 交易所净流入流出：大量流入 → 抛压；大量流出 → 持有/囤积
    - 巨鲸活动：大额转账可能预示价格异动
    - 稳定币流向：USDT/USDC 流入交易所 → 买入力增强

    注意：实际生产中需要对接链上数据 API（如 Glassnode、Nansen）。
    此处定义接口和离线分析逻辑。
    """

    # 交易所热钱包地址标签（示例，实际需维护完整列表）
    EXCHANGE_LABELS = {"binance", "coinbase", "okx", "bybit", "bitfinex"}

    # 巨鲸阈值（BTC 等值）
    WHALE_THRESHOLD_BTC = Decimal("100")

    def exchange_netflow(
        self,
        inflows: list[Decimal],
        outflows: list[Decimal],
        window: int = 24,
    ) -> dict:
        """交易所净流入流出分析。

        净流入 = 流入 - 流出
        - 正值：净流入（抛压增加，看跌）
        - 负值：净流出（囤积行为，看涨）

        Args:
            inflows: 交易所流入量序列（每小时/每日）
            outflows: 交易所流出量序列
            window: 分析窗口（默认 24 期）

        Returns:
            {
                "netflow": str,        # 当期净流入
                "cumulative": str,     # 累计净流入
                "trend": str,          # "inflow" / "outflow" / "neutral"
                "signal": str,         # "bullish" / "bearish" / "neutral"
                "intensity": float,    # 强度 0~1
            }
        """
        if not inflows or not outflows:
            return {
                "netflow": "0",
                "cumulative": "0",
                "trend": "neutral",
                "signal": "neutral",
                "intensity": 0.0,
            }

        # 取最近 window 期
        recent_in = inflows[-window:]
        recent_out = outflows[-window:]
        n = min(len(recent_in), len(recent_out))

        netflows = [recent_in[i] - recent_out[i] for i in range(n)]
        current_net = netflows[-1] if netflows else Decimal("0")
        cumulative = sum(netflows, Decimal("0"))

        # 趋势判断
        if cumulative > 0:
            trend = "inflow"
            signal = "bearish"  # 净流入 = 抛压
        elif cumulative < 0:
            trend = "outflow"
            signal = "bullish"  # 净流出 = 囤积
        else:
            trend = "neutral"
            signal = "neutral"

        # 强度：累计净流 / 总流量
        total_in = sum(recent_in, Decimal("0"))
        total_out = sum(recent_out, Decimal("0"))
        total = total_in + total_out
        intensity = float(abs(cumulative) / total) if total > 0 else 0.0
        intensity = min(intensity, 1.0)

        return {
            "netflow": str(current_net.quantize(Decimal("0.01"))),
            "cumulative": str(cumulative.quantize(Decimal("0.01"))),
            "trend": trend,
            "signal": signal,
            "intensity": round(intensity, 4),
        }

    def whale_activity(
        self,
        transfers: list[dict],
        threshold: Decimal | None = None,
    ) -> dict:
        """巨鲸活动分析。

        监控大额转账，判断巨鲸行为模式：
        - 交易所 → 链上：提币囤积（看涨）
        - 链上 → 交易所：准备抛售（看跌）
        - 链上 → 链上：钱包整理（中性）

        Args:
            transfers: 转账记录列表 [{from, to, amount, timestamp}]
            threshold: 巨鲸阈值（默认 100 BTC 等值）

        Returns:
            {
                "whale_count": int,         # 巨鲸转账笔数
                "total_volume": str,        # 总量
                "net_direction": str,       # "to_exchange" / "from_exchange" / "internal"
                "signal": str,              # "bullish" / "bearish" / "neutral"
                "largest_tx": dict | None,  # 最大单笔
            }
        """
        thresh = threshold or self.WHALE_THRESHOLD_BTC

        whale_txs = [t for t in transfers if Decimal(str(t.get("amount", 0))) >= thresh]

        if not whale_txs:
            return {
                "whale_count": 0,
                "total_volume": "0",
                "net_direction": "internal",
                "signal": "neutral",
                "largest_tx": None,
            }

        total_vol = sum(Decimal(str(t["amount"])) for t in whale_txs)

        # 分类：流入交易所 vs 流出交易所
        to_exchange = sum(
            Decimal(str(t["amount"]))
            for t in whale_txs
            if str(t.get("to", "")).lower() in self.EXCHANGE_LABELS
        )
        from_exchange = sum(
            Decimal(str(t["amount"]))
            for t in whale_txs
            if str(t.get("from", "")).lower() in self.EXCHANGE_LABELS
        )

        net = to_exchange - from_exchange

        if net > 0:
            direction = "to_exchange"
            signal = "bearish"  # 巨鲸转入交易所 = 准备抛售
        elif net < 0:
            direction = "from_exchange"
            signal = "bullish"  # 巨鲸从交易所提币 = 囤积
        else:
            direction = "internal"
            signal = "neutral"

        largest = max(whale_txs, key=lambda t: Decimal(str(t["amount"])))

        return {
            "whale_count": len(whale_txs),
            "total_volume": str(total_vol.quantize(Decimal("0.01"))),
            "net_direction": direction,
            "signal": signal,
            "largest_tx": {
                "amount": str(largest["amount"]),
                "from": largest.get("from", "unknown"),
                "to": largest.get("to", "unknown"),
            },
        }

    def stablecoin_flow(
        self,
        usdt_inflow: list[Decimal],
        usdc_inflow: list[Decimal],
        window: int = 7,
    ) -> dict:
        """稳定币流向分析。

        USDT/USDC 大量流入交易所 → 买入力增强（看涨）
        USDT/USDC 大量流出交易所 → 买入力减弱（看跌）

        Args:
            usdt_inflow: USDT 流入量序列（每日）
            usdc_inflow: USDC 流入量序列
            window: 分析窗口（默认 7 天）

        Returns:
            {
                "total_inflow": str,
                "trend": str,       # "increasing" / "decreasing" / "stable"
                "signal": str,      # "bullish" / "bearish" / "neutral"
                "usdt_share": float,
            }
        """
        recent_usdt = usdt_inflow[-window:]
        recent_usdc = usdc_inflow[-window:]

        total_usdt = sum(recent_usdt, Decimal("0"))
        total_usdc = sum(recent_usdc, Decimal("0"))
        total = total_usdt + total_usdc

        # 趋势：比较最近半段和前半段
        mid = len(recent_usdt) // 2
        if mid > 0:
            first_half = sum(recent_usdt[:mid], Decimal("0")) + sum(recent_usdc[:mid], Decimal("0"))
            second_half = sum(recent_usdt[mid:], Decimal("0")) + sum(
                recent_usdc[mid:], Decimal("0")
            )

            if second_half > first_half * Decimal("1.1"):
                trend = "increasing"
                signal = "bullish"
            elif second_half < first_half * Decimal("0.9"):
                trend = "decreasing"
                signal = "bearish"
            else:
                trend = "stable"
                signal = "neutral"
        else:
            trend = "stable"
            signal = "neutral"

        usdt_share = float(total_usdt / total) if total > 0 else 0.5

        return {
            "total_inflow": str(total.quantize(Decimal("0.01"))),
            "trend": trend,
            "signal": signal,
            "usdt_share": round(usdt_share, 4),
        }


# ──────────────────────────── 衍生品结构 ────────────────────────────


class DerivativesStructure:
    """衍生品结构分析。

    分析合约市场的结构性指标：
    - 资金费率极值：过高的正费率 → 多头拥挤（看跌）；过高的负费率 → 空头拥挤（看涨）
    - OI 变化：未平仓量增减反映市场参与度
    - 清算热力图：止损聚集区域，价格可能被吸引
    """

    # 资金费率极值阈值（年化）
    FUNDING_EXTREME_HIGH = Decimal("0.001")  # 0.1% 每 8h ≈ 109% 年化
    FUNDING_EXTREME_LOW = Decimal("-0.001")  # -0.1% 每 8h

    def funding_rate_extreme(self, rate: Decimal) -> dict:
        """资金费率极值分析。

        资金费率是永续合约的多空平衡机制：
        - 正费率：多头付给空头（多头拥挤）
        - 负费率：空头付给多头（空头拥挤）

        极值费率往往预示反转：
        - 极高正费率 → 多头过热 → 可能回调
        - 极高负费率 → 空头过热 → 可能反弹

        Args:
            rate: 当前资金费率（如 0.0001 = 0.01%）

        Returns:
            {
                "level": str,       # "extreme_high" / "high" / "normal" / "low" / "extreme_low"
                "signal": str,      # "bearish" / "bullish" / "neutral"
                "intensity": float, # 强度 0~1
                "annualized": str,  # 年化费率
            }
        """
        # 年化 = 每 8h 费率 × 3 × 365
        annualized = rate * Decimal("3") * Decimal("365")

        if rate >= self.FUNDING_EXTREME_HIGH:
            level = "extreme_high"
            signal = "bearish"
            intensity = min(float(rate / self.FUNDING_EXTREME_HIGH), 1.0)
        elif rate >= self.FUNDING_EXTREME_HIGH / 2:
            level = "high"
            signal = "bearish"
            intensity = float(rate / self.FUNDING_EXTREME_HIGH) * 0.5
        elif rate <= self.FUNDING_EXTREME_LOW:
            level = "extreme_low"
            signal = "bullish"
            intensity = min(float(abs(rate) / abs(self.FUNDING_EXTREME_LOW)), 1.0)
        elif rate <= self.FUNDING_EXTREME_LOW / 2:
            level = "low"
            signal = "bullish"
            intensity = float(abs(rate) / abs(self.FUNDING_EXTREME_LOW)) * 0.5
        else:
            level = "normal"
            signal = "neutral"
            intensity = 0.0

        return {
            "level": level,
            "signal": signal,
            "intensity": round(intensity, 4),
            "annualized": str(annualized.quantize(Decimal("0.0001"))),
        }

    def oi_change(self, oi_data: list[dict]) -> dict:
        """OI（Open Interest）变化分析。

        OI 反映市场未平仓合约总量：
        - OI 增 + 价格涨 → 新多头入场（趋势延续）
        - OI 增 + 价格跌 → 新空头入场（趋势延续）
        - OI 减 + 价格涨 → 空头平仓（反弹，非趋势）
        - OI 减 + 价格跌 → 多头平仓（回调，非趋势）

        Args:
            oi_data: OI 数据列表 [{timestamp, oi, price}]

        Returns:
            {
                "current_oi": str,
                "change": str,       # OI 变化量
                "change_pct": str,   # OI 变化百分比
                "price_direction": str,  # "up" / "down" / "flat"
                "signal": str,
                "interpretation": str,
            }
        """
        if len(oi_data) < 2:
            return {
                "current_oi": "0",
                "change": "0",
                "change_pct": "0",
                "price_direction": "flat",
                "signal": "neutral",
                "interpretation": "数据不足",
            }

        current = oi_data[-1]
        prev = oi_data[-2]

        current_oi = Decimal(str(current["oi"]))
        prev_oi = Decimal(str(prev["oi"]))
        current_price = Decimal(str(current["price"]))
        prev_price = Decimal(str(prev["price"]))

        oi_change_val = current_oi - prev_oi
        oi_change_pct = (oi_change_val / prev_oi * 100) if prev_oi > 0 else Decimal("0")

        price_change = current_price - prev_price
        if price_change > 0:
            price_dir = "up"
        elif price_change < 0:
            price_dir = "down"
        else:
            price_dir = "flat"

        # 解读
        if oi_change_val > 0 and price_dir == "up":
            signal = "bullish"
            interpretation = "OI增+价涨：新多头入场，上涨趋势延续"
        elif oi_change_val > 0 and price_dir == "down":
            signal = "bearish"
            interpretation = "OI增+价跌：新空头入场，下跌趋势延续"
        elif oi_change_val < 0 and price_dir == "up":
            signal = "bullish_weak"
            interpretation = "OI减+价涨：空头平仓反弹，非趋势性上涨"
        elif oi_change_val < 0 and price_dir == "down":
            signal = "bearish_weak"
            interpretation = "OI减+价跌：多头平仓回调，非趋势性下跌"
        else:
            signal = "neutral"
            interpretation = "OI和价格无明显方向"

        return {
            "current_oi": str(current_oi.quantize(Decimal("0.01"))),
            "change": str(oi_change_val.quantize(Decimal("0.01"))),
            "change_pct": str(oi_change_pct.quantize(Decimal("0.01"))),
            "price_direction": price_dir,
            "signal": signal,
            "interpretation": interpretation,
        }

    def liquidation_heatmap(
        self,
        positions: list[dict],
        price_bins: int = 50,
    ) -> dict:
        """清算热力图。

        将持仓按清算价格分布，识别止损/强平聚集区。
        价格往往会向高密度清算区域移动（猎杀止损）。

        Args:
            positions: 持仓列表 [{side, size, liquidation_price, entry_price}]
            price_bins: 价格分箱数

        Returns:
            {
                "heatmap": {price_str: volume_str, ...},
                "high_density_zones": [{"price": str, "volume": str, "side": str}],
                "signal": str,
            }
        """
        if not positions:
            return {"heatmap": {}, "high_density_zones": [], "signal": "neutral"}

        # 按清算价格分箱
        liq_prices = [Decimal(str(p["liquidation_price"])) for p in positions]
        min_price = min(liq_prices)
        max_price = max(liq_prices)

        if min_price == max_price:
            total_size = sum(Decimal(str(p["size"])) for p in positions)
            return {
                "heatmap": {str(min_price): str(total_size)},
                "high_density_zones": [
                    {
                        "price": str(min_price),
                        "volume": str(total_size),
                        "side": positions[0]["side"],
                    }
                ],
                "signal": "neutral",
            }

        bin_size = (max_price - min_price) / Decimal(price_bins)

        # 统计每个分箱的清算量
        heatmap: dict[Decimal, Decimal] = {}
        side_map: dict[Decimal, str] = {}

        for p in positions:
            liq = Decimal(str(p["liquidation_price"]))
            size = Decimal(str(p["size"]))
            bin_idx = min(
                int((liq - min_price) / bin_size),
                price_bins - 1,
            )
            bin_price = min_price + bin_size * Decimal(bin_idx) + bin_size / 2
            heatmap[bin_price] = heatmap.get(bin_price, Decimal("0")) + size
            # 记录方向
            if bin_price not in side_map:
                side_map[bin_price] = p["side"]

        if not heatmap:
            return {"heatmap": {}, "high_density_zones": [], "signal": "neutral"}

        # 找高密度区域（前 10%）
        sorted_zones = sorted(heatmap.items(), key=lambda x: x[1], reverse=True)
        top_count = max(1, len(sorted_zones) // 10)
        high_density = [
            {
                "price": str(p.quantize(Decimal("0.01"))),
                "volume": str(v.quantize(Decimal("0.01"))),
                "side": side_map.get(p, "unknown"),
            }
            for p, v in sorted_zones[:top_count]
        ]

        # 信号：多头清算聚集在下方 → 价格可能下探；反之亦然
        long_zones = [z for z in high_density if z["side"] == "long"]
        short_zones = [z for z in high_density if z["side"] == "short"]

        if len(long_zones) > len(short_zones):
            signal = "bearish"  # 多头清算聚集 → 可能下探猎杀
        elif len(short_zones) > len(long_zones):
            signal = "bullish"  # 空头清算聚集 → 可能上探猎杀
        else:
            signal = "neutral"

        return {
            "heatmap": {
                str(p.quantize(Decimal("0.01"))): str(v.quantize(Decimal("0.01")))
                for p, v in sorted(heatmap.items())
            },
            "high_density_zones": high_density,
            "signal": signal,
        }


# ──────────────────────────── 期权结构 ────────────────────────────


class OptionStructure:
    """期权结构分析。

    分析期权市场的结构性指标：
    - Max Pain: 期权到期时让最多期权作废的价格（最大痛苦价）
    - GEX: Gamma 暴露（做市商对冲行为的影响）
    - PCR: Put/Call Ratio（看跌/看涨期权比率）
    - IV Skew: 隐含波动率偏斜（恐慌/贪婪指标）
    """

    def max_pain(self, chain: list[dict]) -> Decimal:
        """Max Pain（最大痛苦价）计算。

        Max Pain 是期权到期时，使所有期权买方亏损最大（即卖方盈利最大）的价格。
        原理：在该价格点，所有未平仓的 call 和 put 的总内在价值最小。

        计算方法：
        1. 遍历每个可能的到期价格
        2. 计算该价格下所有 call 的内在价值 + 所有 put 的内在价值
        3. 总内在价值最小的价格即为 Max Pain

        Args:
            chain: 期权链 [{strike, type, open_interest}]
                type: "call" 或 "put"

        Returns:
            Max Pain 价格
        """
        if not chain:
            return Decimal("0")

        strikes = sorted(set(Decimal(str(c["strike"])) for c in chain))

        if len(strikes) < 2:
            return strikes[0] if strikes else Decimal("0")

        min_pain = Decimal("infinity")
        max_pain_price = strikes[0]

        for test_price in strikes:
            total_pain = Decimal("0")

            for c in chain:
                strike = Decimal(str(c["strike"]))
                oi = Decimal(str(c.get("open_interest", 0)))
                option_type = c.get("type", "call")

                if option_type == "call":
                    # Call 内在价值 = max(0, price - strike)
                    intrinsic = max(Decimal("0"), test_price - strike)
                else:
                    # Put 内在价值 = max(0, strike - price)
                    intrinsic = max(Decimal("0"), strike - test_price)

                total_pain += intrinsic * oi

            if total_pain < min_pain:
                min_pain = total_pain
                max_pain_price = test_price

        return max_pain_price

    def gex_exposure(self, chain: list[dict], spot_price: Decimal) -> dict:
        """GEX（Gamma Exposure）计算。

        GEX 反映做市商的 Gamma 敞口：
        - 正 GEX：做市商做多 Gamma → 价格波动被抑制（均值回归）
        - 负 GEX：做市商做空 Gamma → 价格波动被放大（趋势加速）

        做市商对冲行为：
        - 正 GEX：价格上涨时卖出，下跌时买入 → 稳定器
        - 负 GEX：价格上涨时买入，下跌时卖出 → 加速器

        Args:
            chain: 期权链 [{strike, type, open_interest, gamma}]
            spot_price: 现货价格

        Returns:
            {
                "total_gex": str,
                "positive_gex": str,   # 正 GEX 总量
                "negative_gex": str,   # 负 GEX 总量
                "net_gex": str,
                "regime": str,         # "stabilizing" / "amplifying" / "neutral"
                "call_wall": str,      # 最大 call Gamma 行权价
                "put_wall": str,       # 最大 put Gamma 行权价
            }
        """
        if not chain:
            return {
                "total_gex": "0",
                "positive_gex": "0",
                "negative_gex": "0",
                "net_gex": "0",
                "regime": "neutral",
                "call_wall": "0",
                "put_wall": "0",
            }

        total_gex = Decimal("0")
        pos_gex = Decimal("0")
        neg_gex = Decimal("0")
        call_gamma_map: dict[Decimal, Decimal] = {}
        put_gamma_map: dict[Decimal, Decimal] = {}

        for c in chain:
            strike = Decimal(str(c["strike"]))
            oi = Decimal(str(c.get("open_interest", 0)))
            gamma = Decimal(str(c.get("gamma", 0)))
            option_type = c.get("type", "call")

            # GEX = Gamma × OI × Spot² × 0.01（归一化）
            gex = gamma * oi * spot_price * spot_price / Decimal("100")

            # Call 的 GEX 为正（做市商做多 Gamma）
            # Put 的 GEX 为负（做市商做空 Gamma）
            if option_type == "call":
                total_gex += gex
                pos_gex += gex
                call_gamma_map[strike] = call_gamma_map.get(strike, Decimal("0")) + gex
            else:
                total_gex -= gex
                neg_gex += gex
                put_gamma_map[strike] = put_gamma_map.get(strike, Decimal("0")) + gex

        # 判断市场状态
        net_gex = pos_gex - neg_gex
        if net_gex > 0:
            regime = "stabilizing"  # 正 GEX → 均值回归
        elif net_gex < 0:
            regime = "amplifying"  # 负 GEX → 趋势加速
        else:
            regime = "neutral"

        # Call/Put Wall
        call_wall = (
            max(call_gamma_map.keys(), key=lambda k: call_gamma_map[k])
            if call_gamma_map
            else Decimal("0")
        )
        put_wall = (
            max(put_gamma_map.keys(), key=lambda k: put_gamma_map[k])
            if put_gamma_map
            else Decimal("0")
        )

        return {
            "total_gex": str(total_gex.quantize(Decimal("0.01"))),
            "positive_gex": str(pos_gex.quantize(Decimal("0.01"))),
            "negative_gex": str(neg_gex.quantize(Decimal("0.01"))),
            "net_gex": str(net_gex.quantize(Decimal("0.01"))),
            "regime": regime,
            "call_wall": str(call_wall),
            "put_wall": str(put_wall),
        }

    def put_call_ratio(self, chain: list[dict]) -> dict:
        """Put/Call Ratio（PCR）。

        PCR = Put OI / Call OI（或 Put Volume / Call Volume）

        - PCR > 1.0: 看跌期权更多 → 恐慌/看跌情绪
        - PCR < 1.0: 看涨期权更多 → 贪婪/看涨情绪
        - PCR 极端值往往预示反转

        Args:
            chain: 期权链 [{type, open_interest, volume}]

        Returns:
            {
                "oi_ratio": float,     # OI-based PCR
                "volume_ratio": float, # Volume-based PCR
                "sentiment": str,      # "fear" / "greed" / "neutral"
                "extreme": bool,       # 是否处于极端值
            }
        """
        call_oi = sum(
            Decimal(str(c.get("open_interest", 0))) for c in chain if c.get("type") == "call"
        )
        put_oi = sum(
            Decimal(str(c.get("open_interest", 0))) for c in chain if c.get("type") == "put"
        )
        call_vol = sum(Decimal(str(c.get("volume", 0))) for c in chain if c.get("type") == "call")
        put_vol = sum(Decimal(str(c.get("volume", 0))) for c in chain if c.get("type") == "put")

        oi_ratio = float(put_oi / call_oi) if call_oi > 0 else 0.0
        vol_ratio = float(put_vol / call_vol) if call_vol > 0 else 0.0

        # 情绪判断
        if oi_ratio > 1.5:
            sentiment = "fear"
            extreme = True
        elif oi_ratio > 1.0:
            sentiment = "fear"
            extreme = False
        elif oi_ratio < 0.5:
            sentiment = "greed"
            extreme = True
        elif oi_ratio < 1.0:
            sentiment = "greed"
            extreme = False
        else:
            sentiment = "neutral"
            extreme = False

        return {
            "oi_ratio": round(oi_ratio, 4),
            "volume_ratio": round(vol_ratio, 4),
            "sentiment": sentiment,
            "extreme": extreme,
        }

    def iv_skew(self, chain: list[dict]) -> dict:
        """IV 偏斜（隐含波动率偏斜）。

        IV Skew 反映市场对尾部风险的定价：
        - 正偏斜（OTM put IV > OTM call IV）：市场恐慌，愿意为下行保护付更高溢价
        - 负偏斜（OTM call IV > OTM put IV）：市场贪婪，愿意为上行押注付更高溢价

        Args:
            chain: 期权链 [{strike, type, iv, spot_price}]

        Returns:
            {
                "skew": float,          # 偏斜度（put_iv - call_iv，标准化）
                "put_wing_iv": str,     # OTM Put 平均 IV
                "call_wing_iv": str,    # OTM Call 平均 IV
                "atm_iv": str,          # ATM IV
                "interpretation": str,
            }
        """
        if not chain:
            return {
                "skew": 0.0,
                "put_wing_iv": "0",
                "call_wing_iv": "0",
                "atm_iv": "0",
                "interpretation": "数据不足",
            }

        # 获取 spot price（从第一个期权的 strike 估算）
        strikes = sorted(set(Decimal(str(c["strike"])) for c in chain))
        if not strikes:
            return {
                "skew": 0.0,
                "put_wing_iv": "0",
                "call_wing_iv": "0",
                "atm_iv": "0",
                "interpretation": "无有效行权价",
            }

        # 估算 ATM 价格（中间行权价）
        atm_price = strikes[len(strikes) // 2]

        # 分类：OTM Put（strike < ATM）、ATM、OTM Call（strike > ATM）
        otm_puts = [c for c in chain if Decimal(str(c["strike"])) < atm_price * Decimal("0.95")]
        otm_calls = [c for c in chain if Decimal(str(c["strike"])) > atm_price * Decimal("1.05")]
        atm_options = [
            c
            for c in chain
            if (
                atm_price * Decimal("0.95")
                <= Decimal(str(c["strike"]))
                <= atm_price * Decimal("1.05")
            )
        ]

        def avg_iv(options: list[dict]) -> Decimal:
            if not options:
                return Decimal("0")
            ivs = [Decimal(str(c.get("iv", 0))) for c in options]
            return sum(ivs) / Decimal(len(ivs))

        put_wing_iv = avg_iv(otm_puts)
        call_wing_iv = avg_iv(otm_calls)
        atm_iv = avg_iv(atm_options)

        # 偏斜度 = OTM Put IV - OTM Call IV（标准化）
        skew = float(put_wing_iv - call_wing_iv)

        if skew > 0.05:
            interpretation = "正偏斜：市场恐慌，下行保护溢价高"
        elif skew < -0.05:
            interpretation = "负偏斜：市场贪婪，上行押注溢价高"
        else:
            interpretation = "偏斜中性：市场情绪平稳"

        return {
            "skew": round(skew, 4),
            "put_wing_iv": str(put_wing_iv.quantize(Decimal("0.0001"))),
            "call_wing_iv": str(call_wing_iv.quantize(Decimal("0.0001"))),
            "atm_iv": str(atm_iv.quantize(Decimal("0.0001"))),
            "interpretation": interpretation,
        }


# ──────────────────────────── 策略融合层 ────────────────────────────


class StrategyFusion:
    """策略融合层 — 四层共振。

    将四个维度的信号融合为最终交易决策：
    1. 订单流（微观）：逐笔成交和盘口的即时力量
    2. SMC（中观）：市场结构和机构行为
    3. 因子/ML（统计）：量化因子和机器学习预测
    4. LLM（消息面）：大语言模型对新闻/社交媒体的解读

    共振规则：
    - ≥ 3 层同向 → 高置信信号（strength > 0.7）
    - 2 层同向 → 中等置信信号（strength 0.5~0.7）
    - 1 层 → 低置信信号（不建议交易）
    - LLM 有"一票否决权"（当 LLM 信号与技术信号强烈矛盾时）
    """

    # 各层权重
    WEIGHTS = {
        "order_flow": 0.30,  # 订单流权重最高（最即时）
        "smc": 0.30,  # SMC 结构（机构行为）
        "ml": 0.25,  # ML 因子（统计优势）
        "llm": 0.15,  # LLM（消息面，辅助确认）
    }

    def fuse(
        self,
        order_flow: dict[str, Any],
        smc: dict[str, Any],
        ml_score: float,
        llm_signal: dict[str, Any],
    ) -> dict:
        """四层信号融合。

        Args:
            order_flow: 订单流信号
                {"side": "buy"/"sell"/"neutral", "strength": float, "factors": [...]}
            smc: SMC 信号
                {"side": "buy"/"sell"/"neutral", "strength": float, "trend": str}
            ml_score: ML 模型预测分数 [-1, 1]
                > 0 看涨，< 0 看跌，0 中性
            llm_signal: LLM 信号
                {"side": "buy"/"sell"/"neutral", "confidence": float, "reason": str}

        Returns:
            {
                "side": "buy"/"sell"/"neutral",
                "strength": float,       # 综合信号强度 0~1
                "confidence": str,       # "high" / "medium" / "low"
                "layers_agreed": int,    # 同向层数
                "llm_veto": bool,        # LLM 是否否决
                "detail": dict,          # 各层详情
            }
        """
        # 解析各层方向
        layers: dict[str, dict] = {
            "order_flow": {
                "side": order_flow.get("side", "neutral"),
                "strength": order_flow.get("strength", 0.0),
            },
            "smc": {
                "side": smc.get("side", "neutral"),
                "strength": smc.get("strength", 0.0),
            },
            "ml": {
                "side": "buy" if ml_score > 0.1 else ("sell" if ml_score < -0.1 else "neutral"),
                "strength": abs(ml_score),
            },
            "llm": {
                "side": llm_signal.get("side", "neutral"),
                "strength": llm_signal.get("confidence", 0.0),
            },
        }

        # 统计各方向的加权得分
        buy_score = Decimal("0")
        sell_score = Decimal("0")

        for name, layer in layers.items():
            weight = Decimal(str(self.WEIGHTS.get(name, 0.25)))
            if layer["side"] == "buy":
                buy_score += weight * Decimal(str(layer["strength"]))
            elif layer["side"] == "sell":
                sell_score += weight * Decimal(str(layer["strength"]))

        # 判断最终方向
        if buy_score > sell_score and buy_score > Decimal("0.1"):
            final_side = "buy"
            final_strength = float(buy_score)
        elif sell_score > buy_score and sell_score > Decimal("0.1"):
            final_side = "sell"
            final_strength = float(sell_score)
        else:
            final_side = "neutral"
            final_strength = 0.0

        # 计算同向层数
        agreeing = sum(
            1
            for layer in layers.values()
            if layer["side"] == final_side and layer["side"] != "neutral"
        )

        # LLM 一票否决检查
        llm_veto = False
        llm_side = layers["llm"]["side"]
        llm_conf = layers["llm"]["strength"]

        if final_side != "neutral" and llm_side != "neutral" and llm_side != final_side:
            # LLM 方向与技术信号矛盾
            if llm_conf > 0.8 and agreeing <= 2:
                # LLM 高置信且技术信号不够强 → 否决
                llm_veto = True
                final_side = "neutral"
                final_strength = 0.0

        # 置信度
        if agreeing >= 3:
            confidence = "high"
        elif agreeing >= 2:
            confidence = "medium"
        else:
            confidence = "low"

        return {
            "side": final_side,
            "strength": round(min(final_strength, 1.0), 4),
            "confidence": confidence,
            "layers_agreed": agreeing,
            "llm_veto": llm_veto,
            "detail": {
                "buy_score": str(buy_score.quantize(Decimal("0.0001"))),
                "sell_score": str(sell_score.quantize(Decimal("0.0001"))),
                "layers": {
                    name: {"side": l["side"], "strength": round(l["strength"], 4)}
                    for name, l in layers.items()
                },
            },
        }
