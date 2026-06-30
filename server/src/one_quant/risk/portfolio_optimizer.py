"""
ONE量化 - 组合优化器 + 资金分配引擎

基于 NumPy/SciPy 实现经典组合优化模型：
  - 均值-方差优化 (Markowitz)
  - 风险平价 (Risk Parity)
  - Black-Litterman 模型
  - 波动率目标 (Volatility Targeting)

资金分配引擎在策略间分配资金，支持多种优化目标。
"""

from __future__ import annotations

import time
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

import numpy as np

from one_quant.infra.logging import get_logger

logger = get_logger(__name__)

# SciPy 可选导入（用于凸优化）
try:
    from scipy.optimize import minimize

    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False
    logger.warning("SciPy 未安装，部分优化功能将使用简化实现")


# ──────────────────────────── 组合优化器 ────────────────────────────


class PortfolioOptimizer:
    """组合优化器。

    实现多种经典组合优化模型，输出最优权重向量。
    所有输入使用 list[float]，内部转为 NumPy 数组计算。

    权重约束：
      - 默认：权重之和 = 1，各权重 ∈ [0, 1]（仅做多）
      - 可选：允许做空（权重 ∈ [-1, 1]）
    """

    def mean_variance_optimize(
        self,
        expected_returns: list[float],
        covariance_matrix: list[list[float]],
        target_return: float | None = None,
        allow_short: bool = False,
        max_weight: float = 1.0,
        risk_aversion: float = 1.0,
    ) -> dict[str, Any]:
        """均值-方差优化 (Markowitz Mean-Variance)。

        经典 Markowitz 模型：在给定收益目标下最小化方差，
        或在风险厌恶系数下最大化 E[R] - λ/2 × σ²。

        目标函数：
          min  w^T Σ w - (1/λ) × w^T μ   (最大化效用)
          s.t. Σw = 1, 0 ≤ w ≤ max_weight

        或指定 target_return:
          min  w^T Σ w
          s.t. w^T μ ≥ target_return, Σw = 1, 0 ≤ w ≤ max_weight

        Args:
            expected_returns: 预期收益率列表 [r1, r2, ..., rn]
            covariance_matrix: 协方差矩阵 n×n
            target_return: 目标收益率（None = 最大化效用）
            allow_short: 是否允许做空
            max_weight: 单资产最大权重
            risk_aversion: 风险厌恶系数 λ（越大越厌恶风险）

        Returns:
            {
                "weights": list[float],        # 最优权重
                "expected_return": float,       # 预期组合收益
                "expected_volatility": float,   # 预期组合波动率
                "sharpe_ratio": float,          # 夏普比率（假设无风险利率=0）
                "optimization_status": str,     # 优化状态
            }
        """
        n = len(expected_returns)
        mu = np.array(expected_returns, dtype=np.float64)
        sigma = np.array(covariance_matrix, dtype=np.float64)

        # 输入校验
        if sigma.shape != (n, n):
            raise ValueError(f"协方差矩阵维度 {sigma.shape} 与资产数 {n} 不匹配")

        # 确保协方差矩阵对称正定
        sigma = (sigma + sigma.T) / 2
        sigma += np.eye(n) * 1e-8  # 正则化

        # 权重边界
        lb = -max_weight if allow_short else 0.0
        ub = max_weight

        # 初始权重：等权
        w0 = np.ones(n) / n

        # 约束：权重之和 = 1
        constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1.0}]

        # 如指定目标收益，添加收益约束
        if target_return is not None:
            constraints.append({
                "type": "ineq",
                "fun": lambda w: w @ mu - target_return,
            })

        # 边界
        bounds = [(lb, ub)] * n

        if not HAS_SCIPY:
            # 简化实现：等权组合
            logger.warning("SciPy 不可用，返回等权组合")
            w = w0
        else:
            if target_return is not None:
                # 最小化方差
                def objective(w: np.ndarray) -> float:
                    return float(w @ sigma @ w)
            else:
                # 最大化效用 E[R] - λ/2 × σ²
                def objective(w: np.ndarray) -> float:
                    return float(w @ sigma @ w / risk_aversion - w @ mu)

            result = minimize(
                objective,
                w0,
                method="SLSQP",
                bounds=bounds,
                constraints=constraints,
                options={"maxiter": 1000, "ftol": 1e-12},
            )
            w = result.x
            if not result.success:
                logger.warning("均值-方差优化未完全收敛: %s", result.message)

        # 计算组合指标
        port_return = float(w @ mu)
        port_vol = float(np.sqrt(w @ sigma @ w))
        sharpe = port_return / port_vol if port_vol > 0 else 0.0

        return {
            "weights": [round(float(x), 6) for x in w],
            "expected_return": round(port_return, 6),
            "expected_volatility": round(port_vol, 6),
            "sharpe_ratio": round(sharpe, 4),
            "optimization_status": "success" if HAS_SCIPY else "fallback_equal_weight",
        }

    def risk_parity(
        self,
        covariance_matrix: list[list[float]],
        risk_budget: list[float] | None = None,
    ) -> dict[str, Any]:
        """风险平价 (Risk Parity)。

        目标：使每个资产对组合风险的贡献相等（或按预算分配）。
        风险贡献 = w_i × (Σw)_i / σ_p

        目标函数：
          min Σ_i Σ_j (w_i(Σw)_i - w_j(Σw)_j)²
          或 min Σ_i (w_i(Σw)_i / σ_p² - b_i)²

        Args:
            covariance_matrix: 协方差矩阵 n×n
            risk_budget: 风险预算 b_i（默认等风险 b_i = 1/n）

        Returns:
            {
                "weights": list[float],
                "risk_contributions": list[float],  # 各资产风险贡献
                "expected_volatility": float,
                "optimization_status": str,
            }
        """
        sigma = np.array(covariance_matrix, dtype=np.float64)
        n = sigma.shape[0]

        # 确保对称正定
        sigma = (sigma + sigma.T) / 2
        sigma += np.eye(n) * 1e-8

        if risk_budget is None:
            budget = np.ones(n) / n
        else:
            budget = np.array(risk_budget, dtype=np.float64)
            budget = budget / budget.sum()  # 归一化

        if not HAS_SCIPY:
            # 简化实现：逆波动率加权
            logger.warning("SciPy 不可用，使用逆波动率加权近似风险平价")
            vols = np.sqrt(np.diag(sigma))
            inv_vols = 1.0 / vols
            w = inv_vols / inv_vols.sum()
        else:
            def objective(w: np.ndarray) -> float:
                w = np.abs(w)  # 确保正权重
                sigma_w = sigma @ w
                port_vol = np.sqrt(w @ sigma_w)
                if port_vol < 1e-12:
                    return 1e10
                # 各资产风险贡献
                rc = w * sigma_w / port_vol
                # 目标：风险贡献比例 = 风险预算
                rc_ratio = rc / rc.sum()
                return float(np.sum((rc_ratio - budget) ** 2))

            w0 = np.ones(n) / n
            bounds = [(1e-8, 1.0)] * n
            constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1.0}]

            result = minimize(
                objective,
                w0,
                method="SLSQP",
                bounds=bounds,
                constraints=constraints,
                options={"maxiter": 1000, "ftol": 1e-14},
            )
            w = np.abs(result.x)
            w = w / w.sum()  # 归一化

            if not result.success:
                logger.warning("风险平价优化未完全收敛: %s", result.message)

        # 计算风险贡献
        sigma_w = sigma @ w
        port_vol = float(np.sqrt(w @ sigma_w))
        risk_contrib = w * sigma_w / port_vol if port_vol > 0 else np.zeros(n)
        rc_pct = risk_contrib / risk_contrib.sum() if risk_contrib.sum() > 0 else np.zeros(n)

        return {
            "weights": [round(float(x), 6) for x in w],
            "risk_contributions": [round(float(x), 6) for x in rc_pct],
            "expected_volatility": round(port_vol, 6),
            "optimization_status": "success" if HAS_SCIPY else "fallback_inverse_volatility",
        }

    def black_litterman(
        self,
        market_weights: list[float],
        covariance_matrix: list[list[float]],
        views: dict[int, float],
        confidence: dict[int, float],
        risk_aversion: float = 2.5,
        tau: float = 0.05,
    ) -> dict[str, Any]:
        """Black-Litterman 模型。

        将投资者主观观点与市场均衡结合，生成调整后的预期收益和权重。

        公式：
          市场隐含收益: π = δ × Σ × w_mkt
          调整后收益: E[R] = [(τΣ)^{-1} + P^T Ω^{-1} P]^{-1} [(τΣ)^{-1} π + P^T Ω^{-1} Q]
          调整后权重: w* = (δΣ)^{-1} E[R]

        Args:
            market_weights: 市场均衡权重（市值加权）
            covariance_matrix: 协方差矩阵
            views: 观点 {资产索引: 预期超额收益}
                例: {0: 0.05, 2: -0.03} 表示看好资产0、看空资产2
            confidence: 观点置信度 {资产索引: 0~1}
                例: {0: 0.8, 2: 0.5}
            risk_aversion: 风险厌恶系数 δ
            tau: 不确定性缩放因子（越大 = 对市场均衡越不确定）

        Returns:
            {
                "weights": list[float],
                "implied_returns": list[float],     # 市场隐含收益
                "adjusted_returns": list[float],    # 调整后预期收益
                "expected_volatility": float,
                "optimization_status": str,
            }
        """
        n = len(market_weights)
        w_mkt = np.array(market_weights, dtype=np.float64)
        sigma = np.array(covariance_matrix, dtype=np.float64)

        # 确保对称正定
        sigma = (sigma + sigma.T) / 2
        sigma += np.eye(n) * 1e-8

        # ── 第一步：计算市场隐含收益 π = δ × Σ × w_mkt ──
        pi = risk_aversion * sigma @ w_mkt

        # ── 第二步：构建观点矩阵 P 和观点向量 Q ──
        view_indices = sorted(views.keys())
        k = len(view_indices)

        if k == 0:
            # 无观点，返回市场均衡
            return {
                "weights": [round(float(x), 6) for x in w_mkt],
                "implied_returns": [round(float(x), 6) for x in pi],
                "adjusted_returns": [round(float(x), 6) for x in pi],
                "expected_volatility": round(float(np.sqrt(w_mkt @ sigma @ w_mkt)), 6),
                "optimization_status": "no_views_market_equilibrium",
            }

        P = np.zeros((k, n))
        Q = np.zeros(k)
        omega_diag = np.zeros(k)

        for i, idx in enumerate(view_indices):
            P[i, idx] = 1.0
            Q[i] = views[idx]
            conf = confidence.get(idx, 0.5)
            # Ω = diag(P × (τΣ) × P^T) / conf
            omega_diag[i] = float(P[i] @ (tau * sigma) @ P[i]) / max(conf, 0.01)

        Omega = np.diag(omega_diag)

        # ── 第三步：计算调整后收益 ──
        tau_sigma_inv = np.linalg.inv(tau * sigma)
        omega_inv = np.linalg.inv(Omega)

        # E[R] = [(τΣ)^{-1} + P^T Ω^{-1} P]^{-1} [(τΣ)^{-1} π + P^T Ω^{-1} Q]
        A = tau_sigma_inv + P.T @ omega_inv @ P
        b = tau_sigma_inv @ pi + P.T @ omega_inv @ Q
        adjusted_returns = np.linalg.solve(A, b)

        # ── 第四步：计算调整后权重 ──
        sigma_inv = np.linalg.inv(sigma)
        w_star = sigma_inv @ adjusted_returns / risk_aversion
        w_star = np.maximum(w_star, 0)  # 仅做多
        if w_star.sum() > 0:
            w_star = w_star / w_star.sum()  # 归一化

        port_vol = float(np.sqrt(w_star @ sigma @ w_star))

        return {
            "weights": [round(float(x), 6) for x in w_star],
            "implied_returns": [round(float(x), 6) for x in pi],
            "adjusted_returns": [round(float(x), 6) for x in adjusted_returns],
            "expected_volatility": round(port_vol, 6),
            "optimization_status": "success",
        }

    def volatility_targeting(
        self,
        portfolio_returns: list[float],
        current_weights: list[float],
        covariance_matrix: list[list[float]],
        target_vol: float = 0.15,
        lookback_periods: int = 60,
        rebalance_threshold: float = 0.02,
    ) -> dict[str, Any]:
        """波动率目标 (Volatility Targeting)。

        动态调整仓位杠杆，使组合波动率趋近目标值。
        当实际波动率高于目标时减仓，低于目标时加仓。

        杠杆 = target_vol / realized_vol

        Args:
            portfolio_returns: 历史组合收益率序列
            current_weights: 当前持仓权重
            covariance_matrix: 协方差矩阵
            target_vol: 目标年化波动率（默认 15%）
            lookback_periods: 波动率计算回望期
            rebalance_threshold: 再平衡阈值（杠杆变化超过此值才调仓）

        Returns:
            {
                "target_leverage": float,
                "realized_volatility": float,
                "adjusted_weights": list[float],
                "needs_rebalance": bool,
                "vol_regime": str,  # "low" / "normal" / "high" / "extreme"
            }
        """
        sigma = np.array(covariance_matrix, dtype=np.float64)
        w = np.array(current_weights, dtype=np.float64)

        # 确保对称正定
        sigma = (sigma + sigma.T) / 2
        sigma += np.eye(len(w)) * 1e-8

        # 计算已实现波动率（年化）
        if len(portfolio_returns) >= lookback_periods:
            recent = portfolio_returns[-lookback_periods:]
            realized_vol = float(np.std(recent) * np.sqrt(365))
        else:
            # 用协方差矩阵估算
            realized_vol = float(np.sqrt(w @ sigma @ w))

        # 计算目标杠杆
        if realized_vol > 0:
            target_leverage = target_vol / realized_vol
        else:
            target_leverage = 1.0

        # 杠杆限制：最大 2x，最小 0.1x
        target_leverage = max(0.1, min(2.0, target_leverage))

        # 调整权重
        adjusted_weights = w * target_leverage
        # 如果杠杆 < 1，多余资金为现金（不纳入权重）
        # 归一化：确保调整后权重之和 ≤ 1
        if adjusted_weights.sum() > 1.0:
            adjusted_weights = adjusted_weights / adjusted_weights.sum()

        # 是否需要再平衡
        leverage_change = abs(target_leverage - 1.0)
        needs_rebalance = leverage_change > rebalance_threshold

        # 波动率区间判断
        if realized_vol < target_vol * 0.5:
            vol_regime = "low"
        elif realized_vol < target_vol * 1.2:
            vol_regime = "normal"
        elif realized_vol < target_vol * 2.0:
            vol_regime = "high"
        else:
            vol_regime = "extreme"

        return {
            "target_leverage": round(target_leverage, 4),
            "realized_volatility": round(realized_vol, 4),
            "adjusted_weights": [round(float(x), 6) for x in adjusted_weights],
            "needs_rebalance": needs_rebalance,
            "vol_regime": vol_regime,
        }


# ──────────────────────────── 资金分配引擎 ────────────────────────────


class CapitalAllocator:
    """资金分配引擎。

    在多个策略间分配总资金，支持多种优化目标。

    分配策略：
      - equal: 等权分配
      - risk_parity: 风险平价（各策略风险贡献相等）
      - mean_variance: 均值-方差最优
      - inverse_vol: 逆波动率加权
      - kelly: 凯利公式（基于历史胜率和赔率）
    """

    def allocate(
        self,
        strategies: list[dict[str, Any]],
        total_capital: Decimal,
        optimizer: str = "risk_parity",
    ) -> dict[str, Decimal]:
        """在策略间分配资金。

        Args:
            strategies: 策略列表，每个策略包含：
                {
                    "name": str,
                    "expected_return": float,       # 预期年化收益
                    "volatility": float,            # 年化波动率
                    "win_rate": float,              # 胜率 (0~1)
                    "avg_win": float,               # 平均盈利
                    "avg_loss": float,              # 平均亏损（正数）
                    "max_drawdown": float,          # 历史最大回撤
                    "sharpe_ratio": float,          # 夏普比率
                }
            total_capital: 总资金
            optimizer: 优化方法

        Returns:
            {strategy_name: allocated_capital}
        """
        if not strategies:
            return {}

        n = len(strategies)

        if optimizer == "equal":
            weights = [1.0 / n] * n

        elif optimizer == "risk_parity":
            weights = self._risk_parity_weights(strategies)

        elif optimizer == "mean_variance":
            weights = self._mean_variance_weights(strategies)

        elif optimizer == "inverse_vol":
            weights = self._inverse_vol_weights(strategies)

        elif optimizer == "kelly":
            weights = self._kelly_weights(strategies)

        else:
            logger.warning("未知优化方法 '%s'，使用等权分配", optimizer)
            weights = [1.0 / n] * n

        # 分配资金
        allocation: dict[str, Decimal] = {}
        for i, strat in enumerate(strategies):
            name = strat.get("name", f"strategy_{i}")
            amount = total_capital * Decimal(str(round(weights[i], 6)))
            amount = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            allocation[name] = amount

        # 处理舍入误差（加到最大权重策略上）
        allocated = sum(allocation.values())
        diff = total_capital - allocated
        if diff != 0 and allocation:
            max_key = max(allocation, key=lambda k: allocation[k])
            allocation[max_key] += diff

        logger.info("资金分配 (方法=%s, 总资金=%s): %s", optimizer, total_capital, allocation)
        return allocation

    def rebalance(
        self,
        current: dict[str, Decimal],
        target: dict[str, Decimal],
        min_trade_value: Decimal = Decimal("100"),
    ) -> list[dict[str, Any]]:
        """再平衡操作。

        计算从当前持仓到目标持仓需要的交易。

        Args:
            current: 当前持仓 {策略名: 当前金额}
            target: 目标持仓 {策略名: 目标金额}
            min_trade_value: 最小交易金额（低于此值不交易）

        Returns:
            交易列表 [{"name": str, "action": "buy"/"sell", "amount": Decimal}]
        """
        all_keys = set(current.keys()) | set(target.keys())
        trades: list[dict[str, Any]] = []

        for key in all_keys:
            current_amt = current.get(key, Decimal("0"))
            target_amt = target.get(key, Decimal("0"))
            diff = target_amt - current_amt

            if abs(diff) < min_trade_value:
                continue

            action = "buy" if diff > 0 else "sell"
            trades.append({
                "name": key,
                "action": action,
                "amount": abs(diff),
                "current": current_amt,
                "target": target_amt,
            })

        # 先卖后买（释放资金再分配）
        trades.sort(key=lambda t: (0 if t["action"] == "sell" else 1, -float(t["amount"])))

        logger.info("再平衡交易 %d 笔: %s", len(trades), [
            f"{t['name']}: {t['action']} {t['amount']}" for t in trades
        ])
        return trades

    # ── 内部权重计算 ──

    def _risk_parity_weights(self, strategies: list[dict[str, Any]]) -> list[float]:
        """风险平价权重：使各策略风险贡献相等。"""
        vols = [max(s.get("volatility", 0.01), 0.001) for s in strategies]
        inv_vols = [1.0 / v for v in vols]
        total = sum(inv_vols)
        return [iv / total for iv in inv_vols]

    def _mean_variance_weights(self, strategies: list[dict[str, Any]]) -> list[float]:
        """均值-方差权重：夏普比率加权。"""
        sharpes = [max(s.get("sharpe_ratio", 0), 0.01) for s in strategies]
        total = sum(sharpes)
        return [sh / total for sh in sharpes]

    def _inverse_vol_weights(self, strategies: list[dict[str, Any]]) -> list[float]:
        """逆波动率加权。"""
        vols = [max(s.get("volatility", 0.01), 0.001) for s in strategies]
        inv_vols = [1.0 / v for v in vols]
        total = sum(inv_vols)
        return [iv / total for iv in inv_vols]

    def _kelly_weights(self, strategies: list[dict[str, Any]]) -> list[float]:
        """凯利公式权重。

        Kelly% = (p × b - q) / b
        其中 p=胜率, q=1-p, b=盈亏比(avg_win/avg_loss)

        使用半凯利（Kelly/2）降低波动。
        """
        kelly_fracs: list[float] = []
        for s in strategies:
            p = s.get("win_rate", 0.5)
            avg_win = s.get("avg_win", 0.01)
            avg_loss = s.get("avg_loss", 0.01)

            if avg_loss <= 0:
                avg_loss = 0.01

            b = avg_win / avg_loss  # 盈亏比
            q = 1 - p

            kelly = (p * b - q) / b if b > 0 else 0
            # 半凯利 + 非负约束
            kelly = max(0, kelly / 2)
            kelly_fracs.append(kelly)

        total = sum(kelly_fracs)
        if total <= 0:
            # 回退到等权
            n = len(strategies)
            return [1.0 / n] * n

        return [k / total for k in kelly_fracs]
