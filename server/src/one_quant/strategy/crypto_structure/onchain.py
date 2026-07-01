"""
加密专属结构分析 — 链上分析
"""

from __future__ import annotations

from decimal import Decimal


class OnChainAnalyzer:
    """链上分析器。

    分析区块链上的资金流动，判断市场参与者行为：
    - 交易所净流入流出：大量流入 → 抛压；大量流出 → 持有/囤积
    - 巨鲸活动：大额转账可能预示价格异动
    - 稳定币流向：USDT/USDC 流入交易所 → 买入力增强
    """

    EXCHANGE_LABELS = {"binance", "coinbase", "okx", "bybit", "bitfinex"}
    WHALE_THRESHOLD_BTC = Decimal("100")

    def exchange_netflow(
        self,
        inflows: list[Decimal],
        outflows: list[Decimal],
        window: int = 24,
    ) -> dict:
        """交易所净流入流出分析。"""
        if not inflows or not outflows:
            return {
                "netflow": "0",
                "cumulative": "0",
                "trend": "neutral",
                "signal": "neutral",
                "intensity": 0.0,
            }

        recent_in = inflows[-window:]
        recent_out = outflows[-window:]
        n = min(len(recent_in), len(recent_out))

        netflows = [recent_in[i] - recent_out[i] for i in range(n)]
        current_net = netflows[-1] if netflows else Decimal("0")
        cumulative = sum(netflows, Decimal("0"))

        if cumulative > 0:
            trend = "inflow"
            signal = "bearish"
        elif cumulative < 0:
            trend = "outflow"
            signal = "bullish"
        else:
            trend = "neutral"
            signal = "neutral"

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
        """巨鲸活动分析。"""
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
            signal = "bearish"
        elif net < 0:
            direction = "from_exchange"
            signal = "bullish"
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
        """稳定币流向分析。"""
        recent_usdt = usdt_inflow[-window:]
        recent_usdc = usdc_inflow[-window:]

        total_usdt = sum(recent_usdt, Decimal("0"))
        total_usdc = sum(recent_usdc, Decimal("0"))
        total = total_usdt + total_usdc

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
