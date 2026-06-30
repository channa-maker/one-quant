"""
ONE量化 - 宏观智能体

宏观/美联储/CPI 影响研判，分析宏观经济因素对市场的影响。

设计原则：
- 全中文注释和输出
- AI 无否决权：只产研判建议，必过风控
- 所有异步方法完整类型标注
"""

from __future__ import annotations

from typing import Any

from one_quant.agents.base import BaseAgent
from one_quant.infra.logging import get_logger

logger = get_logger(__name__)


# 宏观事件类型
MACRO_EVENT_TYPES = {
    "fed_rate": "美联储利率决议",
    "cpi": "CPI 数据公布",
    "nfp": "非农就业数据",
    "gdp": "GDP 数据",
    "pmi": "PMI 采购经理指数",
    "ppi": "PPI 生产者价格指数",
    "retail_sales": "零售销售数据",
    "consumer_confidence": "消费者信心指数",
    "fomc_minutes": "FOMC 会议纪要",
    "fed_speech": "美联储官员讲话",
    "geopolitical": "地缘政治事件",
    "trade_war": "贸易摩擦",
    "oil_price": "油价波动",
    "dollar_index": "美元指数",
    "bond_yield": "国债收益率",
}


class MacroAgent(BaseAgent):
    """宏观智能体。

    职责：
    1. 分析宏观经济事件对市场的影响
    2. 评估美联储政策走向
    3. 解读 CPI/PPI 等通胀数据
    4. 评估地缘政治风险
    5. 输出中文宏观研判报告

    输入：宏观事件数据、经济指标、市场状态
    输出：中文宏观研判 + 影响评估 + 交易建议
    """

    name = "macro"
    description = "宏观经济因素影响研判"

    async def run(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """执行宏观研判。

        Args:
            input_data: 包含 events（宏观事件列表）、indicators（经济指标）、
                       market_state（市场状态）。

        Returns:
            中文宏观研判 + 影响评估。
        """
        events = input_data.get("events", [])
        indicators = input_data.get("indicators", {})
        market_state = input_data.get("market_state", {})

        if not events and not indicators:
            return {
                "success": True,
                "agent": self.name,
                "report": "## 📭 宏观研判\n\n当前无重大宏观事件和经济数据需要分析。",
                "impact_score": 0.0,
                "risk_level": "低",
            }

        # 分析宏观事件
        event_analyses = self._analyze_events(events)

        # 解读经济指标
        indicator_insights = self._interpret_indicators(indicators)

        # 评估综合影响
        impact_score = self._calculate_impact(event_analyses, indicator_insights)

        # 生成中文报告
        report = self._generate_report(event_analyses, indicator_insights, impact_score, market_state)

        # 风险等级
        risk_level = self._assess_risk_level(impact_score)

        return {
            "success": True,
            "agent": self.name,
            "report": report,
            "impact_score": round(impact_score, 3),
            "risk_level": risk_level,
            "event_count": len(events),
            "key_events": [e["type"] for e in events[:3]],
        }

    def _analyze_events(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """分析宏观事件。

        Args:
            events: 事件列表，每项包含 type, description, date 等。

        Returns:
            分析结果列表。
        """
        analyses: list[dict[str, Any]] = []

        for event in events:
            event_type = event.get("type", "unknown")
            description = event.get("description", "")
            impact_direction = event.get("impact", "neutral")  # positive/negative/neutral

            # 获取事件中文名称
            type_zh = MACRO_EVENT_TYPES.get(event_type, event_type)

            # 评估影响
            severity = self._assess_event_severity(event_type, impact_direction)
            market_impact = self._predict_market_impact(event_type, impact_direction)

            analyses.append({
                "type": event_type,
                "type_zh": type_zh,
                "description": description,
                "impact_direction": impact_direction,
                "severity": severity,
                "market_impact": market_impact,
            })

        return analyses

    def _interpret_indicators(self, indicators: dict[str, Any]) -> list[dict[str, Any]]:
        """解读经济指标。

        Args:
            indicators: 经济指标字典。

        Returns:
            解读结果列表。
        """
        insights: list[dict[str, Any]] = []

        for name, value in indicators.items():
            if not isinstance(value, (int, float)):
                continue

            insight = self._interpret_single_indicator(name, value)
            if insight:
                insights.append(insight)

        return insights

    def _interpret_single_indicator(self, name: str, value: float) -> dict[str, Any] | None:
        """解读单个经济指标。

        Args:
            name: 指标名称。
            value: 指标值。

        Returns:
            解读结果或 None。
        """
        interpretations: dict[str, dict[str, Any]] = {
            "cpi_yoy": {
                "name_zh": "CPI 同比",
                "high_threshold": 3.5,
                "low_threshold": 1.5,
                "high_meaning": "通胀偏高，美联储可能维持鹰派立场",
                "low_meaning": "通胀温和，有利于宽松政策预期",
            },
            "fed_rate": {
                "name_zh": "联邦基金利率",
                "high_threshold": 5.0,
                "low_threshold": 2.0,
                "high_meaning": "利率处于高位，借贷成本上升，风险资产承压",
                "low_meaning": "利率处于低位，流动性充裕，利好风险资产",
            },
            "unemployment": {
                "name_zh": "失业率",
                "high_threshold": 5.0,
                "low_threshold": 3.5,
                "high_meaning": "就业市场疲软，可能促使美联储降息",
                "low_meaning": "就业市场强劲，支撑消费和经济",
            },
            "dollar_index": {
                "name_zh": "美元指数",
                "high_threshold": 105.0,
                "low_threshold": 95.0,
                "high_meaning": "美元走强，新兴市场和大宗商品承压",
                "low_meaning": "美元走弱，利好风险资产和大宗商品",
            },
            "vix": {
                "name_zh": "VIX 恐慌指数",
                "high_threshold": 30.0,
                "low_threshold": 15.0,
                "high_meaning": "市场恐慌情绪升温，波动性加大",
                "low_meaning": "市场情绪平稳，波动性较低",
            },
        }

        if name not in interpretations:
            return None

        config = interpretations[name]
        name_zh = config["name_zh"]

        if value > config["high_threshold"]:
            direction = "偏高"
            meaning = config["high_meaning"]
            signal = "bearish"
        elif value < config["low_threshold"]:
            direction = "偏低"
            meaning = config["low_meaning"]
            signal = "bullish"
        else:
            direction = "正常"
            meaning = f"{name_zh}处于正常范围"
            signal = "neutral"

        return {
            "name": name,
            "name_zh": name_zh,
            "value": value,
            "direction": direction,
            "meaning": meaning,
            "signal": signal,
        }

    @staticmethod
    def _assess_event_severity(event_type: str, impact: str) -> str:
        """评估事件严重程度。

        Args:
            event_type: 事件类型。
            impact: 影响方向。

        Returns:
            严重程度描述。
        """
        high_impact_events = {"fed_rate", "cpi", "geopolitical", "trade_war"}
        medium_impact_events = {"nfp", "fomc_minutes", "fed_speech", "dollar_index"}

        if event_type in high_impact_events:
            return "高"
        elif event_type in medium_impact_events:
            return "中"
        return "低"

    @staticmethod
    def _predict_market_impact(event_type: str, impact: str) -> str:
        """预测市场影响。

        Args:
            event_type: 事件类型。
            impact: 影响方向。

        Returns:
            市场影响描述。
        """
        if impact == "positive":
            return "利好风险资产，可能推动上涨"
        elif impact == "negative":
            return "利空风险资产，可能导致下跌"
        return "影响不确定，需观察市场反应"

    def _calculate_impact(
        self,
        events: list[dict[str, Any]],
        indicators: list[dict[str, Any]],
    ) -> float:
        """计算综合影响分数。

        Args:
            events: 事件分析结果。
            indicators: 指标解读结果。

        Returns:
            影响分数 (-1 到 1)，正为利好，负为利空。
        """
        score = 0.0
        count = 0

        # 事件影响
        for event in events:
            severity_weight = {"高": 1.0, "中": 0.6, "低": 0.3}.get(event.get("severity", "低"), 0.3)
            direction = event.get("impact_direction", "neutral")
            if direction == "positive":
                score += severity_weight
            elif direction == "negative":
                score -= severity_weight
            count += 1

        # 指标影响
        for indicator in indicators:
            signal = indicator.get("signal", "neutral")
            if signal == "bullish":
                score += 0.3
            elif signal == "bearish":
                score -= 0.3
            count += 1

        if count > 0:
            score = score / count

        return max(-1.0, min(1.0, score))

    def _generate_report(
        self,
        events: list[dict[str, Any]],
        indicators: list[dict[str, Any]],
        impact_score: float,
        market_state: dict[str, Any],
    ) -> str:
        """生成中文宏观研判报告。

        Args:
            events: 事件分析结果。
            indicators: 指标解读结果。
            impact_score: 综合影响分数。
            market_state: 市场状态。

        Returns:
            中文报告文本。
        """
        lines: list[str] = ["## 🌍 宏观研判报告\n"]

        # 影响总览
        if impact_score > 0.3:
            sentiment = "偏乐观"
            emoji = "🟢"
        elif impact_score < -0.3:
            sentiment = "偏悲观"
            emoji = "🔴"
        else:
            sentiment = "中性"
            emoji = "🟡"

        lines.append(f"**宏观环境: {emoji} {sentiment}** (影响分数: {impact_score:+.3f})\n")

        # 事件分析
        if events:
            lines.append("### 📰 宏观事件分析\n")
            for event in events:
                severity = event.get("severity", "低")
                type_zh = event.get("type_zh", "")
                description = event.get("description", "")
                impact = event.get("market_impact", "")

                severity_emoji = {"高": "🔴", "中": "🟡", "低": "🟢"}.get(severity, "⚪")
                lines.append(f"- {severity_emoji} **{type_zh}** [{severity}影响]")
                if description:
                    lines.append(f"  - {description}")
                lines.append(f"  - 影响预判: {impact}")

        # 指标解读
        if indicators:
            lines.append("\n### 📊 经济指标解读\n")
            for ind in indicators:
                signal_emoji = {"bullish": "🟢", "bearish": "🔴", "neutral": "🟡"}.get(
                    ind.get("signal", "neutral"), "⚪"
                )
                name_zh = ind.get("name_zh", ind.get("name", ""))
                value = ind.get("value", 0)
                direction = ind.get("direction", "")
                meaning = ind.get("meaning", "")

                lines.append(f"- {signal_emoji} **{name_zh}**: {value} ({direction})")
                lines.append(f"  - {meaning}")

        # 交易启示
        lines.append("\n### 💡 交易启示\n")
        if impact_score > 0.3:
            lines.append("- 宏观环境利好，可适当增加风险敞口")
            lines.append("- 关注受益板块和品种的做多机会")
        elif impact_score < -0.3:
            lines.append("- 宏观环境利空，建议降低风险敞口")
            lines.append("- 加强对冲，关注避险资产配置")
        else:
            lines.append("- 宏观环境无明显方向，建议维持当前配置")
            lines.append("- 等待更多数据确认方向")

        return "\n".join(lines)

    @staticmethod
    def _assess_risk_level(impact_score: float) -> str:
        """评估宏观风险等级。

        Args:
            impact_score: 综合影响分数。

        Returns:
            风险等级描述。
        """
        if abs(impact_score) > 0.5:
            return "高"
        elif abs(impact_score) > 0.2:
            return "中"
        return "低"
