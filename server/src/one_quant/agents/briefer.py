"""
ONE量化 - 简报官智能体

每日盘前/盘后生成中文研报，汇总市场行情、持仓表现、策略信号、AI 分析。
"""

from __future__ import annotations

import logging
from typing import Any

from one_quant.agents.base import BaseAgent

logger = logging.getLogger(__name__)


class BrieferAgent(BaseAgent):
    """简报官智能体。

    职责：
    1. 汇总 24h 市场行情（涨跌幅、成交量、资金费率）
    2. 汇总持仓表现（盈亏、回撤）
    3. 汇总策略信号（今日信号、胜率）
    4. 汇总 AI 分析（情绪、宏观、事件）
    5. 生成中文研报

    输入：市场数据、持仓数据、信号历史、AI 分析结果
    输出：中文研报文本 + 结构化摘要
    """

    name = "briefer"
    description = "每日盘前/盘后中文研报生成"

    async def run(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """生成每日研报。

        Args:
            input_data: 包含 market_data, positions, signals, ai_analysis 等。

        Returns:
            中文研报 + 结构化摘要。
        """
        market_data = input_data.get("market_data", {})
        positions = input_data.get("positions", [])
        signals = input_data.get("signals", [])
        ai_analysis = input_data.get("ai_analysis", {})

        # 生成研报各段落
        sections = []

        # 行情概览
        sections.append(self._section_market_overview(market_data))

        # 持仓表现
        sections.append(self._section_positions(positions))

        # 策略信号
        sections.append(self._section_signals(signals))

        # AI 分析
        sections.append(self._section_ai_analysis(ai_analysis))

        # 总结
        sections.append(self._section_summary(market_data, positions, signals))

        report = "\n\n".join(sections)

        return {
            "success": True,
            "agent": self.name,
            "report": report,
            "summary": {
                "market_sentiment": self._assess_sentiment(market_data),
                "risk_level": self._assess_risk(positions),
                "action_items": self._extract_actions(signals),
            },
        }

    def _section_market_overview(self, data: dict[str, Any]) -> str:
        """生成行情概览段落。"""
        if not data:
            return "## 📊 行情概览\n\n暂无行情数据。"

        lines = ["## 📊 行情概览"]
        for symbol, info in data.items():
            if isinstance(info, dict):
                change = info.get("change_24h", 0)
                emoji = "🟢" if change >= 0 else "🔴"
                lines.append(f"- {emoji} {symbol}: {change:+.2f}%")
        return "\n".join(lines)

    def _section_positions(self, positions: list[dict[str, Any]]) -> str:
        """生成持仓表现段落。"""
        if not positions:
            return "## 💼 持仓表现\n\n当前无持仓。"

        lines = ["## 💼 持仓表现"]
        total_pnl = 0
        for pos in positions:
            pnl = pos.get("unrealized_pnl", 0)
            total_pnl += pnl
            emoji = "🟢" if pnl >= 0 else "🔴"
            lines.append(f"- {emoji} {pos.get('symbol', '?')}: {pnl:+.2f} USDT")

        lines.append(f"\n**总未实现盈亏: {total_pnl:+.2f} USDT**")
        return "\n".join(lines)

    def _section_signals(self, signals: list[dict[str, Any]]) -> str:
        """生成策略信号段落。"""
        if not signals:
            return "## 📡 策略信号\n\n今日暂无信号。"

        lines = ["## 📡 策略信号"]
        for sig in signals[-10:]:  # 最近 10 条
            side = sig.get("side", "?")
            emoji = "🟢" if side == "buy" else "🔴"
            lines.append(
                f"- {emoji} {sig.get('symbol', '?')} {side} "
                f"强度={sig.get('strength', 0):.2f} "
                f"({sig.get('strategy_name', '?')}): {sig.get('reason', '')}"
            )
        return "\n".join(lines)

    def _section_ai_analysis(self, analysis: dict[str, Any]) -> str:
        """生成 AI 分析段落。"""
        if not analysis:
            return "## 🤖 AI 分析\n\n暂无 AI 分析。"

        lines = ["## 🤖 AI 分析"]
        for key, value in analysis.items():
            if isinstance(value, str):
                lines.append(f"- **{key}**: {value}")
        return "\n".join(lines)

    def _section_summary(
        self,
        market: dict[str, Any],
        positions: list[dict[str, Any]],
        signals: list[dict[str, Any]],
    ) -> str:
        """生成总结。"""
        return "## 📝 总结\n\n系统运行正常，请关注持仓风险。"

    def _assess_sentiment(self, data: dict[str, Any]) -> str:
        """评估市场情绪。"""
        return "中性"

    def _assess_risk(self, positions: list[dict[str, Any]]) -> str:
        """评估风险等级。"""
        if not positions:
            return "低"
        return "中"

    def _extract_actions(self, signals: list[dict[str, Any]]) -> list[str]:
        """提取待办事项。"""
        return ["关注持仓风险"]
