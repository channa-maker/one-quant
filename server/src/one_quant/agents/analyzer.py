"""
ONE量化 - 解读员智能体

回测结果中文解读：将策略回测数据转化为人类可读的中文分析报告。

设计原则：
- 全中文注释和输出
- AI 无否决权：只产分析建议，必过风控
- 所有异步方法完整类型标注
"""

from __future__ import annotations

from typing import Any

from one_quant.agents.base import BaseAgent
from one_quant.infra.logging import get_logger

logger = get_logger(__name__)


class AnalyzerAgent(BaseAgent):
    """解读员智能体。

    职责：
    1. 接收策略回测结果数据
    2. 解读关键指标（夏普比率、最大回撤、胜率、盈亏比等）
    3. 识别策略优劣势
    4. 生成中文解读报告
    5. 提供优化建议

    输入：回测结果数据
    输出：中文解读报告 + 结构化评估
    """

    name = "analyzer"
    description = "回测结果中文解读与策略评估"

    # 指标评级阈值
    SHARPE_EXCELLENT = 2.0
    SHARPE_GOOD = 1.0
    SHARPE_POOR = 0.5

    MAX_DD_EXCELLENT = 0.10  # 10%
    MAX_DD_GOOD = 0.20  # 20%
    MAX_DD_POOR = 0.30  # 30%

    WIN_RATE_EXCELLENT = 0.60
    WIN_RATE_GOOD = 0.45
    WIN_RATE_POOR = 0.35

    PROFIT_FACTOR_EXCELLENT = 2.0
    PROFIT_FACTOR_GOOD = 1.5
    PROFIT_FACTOR_POOR = 1.0

    async def run(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """执行回测结果解读。

        Args:
            input_data: 包含 backtest_result（回测结果数据）。

        Returns:
            中文解读报告 + 结构化评估。
        """
        bt = input_data.get("backtest_result", {})

        if not bt:
            return {
                "success": True,
                "agent": self.name,
                "report": "## ⚠️ 无回测数据\n\n未提供回测结果，无法生成解读报告。",
                "evaluation": {},
            }

        # 解读各指标
        sections: list[str] = []
        evaluation: dict[str, Any] = {}

        # 标题
        strategy_name = bt.get("strategy_name", "未知策略")
        sections.append(f"## 📊 回测解读报告 — {strategy_name}\n")

        # 收益分析
        return_eval = self._analyze_returns(bt)
        sections.append(return_eval["section"])
        evaluation["returns"] = return_eval["rating"]

        # 风险分析
        risk_eval = self._analyze_risk(bt)
        sections.append(risk_eval["section"])
        evaluation["risk"] = risk_eval["rating"]

        # 交易统计
        trade_eval = self._analyze_trades(bt)
        sections.append(trade_eval["section"])
        evaluation["trades"] = trade_eval["rating"]

        # 综合评估
        overall = self._overall_evaluation(evaluation)
        sections.append(overall["section"])
        evaluation["overall"] = overall["rating"]
        evaluation["grade"] = overall["grade"]

        # 优化建议
        suggestions = self._generate_suggestions(bt, evaluation)
        sections.append(suggestions)

        report = "\n\n".join(sections)

        return {
            "success": True,
            "agent": self.name,
            "report": report,
            "evaluation": evaluation,
        }

    def _analyze_returns(self, bt: dict[str, Any]) -> dict[str, Any]:
        """分析收益指标。

        Args:
            bt: 回测结果数据。

        Returns:
            包含 section（报告段落）和 rating（评级）的字典。
        """
        total_return = float(bt.get("total_return", 0))
        annual_return = float(bt.get("annual_return", 0))
        sharpe = float(bt.get("sharpe_ratio", 0))

        # 评级
        if sharpe >= self.SHARPE_EXCELLENT:
            rating = "优秀"
            emoji = "🌟"
        elif sharpe >= self.SHARPE_GOOD:
            rating = "良好"
            emoji = "✅"
        elif sharpe >= self.SHARPE_POOR:
            rating = "一般"
            emoji = "⚠️"
        else:
            rating = "较差"
            emoji = "❌"

        ret_rating = "正收益" if total_return > 0 else "负收益"
        annual_rating = "可观" if annual_return > 0.15 else "一般" if annual_return > 0 else "亏损"
        section = f"""### 📈 收益分析 {emoji}

| 指标 | 数值 | 评级 |
|------|------|------|
| 总收益率 | {total_return:+.2%} | {ret_rating} |
| 年化收益率 | {annual_return:+.2%} | {annual_rating} |
| 夏普比率 | {sharpe:.2f} | {rating} |

**解读**: 该策略{self._describe_sharpe(sharpe)}，{self._describe_return(total_return)}。"""

        return {"section": section, "rating": rating}

    def _analyze_risk(self, bt: dict[str, Any]) -> dict[str, Any]:
        """分析风险指标。

        Args:
            bt: 回测结果数据。

        Returns:
            包含 section 和 rating 的字典。
        """
        max_dd = float(bt.get("max_drawdown", 0))
        volatility = float(bt.get("volatility", 0))
        calmar = float(bt.get("calmar_ratio", 0))

        # 评级
        if max_dd <= self.MAX_DD_EXCELLENT:
            rating = "优秀"
            emoji = "🌟"
        elif max_dd <= self.MAX_DD_GOOD:
            rating = "良好"
            emoji = "✅"
        elif max_dd <= self.MAX_DD_POOR:
            rating = "一般"
            emoji = "⚠️"
        else:
            rating = "较差"
            emoji = "❌"

        vol_rating = "低波动" if volatility < 0.15 else "中波动" if volatility < 0.25 else "高波动"
        calmar_rating = "优秀" if calmar > 3 else "良好" if calmar > 1 else "一般"
        section = f"""### 🛡️ 风险分析 {emoji}

| 指标 | 数值 | 评级 |
|------|------|------|
| 最大回撤 | {max_dd:.2%} | {rating} |
| 年化波动率 | {volatility:.2%} | {vol_rating} |
| 卡玛比率 | {calmar:.2f} | {calmar_rating} |

**解读**: {self._describe_drawdown(max_dd)}。"""

        return {"section": section, "rating": rating}

    def _analyze_trades(self, bt: dict[str, Any]) -> dict[str, Any]:
        """分析交易统计。

        Args:
            bt: 回测结果数据。

        Returns:
            包含 section 和 rating 的字典。
        """
        total_trades = int(bt.get("total_trades", 0))
        win_rate = float(bt.get("win_rate", 0))
        profit_factor = float(bt.get("profit_factor", 0))
        avg_win = float(bt.get("avg_win", 0))
        avg_loss = float(bt.get("avg_loss", 0))

        # 盈亏比
        pnl_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else float("inf")

        # 评级
        if win_rate >= self.WIN_RATE_EXCELLENT and profit_factor >= self.PROFIT_FACTOR_EXCELLENT:
            rating = "优秀"
            emoji = "🌟"
        elif win_rate >= self.WIN_RATE_GOOD and profit_factor >= self.PROFIT_FACTOR_GOOD:
            rating = "良好"
            emoji = "✅"
        elif win_rate >= self.WIN_RATE_POOR and profit_factor >= self.PROFIT_FACTOR_POOR:
            rating = "一般"
            emoji = "⚠️"
        else:
            rating = "较差"
            emoji = "❌"

        trades_rating = "样本充足" if total_trades >= 100 else "样本偏少"
        pf_rating = "优秀" if profit_factor >= 2 else "良好" if profit_factor >= 1.5 else "一般"
        pr_rating = "优秀" if pnl_ratio >= 2 else "良好" if pnl_ratio >= 1.5 else "一般"
        section = f"""### 📊 交易统计 {emoji}

| 指标 | 数值 | 评级 |
|------|------|------|
| 总交易次数 | {total_trades} | {trades_rating} |
| 胜率 | {win_rate:.2%} | {rating} |
| 盈利因子 | {profit_factor:.2f} | {pf_rating} |
| 盈亏比 | {pnl_ratio:.2f} | {pr_rating} |
| 平均盈利 | {avg_win:+.2f} | — |
| 平均亏损 | {avg_loss:+.2f} | — |

**解读**: {self._describe_trades(win_rate, profit_factor, total_trades)}。"""

        return {"section": section, "rating": rating}

    def _overall_evaluation(self, evaluation: dict[str, str]) -> dict[str, Any]:
        """综合评估。

        Args:
            evaluation: 各维度评级字典。

        Returns:
            综合评估结果。
        """
        rating_scores = {"优秀": 4, "良好": 3, "一般": 2, "较差": 1}
        scores = [rating_scores.get(v, 2) for v in evaluation.values() if v in rating_scores]

        if not scores:
            avg = 2
        else:
            avg = sum(scores) / len(scores)

        if avg >= 3.5:
            grade = "A"
            desc = "策略表现优秀，可考虑实盘部署"
        elif avg >= 2.5:
            grade = "B"
            desc = "策略表现良好，建议进一步优化后部署"
        elif avg >= 1.5:
            grade = "C"
            desc = "策略表现一般，需要显著优化"
        else:
            grade = "D"
            desc = "策略表现较差，建议重新设计"

        section = f"""### 🏆 综合评估

**策略等级: {grade}**

{desc}

各维度评级: {" → ".join(f"{k}={v}" for k, v in evaluation.items())}"""

        return {"section": section, "rating": desc, "grade": grade}

    def _generate_suggestions(
        self,
        bt: dict[str, Any],
        evaluation: dict[str, Any],
    ) -> str:
        """生成优化建议。

        Args:
            bt: 回测数据。
            evaluation: 评估结果。

        Returns:
            中文优化建议段落。
        """
        suggestions: list[str] = []

        max_dd = float(bt.get("max_drawdown", 0))
        win_rate = float(bt.get("win_rate", 0))
        sharpe = float(bt.get("sharpe_ratio", 0))
        total_trades = int(bt.get("total_trades", 0))

        if max_dd > self.MAX_DD_GOOD:
            suggestions.append("- 🔒 **降低最大回撤**: 考虑收紧止损、降低仓位比例、或增加对冲")

        if win_rate < self.WIN_RATE_GOOD:
            suggestions.append("- 🎯 **提高胜率**: 优化入场条件、增加过滤器、或调整信号阈值")

        if sharpe < self.SHARPE_GOOD:
            suggestions.append("- 📊 **提升夏普比率**: 优化收益/风险比、减少无意义交易")

        if total_trades < 50:
            suggestions.append("- 📈 **增加样本量**: 回测交易次数偏少，结论统计意义不足")

        if not suggestions:
            suggestions.append("- ✅ 策略各指标表现均衡，建议进入影子运行阶段验证")

        return "### 💡 优化建议\n\n" + "\n".join(suggestions)

    # ── 中文描述辅助方法 ──

    @staticmethod
    def _describe_sharpe(sharpe: float) -> str:
        if sharpe >= 2.0:
            return "风险调整收益极佳，属于顶级策略水平"
        elif sharpe >= 1.0:
            return "风险调整收益良好，是一套可用的策略"
        elif sharpe >= 0.5:
            return "风险调整收益一般，收益未能充分覆盖风险"
        else:
            return "风险调整收益较差，策略盈利能力不足"

    @staticmethod
    def _describe_return(ret: float) -> str:
        if ret > 0.5:
            return f"总收益 {ret:.1%} 表现亮眼"
        elif ret > 0.1:
            return f"总收益 {ret:.1%} 尚可"
        elif ret > 0:
            return f"总收益 {ret:.1%} 略有盈利"
        else:
            return f"总收益 {ret:.1%} 出现亏损"

    @staticmethod
    def _describe_drawdown(dd: float) -> str:
        if dd <= 0.10:
            return f"最大回撤 {dd:.1%} 控制优秀，风险可控"
        elif dd <= 0.20:
            return f"最大回撤 {dd:.1%} 处于可接受范围，但仍有优化空间"
        elif dd <= 0.30:
            return f"最大回撤 {dd:.1%} 偏高，需要加强风控"
        else:
            return f"最大回撤 {dd:.1%} 严重偏高，策略风险过大"

    @staticmethod
    def _describe_trades(win_rate: float, profit_factor: float, count: int) -> str:
        parts: list[str] = []
        if win_rate >= 0.5:
            parts.append(f"胜率 {win_rate:.1%} 表现不错")
        else:
            parts.append(f"胜率 {win_rate:.1%} 偏低")

        if profit_factor >= 1.5:
            parts.append(f"盈利因子 {profit_factor:.2f} 说明盈亏结构健康")
        else:
            parts.append(f"盈利因子 {profit_factor:.2f} 说明盈亏结构有待改善")

        if count < 50:
            parts.append(f"总交易 {count} 笔，样本偏少，结论需谨慎")

        return "，".join(parts)
