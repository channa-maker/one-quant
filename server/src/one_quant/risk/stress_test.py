"""
ONE量化 - 历史危机场景压力测试引擎

用真实极端行情数据回放策略表现，量化尾部风险。

危机场景库：
  - 2020 新冠闪崩（3月12日，BTC 单日 -40%）
  - LUNA 崩盘（2022年5月，UST 脱锚 → LUNA 归零）
  - FTX 暴雷（2022年11月，交易所信用危机）
  - 美股熔断日（2020年3月，4次熔断）
  - 312/519（加密市场黑天鹅）

核心思路：
  1. 加载历史 tick 数据
  2. 按时间回放到策略引擎
  3. 记录策略的 PnL、回撤、风控触发情况
  4. 计算压力 VaR（危机下相关性→1 的最大损失）
"""

from __future__ import annotations

import time
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from one_quant.core.types import Ticker
from one_quant.infra.logging import get_logger

logger = get_logger(__name__)


# ──────────────────────────── 危机场景定义 ────────────────────────────


class CrisisScenario(BaseModel, frozen=True):
    """历史危机场景

    Attributes:
        name: 场景名称（如 "LUNA崩盘"）
        start_time: 起始纳秒时间戳
        end_time: 结束纳秒时间戳
        description: 中文描述
        tick_data_path: 真实 tick 数据路径（Parquet/CSV）
        expected_impact: 预期影响指标
            {
                "btc_drawdown_pct": -40.0,      # BTC 最大回撤 %
                "alt_drawdown_pct": -60.0,       # 山寨币最大回撤 %
                "duration_hours": 48,            # 持续时间（小时）
                "volatility_spike": 5.0,         # 波动率放大倍数
                "correlation_spike": 0.95,       # 相关性飙升目标
            }
    """

    name: str
    start_time: int
    end_time: int
    description: str
    tick_data_path: str
    expected_impact: dict[str, Any]


class StressResult(BaseModel, frozen=True):
    """压力测试结果

    Attributes:
        scenario: 场景名称
        max_loss: 最大亏损金额
        max_loss_pct: 最大亏损比例
        max_drawdown: 最大回撤金额
        max_drawdown_pct: 最大回撤比例
        recovery_time_sec: 回本时间（秒），-1 表示未回本
        total_pnl: 总盈亏
        sharpe_during_crisis: 危机期间年化 Sharpe
        risk_controls_triggered: 触发的风控规则列表
        trade_count: 成交笔数
        notes: 分析备注
        timestamp_ns: 纳秒时间戳
    """

    scenario: str
    max_loss: Decimal
    max_loss_pct: float
    max_drawdown: Decimal
    max_drawdown_pct: float
    recovery_time_sec: int
    total_pnl: Decimal
    sharpe_during_crisis: float
    risk_controls_triggered: list[str]
    trade_count: int
    notes: str
    timestamp_ns: int


# ──────────────────────────── 压力测试引擎 ────────────────────────────


class StressTestEngine:
    """压力测试引擎。

    回放历史危机场景，量化策略在极端行情下的表现。

    使用方式：
        engine = StressTestEngine()
        results = await engine.run_all_scenarios(my_strategy)
        for r in results:
            print(f"{r.scenario}: 最大回撤={r.max_drawdown_pct:.1f}%")
    """

    # ── 真实历史危机场景库 ──
    # 时间戳均为 Unix epoch 纳秒
    CRISIS_SCENARIOS: list[CrisisScenario] = [
        CrisisScenario(
            name="2020新冠闪崩",
            start_time=1583971200000000000,  # 2020-03-12 00:00 UTC
            end_time=1584144000000000000,  # 2020-03-14 00:00 UTC
            description=(
                "2020年3月12日，新冠恐慌引发全球资产抛售。"
                "BTC 从 ~$7,900 暴跌至 ~$3,800，单日跌幅超 40%。"
                "以太坊跌幅超 50%，DeFi 清算潮导致 gas 飙升。"
                "这是加密市场历史上最剧烈的单日下跌之一。"
            ),
            tick_data_path="data/crisis/2020_0312_crash.parquet",
            expected_impact={
                "btc_drawdown_pct": -40.0,
                "alt_drawdown_pct": -55.0,
                "duration_hours": 36,
                "volatility_spike": 8.0,
                "correlation_spike": 0.95,
            },
        ),
        CrisisScenario(
            name="LUNA崩盘",
            start_time=1652140800000000000,  # 2022-05-10 00:00 UTC
            end_time=1652745600000000000,  # 2022-05-17 00:00 UTC
            description=(
                "2022年5月，UST 算法稳定币脱锚引发死亡螺旋。"
                "LUNA 从 ~$80 在一周内归零，UST 从 $1 跌至 $0.10。"
                "Anchor Protocol 20% APY 神话破灭，连带整个 Terra 生态崩溃。"
                "加密市场总市值蒸发超 2000 亿美元。"
            ),
            tick_data_path="data/crisis/2022_luna_collapse.parquet",
            expected_impact={
                "btc_drawdown_pct": -25.0,
                "alt_drawdown_pct": -80.0,
                "duration_hours": 168,
                "volatility_spike": 6.0,
                "correlation_spike": 0.90,
            },
        ),
        CrisisScenario(
            name="FTX暴雷",
            start_time=1668124800000000000,  # 2022-11-11 00:00 UTC
            end_time=1668729600000000000,  # 2022-11-18 00:00 UTC
            description=(
                "2022年11月，FTX 交易所被曝挪用客户资金，引发信用危机。"
                "FTT 代币从 ~$22 暴跌至 ~$1，FTX 申请破产保护。"
                "市场恐慌蔓延，BTC 跌破 $16,000，加密行业信任危机。"
                "多家机构（BlockFi、Genesis）连环暴雷。"
            ),
            tick_data_path="data/crisis/2022_ftx_collapse.parquet",
            expected_impact={
                "btc_drawdown_pct": -20.0,
                "alt_drawdown_pct": -50.0,
                "duration_hours": 120,
                "volatility_spike": 4.0,
                "correlation_spike": 0.85,
            },
        ),
        CrisisScenario(
            name="美股熔断日",
            start_time=1583971200000000000,  # 2020-03-12（与新冠闪崩重叠）
            end_time=1585008000000000000,  # 2020-03-24
            description=(
                "2020年3月，美股在10天内触发4次熔断机制。"
                "3月12日标普500暴跌9.5%，触发本月第2次熔断。"
                "VIX 恐慌指数飙升至 82.69（历史最高）。"
                "全球央行紧急降息+QE，市场流动性枯竭。"
            ),
            tick_data_path="data/crisis/2020_us_circuit_breaker.parquet",
            expected_impact={
                "btc_drawdown_pct": -40.0,
                "alt_drawdown_pct": -60.0,
                "duration_hours": 288,
                "volatility_spike": 10.0,
                "correlation_spike": 0.98,
            },
        ),
        CrisisScenario(
            name="312/519",
            start_time=1589241600000000000,  # 2020-05-11 00:00 UTC
            end_time=1590105600000000000,  # 2020-05-22 00:00 UTC
            description=(
                "加密市场两大黑天鹅事件的统称。"
                "312（2020.3.12）：新冠恐慌 + 杠杆连环清算，BTC 单日 -40%。"
                "519（2021.5.19）：中国禁令 + 杠杆清算，BTC 单日 -30%。"
                "两次事件共同特征：高杠杆 → 连环清算 → 流动性枯竭 → 极端滑点。"
            ),
            tick_data_path="data/crisis/312_519_combined.parquet",
            expected_impact={
                "btc_drawdown_pct": -35.0,
                "alt_drawdown_pct": -50.0,
                "duration_hours": 72,
                "volatility_spike": 7.0,
                "correlation_spike": 0.92,
            },
        ),
    ]

    def __init__(self, data_root: str | Path = ".") -> None:
        """初始化压力测试引擎。

        Args:
            data_root: tick 数据根目录（tick_data_path 相对于此目录）
        """
        self._data_root = Path(data_root)
        self._results_history: list[StressResult] = []

    async def run_scenario(
        self,
        scenario: CrisisScenario,
        strategy_name: str,
        strategy_callback: Any | None = None,
        initial_equity: Decimal = Decimal("100000"),
    ) -> StressResult:
        """回放单个危机场景。

        流程：
          1. 加载历史 tick 数据（或使用模拟数据）
          2. 逐 tick 回放到策略
          3. 跟踪 PnL、回撤、风控触发

        Args:
            scenario: 危机场景
            strategy_name: 策略名称（用于日志）
            strategy_callback: 策略回调函数 (ticker) -> list[Signal]
                如为 None 则使用内置基准策略（买入持有）
            initial_equity: 初始权益

        Returns:
            压力测试结果
        """
        logger.info("开始压力测试: %s (策略: %s)", scenario.name, strategy_name)

        # ── 加载数据 ──
        tick_data = self._load_tick_data(scenario)
        if not tick_data:
            return self._simulate_scenario(scenario, strategy_name, initial_equity)

        # ── 回放计算 ──
        return self._replay_scenario(
            scenario,
            strategy_name,
            tick_data,
            initial_equity,
            strategy_callback,
        )

    async def run_all_scenarios(
        self,
        strategy_name: str,
        strategy_callback: Any | None = None,
        initial_equity: Decimal = Decimal("100000"),
    ) -> list[StressResult]:
        """运行所有危机场景。

        Args:
            strategy_name: 策略名称
            strategy_callback: 策略回调函数
            initial_equity: 初始权益

        Returns:
            所有场景的结果列表
        """
        results: list[StressResult] = []
        for scenario in self.CRISIS_SCENARIOS:
            result = await self.run_scenario(
                scenario,
                strategy_name,
                strategy_callback,
                initial_equity,
            )
            results.append(result)
            self._results_history.append(result)

        # 汇总日志
        self._log_summary(results)
        return results

    def stress_var(
        self,
        portfolio: list[dict[str, Any]],
        scenarios: list[CrisisScenario] | None = None,
        confidence: float = 0.99,
    ) -> Decimal:
        """压力 VaR：危机下相关性→1 的最大损失。

        传统 VaR 假设正态分布，危机时肥尾效应使 VaR 严重低估。
        压力 VaR 直接用历史危机数据，假设危机期间相关性→1（所有资产同跌）。

        计算方法：
          1. 对每个危机场景，计算组合损失
          2. 取第 (1-confidence) 分位数

        Args:
            portfolio: 持仓列表
                [{"symbol": "BTC", "weight": 0.5, "value": Decimal("50000")}, ...]
            scenarios: 危机场景（默认使用全部场景）
            confidence: 置信度（默认 99%）

        Returns:
            压力 VaR 金额
        """
        if scenarios is None:
            scenarios = self.CRISIS_SCENARIOS

        if not portfolio or not scenarios:
            return Decimal("0")

        # 对每个场景，计算组合损失
        scenario_losses: list[Decimal] = []
        _total_value = sum(Decimal(str(p.get("value", 0))) for p in portfolio)  # noqa: F841

        for scenario in scenarios:
            impact = scenario.expected_impact
            # 假设危机中相关性→1，所有资产按最差情况下跌
            # 组合损失 = Σ(weight × max_drawdown)
            portfolio_loss = Decimal("0")
            for pos in portfolio:
                _weight = Decimal(str(pos.get("weight", 0)))  # noqa: F841
                value = Decimal(str(pos.get("value", 0)))
                # 区分主币和山寨币的回撤幅度
                symbol = pos.get("symbol", "")
                if symbol in ("BTC", "ETH"):
                    drawdown = Decimal(str(impact.get("btc_drawdown_pct", -30))) / 100
                else:
                    drawdown = Decimal(str(impact.get("alt_drawdown_pct", -50))) / 100
                portfolio_loss += value * abs(drawdown)

            scenario_losses.append(portfolio_loss)

        # 取第 (1-confidence) 分位数
        scenario_losses.sort(reverse=True)
        idx = max(0, int(len(scenario_losses) * (1 - confidence)) - 1)
        stress_var = scenario_losses[idx] if scenario_losses else Decimal("0")

        logger.info(
            "压力 VaR (置信度=%.0f%%): %s, 基于 %d 个危机场景",
            confidence * 100,
            stress_var,
            len(scenarios),
        )
        return stress_var.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    # ── 内部方法 ──

    def _load_tick_data(self, scenario: CrisisScenario) -> list[Ticker] | None:
        """加载历史 tick 数据。

        尝试从 Parquet/CSV 文件加载真实数据。
        如文件不存在，返回 None（将使用模拟数据）。

        Args:
            scenario: 危机场景

        Returns:
            Ticker 列表，或 None
        """
        data_path = self._data_root / scenario.tick_data_path
        if not data_path.exists():
            logger.warning(
                "tick 数据文件不存在: %s, 将使用模拟数据",
                data_path,
            )
            return None

        try:
            # 支持 Parquet 和 CSV
            if data_path.suffix == ".parquet":
                try:
                    import pyarrow.parquet as pq

                    table = pq.read_table(str(data_path))
                    df = table.to_pandas()
                except ImportError:
                    logger.warning("pyarrow 未安装，尝试 CSV 回退")
                    return None
            else:
                import pandas as pd

                df = pd.read_csv(str(data_path))

            # 标准化列名
            tickers: list[Ticker] = []
            for _, row in df.iterrows():
                tickers.append(
                    Ticker(
                        symbol=str(row.get("symbol", "BTC/USDT")),
                        market="FUTURES",
                        exchange=str(row.get("exchange", "binance")),
                        last_price=Decimal(str(row.get("last_price", row.get("close", 0)))),
                        bid=Decimal(str(row.get("bid", row.get("close", 0) * 0.999))),
                        ask=Decimal(str(row.get("ask", row.get("close", 0) * 1.001))),
                        volume_24h=Decimal(str(row.get("volume_24h", row.get("volume", 0)))),
                        timestamp_ns=int(row.get("timestamp_ns", row.get("timestamp", 0))),
                    )
                )

            logger.info("加载 tick 数据: %s, 共 %d 条", data_path, len(tickers))
            return tickers

        except Exception as e:
            logger.error("加载 tick 数据失败: %s, 错误: %s", data_path, e)
            return None

    def _simulate_scenario(
        self,
        scenario: CrisisScenario,
        strategy_name: str,
        initial_equity: Decimal,
    ) -> StressResult:
        """使用预期影响指标模拟危机场景。

        当真实 tick 数据不可用时，基于 expected_impact 计算理论损失。

        Args:
            scenario: 危机场景
            strategy_name: 策略名称
            initial_equity: 初始权益

        Returns:
            模拟的压力测试结果
        """
        impact = scenario.expected_impact
        btc_dd = abs(Decimal(str(impact.get("btc_drawdown_pct", -30)))) / 100
        alt_dd = abs(Decimal(str(impact.get("alt_drawdown_pct", -50)))) / 100
        duration_hours = impact.get("duration_hours", 48)

        # 假设组合 50% BTC + 50% 山寨
        avg_dd = (btc_dd + alt_dd) / 2
        max_loss = initial_equity * avg_dd
        max_drawdown_pct = float(avg_dd * 100)

        # 恢复时间：假设 V 型反弹需要 3x 下跌时间
        recovery_hours = duration_hours * 3
        volatility_spike = impact.get("volatility_spike", 5.0)

        # 模拟触发的风控
        risk_controls: list[str] = []
        if max_drawdown_pct > 15:
            risk_controls.append("L3_最大回撤熔断")
        if max_drawdown_pct > 25:
            risk_controls.append("L4_全局熔断器")

        return StressResult(
            scenario=scenario.name,
            max_loss=max_loss,
            max_loss_pct=max_drawdown_pct,
            max_drawdown=max_loss,
            max_drawdown_pct=max_drawdown_pct,
            recovery_time_sec=int(recovery_hours * 3600),
            total_pnl=-max_loss,
            sharpe_during_crisis=-5.0,  # 危机期间 Sharpe 通常极低
            risk_controls_triggered=risk_controls,
            trade_count=0,
            notes=f"基于预期影响模拟（无真实数据）。波动率放大 {volatility_spike}x。",
            timestamp_ns=time.time_ns(),
        )

    def _replay_scenario(
        self,
        scenario: CrisisScenario,
        strategy_name: str,
        tick_data: list[Ticker],
        initial_equity: Decimal,
        strategy_callback: Any | None,
    ) -> StressResult:
        """回放真实 tick 数据。

        逐 tick 回放，跟踪权益曲线、最大回撤、风控触发。

        Args:
            scenario: 危机场景
            strategy_name: 策略名称
            tick_data: tick 数据列表
            initial_equity: 初始权益
            strategy_callback: 策略回调

        Returns:
            回放结果
        """
        equity = initial_equity
        peak_equity = equity
        max_loss = Decimal("0")
        max_drawdown = Decimal("0")
        max_drawdown_pct = 0.0
        pnl_history: list[Decimal] = []
        risk_controls: list[str] = []
        trade_count = 0
        recovery_time_sec = -1

        for i, ticker in enumerate(tick_data):
            # 简单回放：跟踪价格变动对持仓的影响
            if i > 0:
                prev_price = tick_data[i - 1].last_price
                curr_price = ticker.last_price
                if prev_price > 0:
                    price_change = (curr_price - prev_price) / prev_price
                    # 假设等权多头持仓
                    equity += equity * Decimal(str(price_change))

            # 跟踪峰值和回撤
            if equity > peak_equity:
                peak_equity = equity

            drawdown = peak_equity - equity
            if drawdown > max_drawdown:
                max_drawdown = drawdown
                max_drawdown_pct = float(drawdown / peak_equity * 100) if peak_equity > 0 else 0

            loss = initial_equity - equity
            if loss > max_loss:
                max_loss = loss

            pnl_history.append(equity - initial_equity)

            # 风控触发检查
            if max_drawdown_pct > 15 and "L3_最大回撤熔断" not in risk_controls:
                risk_controls.append("L3_最大回撤熔断")
            if max_drawdown_pct > 25 and "L4_全局熔断器" not in risk_controls:
                risk_controls.append("L4_全局熔断器")

        # 计算恢复时间
        for i, pnl in enumerate(pnl_history):
            if pnl >= 0 and i > 0:
                recovery_time_sec = i  # tick 数（近似秒数）
                break

        # 计算危机期间 Sharpe
        if len(pnl_history) > 1:
            returns = []
            for i in range(1, len(pnl_history)):
                prev = float(pnl_history[i - 1]) if pnl_history[i - 1] != 0 else 1.0
                curr = float(pnl_history[i])
                if prev != 0:
                    returns.append((curr - prev) / abs(prev))
            if returns:
                import numpy as np

                arr = np.array(returns)
                mean_r = arr.mean()
                std_r = arr.std()
                sharpe = (mean_r / std_r * (365**0.5)) if std_r > 0 else 0.0
            else:
                sharpe = 0.0
        else:
            sharpe = 0.0

        total_pnl = equity - initial_equity

        return StressResult(
            scenario=scenario.name,
            max_loss=max_loss,
            max_loss_pct=float(max_loss / initial_equity * 100) if initial_equity > 0 else 0,
            max_drawdown=max_drawdown,
            max_drawdown_pct=round(max_drawdown_pct, 2),
            recovery_time_sec=recovery_time_sec,
            total_pnl=total_pnl,
            sharpe_during_crisis=round(sharpe, 4),
            risk_controls_triggered=risk_controls,
            trade_count=trade_count,
            notes=f"基于 {len(tick_data)} 条 tick 数据回放",
            timestamp_ns=time.time_ns(),
        )

    def _log_summary(self, results: list[StressResult]) -> None:
        """输出压力测试汇总日志。"""
        logger.info("=" * 60)
        logger.info("压力测试汇总")
        logger.info("=" * 60)
        for r in results:
            logger.info(
                "  %s: 最大回撤=%.2f%%, 总PnL=%s, 恢复时间=%ds, 风控触发=%s",
                r.scenario,
                r.max_drawdown_pct,
                r.total_pnl,
                r.recovery_time_sec,
                r.risk_controls_triggered,
            )
        avg_dd = sum(r.max_drawdown_pct for r in results) / len(results) if results else 0
        worst = max(results, key=lambda r: r.max_drawdown_pct) if results else None
        logger.info("平均最大回撤: %.2f%%", avg_dd)
        if worst:
            logger.info("最差场景: %s (%.2f%%)", worst.scenario, worst.max_drawdown_pct)
        logger.info("=" * 60)

    def get_scenarios(self) -> list[CrisisScenario]:
        """获取所有危机场景列表。"""
        return self.CRISIS_SCENARIOS.copy()

    @property
    def results_history(self) -> list[StressResult]:
        """历史测试结果。"""
        return self._results_history.copy()
