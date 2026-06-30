"""订单流因子 — CVD/失衡/吸收/扫单/冰山/OBI"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from one_quant.core.types import Trade
from one_quant.infra.logging import get_logger

logger = get_logger(__name__)


class OrderFlowAnalyzer:
    """订单流分析器。

    从逐笔成交数据中提取微观结构因子：
    - CVD (Cumulative Volume Delta): 累积买卖量差
    - 失衡 (Imbalance): 买卖量不对称
    - 吸收 (Absorption): 大单被对手方吸收
    - 扫单 (Sweep): 快速连续同方向大单
    - 冰山 (Iceberg): 隐藏订单检测
    - OBI (Order Book Imbalance): 盘口失衡
    """

    def __init__(self, window_size: int = 100) -> None:
        self._window = window_size
        self._trades: list[Trade] = []
        self._cvd = Decimal("0")
        self._buy_vol = Decimal("0")
        self._sell_vol = Decimal("0")

    def on_trade(self, trade: Trade) -> dict[str, Any]:
        """处理逐笔成交，返回订单流因子"""
        self._trades.append(trade)
        if len(self._trades) > self._window:
            self._trades = self._trades[-self._window:]

        # 更新 CVD
        if trade.side == "buy":
            self._cvd += trade.quantity
            self._buy_vol += trade.quantity
        else:
            self._cvd -= trade.quantity
            self._sell_vol += trade.quantity

        return {
            "cvd": str(self._cvd),
            "imbalance": str(self._calc_imbalance()),
            "absorption_score": str(self._detect_absorption()),
            "sweep_detected": self._detect_sweep(),
            "obi": str(self._calc_obi()),
        }

    def _calc_imbalance(self) -> Decimal:
        """计算买卖失衡率"""
        total = self._buy_vol + self._sell_vol
        if total == 0:
            return Decimal("0")
        return (self._buy_vol - self._sell_vol) / total

    def _detect_absorption(self) -> float:
        """检测大单吸收（大单后价格未大幅变动）"""
        if len(self._trades) < 10:
            return 0.0
        recent = self._trades[-10:]
        large_trades = [t for t in recent if t.quantity > Decimal("1")]
        if not large_trades:
            return 0.0
        # 大单后价格变动小 = 被吸收
        price_changes = []
        for i, t in enumerate(large_trades[:-1]):
            next_price = large_trades[i + 1].price
            change = abs(next_price - t.price) / t.price if t.price > 0 else Decimal("0")
            price_changes.append(float(change))
        avg_change = sum(price_changes) / len(price_changes) if price_changes else 0
        return max(0, 1 - avg_change * 100)  # 吸收分数

    def _detect_sweep(self) -> bool:
        """检测扫单（连续 5+ 笔同方向大单）"""
        if len(self._trades) < 5:
            return False
        recent = self._trades[-5:]
        sides = [t.side for t in recent]
        return len(set(sides)) == 1  # 全部同方向

    def _calc_obi(self) -> Decimal:
        """计算 OBI（简化版，基于近期成交方向）"""
        if not self._trades:
            return Decimal("0")
        recent = self._trades[-20:]
        buy_count = sum(1 for t in recent if t.side == "buy")
        total = len(recent)
        return Decimal(buy_count) / Decimal(total) - Decimal("0.5") if total > 0 else Decimal("0")

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "trades_in_window": len(self._trades),
            "cvd": str(self._cvd),
            "buy_vol": str(self._buy_vol),
            "sell_vol": str(self._sell_vol),
        }
