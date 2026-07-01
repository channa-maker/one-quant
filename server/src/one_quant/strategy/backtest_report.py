"""
ONE量化 - 回测报告生成器

生成结构化的中文回测报告，支持：
  - 中文摘要（策略概况、核心指标一览）
  - 样本内 vs 样本外对比分析
  - 月度收益明细表
  - 风险指标（最大回撤、夏普、卡玛、Sortino 等）
  - 文本 / 字典 / JSON 多种输出格式

使用示例::

    result = engine.run(data)  # BacktestResult
    report = BacktestReport(result)
    print(report.summary())           # 中文摘要
    print(report.to_json())           # JSON 格式
    report.save("report.json")        # 保存到文件
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

from one_quant.infra.logging import get_logger
from one_quant.strategy.backtest import BacktestResult

logger = get_logger(__name__)


class DecimalEncoder(json.JSONEncoder):
    """支持 Decimal 类型的 JSON 编码器。"""

    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)


class BacktestReport:
    """回测报告生成器。

    将 BacktestResult 转换为结构化的中文报告，包含：
      - 策略概况摘要
      - 核心绩效指标
      - 样本内/外对比
      - 月度收益明细
      - 风险指标

    Attributes:
        _result: 回测结果
        _start_dt: 回测起始时间
        _end_dt: 回测结束时间
    """

    def __init__(self, result: BacktestResult) -> None:
        """初始化报告生成器。

        Args:
            result: BacktestEngine.run() 返回的回测结果
        """
        self._result = result
        self._start_dt, self._end_dt = self._parse_time_range()

    # ──────────────────── 公开接口 ────────────────────

    def summary(self) -> str:
        """生成中文摘要报告。

        包含策略概况、核心指标、风险指标、样本内外对比等。

        Returns:
            格式化的中文报告字符串
        """
        lines: list[str] = []
        sep = "─" * 56

        # ── 标题 ──
        lines.append("=" * 56)
        lines.append("            ONE量化 · 回测报告")
        lines.append("=" * 56)
        lines.append("")

        # ── 回测概况 ──
        lines.append("【回测概况】")
        lines.append(f"  回测区间 : {self._fmt_dt(self._start_dt)} ~ {self._fmt_dt(self._end_dt)}")
        lines.append(f"  交易笔数 : {self._result.total_trades}")
        lines.append(f"  换手率   : {self._pct(self._result.turnover_rate)}")
        lines.append("")
        lines.append(sep)

        # ── 核心绩效 ──
        lines.append("【核心绩效指标】")
        lines.append(f"  总收益率   : {self._pct(self._result.total_return)}")
        lines.append(f"  年化收益   : {self._pct(self._result.annual_return)}")
        lines.append(f"  最大回撤   : {self._pct(self._result.max_drawdown)}")
        lines.append(f"  夏普比率   : {self._result.sharpe_ratio:.4f}")
        lines.append(f"  卡玛比率   : {self._result.calmar_ratio:.4f}")
        lines.append(f"  胜率       : {self._pct(self._result.win_rate)}")
        lines.append(f"  盈亏比     : {self._result.profit_factor:.4f}")
        lines.append("")
        lines.append(sep)

        # ── 风险评估 ──
        lines.append("【风险评估】")
        risk_level, risk_notes = self._assess_risk()
        lines.append(f"  风险等级   : {risk_level}")
        for note in risk_notes:
            lines.append(f"  ⚠ {note}")
        lines.append("")
        lines.append(sep)

        # ── 样本内/外对比 ──
        if self._result.sample_in_metrics or self._result.sample_out_metrics:
            lines.append("【样本内 vs 样本外对比】")
            lines.append(self._format_sample_comparison())
            lines.append("")
            lines.append(sep)

        # ── 月度收益 ──
        monthly = self._calculate_monthly_returns()
        if monthly:
            lines.append("【月度收益明细】")
            lines.append(self._format_monthly_table(monthly))
            lines.append("")
            lines.append(sep)

        # ── 综合评价 ──
        lines.append("【综合评价】")
        lines.append(f"  {self._overall_comment()}")
        lines.append("")
        lines.append("=" * 56)

        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        """将报告转为字典格式（便于序列化和前端展示）。

        Returns:
            包含所有报告字段的字典
        """
        monthly = self._calculate_monthly_returns()
        risk_level, risk_notes = self._assess_risk()

        return {
            "概况": {
                "回测区间_开始": self._fmt_dt(self._start_dt),
                "回测区间_结束": self._fmt_dt(self._end_dt),
                "交易笔数": self._result.total_trades,
                "换手率": float(self._result.turnover_rate),
            },
            "核心绩效": {
                "总收益率": float(self._result.total_return),
                "年化收益": float(self._result.annual_return),
                "最大回撤": float(self._result.max_drawdown),
                "夏普比率": self._result.sharpe_ratio,
                "卡玛比率": self._result.calmar_ratio,
                "胜率": self._result.win_rate,
                "盈亏比": self._result.profit_factor,
            },
            "风险评估": {
                "风险等级": risk_level,
                "风险提示": risk_notes,
            },
            "样本内指标": self._result.sample_in_metrics,
            "样本外指标": self._result.sample_out_metrics,
            "月度收益": {k: float(v) for k, v in monthly.items()},
            "综合评价": self._overall_comment(),
        }

    def to_json(self, indent: int = 2, ensure_ascii: bool = False) -> str:
        """将报告转为 JSON 字符串。

        Args:
            indent: 缩进空格数
            ensure_ascii: 是否转义非 ASCII 字符（中文场景建议 False）

        Returns:
            JSON 格式报告
        """
        return json.dumps(
            self.to_dict(),
            indent=indent,
            ensure_ascii=ensure_ascii,
            cls=DecimalEncoder,
        )

    def save(self, path: str | Path, fmt: str = "json") -> Path:
        """保存报告到文件。

        Args:
            path: 输出文件路径
            fmt: 输出格式，支持 "json" 或 "txt"

        Returns:
            实际写入的文件路径
        """
        out_path = Path(path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        if fmt == "json":
            out_path.write_text(self.to_json(ensure_ascii=False), encoding="utf-8")
        elif fmt == "txt":
            out_path.write_text(self.summary(), encoding="utf-8")
        else:
            raise ValueError(f"不支持的输出格式: {fmt}（仅支持 json / txt）")

        logger.info("报告已保存: %s", out_path)
        return out_path

    # ──────────────────── 月度收益计算 ────────────────────

    def _calculate_monthly_returns(self) -> dict[str, Decimal]:
        """根据权益曲线计算月度收益率。

        按自然月分段，计算每个月的收益率：
          月收益 = (月末权益 - 月初权益) / 月初权益

        Returns:
            {月份字符串: 收益率} 的有序字典，如 {"2024-01": 0.05, ...}
        """
        curve = self._result.equity_curve
        if len(curve) < 2:
            return {}

        # 按自然月分组：{ "YYYY-MM": [(ts, equity), ...] }
        monthly_data: dict[str, list[tuple[int, Decimal]]] = defaultdict(list)
        for ts_ns, equity in curve:
            dt = datetime.fromtimestamp(ts_ns / 1_000_000_000, tz=UTC)
            month_key = dt.strftime("%Y-%m")
            monthly_data[month_key].append((ts_ns, equity))

        # 计算每个月的收益率
        monthly_returns: dict[str, Decimal] = {}
        prev_month_end: Decimal | None = None

        for month_key in sorted(monthly_data.keys()):
            points = monthly_data[month_key]
            if not points:
                continue

            month_start_equity = points[0][1]
            month_end_equity = points[-1][1]

            # 月初基准：上月末权益（如有），否则用本月首条
            base = prev_month_end if prev_month_end is not None else month_start_equity

            if base > 0:
                ret = (month_end_equity - base) / base
                monthly_returns[month_key] = ret.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
            else:
                monthly_returns[month_key] = Decimal("0")

            prev_month_end = month_end_equity

        return monthly_returns

    # ──────────────────── 样本内外对比 ────────────────────

    def _format_sample_comparison(self) -> str:
        """格式化样本内/外对比表。

        Returns:
            对比表格字符串
        """
        si = self._result.sample_in_metrics or {}
        so = self._result.sample_out_metrics or {}

        if not si and not so:
            return "  （无样本内/外数据）"

        # 合并所有指标名
        all_keys = sorted(set(list(si.keys()) + list(so.keys())))

        lines: list[str] = []
        header = f"  {'指标':<14} {'样本内':>12} {'样本外':>12} {'差异':>12}"
        lines.append(header)
        lines.append("  " + "─" * 52)

        for key in all_keys:
            in_val = si.get(key)
            out_val = so.get(key)

            in_str = self._fmt_metric_value(in_val)
            out_str = self._fmt_metric_value(out_val)

            # 计算差异
            diff_str = "—"
            if in_val is not None and out_val is not None:
                try:
                    in_num = float(in_val)
                    out_num = float(out_val)
                    diff = out_num - in_num
                    diff_str = f"{diff:+.4f}"
                except (ValueError, TypeError):
                    pass

            label = self._translate_metric_name(key)
            lines.append(f"  {label:<14} {in_str:>12} {out_str:>12} {diff_str:>12}")

        return "\n".join(lines)

    # ──────────────────── 月度收益表 ────────────────────

    def _format_monthly_table(self, monthly: dict[str, Decimal]) -> str:
        """格式化月度收益表。

        按年份分行展示，每年一行12个月。

        Args:
            monthly: {月份: 收益率} 字典

        Returns:
            格式化的月度收益表
        """
        if not monthly:
            return "  （无月度数据）"

        # 按年份分组
        yearly: dict[str, dict[str, Decimal]] = defaultdict(dict[str, Any])
        for month_key, ret in monthly.items():
            year = month_key[:4]
            month = month_key[5:7]
            yearly[year][month] = ret

        lines: list[str] = []
        # 表头
        months_header = "    " + "".join(f" {m:>5}月" for m in [f"{i:02d}" for i in range(1, 13)])
        lines.append(months_header)
        lines.append("    " + "─" * (7 * 12 + 1))

        for year in sorted(yearly.keys()):
            row = f"{year} "
            for m in range(1, 13):
                m_key = f"{m:02d}"
                if m_key in yearly[year]:
                    val = yearly[year][m_key]
                    # 颜色标记：正收益绿色，负收益红色（终端 ANSI）
                    row += f" {val * 100:>+5.1f}%"
                else:
                    row += "     — "
            lines.append("    " + row)

        return "\n".join(lines)

    # ──────────────────── 风险评估 ────────────────────

    def _assess_risk(self) -> tuple[str, list[str]]:
        """评估风险等级并生成风险提示。

        风险等级：
          - 低风险：最大回撤 < 10%，夏普 > 1.5
          - 中风险：最大回撤 < 20%，夏普 > 0.5
          - 高风险：最大回撤 >= 20% 或 夏普 < 0.5

        Returns:
            (风险等级, 风险提示列表)
        """
        notes: list[str] = []
        dd = float(self._result.max_drawdown)
        sharpe = self._result.sharpe_ratio
        win_rate = self._result.win_rate
        pf = self._result.profit_factor

        # 最大回撤提示
        if dd >= 0.30:
            notes.append(f"最大回撤 {dd:.1%}，风险极高，建议降低仓位或优化止损")
        elif dd >= 0.20:
            notes.append(f"最大回撤 {dd:.1%}，风险较高，需关注回撤控制")

        # 夏普比率提示
        if sharpe < 0:
            notes.append(f"夏普比率 {sharpe:.2f} 为负，策略收益不及无风险利率")
        elif sharpe < 0.5:
            notes.append(f"夏普比率 {sharpe:.2f} 偏低，风险调整后收益不佳")

        # 胜率提示
        if win_rate < 0.3:
            notes.append(f"胜率仅 {win_rate:.1%}，需确保盈亏比足够高")

        # 盈亏比提示
        if pf < 1.0 and pf > 0:
            notes.append(f"盈亏比 {pf:.2f} < 1，总体亏损，策略需优化")

        # 交易次数提示
        if self._result.total_trades < 30:
            notes.append(f"交易笔数仅 {self._result.total_trades}，统计显著性不足")

        # 确定风险等级
        if dd >= 0.20 or sharpe < 0.5:
            level = "🔴 高风险"
        elif dd >= 0.10 or sharpe < 1.0:
            level = "🟡 中风险"
        else:
            level = "🟢 低风险"

        if not notes:
            notes.append("各项指标表现良好，未发现明显风险")

        return level, notes

    # ──────────────────── 综合评价 ────────────────────

    def _overall_comment(self) -> str:
        """生成综合评价文字。

        Returns:
            中文综合评价
        """
        dd = float(self._result.max_drawdown)
        sharpe = self._result.sharpe_ratio
        total_ret = float(self._result.total_return)
        win_rate = self._result.win_rate

        parts: list[str] = []

        # 收益评价
        if total_ret > 0.5:
            parts.append(f"策略表现优异，总收益 {total_ret:.1%}")
        elif total_ret > 0.1:
            parts.append(f"策略收益尚可，总收益 {total_ret:.1%}")
        elif total_ret > 0:
            parts.append(f"策略微盈，总收益 {total_ret:.1%}")
        else:
            parts.append(f"策略亏损，总收益 {total_ret:.1%}")

        # 风险评价
        if dd < 0.10 and sharpe > 1.5:
            parts.append("风险控制优秀，收益质量高")
        elif dd < 0.20:
            parts.append("风险可控")
        else:
            parts.append(f"回撤偏大（{dd:.1%}），建议加强风控")

        # 交易质量
        if win_rate > 0.6:
            parts.append(f"胜率 {win_rate:.1%} 表现出色")
        elif win_rate > 0.45:
            parts.append(f"胜率 {win_rate:.1%} 中规中矩")

        # 样本外验证
        si = self._result.sample_in_metrics
        so = self._result.sample_out_metrics
        if si and so:
            # 检查样本外是否明显退化
            in_sharpe = si.get("sharpe_ratio", 0)
            out_sharpe = so.get("sharpe_ratio", 0)
            try:
                if float(out_sharpe) < float(in_sharpe) * 0.5:
                    parts.append("⚠ 样本外表现明显退化，存在过拟合风险")
                else:
                    parts.append("样本内外表现一致，策略稳健性良好")
            except (ValueError, TypeError):
                pass

        return "；".join(parts) + "。"

    # ──────────────────── 工具方法 ────────────────────

    def _parse_time_range(self) -> tuple[datetime | None, datetime | None]:
        """从权益曲线解析回测起止时间。

        Returns:
            (起始时间, 结束时间) 的 datetime 对象
        """
        curve = self._result.equity_curve
        if not curve:
            return None, None

        start_dt = datetime.fromtimestamp(curve[0][0] / 1_000_000_000, tz=UTC)
        end_dt = datetime.fromtimestamp(curve[-1][0] / 1_000_000_000, tz=UTC)
        return start_dt, end_dt

    @staticmethod
    def _fmt_dt(dt: datetime | None) -> str:
        """格式化 datetime 为中文友好的字符串。"""
        if dt is None:
            return "未知"
        return dt.strftime("%Y年%m月%d日 %H:%M")

    @staticmethod
    def _pct(value: float | Decimal) -> str:
        """格式化百分比。"""
        return f"{float(value) * 100:+.2f}%"

    @staticmethod
    def _fmt_metric_value(value) -> str:
        """格式化指标值用于对比表。"""
        if value is None:
            return "—"
        try:
            v = float(value)
            if abs(v) < 10:
                return f"{v:.4f}"
            return f"{v:.2f}"
        except (ValueError, TypeError):
            return str(value)

    @staticmethod
    def _translate_metric_name(key: str) -> str:
        """将英文指标名翻译为中文。"""
        translations = {
            "total_return": "总收益率",
            "annual_return": "年化收益",
            "max_drawdown": "最大回撤",
            "sharpe_ratio": "夏普比率",
            "calmar_ratio": "卡玛比率",
            "sortino_ratio": "Sortino比率",
            "win_rate": "胜率",
            "profit_factor": "盈亏比",
            "turnover_rate": "换手率",
            "total_trades": "交易笔数",
            "avg_holding_period": "平均持仓周期",
            "max_consecutive_losses": "最大连亏次数",
        }
        return translations.get(key, key)
