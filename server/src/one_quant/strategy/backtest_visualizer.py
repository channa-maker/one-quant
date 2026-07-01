"""
ONE量化 - 回测可视化

生成回测结果的可视化图表，支持：
  - 权益曲线（净值走势 + 基准对比）
  - 回撤曲线（水下图）
  - 月度收益热力图
  - 完整 HTML 报告（单文件自包含）

使用示例::

    result = engine.run(data)
    viz = BacktestVisualizer(result)

    # 单独生成图表
    viz.plot_equity_curve("equity.png")
    viz.plot_drawdown("drawdown.png")
    viz.plot_monthly_heatmap("monthly.png")

    # 生成完整 HTML 报告
    viz.generate_html_report("report.html")

    # 返回 matplotlib Figure 对象（用于自定义展示）
    fig = viz.create_equity_figure()
"""

from __future__ import annotations

import base64
import io
from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from one_quant.infra.logging import get_logger
from one_quant.strategy.backtest import BacktestResult

logger = get_logger(__name__)

try:
    import matplotlib

    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False

# ──────────────────── matplotlib 全局配置 ────────────────────


def _setup_matplotlib():
    """配置 matplotlib 中文支持和全局样式。"""
    if not HAS_MATPLOTLIB:
        raise ImportError("matplotlib 未安装，可视化功能不可用。安装: pip install matplotlib")

    matplotlib.use("Agg")  # 无头模式，适合服务器环境
    import matplotlib.pyplot as plt

    # 尝试配置中文字体（按优先级尝试）
    font_candidates = [
        "SimHei",  # Windows 黑体
        "Microsoft YaHei",  # Windows 微软雅黑
        "WenQuanYi Micro Hei",  # Linux 文泉驿
        "Noto Sans CJK SC",  # Google Noto
        "PingFang SC",  # macOS 苹方
        "Arial Unicode MS",  # macOS 通用
    ]

    import matplotlib.font_manager as fm

    available_fonts = {f.name for f in fm.fontManager.ttflist}
    chosen_font = None
    for candidate in font_candidates:
        if candidate in available_fonts:
            chosen_font = candidate
            break

    if chosen_font:
        plt.rcParams["font.sans-serif"] = [chosen_font]
    else:
        # 没有中文字体时使用默认（中文可能显示为方框，但不影响功能）
        logger.warning("未找到中文字体，图表中文标签可能无法正常显示")

    plt.rcParams["axes.unicode_minus"] = False  # 解决负号显示问题

    # 全局样式
    plt.rcParams.update(
        {
            "figure.facecolor": "#ffffff",
            "axes.facecolor": "#fafafa",
            "axes.grid": True,
            "grid.alpha": 0.3,
            "axes.spines.top": False,
            "axes.spines.right": False,
        }
    )

    return plt


class BacktestVisualizer:
    """回测可视化生成器。

    基于 matplotlib 生成回测结果的各类图表。

    Attributes:
        _result: 回测结果
        _plt: matplotlib.pyplot 模块引用
    """

    # 配色方案
    _COLOR_EQUITY = "#1976D2"  # 权益曲线：蓝色
    _COLOR_BENCHMARK = "#9E9E9E"  # 基准线：灰色
    _COLOR_DRAWDOWN = "#E53935"  # 回撤：红色
    _COLOR_POSITIVE = "#4CAF50"  # 正收益：绿色
    _COLOR_NEGATIVE = "#F44336"  # 负收益：红色
    _COLOR_NEUTRAL = "#BDBDBD"  # 无数据：灰色

    def __init__(self, result: BacktestResult) -> None:
        """初始化可视化器。

        Args:
            result: BacktestEngine.run() 返回的回测结果
        """
        self._result = result
        self._plt = _setup_matplotlib()

    # ──────────────────── 权益曲线 ────────────────────

    def create_equity_figure(
        self,
        benchmark_curve: list[tuple[int, Decimal]] | None = None,
        figsize: tuple[int, int] = (14, 6),
    ):
        """创建权益曲线 Figure 对象。

        Args:
            benchmark_curve: 基准权益曲线（可选），格式同 equity_curve
            figsize: 图表尺寸

        Returns:
            matplotlib Figure 对象
        """
        plt = self._plt
        fig, ax = plt.subplots(figsize=figsize)

        curve = self._result.equity_curve
        if not curve:
            ax.text(0.5, 0.5, "无权益数据", ha="center", va="center", fontsize=16)
            return fig

        # 提取时间和权益
        timestamps = [datetime.fromtimestamp(ts / 1e9, tz=UTC) for ts, _ in curve]
        equities = [float(e) for _, e in curve]

        # 归一化为净值（初始值 = 1.0）
        initial = equities[0] if equities[0] != 0 else 1.0
        nav = [e / initial for e in equities]

        # 绘制策略净值曲线
        ax.plot(
            timestamps,
            nav,
            color=self._COLOR_EQUITY,
            linewidth=1.5,
            label="策略净值",
            zorder=3,
        )

        # 绘制基准曲线（如有）
        if benchmark_curve:
            bm_timestamps = [datetime.fromtimestamp(ts / 1e9, tz=UTC) for ts, _ in benchmark_curve]
            bm_equities = [float(e) for _, e in benchmark_curve]
            bm_initial = bm_equities[0] if bm_equities[0] != 0 else 1.0
            bm_nav = [e / bm_initial for e in bm_equities]
            ax.plot(
                bm_timestamps,
                bm_nav,
                color=self._COLOR_BENCHMARK,
                linewidth=1.0,
                linestyle="--",
                label="基准",
                zorder=2,
            )

        # 填充正收益区域
        ax.fill_between(
            timestamps,
            1.0,
            nav,
            where=[n >= 1.0 for n in nav],
            color=self._COLOR_POSITIVE,
            alpha=0.08,
            interpolate=True,
        )
        # 填充负收益区域
        ax.fill_between(
            timestamps,
            1.0,
            nav,
            where=[n < 1.0 for n in nav],
            color=self._COLOR_NEGATIVE,
            alpha=0.08,
            interpolate=True,
        )

        # 基准线
        ax.axhline(y=1.0, color="#888888", linewidth=0.8, linestyle="-", alpha=0.5)

        # 标注起止净值
        ax.annotate(
            f"{nav[0]:.3f}",
            xy=(timestamps[0], nav[0]),
            fontsize=8,
            color="#666",
            ha="left",
            va="bottom",
        )
        ax.annotate(
            f"{nav[-1]:.3f}",
            xy=(timestamps[-1], nav[-1]),
            fontsize=8,
            color="#666",
            ha="right",
            va="bottom" if nav[-1] >= 1.0 else "top",
        )

        # 添加指标文本框
        total_ret = float(self._result.total_return) * 100
        max_dd = float(self._result.max_drawdown) * 100
        sharpe = self._result.sharpe_ratio
        info_text = f"总收益: {total_ret:+.2f}%\n最大回撤: {max_dd:.2f}%\n夏普比率: {sharpe:.2f}"
        ax.text(
            0.02,
            0.97,
            info_text,
            transform=ax.transAxes,
            fontsize=9,
            verticalalignment="top",
            bbox=dict(boxstyle="round,pad=0.5", facecolor="white", alpha=0.8, edgecolor="#ddd"),
        )

        ax.set_title("策略权益曲线", fontsize=14, fontweight="bold", pad=15)
        ax.set_xlabel("日期", fontsize=10)
        ax.set_ylabel("净值", fontsize=10)
        ax.legend(loc="upper left", fontsize=9)
        fig.autofmt_xdate()
        fig.tight_layout()

        return fig

    def plot_equity_curve(
        self,
        save_path: str | Path,
        benchmark_curve: list[tuple[int, Decimal]] | None = None,
        dpi: int = 150,
    ) -> Path:
        """保存权益曲线图片。

        Args:
            save_path: 输出图片路径
            benchmark_curve: 基准权益曲线（可选）
            dpi: 图片分辨率

        Returns:
            实际写入的文件路径
        """
        fig = self._create_equity_figure(benchmark_curve)
        return self._save_figure(fig, save_path, dpi)

    # ──────────────────── 回撤曲线 ────────────────────

    def create_drawdown_figure(self, figsize: tuple[int, int] = (14, 4)):
        """创建回撤曲线（水下图）Figure 对象。

        显示权益相对历史最高点的回撤百分比。

        Args:
            figsize: 图表尺寸

        Returns:
            matplotlib Figure 对象
        """
        plt = self._plt
        fig, ax = plt.subplots(figsize=figsize)

        curve = self._result.equity_curve
        if not curve:
            ax.text(0.5, 0.5, "无权益数据", ha="center", va="center", fontsize=16)
            return fig

        # 计算逐点回撤
        timestamps = [datetime.fromtimestamp(ts / 1e9, tz=UTC) for ts, _ in curve]
        equities = [float(e) for _, e in curve]

        drawdowns: list[float] = []
        peak = equities[0]
        for eq in equities:
            if eq > peak:
                peak = eq
            dd = (eq - peak) / peak if peak != 0 else 0.0
            drawdowns.append(dd * 100)  # 转为百分比

        # 绘制回撤曲线（填充）
        ax.fill_between(timestamps, 0, drawdowns, color=self._COLOR_DRAWDOWN, alpha=0.4)
        ax.plot(timestamps, drawdowns, color=self._COLOR_DRAWDOWN, linewidth=1.0)

        # 标注最大回撤点
        min_dd_idx = drawdowns.index(min(drawdowns))
        max_dd_val = drawdowns[min_dd_idx]
        ax.annotate(
            f"最大回撤: {max_dd_val:.2f}%",
            xy=(timestamps[min_dd_idx], max_dd_val),
            xytext=(15, -15),
            textcoords="offset points",
            fontsize=9,
            color=self._COLOR_DRAWDOWN,
            fontweight="bold",
            arrowprops=dict(arrowstyle="->", color=self._COLOR_DRAWDOWN, lw=1.5),
        )

        ax.axhline(y=0, color="#888888", linewidth=0.8)
        ax.set_title("回撤曲线（水下图）", fontsize=14, fontweight="bold", pad=10)
        ax.set_xlabel("日期", fontsize=10)
        ax.set_ylabel("回撤 (%)", fontsize=10)
        ax.set_ylim(top=1)  # 上方留白

        fig.autofmt_xdate()
        fig.tight_layout()
        return fig

    def plot_drawdown(self, save_path: str | Path, dpi: int = 150) -> Path:
        """保存回撤曲线图片。

        Args:
            save_path: 输出图片路径
            dpi: 图片分辨率

        Returns:
            实际写入的文件路径
        """
        fig = self.create_drawdown_figure()
        return self._save_figure(fig, save_path, dpi)

    # ──────────────────── 月度收益热力图 ────────────────────

    def create_monthly_heatmap_figure(self, figsize: tuple[int, int] = (14, 5)):
        """创建月度收益热力图 Figure 对象。

        横轴为月份（1-12），纵轴为年份，颜色表示收益率。

        Returns:
            matplotlib Figure 对象
        """
        plt = self._plt
        import numpy as np

        # 计算月度收益
        monthly = self._calculate_monthly_returns()
        if not monthly:
            fig, ax = plt.subplots(figsize=figsize)
            ax.text(0.5, 0.5, "无月度收益数据", ha="center", va="center", fontsize=16)
            return fig

        # 按年份和月份组织数据
        years = sorted(set(k[:4] for k in monthly.keys()))
        _months = list(range(1, 13))  # noqa: F841

        # 构建矩阵（行=年份，列=月份）
        matrix = np.full((len(years), 12), np.nan)
        for key, ret in monthly.items():
            year_idx = years.index(key[:4])
            month_idx = int(key[5:7]) - 1
            matrix[year_idx, month_idx] = float(ret) * 100

        fig, ax = plt.subplots(figsize=figsize)

        # 自定义配色：红（负）→ 白（零）→ 绿（正）
        from matplotlib.colors import LinearSegmentedColormap

        colors = ["#F44336", "#FFCDD2", "#FFFFFF", "#C8E6C9", "#4CAF50"]
        cmap = LinearSegmentedColormap.from_list("pnl", colors, N=256)

        # 计算颜色范围（对称）
        valid_vals = matrix[~np.isnan(matrix)]
        if len(valid_vals) > 0:
            vmax = max(abs(valid_vals.min()), abs(valid_vals.max()), 1.0)
        else:
            vmax = 1.0

        # 绘制热力图
        im = ax.imshow(matrix, cmap=cmap, aspect="auto", vmin=-vmax, vmax=vmax)

        # 设置刻度
        ax.set_xticks(range(12))
        ax.set_xticklabels([f"{m}月" for m in range(1, 13)], fontsize=9)
        ax.set_yticks(range(len(years)))
        ax.set_yticklabels(years, fontsize=10)

        # 在每个格子中标注数值
        for i in range(len(years)):
            for j in range(12):
                val = matrix[i, j]
                if np.isnan(val):
                    continue
                # 根据背景深浅选择文字颜色
                text_color = "#ffffff" if abs(val) > vmax * 0.6 else "#333333"
                ax.text(
                    j,
                    i,
                    f"{val:+.1f}%",
                    ha="center",
                    va="center",
                    fontsize=8,
                    color=text_color,
                    fontweight="bold",
                )

        # 添加颜色条
        cbar = fig.colorbar(im, ax=ax, shrink=0.8, pad=0.02)
        cbar.set_label("月度收益率 (%)", fontsize=10)

        ax.set_title("月度收益热力图", fontsize=14, fontweight="bold", pad=15)
        fig.tight_layout()
        return fig

    def plot_monthly_heatmap(self, save_path: str | Path, dpi: int = 150) -> Path:
        """保存月度收益热力图。

        Args:
            save_path: 输出图片路径
            dpi: 图片分辨率

        Returns:
            实际写入的文件路径
        """
        fig = self.create_monthly_heatmap_figure()
        return self._save_figure(fig, save_path, dpi)

    # ──────────────────── HTML 报告 ────────────────────

    def generate_html_report(
        self,
        save_path: str | Path,
        title: str = "ONE量化 · 回测报告",
        benchmark_curve: list[tuple[int, Decimal]] | None = None,
    ) -> Path:
        """生成自包含 HTML 报告。

        所有图表嵌入为 Base64 图片，无需外部依赖，单文件即可查看。

        Args:
            save_path: 输出 HTML 文件路径
            title: 报告标题
            benchmark_curve: 基准权益曲线（可选）

        Returns:
            实际写入的文件路径
        """
        # 生成各图表的 Base64 编码
        equity_img = self._fig_to_base64(self.create_equity_figure(benchmark_curve))
        drawdown_img = self._fig_to_base64(self.create_drawdown_figure())
        heatmap_img = self._fig_to_base64(self.create_monthly_heatmap_figure())

        # 计算月度收益表 HTML
        monthly = self._calculate_monthly_returns()
        monthly_html = self._build_monthly_html(monthly)

        # 核心指标
        total_ret = float(self._result.total_return) * 100
        annual_ret = float(self._result.annual_return) * 100
        max_dd = float(self._result.max_drawdown) * 100
        sharpe = self._result.sharpe_ratio
        calmar = self._result.calmar_ratio
        win_rate = self._result.win_rate * 100
        pf = self._result.profit_factor
        trades = self._result.total_trades
        turnover = self._result.turnover_rate * 100

        # 指标卡片颜色
        ret_color = "#4CAF50" if total_ret >= 0 else "#F44336"
        dd_color = "#F44336" if max_dd > 20 else "#FF9800" if max_dd > 10 else "#4CAF50"
        sharpe_color = "#4CAF50" if sharpe > 1 else "#FF9800" if sharpe > 0 else "#F44336"

        html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
                         "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
            background: #f5f5f5; color: #333; line-height: 1.6;
        }}
        .container {{ max-width: 1200px; margin: 0 auto; padding: 20px; }}
        .header {{
            text-align: center; padding: 30px 0; margin-bottom: 30px;
            background: linear-gradient(135deg, #1976D2, #1565C0);
            color: white; border-radius: 12px;
        }}
        .header h1 {{ font-size: 28px; margin-bottom: 8px; }}
        .header p {{ opacity: 0.85; font-size: 14px; }}
        .card {{
            background: white; border-radius: 10px; padding: 24px;
            margin-bottom: 24px; box-shadow: 0 2px 8px rgba(0,0,0,0.06);
        }}
        .card h2 {{
            font-size: 18px; margin-bottom: 16px; padding-bottom: 10px;
            border-bottom: 2px solid #e0e0e0;
        }}
        .metrics-grid {{
            display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 16px;
        }}
        .metric-item {{
            text-align: center; padding: 16px; background: #fafafa;
            border-radius: 8px; border: 1px solid #eee;
        }}
        .metric-value {{
            font-size: 24px; font-weight: bold; margin: 4px 0;
        }}
        .metric-label {{ font-size: 13px; color: #888; }}
        .chart-img {{ width: 100%; border-radius: 8px; }}
        table {{
            width: 100%; border-collapse: collapse; font-size: 13px;
        }}
        th, td {{
            padding: 8px 10px; text-align: center;
            border: 1px solid #e0e0e0;
        }}
        th {{ background: #f0f0f0; font-weight: 600; }}
        .positive {{ color: #4CAF50; font-weight: bold; }}
        .negative {{ color: #F44336; font-weight: bold; }}
        .footer {{
            text-align: center; padding: 20px; color: #aaa; font-size: 12px;
        }}
    </style>
</head>
<body>
<div class="container">
    <div class="header">
        <h1>{title}</h1>
        <p>自动生成 · 仅供研究参考</p>
    </div>

    <!-- 核心指标卡片 -->
    <div class="card">
        <h2>📊 核心绩效指标</h2>
        <div class="metrics-grid">
            <div class="metric-item">
                <div class="metric-label">总收益率</div>
                <div class="metric-value" style="color:{ret_color}">{total_ret:+.2f}%</div>
            </div>
            <div class="metric-item">
                <div class="metric-label">年化收益</div>
                <div class="metric-value" style="color:{ret_color}">{annual_ret:+.2f}%</div>
            </div>
            <div class="metric-item">
                <div class="metric-label">最大回撤</div>
                <div class="metric-value" style="color:{dd_color}">{max_dd:.2f}%</div>
            </div>
            <div class="metric-item">
                <div class="metric-label">夏普比率</div>
                <div class="metric-value" style="color:{sharpe_color}">{sharpe:.4f}</div>
            </div>
            <div class="metric-item">
                <div class="metric-label">卡玛比率</div>
                <div class="metric-value">{calmar:.4f}</div>
            </div>
            <div class="metric-item">
                <div class="metric-label">胜率</div>
                <div class="metric-value">{win_rate:.1f}%</div>
            </div>
            <div class="metric-item">
                <div class="metric-label">盈亏比</div>
                <div class="metric-value">{pf:.4f}</div>
            </div>
            <div class="metric-item">
                <div class="metric-label">交易笔数</div>
                <div class="metric-value">{trades}</div>
            </div>
            <div class="metric-item">
                <div class="metric-label">换手率</div>
                <div class="metric-value">{turnover:.1f}%</div>
            </div>
        </div>
    </div>

    <!-- 权益曲线 -->
    <div class="card">
        <h2>📈 权益曲线</h2>
        <img class="chart-img" src="data:image/png;base64,{equity_img}" alt="权益曲线">
    </div>

    <!-- 回撤曲线 -->
    <div class="card">
        <h2>📉 回撤曲线</h2>
        <img class="chart-img" src="data:image/png;base64,{drawdown_img}" alt="回撤曲线">
    </div>

    <!-- 月度收益热力图 -->
    <div class="card">
        <h2>🗓 月度收益热力图</h2>
        <img class="chart-img" src="data:image/png;base64,{heatmap_img}" alt="月度收益热力图">
    </div>

    <!-- 月度收益明细表 -->
    <div class="card">
        <h2>📋 月度收益明细</h2>
        {monthly_html}
    </div>

    <div class="footer">
        ONE量化 · 回测引擎 · 自动生成
    </div>
</div>
</body>
</html>"""

        out_path = Path(save_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(html, encoding="utf-8")
        logger.info("HTML 报告已生成: %s", out_path)
        return out_path

    # ──────────────────── 内部方法 ────────────────────

    def _calculate_monthly_returns(self) -> dict[str, Decimal]:
        """计算月度收益率（与 BacktestReport 逻辑一致）。"""
        curve = self._result.equity_curve
        if len(curve) < 2:
            return {}

        monthly_data: dict[str, list[tuple[int, Decimal]]] = defaultdict(list)
        for ts_ns, equity in curve:
            dt = datetime.fromtimestamp(ts_ns / 1_000_000_000, tz=UTC)
            month_key = dt.strftime("%Y-%m")
            monthly_data[month_key].append((ts_ns, equity))

        monthly_returns: dict[str, Decimal] = {}
        prev_month_end: Decimal | None = None

        for month_key in sorted(monthly_data.keys()):
            points = monthly_data[month_key]
            if not points:
                continue
            month_start_equity = points[0][1]
            month_end_equity = points[-1][1]
            base = prev_month_end if prev_month_end is not None else month_start_equity
            if base > 0:
                ret = (month_end_equity - base) / base
                monthly_returns[month_key] = ret.quantize(Decimal("0.0001"))
            else:
                monthly_returns[month_key] = Decimal("0")
            prev_month_end = month_end_equity

        return monthly_returns

    def _fig_to_base64(self, fig) -> str:
        """将 matplotlib Figure 转为 Base64 编码的 PNG 字符串。

        Args:
            fig: matplotlib Figure 对象

        Returns:
            Base64 编码字符串
        """
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=120, bbox_inches="tight", facecolor="white")
        buf.seek(0)
        encoded = base64.b64encode(buf.read()).decode("utf-8")
        self._plt.close(fig)  # 释放内存
        return encoded

    def _save_figure(self, fig, save_path: str | Path, dpi: int = 150) -> Path:
        """保存 Figure 到文件。

        Args:
            fig: matplotlib Figure 对象
            save_path: 输出路径
            dpi: 分辨率

        Returns:
            实际写入的文件路径
        """
        out_path = Path(save_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(str(out_path), dpi=dpi, bbox_inches="tight", facecolor="white")
        self._plt.close(fig)
        logger.info("图表已保存: %s", out_path)
        return out_path

    def _build_monthly_html(self, monthly: dict[str, Decimal]) -> str:
        """构建月度收益 HTML 表格。

        Args:
            monthly: {月份: 收益率} 字典

        Returns:
            HTML 表格字符串
        """
        if not monthly:
            return "<p style='text-align:center;color:#999;'>无月度数据</p>"

        # 按年份分组
        yearly: dict[str, dict[str, Decimal]] = defaultdict(dict)
        for month_key, ret in monthly.items():
            year = month_key[:4]
            month = month_key[5:7]
            yearly[year][month] = ret

        rows_html = ""
        for year in sorted(yearly.keys()):
            cells = f"<td style='font-weight:bold;'>{year}</td>"
            year_total = Decimal("0")
            count = 0
            for m in range(1, 13):
                m_key = f"{m:02d}"
                if m_key in yearly[year]:
                    val = float(yearly[year][m_key]) * 100
                    year_total += yearly[year][m_key]
                    count += 1
                    css_class = "positive" if val >= 0 else "negative"
                    cells += f'<td class="{css_class}">{val:+.1f}%</td>'
                else:
                    cells += "<td style='color:#ccc;'>—</td>"

            # 年度合计
            yr_val = float(year_total) * 100
            css_class = "positive" if yr_val >= 0 else "negative"
            cells += f'<td class="{css_class}" style="font-weight:bold;">{yr_val:+.1f}%</td>'
            rows_html += f"<tr>{cells}</tr>"

        header = "<tr><th>年份</th>"
        for m in range(1, 13):
            header += f"<th>{m}月</th>"
        header += "<th>合计</th></tr>"

        return f"""
        <table>
            {header}
            {rows_html}
        </table>
        """

    # 别名，供外部使用
    _create_equity_figure = create_equity_figure
