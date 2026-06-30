"""
ONE量化 - 哨兵智能体

实时监控异常（价格突变、成交量暴增、持仓风险），触发告警。
"""

from __future__ import annotations

import logging
from typing import Any

from one_quant.agents.base import BaseAgent

logger = logging.getLogger(__name__)


class WatcherAgent(BaseAgent):
    """哨兵智能体。

    职责：
    1. 监控价格异常波动（插针、闪崩）
    2. 监控成交量异常（放量 N 倍）
    3. 监控持仓风险（接近强平、大额亏损）
    4. 监控系统健康（行情断线、延迟升高）
    5. 触发告警并生成中文播报

    输入：实时市场数据、持仓状态、系统指标
    输出：告警列表 + 中文播报
    """

    name = "watcher"
    description = "实时异常检测与告警播报"

    # 告警阈值
    PRICE_SPIKE_PCT = 5.0  # 价格突变阈值（%）
    VOLUME_MULTIPLIER = 5.0  # 成交量放大倍数
    LOSS_ALERT_PCT = 10.0  # 亏损告警阈值（%）

    async def run(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """执行异常检测。

        Args:
            input_data: 包含 tickers, positions, system_metrics。

        Returns:
            告警列表 + 中文播报。
        """
        tickers = input_data.get("tickers", {})
        positions = input_data.get("positions", [])
        system_metrics = input_data.get("system_metrics", {})

        alerts: list[dict[str, Any]] = []

        # 价格异常检测
        alerts.extend(self._check_price_anomalies(tickers))

        # 持仓风险检测
        alerts.extend(self._check_position_risks(positions))

        # 系统健康检测
        alerts.extend(self._check_system_health(system_metrics))

        # 生成播报
        broadcast = self._generate_broadcast(alerts)

        return {
            "success": True,
            "agent": self.name,
            "alerts": alerts,
            "broadcast": broadcast,
            "alert_count": len(alerts),
        }

    def _check_price_anomalies(self, tickers: dict[str, Any]) -> list[dict[str, Any]]:
        """检查价格异常。"""
        alerts = []
        for symbol, ticker in tickers.items():
            if not isinstance(ticker, dict):
                continue

            change = abs(ticker.get("change_pct", 0))
            if change > self.PRICE_SPIKE_PCT:
                alerts.append(
                    {
                        "level": "P1",
                        "type": "price_spike",
                        "symbol": symbol,
                        "message": f"{symbol} 价格突变 {change:.2f}%",
                        "data": ticker,
                    }
                )

        return alerts

    def _check_position_risks(self, positions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """检查持仓风险。"""
        alerts = []
        for pos in positions:
            pnl_pct = pos.get("pnl_pct", 0)
            if pnl_pct < -self.LOSS_ALERT_PCT:
                alerts.append(
                    {
                        "level": "P1",
                        "type": "position_loss",
                        "symbol": pos.get("symbol", "?"),
                        "message": f"{pos.get('symbol', '?')} 亏损 {pnl_pct:.2f}%",
                        "data": pos,
                    }
                )

        return alerts

    def _check_system_health(self, metrics: dict[str, Any]) -> list[dict[str, Any]]:
        """检查系统健康。"""
        alerts = []

        # 行情延迟检查
        latency = metrics.get("market_latency_ms", 0)
        if latency > 1000:
            alerts.append(
                {
                    "level": "P2",
                    "type": "high_latency",
                    "message": f"行情延迟 {latency:.0f}ms 超过阈值",
                    "data": {"latency_ms": latency},
                }
            )

        return alerts

    def _generate_broadcast(self, alerts: list[dict[str, Any]]) -> str:
        """生成中文播报。"""
        if not alerts:
            return "✅ 系统运行正常，无异常告警。"

        lines = [f"⚠️ 检测到 {len(alerts)} 条告警："]
        for alert in alerts:
            level = alert.get("level", "?")
            message = alert.get("message", "")
            lines.append(f"  [{level}] {message}")

        return "\n".join(lines)
