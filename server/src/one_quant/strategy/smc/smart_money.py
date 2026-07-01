"""
SMC — 聪明钱指数
"""

from __future__ import annotations

from decimal import Decimal

from one_quant.core.types import Kline
from one_quant.strategy.smc.analyzer import SMCAnalyzer


class SmartMoneyIndex:
    """聪明钱指数 — 两种实现。

    1. 经典 SMI：基于"早盘散户、尾盘机构"的假设
    2. SMC 结构线：自动标注 BOS/CHoCH/OB/FVG 的可视化结构线
    """

    def classic_smi(
        self,
        opens: list[Decimal],
        closes: list[Decimal],
        volumes: list[Decimal],
    ) -> list[Decimal]:
        """经典 Smart Money Index。"""
        if len(opens) != len(closes) or len(opens) < 2:
            return []

        smi = Decimal("0")
        smi_series: list[Decimal] = [Decimal("0")]

        for i in range(1, len(opens)):
            close_change = closes[i] - closes[i - 1]
            open_change = opens[i] - opens[i - 1]
            smi += close_change - open_change
            smi_series.append(smi)

        return smi_series

    def smc_structure_line(self, klines: list[Kline]) -> list[dict]:
        """SMC 结构线：自动标注 BOS/CHoCH/OB/FVG。"""
        if len(klines) < 10:
            return []

        analyzer = SMCAnalyzer()
        highs = [k.high for k in klines]
        lows = [k.low for k in klines]

        events: list[dict] = []

        trend = analyzer.update_trend("auto", highs, lows)

        bos = analyzer.detect_bos(highs, lows)
        if bos:
            bos["event"] = "BOS"
            events.append(bos)

        choch = analyzer.detect_choch(highs, lows, trend)
        if choch:
            choch["event"] = "CHoCH"
            events.append(choch)

        obs = analyzer.find_order_blocks(klines)
        for ob in obs:
            ob["event"] = "OB"
            events.append(ob)

        fvgs = analyzer.find_fvg(klines)
        for fvg in fvgs:
            fvg["event"] = "FVG"
            events.append(fvg)

        pools = analyzer.find_liquidity_pools(highs, lows)
        for pool in pools:
            pool["event"] = "LIQUIDITY_POOL"
            events.append(pool)

        events.sort(key=lambda e: e.get("index", 0))

        return events
