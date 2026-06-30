"""
ONE量化 - 分诊员智能体

告警分级归类：P0 紧急 / P1 高 / P2 中 / P3 低，中文输出。
对系统产生的各类告警进行智能分类、优先级排序和中文播报。

设计原则：
- 全中文注释和输出
- AI 无否决权：只产告警建议，必过风控
- 所有异步方法完整类型标注
"""

from __future__ import annotations

import time
from enum import Enum
from typing import Any

from one_quant.agents.base import BaseAgent
from one_quant.infra.logging import get_logger

logger = get_logger(__name__)


class AlertLevel(str, Enum):
    """告警等级枚举。"""

    P0 = "P0"  # 紧急：系统故障、大面积爆仓、行情断线
    P1 = "P1"  # 高：单品种异常、大额亏损、流动性枯竭
    P2 = "P2"  # 中：策略信号冲突、延迟升高、小幅度异常
    P3 = "P3"  # 低：信息类、日常波动、系统提示


# 告警等级中文描述
LEVEL_DESC_ZH: dict[str, str] = {
    AlertLevel.P0: "🔴 紧急",
    AlertLevel.P1: "🟠 高",
    AlertLevel.P2: "🟡 中",
    AlertLevel.P3: "🟢 低",
}


class TriagerAgent(BaseAgent):
    """分诊员智能体。

    职责：
    1. 接收原始告警数据
    2. 按严重程度分为 P0/P1/P2/P3 四级
    3. 归类告警类型（价格异常、持仓风险、系统故障等）
    4. 生成中文告警播报
    5. 提取关键行动建议

    输入：原始告警列表
    输出：分级告警 + 中文播报 + 行动建议
    """

    name = "triager"
    description = "告警分级归类与中文播报"

    # 关键词 → 告警等级映射（规则引擎，兜底用）
    KEYWORD_RULES: dict[str, AlertLevel] = {
        # P0 紧急
        "系统故障": AlertLevel.P0,
        "行情断线": AlertLevel.P0,
        "大面积爆仓": AlertLevel.P0,
        "服务不可用": AlertLevel.P0,
        "数据丢失": AlertLevel.P0,
        "强平": AlertLevel.P0,
        # P1 高
        "闪崩": AlertLevel.P1,
        "暴跌": AlertLevel.P1,
        "暴涨": AlertLevel.P1,
        "大额亏损": AlertLevel.P1,
        "流动性枯竭": AlertLevel.P1,
        "插针": AlertLevel.P1,
        "异常成交": AlertLevel.P1,
        # P2 中
        "延迟升高": AlertLevel.P2,
        "策略冲突": AlertLevel.P2,
        "信号分歧": AlertLevel.P2,
        "小幅异常": AlertLevel.P2,
        "成交量异常": AlertLevel.P2,
        # P3 低
        "日常波动": AlertLevel.P3,
        "信息提示": AlertLevel.P3,
        "系统提示": AlertLevel.P3,
    }

    async def run(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """执行告警分诊。

        Args:
            input_data: 包含 alerts（原始告警列表）。

        Returns:
            分级告警 + 中文播报 + 行动建议。
        """
        raw_alerts = input_data.get("alerts", [])

        if not raw_alerts:
            return {
                "success": True,
                "agent": self.name,
                "triaged_alerts": [],
                "broadcast": "✅ 当前无告警，系统运行正常。",
                "action_items": [],
                "stats": {"P0": 0, "P1": 0, "P2": 0, "P3": 0},
            }

        # 分诊每条告警
        triaged: list[dict[str, Any]] = []
        for alert in raw_alerts:
            triaged.append(self._triage_single(alert))

        # 按等级排序（P0 在前）
        level_order = {AlertLevel.P0: 0, AlertLevel.P1: 1, AlertLevel.P2: 2, AlertLevel.P3: 3}
        triaged.sort(key=lambda a: level_order.get(AlertLevel(a["level"]), 99))

        # 统计
        stats: dict[str, int] = {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
        for a in triaged:
            stats[a["level"]] = stats.get(a["level"], 0) + 1

        # 生成播报
        broadcast = self._generate_broadcast(triaged, stats)

        # 提取行动建议
        action_items = self._extract_actions(triaged)

        return {
            "success": True,
            "agent": self.name,
            "triaged_alerts": triaged,
            "broadcast": broadcast,
            "action_items": action_items,
            "stats": stats,
            "has_p0": stats["P0"] > 0,
        }

    def _triage_single(self, alert: dict[str, Any]) -> dict[str, Any]:
        """对单条告警进行分诊。

        Args:
            alert: 原始告警数据。

        Returns:
            分诊后的告警数据。
        """
        # 如果已有等级，先尊重原等级
        existing_level = alert.get("level", "")

        # 通过关键词规则重新判定
        message = alert.get("message", "")
        alert_type = alert.get("type", "unknown")
        keyword_level = self._match_keyword_level(message)

        # 取更严重的等级
        final_level = self._pick_severity(existing_level, keyword_level)

        # 生成中文描述
        level_desc = LEVEL_DESC_ZH.get(final_level, "❓ 未知")
        category = self._categorize(alert_type, message)

        return {
            **alert,
            "level": final_level,
            "level_desc": level_desc,
            "category": category,
            "triaged_at": time.time_ns(),
        }

    def _match_keyword_level(self, message: str) -> AlertLevel | None:
        """通过关键词匹配告警等级。

        Args:
            message: 告警消息文本。

        Returns:
            匹配到的最高等级，None 表示未匹配。
        """
        matched: AlertLevel | None = None
        severity_order = {AlertLevel.P0: 0, AlertLevel.P1: 1, AlertLevel.P2: 2, AlertLevel.P3: 3}

        for keyword, level in self.KEYWORD_RULES.items():
            if keyword in message:
                if matched is None or severity_order[level] < severity_order[matched]:
                    matched = level

        return matched

    @staticmethod
    def _pick_severity(level_a: str, level_b: AlertLevel | None) -> str:
        """取两个等级中更严重的一个。

        Args:
            level_a: 等级字符串。
            level_b: 等级枚举或 None。

        Returns:
            更严重的等级字符串。
        """
        if level_b is None:
            return level_a or AlertLevel.P3

        severity_order = {AlertLevel.P0: 0, AlertLevel.P1: 1, AlertLevel.P2: 2, AlertLevel.P3: 3}
        a_score = severity_order.get(AlertLevel(level_a), 99) if level_a else 99
        b_score = severity_order.get(level_b, 99)

        return level_a if a_score <= b_score else level_b

    @staticmethod
    def _categorize(alert_type: str, message: str) -> str:
        """告警分类（中文）。

        Args:
            alert_type: 原始告警类型。
            message: 告警消息。

        Returns:
            中文分类名称。
        """
        category_map = {
            "price_spike": "价格异常",
            "price_drop": "价格异常",
            "volume_spike": "成交量异常",
            "position_loss": "持仓风险",
            "position_risk": "持仓风险",
            "high_latency": "系统延迟",
            "connection_lost": "连接故障",
            "system_error": "系统故障",
            "liquidation_risk": "强平风险",
            "strategy_conflict": "策略冲突",
        }

        if alert_type in category_map:
            return category_map[alert_type]

        # 关键词兜底分类
        if any(w in message for w in ["价格", "涨", "跌", "插针"]):
            return "价格异常"
        if any(w in message for w in ["成交", "放量", "缩量"]):
            return "成交量异常"
        if any(w in message for w in ["持仓", "亏损", "盈亏", "强平"]):
            return "持仓风险"
        if any(w in message for w in ["延迟", "超时", "断线", "故障"]):
            return "系统异常"

        return "其他"

    def _generate_broadcast(
        self,
        triaged: list[dict[str, Any]],
        stats: dict[str, int],
    ) -> str:
        """生成中文告警播报。

        Args:
            triaged: 分诊后的告警列表。
            stats: 各等级统计。

        Returns:
            中文播报文本。
        """
        if not triaged:
            return "✅ 当前无告警，系统运行正常。"

        lines: list[str] = []

        # 摘要行
        summary_parts: list[str] = []
        for level in [AlertLevel.P0, AlertLevel.P1, AlertLevel.P2, AlertLevel.P3]:
            count = stats.get(level, 0)
            if count > 0:
                summary_parts.append(f"{LEVEL_DESC_ZH[level]}×{count}")

        lines.append(f"📋 告警分诊报告 — 共 {len(triaged)} 条: {', '.join(summary_parts)}")
        lines.append("")

        # 按等级分组输出
        current_level = ""
        for alert in triaged:
            level = alert["level"]
            if level != current_level:
                current_level = level
                lines.append(f"【{LEVEL_DESC_ZH[level]}】")

            category = alert.get("category", "其他")
            message = alert.get("message", "")
            symbol = alert.get("symbol", "")
            prefix = f"  • [{category}]"
            if symbol:
                prefix += f" {symbol}:"
            lines.append(f"{prefix} {message}")

        return "\n".join(lines)

    def _extract_actions(self, triaged: list[dict[str, Any]]) -> list[str]:
        """提取关键行动建议。

        Args:
            triaged: 分诊后的告警列表。

        Returns:
            行动建议列表。
        """
        actions: list[str] = []

        p0_alerts = [a for a in triaged if a["level"] == AlertLevel.P0]
        p1_alerts = [a for a in triaged if a["level"] == AlertLevel.P1]

        if p0_alerts:
            actions.append("🚨 存在 P0 紧急告警，建议立即人工介入")
            for a in p0_alerts:
                if "强平" in a.get("message", ""):
                    actions.append("⚠️ 检查强平风险仓位，必要时手动减仓")
                if "断线" in a.get("message", "") or "故障" in a.get("message", ""):
                    actions.append("⚠️ 检查行情连接和系统健康状态")

        if p1_alerts:
            actions.append("🟠 存在 P1 高级告警，建议密切关注")
            for a in p1_alerts:
                if "亏损" in a.get("message", ""):
                    actions.append("📊 检查亏损仓位，评估止损策略")
                if "异常" in a.get("message", "") and "价格" in a.get("message", ""):
                    actions.append("📊 关注异常价格走势，防范假突破")

        if not actions:
            actions.append("✅ 无需立即行动，持续监控即可")

        return actions
