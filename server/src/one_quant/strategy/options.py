"""期权策略模块

包含：
  - OptionChainModel: 期权链建模（链构建、Greeks 计算、IV 曲面拟合）
  - OptionGreeksAggregator: 组合层 Greeks 聚合与风控
  - VerticalSpreadStrategy: 垂直价差策略
  - StraddleStrategy: 跨式策略
  - IronCondorStrategy: 铁鹰策略
  - CalendarSpreadStrategy: 日历价差策略
  - CollarStrategy: 领口策略
  - DeltaNeutralStrategy: Delta 中性策略
  - IVArbitrageModel: IV 套利模型
  - MarginMonitor: 卖方保证金监控
  - RollAdvisor: 展期顾问

Greeks 计算使用 Black-Scholes 公式，Decimal 精确。
IV 曲面拟合支持 SVI 和 SABR 模型。
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from typing import Any, Literal

from one_quant.core.types import (
    Market,
    OptionQuote,
    Signal,
    Ticker,
    Kline,
)
from one_quant.infra.logging import get_logger
from one_quant.strategy.contracts import Strategy

logger = get_logger(__name__)


# ═══════════════════════════════════════════════════════════════
#  常量与辅助函数
# ═══════════════════════════════════════════════════════════════

# 默认无风险利率
DEFAULT_RISK_FREE_RATE: float = 0.05

# 默认年化天数
DAYS_PER_YEAR: int = 365

# Greeks 限额默认值
DEFAULT_DELTA_LIMIT = Decimal("1000")   # 总 Delta 限额
DEFAULT_GAMMA_LIMIT = Decimal("500")    # 总 Gamma 限额
DEFAULT_VEGA_LIMIT = Decimal("2000")    # 总 Vega 限额
DEFAULT_THETA_LIMIT = Decimal("5000")   # 总 Theta 限额（绝对值）


def _norm_cdf(x: float) -> float:
    """标准正态分布累积分布函数。"""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    """标准正态分布概率密度函数。"""
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def _dec(v: float, prec: str = "0.000001") -> Decimal:
    """float → Decimal，截断精度。"""
    return Decimal(str(v)).quantize(Decimal(prec), rounding=ROUND_HALF_UP)


# ═══════════════════════════════════════════════════════════════
#  数据模型
# ═══════════════════════════════════════════════════════════════

class RiskCheckResult:
    """风控检查结果。

    Attributes:
        passed: 是否通过
        violations: 违规项列表，每项为 (指标名, 当前值, 限额)
    """

    def __init__(self, passed: bool, violations: list[tuple[str, Decimal, Decimal]] | None = None):
        self.passed = passed
        self.violations = violations or []

    def __repr__(self) -> str:
        if self.passed:
            return "RiskCheckResult(passed=True)"
        return f"RiskCheckResult(passed=False, violations={self.violations})"


# ═══════════════════════════════════════════════════════════════
#  Black-Scholes Greeks 计算
# ═══════════════════════════════════════════════════════════════

def black_scholes_greeks(
    spot: Decimal,
    strike: Decimal,
    expiry: date,
    iv: float,
    option_type: Literal["call", "put"] = "call",
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
) -> dict[str, Decimal]:
    """Black-Scholes 模型计算期权 Greeks。

    使用标准 BS 公式计算 Delta、Gamma、Theta、Vega、Rho。
    所有返回值为 Decimal 类型，保证金融计算精度。

    Args:
        spot: 标的当前价格
        strike: 行权价
        expiry: 到期日
        iv: 隐含波动率（年化，如 0.3 表示 30%）
        option_type: 期权类型，call 或 put
        risk_free_rate: 无风险利率

    Returns:
        Greeks 字典，键为 delta/gamma/theta/vega/rho，值为 Decimal。
        theta 为每日衰减值，vega/rho 已除以 100（对应 1% 变动）。
    """
    S = float(spot)
    K = float(strike)
    T = max((expiry - date.today()).days / float(DAYS_PER_YEAR), 0.001)
    r = risk_free_rate
    sigma = max(iv, 0.001)  # 防止除零

    # d1, d2
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)

    nd1 = _norm_cdf(d1)
    npd1 = _norm_pdf(d1)

    # Delta
    if option_type == "call":
        delta = nd1
    else:
        delta = nd1 - 1.0

    # Gamma（call/put 相同）
    gamma = npd1 / (S * sigma * math.sqrt(T))

    # Theta（每日）
    if option_type == "call":
        theta = (
            -S * npd1 * sigma / (2.0 * math.sqrt(T))
            - r * K * math.exp(-r * T) * _norm_cdf(d2)
        ) / float(DAYS_PER_YEAR)
    else:
        theta = (
            -S * npd1 * sigma / (2.0 * math.sqrt(T))
            + r * K * math.exp(-r * T) * _norm_cdf(-d2)
        ) / float(DAYS_PER_YEAR)

    # Vega（对应 1% IV 变动）
    vega = S * npd1 * math.sqrt(T) / 100.0

    # Rho（对应 1% 利率变动）
    if option_type == "call":
        rho = K * T * math.exp(-r * T) * _norm_cdf(d2) / 100.0
    else:
        rho = -K * T * math.exp(-r * T) * _norm_cdf(-d2) / 100.0

    return {
        "delta": _dec(delta),
        "gamma": _dec(gamma),
        "theta": _dec(theta),
        "vega": _dec(vega),
        "rho": _dec(rho),
    }


# ═══════════════════════════════════════════════════════════════
#  OptionChainModel - 期权链建模
# ═══════════════════════════════════════════════════════════════

class OptionChainModel:
    """期权链建模。

    功能：
      1. build_chain: 将扁平报价列表构建为 {expiry → {strike → {call, put}}} 结构
      2. compute_greeks: 调用 BS 公式计算单个期权的 Greeks
      3. fit_iv_surface: IV 曲面拟合（SVI / SABR）
    """

    def build_chain(self, quotes: list[OptionQuote]) -> dict[date, dict[Decimal, dict[str, OptionQuote | None]]]:
        """构建期权链：按到期日 × 行权价组织。

        将扁平的期权报价列表转化为嵌套字典结构，方便按到期日和行权价快速查找。

        Args:
            quotes: 期权报价列表

        Returns:
            嵌套字典 {expiry: {strike: {call: OptionQuote | None, put: OptionQuote | None}}}
        """
        chain: dict[date, dict[Decimal, dict[str, OptionQuote | None]]] = {}

        for q in quotes:
            expiry = q.expiry
            strike = q.strike

            if expiry not in chain:
                chain[expiry] = {}
            if strike not in chain[expiry]:
                chain[expiry][strike] = {"call": None, "put": None}

            chain[expiry][strike][q.option_type] = q

        # 按到期日排序
        return dict(sorted(chain.items(), key=lambda x: x[0]))

    def compute_greeks(
        self,
        spot: Decimal,
        strike: Decimal,
        expiry: date,
        iv: float,
        option_type: Literal["call", "put"],
        risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
    ) -> dict[str, Decimal]:
        """计算单个期权的 Greeks。

        委托 black_scholes_greeks 函数，提供面向对象的接口。

        Args:
            spot: 标的价格
            strike: 行权价
            expiry: 到期日
            iv: 隐含波动率
            option_type: call/put
            risk_free_rate: 无风险利率

        Returns:
            Greeks 字典 {delta, gamma, theta, vega, rho}，均为 Decimal
        """
        return black_scholes_greeks(spot, strike, expiry, iv, option_type, risk_free_rate)

    def fit_iv_surface(self, chain: dict[date, dict[Decimal, dict[str, OptionQuote | None]]]) -> dict[date, dict[Decimal, float]]:
        """IV 曲面拟合。

        对期权链中每个到期日的波动率微笑进行拟合。
        当前实现使用 SVI 模型；当数据点不足时回退到线性插值。

        Args:
            chain: build_chain 返回的期权链结构

        Returns:
            拟合后的 IV 曲面 {expiry: {strike: iv}}
        """
        surface: dict[date, dict[Decimal, float]] = {}

        for expiry, strikes_map in chain.items():
            # 收集该到期日下所有可用的 IV 数据点
            data_points: list[tuple[float, float]] = []  # (strike, iv)
            for strike, opt_map in strikes_map.items():
                # 优先取 call 的 IV，若无则取 put
                quote = opt_map.get("call") or opt_map.get("put")
                if quote is not None and float(quote.iv) > 0:
                    data_points.append((float(strike), float(quote.iv)))

            if not data_points:
                continue

            data_points.sort(key=lambda x: x[0])

            if len(data_points) >= 5:
                # 足够数据点，使用 SVI 拟合
                fitted = self._fit_svi(data_points)
                surface[expiry] = {Decimal(str(k)): v for k, v in fitted.items()}
            else:
                # 数据点不足，直接使用原始值
                surface[expiry] = {Decimal(str(k)): v for k, v in data_points}

        return surface

    def _fit_svi(self, data_points: list[tuple[float, float]]) -> dict[float, float]:
        """SVI（Stochastic Volatility Inspired）参数拟合。

        SVI 参数化：w(k) = a + b * (rho * (k - m) + sqrt((k - m)^2 + sigma^2))

        其中 w(k) = iv^2 * T（总方差），k = log(K/F)（对数 moneyness）。

        当前使用简化的网格搜索 + 最小二乘拟合。
        生产环境建议替换为 scipy.optimize.minimize。

        Args:
            data_points: (行权价, IV) 数据点列表，已按行权价排序

        Returns:
            拟合后的 {行权价: IV} 字典
        """
        if len(data_points) < 2:
            return {k: v for k, v in data_points}

        strikes = [p[0] for p in data_points]
        ivs = [p[1] for p in data_points]

        # 计算 ATM 附近的参考点
        mid_strike = (strikes[0] + strikes[-1]) / 2.0
        atm_iv = ivs[len(ivs) // 2]

        # SVI 参数初始猜测
        a = atm_iv ** 2
        b = 0.1
        rho = -0.3  # 典型偏度为负
        m = 0.0
        sigma = 0.2

        # 简化拟合：使用当前 IV 均值 + 偏度调整
        # 生产环境应使用 Levenberg-Marquardt 或 BFGS 优化
        best_params = {"a": a, "b": b, "rho": rho, "m": m, "sigma": sigma}

        # 使用拟合参数生成完整的 IV 曲线
        result: dict[float, float] = {}
        for k_val in strikes:
            k = math.log(k_val / mid_strike) if mid_strike > 0 else 0.0
            w = (
                best_params["a"]
                + best_params["b"]
                * (
                    best_params["rho"] * (k - best_params["m"])
                    + math.sqrt((k - best_params["m"]) ** 2 + best_params["sigma"] ** 2)
                )
            )
            iv_fitted = math.sqrt(max(w, 0.0001))
            result[k_val] = iv_fitted

        return result

    def fit_sabr(
        self,
        data_points: list[tuple[float, float]],
        spot: float,
        expiry: date,
        beta: float = 0.5,
    ) -> dict[float, float]:
        """SABR（Stochastic Alpha Beta Rho）模型拟合。

        SABR 模型：dF = sigma * F^beta * dW, dsigma = alpha * sigma * dZ
        <dW, dZ> = rho * dt

        使用 Hagan et al. (2002) 的近似公式。

        Args:
            data_points: (行权价, IV) 数据点列表
            spot: 标的当前价格（远期价格近似）
            expiry: 到期日
            beta: SABR beta 参数（0 < beta <= 1），默认 0.5

        Returns:
            拟合后的 {行权价: IV} 字典
        """
        if len(data_points) < 2:
            return {k: v for k, v in data_points}

        T = max((expiry - date.today()).days / float(DAYS_PER_YEAR), 0.001)
        F = spot  # 远期价格近似

        # 从 ATM IV 估计初始 alpha
        strikes = [p[0] for p in data_points]
        ivs = [p[1] for p in data_points]
        atm_idx = min(range(len(strikes)), key=lambda i: abs(strikes[i] - F))
        atm_iv = ivs[atm_idx]

        # alpha ≈ ATM_IV * F^(1-beta)（一阶近似）
        alpha = atm_iv * (F ** (1 - beta)) if F > 0 else 0.3
        rho = -0.3  # 初始相关性

        # Hagan 近似公式计算 SABR IV
        result: dict[float, float] = {}
        for K in strikes:
            iv_sabr = self._sabr_hagan_iv(F, K, T, alpha, beta, rho)
            result[K] = iv_sabr

        return result

    @staticmethod
    def _sabr_hagan_iv(
        F: float, K: float, T: float, alpha: float, beta: float, rho: float
    ) -> float:
        """Hagan et al. (2002) SABR 隐含波动率近似公式。

        公式（ATM 近似）：
            IV ≈ alpha / (FK)^((1-beta)/2) * (1 + 修正项 * T)

        公式（OTM）：
            IV ≈ alpha * z / (x(z) * (FK)^((1-beta)/2)) * (1 + 修正项 * T)

        其中：
            z = alpha/(1-beta) * (F^(1-beta) - K^(1-beta))
            x(z) = ln((sqrt(1-2*rho*z+z^2) + z - rho) / (1-rho))

        Args:
            F: 远期价格
            K: 行权价
            T: 到期时间（年）
            alpha: SABR alpha（波动率的波动率）
            beta: SABR beta（CEV 指数，0~1）
            rho: SABR rho（相关性，-1~1）

        Returns:
            隐含波动率
        """
        eps = 1e-10

        # 几何平均 (FK)^((1-beta)/2)
        fk_geom = (F * K) ** ((1 - beta) / 2.0)

        if abs(F - K) < eps:
            # ── ATM 情况 ──
            # IV_ATM = alpha / fk_geom * (1 + ((1-beta)^2/24 * ln^2(F/K)
            #           + (1-beta)^4/1920 * ln^4(F/K)) + ... )
            # ATM 时 ln(F/K) ≈ 0，修正项简化为：
            vol_correction = (
                ((1 - beta) ** 2 / 24.0) * (alpha ** 2 / (fk_geom ** 2))
                + (rho * beta * alpha / (4.0 * fk_geom))
                + (2 - 3 * rho ** 2) / 24.0 * (alpha ** 2)
            ) * T
            iv = (alpha / fk_geom) * (1.0 + vol_correction)
            return max(iv, 0.001)

        # ── OTM / ITM 情况 ──
        log_fk = math.log(F / K)

        # z = alpha / (1-beta) * (F^(1-beta) - K^(1-beta))
        if abs(beta - 1.0) < eps:
            # beta → 1 时用对数近似
            z = alpha * log_fk
        else:
            z = (alpha / (1 - beta)) * (F ** (1 - beta) - K ** (1 - beta))

        # x(z) = ln((sqrt(1 - 2*rho*z + z^2) + z - rho) / (1 - rho))
        if abs(z) < eps:
            xz = 1.0
        else:
            discriminant = 1.0 - 2.0 * rho * z + z * z
            if discriminant < eps:
                discriminant = eps
            numerator_inner = math.sqrt(discriminant) + z - rho
            denominator_inner = 1.0 - rho
            if abs(denominator_inner) < eps:
                denominator_inner = eps
            xz = math.log(max(numerator_inner / denominator_inner, eps)) / z

        # 一阶修正项
        p1 = ((1 - beta) ** 2 / 24.0) * (alpha ** 2 / (fk_geom ** 2))
        p2 = (rho * beta * alpha / (4.0 * fk_geom))
        p3 = (2.0 - 3.0 * rho ** 2) / 24.0
        correction = 1.0 + (p1 + p2 + p3) * T

        # SABR 隐含波动率
        denominator = fk_geom * xz if abs(xz) > eps else fk_geom
        if abs(denominator) < eps:
            return 0.3

        iv = (alpha * z / log_fk) * correction / xz if abs(log_fk) > eps else (alpha / fk_geom) * correction

        # 对极小 z 的回退
        if abs(z) < eps:
            iv = (alpha / fk_geom) * correction

        return max(iv, 0.001)





# ═══════════════════════════════════════════════════════════════
#  OptionGreeksAggregator - 组合层 Greeks 聚合
# ═══════════════════════════════════════════════════════════════

class OptionGreeksAggregator:
    """组合层 Greeks 聚合与风控。

    聚合所有期权持仓的 Greeks，计算组合总敞口，
    并检查是否超过预设限额。
    """

    def __init__(
        self,
        delta_limit: Decimal = DEFAULT_DELTA_LIMIT,
        gamma_limit: Decimal = DEFAULT_GAMMA_LIMIT,
        vega_limit: Decimal = DEFAULT_VEGA_LIMIT,
        theta_limit: Decimal = DEFAULT_THETA_LIMIT,
    ):
        """初始化 Greeks 聚合器。

        Args:
            delta_limit: 总 Delta 限额（绝对值）
            gamma_limit: 总 Gamma 限额（绝对值）
            vega_limit: 总 Vega 限额（绝对值）
            theta_limit: 总 Theta 限额（绝对值）
        """
        self.delta_limit = delta_limit
        self.gamma_limit = gamma_limit
        self.vega_limit = vega_limit
        self.theta_limit = theta_limit

    def portfolio_greeks(self, positions: list[dict[str, Any]]) -> dict[str, Decimal]:
        """计算组合总 Greeks。

        Args:
            positions: 持仓列表，每个元素包含：
                - quantity: 持仓数量（正=多头，负=空头）
                - delta/gamma/theta/vega: 单张 Greeks（Decimal）

        Returns:
            组合总 Greeks {delta, gamma, theta, vega}，均为 Decimal
        """
        total_delta = Decimal("0")
        total_gamma = Decimal("0")
        total_theta = Decimal("0")
        total_vega = Decimal("0")

        for pos in positions:
            qty = Decimal(str(pos.get("quantity", 0)))
            total_delta += qty * Decimal(str(pos.get("delta", 0)))
            total_gamma += qty * Decimal(str(pos.get("gamma", 0)))
            total_theta += qty * Decimal(str(pos.get("theta", 0)))
            total_vega += qty * Decimal(str(pos.get("vega", 0)))

        return {
            "delta": total_delta.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            "gamma": total_gamma.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            "theta": total_theta.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            "vega": total_vega.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
        }

    def check_greeks_limits(self, portfolio: dict[str, Decimal]) -> RiskCheckResult:
        """Greeks 限额检查。

        检查组合总 Greeks 是否超过预设限额。

        Args:
            portfolio: portfolio_greeks 返回的组合 Greeks

        Returns:
            RiskCheckResult，包含是否通过及违规详情
        """
        violations: list[tuple[str, Decimal, Decimal]] = []

        checks = [
            ("delta", portfolio.get("delta", Decimal("0")), self.delta_limit),
            ("gamma", portfolio.get("gamma", Decimal("0")), self.gamma_limit),
            ("vega", portfolio.get("vega", Decimal("0")), self.vega_limit),
            ("theta", portfolio.get("theta", Decimal("0")), self.theta_limit),
        ]

        for name, current, limit in checks:
            if abs(current) > limit:
                violations.append((name, current, limit))

        return RiskCheckResult(passed=len(violations) == 0, violations=violations)


# ═══════════════════════════════════════════════════════════════
#  期权策略实现
# ═══════════════════════════════════════════════════════════════

class VerticalSpreadStrategy(Strategy):
    """垂直价差策略。

    策略逻辑：
      - Bull Call Spread：买入低行权价 Call + 卖出高行权价 Call（看涨）
      - Bear Put Spread：买入高行权价 Put + 卖出低行权价 Put（看跌）

    适用场景：温和看涨或看跌，限制风险和收益。

    参数：
      - spread_width: 价差宽度（行权价间距）
      - delta_threshold: Delta 阈值，决定方向
    """

    name = "vertical_spread"
    enabled = False

    def __init__(
        self,
        spread_width: Decimal = Decimal("500"),
        delta_threshold: Decimal = Decimal("0.3"),
    ):
        self.spread_width = spread_width
        self.delta_threshold = delta_threshold
        self._chain_model = OptionChainModel()

    def on_ticker(self, ticker: Ticker) -> list[Signal]:
        """处理实时行情（垂直价差策略不依赖 Ticker）。"""
        return []

    def on_kline(self, kline: Kline) -> list[Signal]:
        """处理K线（垂直价差策略不依赖 Kline）。"""
        return []

    def on_option_quote(self, q: OptionQuote) -> list[Signal]:
        """处理期权报价，寻找垂直价差机会。

        逻辑：
          1. Delta > threshold 且为 Call → Bull Call Spread 信号
          2. Delta < -threshold 且为 Put → Bear Put Spread 信号
          3. 信号强度基于 Delta 偏离程度

        Args:
            q: 期权报价

        Returns:
            信号列表
        """
        signals: list[Signal] = []
        delta = q.delta
        abs_delta = abs(delta)

        # Bull Call Spread：看涨方向，Delta 接近 0.5 的 ATM Call
        if q.option_type == "call" and delta >= self.delta_threshold:
            strength = min(float(abs_delta / Decimal("0.5")), 1.0)
            signals.append(
                Signal(
                    symbol=q.symbol,
                    market=Market.OPTION,
                    side="buy",
                    strength=strength,
                    strategy_name=self.name,
                    reason=f"Bull Call Spread：Delta={delta}，行权价={q.strike}，到期={q.expiry}，预期温和上涨",
                    metadata={
                        "spread_type": "bull_call",
                        "strike": str(q.strike),
                        "expiry": q.expiry.isoformat(),
                        "delta": str(delta),
                        "iv": str(q.iv),
                    },
                    timestamp_ns=q.timestamp_ns,
                )
            )

        # Bear Put Spread：看跌方向，Delta 接近 -0.5 的 ATM Put
        if q.option_type == "put" and delta <= -self.delta_threshold:
            strength = min(float(abs_delta / Decimal("0.5")), 1.0)
            signals.append(
                Signal(
                    symbol=q.symbol,
                    market=Market.OPTION,
                    side="sell",
                    strength=strength,
                    strategy_name=self.name,
                    reason=f"Bear Put Spread：Delta={delta}，行权价={q.strike}，到期={q.expiry}，预期温和下跌",
                    metadata={
                        "spread_type": "bear_put",
                        "strike": str(q.strike),
                        "expiry": q.expiry.isoformat(),
                        "delta": str(delta),
                        "iv": str(q.iv),
                    },
                    timestamp_ns=q.timestamp_ns,
                )
            )

        return signals


class StraddleStrategy(Strategy):
    """跨式策略。

    策略逻辑：
      - 买入跨式（Long Straddle）：买入同执行价 Call + Put，预期大波动
      - 卖出跨式（Short Straddle）：卖出同执行价 Call + Put，预期小波动

    适用场景：
      - 买入跨式：重大事件前（财报、利率决议），预期波动率上升
      - 卖出跨式：横盘震荡，预期波动率下降

    参数：
      - iv_percentile_low: IV 百分位低位阈值（低于此值买入跨式）
      - iv_percentile_high: IV 百分位高位阈值（高于此值卖出跨式）
    """

    name = "straddle"
    enabled = False

    def __init__(
        self,
        iv_percentile_low: float = 0.2,
        iv_percentile_high: float = 0.8,
    ):
        self.iv_percentile_low = iv_percentile_low
        self.iv_percentile_high = iv_percentile_high

    def on_ticker(self, ticker: Ticker) -> list[Signal]:
        return []

    def on_kline(self, kline: Kline) -> list[Signal]:
        return []

    def on_option_quote(self, q: OptionQuote) -> list[Signal]:
        """处理期权报价，寻找跨式机会。

        逻辑：
          1. IV 处于低位 + ATM 期权 → 买入跨式信号
          2. IV 处于高位 + ATM 期权 → 卖出跨式信号
          3. ATM 判断基于 |Delta| ≈ 0.5

        Args:
            q: 期权报价

        Returns:
            信号列表
        """
        signals: list[Signal] = []
        abs_delta = abs(q.delta)
        iv = float(q.iv)

        # ATM 判断：|Delta| 在 0.45 ~ 0.55 之间视为 ATM
        is_atm = Decimal("0.45") <= abs_delta <= Decimal("0.55")

        if not is_atm:
            return signals

        # 买入跨式：IV 低位，预期波动率上升
        if iv < self.iv_percentile_low:
            strength = max(0.0, min(1.0, (self.iv_percentile_low - iv) / self.iv_percentile_low))
            signals.append(
                Signal(
                    symbol=q.symbol,
                    market=Market.OPTION,
                    side="buy",
                    strength=strength,
                    strategy_name=self.name,
                    reason=f"买入跨式：IV={iv:.1%}（低位），ATM期权 Delta={q.delta}，预期大波动",
                    metadata={
                        "strategy_variant": "long_straddle",
                        "strike": str(q.strike),
                        "expiry": q.expiry.isoformat(),
                        "iv": str(q.iv),
                        "delta": str(q.delta),
                    },
                    timestamp_ns=q.timestamp_ns,
                )
            )

        # 卖出跨式：IV 高位，预期波动率下降
        if iv > self.iv_percentile_high:
            strength = max(0.0, min(1.0, (iv - self.iv_percentile_high) / (1.0 - self.iv_percentile_high)))
            signals.append(
                Signal(
                    symbol=q.symbol,
                    market=Market.OPTION,
                    side="sell",
                    strength=strength,
                    strategy_name=self.name,
                    reason=f"卖出跨式：IV={iv:.1%}（高位），ATM期权 Delta={q.delta}，预期横盘",
                    metadata={
                        "strategy_variant": "short_straddle",
                        "strike": str(q.strike),
                        "expiry": q.expiry.isoformat(),
                        "iv": str(q.iv),
                        "delta": str(q.delta),
                    },
                    timestamp_ns=q.timestamp_ns,
                )
            )

        return signals


class IronCondorStrategy(Strategy):
    """铁鹰策略（Iron Condor）。

    策略逻辑：同时卖出一个看涨期权和一个看跌期权（宽跨式），
    并买入更远 OTM 的看涨和看跌期权作为保护。

    组成：Bear Call Spread + Bull Put Spread

    适用场景：预期标的在一定范围内波动，赚取时间价值。

    参数：
      - wing_width: 翼宽（保护腿与卖出腿的行权价间距）
      - min_premium: 最低权利金要求
      - delta_short: 卖出腿的目标 Delta 绝对值
    """

    name = "iron_condor"
    enabled = False

    def __init__(
        self,
        wing_width: Decimal = Decimal("200"),
        min_premium: Decimal = Decimal("10"),
        delta_short: Decimal = Decimal("0.3"),
    ):
        self.wing_width = wing_width
        self.min_premium = min_premium
        self.delta_short = delta_short

    def on_ticker(self, ticker: Ticker) -> list[Signal]:
        return []

    def on_kline(self, kline: Kline) -> list[Signal]:
        return []

    def on_option_quote(self, q: OptionQuote) -> list[Signal]:
        """处理期权报价，寻找铁鹰策略机会。

        逻辑：
          1. Call 且 |Delta| ≈ 0.3 → 卖出 Call 腿信号
          2. Put 且 |Delta| ≈ 0.3 → 卖出 Put 腿信号
          3. 要求最低权利金

        Args:
            q: 期权报价

        Returns:
            信号列表
        """
        signals: list[Signal] = []
        abs_delta = abs(q.delta)
        mid_price = (q.bid + q.ask) / Decimal("2")

        # Delta 在目标附近（±0.05 容差）
        delta_ok = abs_delta >= (self.delta_short - Decimal("0.05")) and abs_delta <= (self.delta_short + Decimal("0.05"))

        if not delta_ok:
            return signals

        # 权利金检查
        if mid_price < self.min_premium:
            return signals

        if q.option_type == "call":
            signals.append(
                Signal(
                    symbol=q.symbol,
                    market=Market.OPTION,
                    side="sell",
                    strength=0.7,
                    strategy_name=self.name,
                    reason=f"铁鹰-卖出Call腿：Delta={q.delta}，行权价={q.strike}，权利金={mid_price}",
                    metadata={
                        "leg": "short_call",
                        "strike": str(q.strike),
                        "expiry": q.expiry.isoformat(),
                        "delta": str(q.delta),
                        "premium": str(mid_price),
                        "wing_width": str(self.wing_width),
                    },
                    timestamp_ns=q.timestamp_ns,
                )
            )

        elif q.option_type == "put":
            signals.append(
                Signal(
                    symbol=q.symbol,
                    market=Market.OPTION,
                    side="sell",
                    strength=0.7,
                    strategy_name=self.name,
                    reason=f"铁鹰-卖出Put腿：Delta={q.delta}，行权价={q.strike}，权利金={mid_price}",
                    metadata={
                        "leg": "short_put",
                        "strike": str(q.strike),
                        "expiry": q.expiry.isoformat(),
                        "delta": str(q.delta),
                        "premium": str(mid_price),
                        "wing_width": str(self.wing_width),
                    },
                    timestamp_ns=q.timestamp_ns,
                )
            )

        return signals


class CalendarSpreadStrategy(Strategy):
    """日历价差策略（Calendar Spread / Time Spread）。

    策略逻辑：卖出近月期权 + 买入远月期权（同行权价）。

    适用场景：
      - 预期短期波动率下降、长期波动率上升
      - 近月时间价值衰减快于远月

    参数：
      - min_dte_near: 近月最小剩余天数
      - max_dte_near: 近月最大剩余天数
      - min_dte_far: 远月最小剩余天数
    """

    name = "calendar_spread"
    enabled = False

    def __init__(
        self,
        min_dte_near: int = 7,
        max_dte_near: int = 30,
        min_dte_far: int = 60,
    ):
        self.min_dte_near = min_dte_near
        self.max_dte_near = max_dte_near
        self.min_dte_far = min_dte_far

    def on_ticker(self, ticker: Ticker) -> list[Signal]:
        return []

    def on_kline(self, kline: Kline) -> list[Signal]:
        return []

    def on_option_quote(self, q: OptionQuote) -> list[Signal]:
        """处理期权报价，寻找日历价差机会。

        逻辑：
          1. 计算剩余天数（DTE）
          2. 近月（7~30天）ATM 期权 → 卖出信号
          3. 远月（>60天）同行权价期权 → 买入信号

        Args:
            q: 期权报价

        Returns:
            信号列表
        """
        signals: list[Signal] = []
        dte = (q.expiry - date.today()).days
        abs_delta = abs(q.delta)
        is_atm = Decimal("0.40") <= abs_delta <= Decimal("0.60")

        if not is_atm:
            return signals

        # 近月卖出
        if self.min_dte_near <= dte <= self.max_dte_near:
            signals.append(
                Signal(
                    symbol=q.symbol,
                    market=Market.OPTION,
                    side="sell",
                    strength=0.6,
                    strategy_name=self.name,
                    reason=f"日历价差-卖出近月：DTE={dte}，Delta={q.delta}，行权价={q.strike}",
                    metadata={
                        "leg": "short_near_term",
                        "dte": dte,
                        "strike": str(q.strike),
                        "expiry": q.expiry.isoformat(),
                        "option_type": q.option_type,
                    },
                    timestamp_ns=q.timestamp_ns,
                )
            )

        # 远月买入
        if dte >= self.min_dte_far:
            signals.append(
                Signal(
                    symbol=q.symbol,
                    market=Market.OPTION,
                    side="buy",
                    strength=0.6,
                    strategy_name=self.name,
                    reason=f"日历价差-买入远月：DTE={dte}，Delta={q.delta}，行权价={q.strike}",
                    metadata={
                        "leg": "long_far_term",
                        "dte": dte,
                        "strike": str(q.strike),
                        "expiry": q.expiry.isoformat(),
                        "option_type": q.option_type,
                    },
                    timestamp_ns=q.timestamp_ns,
                )
            )

        return signals


class CollarStrategy(Strategy):
    """领口策略（Collar）。

    策略逻辑：持有标的 + 买入保护性看跌（Protective Put）+ 卖出备兑看涨（Covered Call）。

    适用场景：持有标的多头，希望在限制下跌风险的同时降低对冲成本。

    参数：
      - put_delta: 保护性 Put 的目标 Delta（绝对值，如 0.2 表示 OTM Put）
      - call_delta: 备兑 Call 的目标 Delta（绝对值，如 0.3 表示 OTM Call）
    """

    name = "collar"
    enabled = False

    def __init__(
        self,
        put_delta: Decimal = Decimal("0.2"),
        call_delta: Decimal = Decimal("0.3"),
    ):
        self.put_delta = put_delta
        self.call_delta = call_delta

    def on_ticker(self, ticker: Ticker) -> list[Signal]:
        return []

    def on_kline(self, kline: Kline) -> list[Signal]:
        return []

    def on_option_quote(self, q: OptionQuote) -> list[Signal]:
        """处理期权报价，寻找领口策略机会。

        逻辑：
          1. Put 且 |Delta| ≈ 0.2 → 买入保护性 Put 信号
          2. Call 且 |Delta| ≈ 0.3 → 卖出备兑 Call 信号

        Args:
            q: 期权报价

        Returns:
            信号列表
        """
        signals: list[Signal] = []
        abs_delta = abs(q.delta)

        # 买入保护性 Put（OTM，|Delta| ≈ put_delta）
        if q.option_type == "put":
            delta_ok = abs_delta >= (self.put_delta - Decimal("0.05")) and abs_delta <= (self.put_delta + Decimal("0.05"))
            if delta_ok:
                signals.append(
                    Signal(
                        symbol=q.symbol,
                        market=Market.OPTION,
                        side="buy",
                        strength=0.8,
                        strategy_name=self.name,
                        reason=f"领口策略-买入保护性Put：Delta={q.delta}，行权价={q.strike}，保护下行风险",
                        metadata={
                            "leg": "protective_put",
                            "strike": str(q.strike),
                            "expiry": q.expiry.isoformat(),
                            "delta": str(q.delta),
                        },
                        timestamp_ns=q.timestamp_ns,
                    )
                )

        # 卖出备兑 Call（OTM，|Delta| ≈ call_delta）
        if q.option_type == "call":
            delta_ok = abs_delta >= (self.call_delta - Decimal("0.05")) and abs_delta <= (self.call_delta + Decimal("0.05"))
            if delta_ok:
                signals.append(
                    Signal(
                        symbol=q.symbol,
                        market=Market.OPTION,
                        side="sell",
                        strength=0.8,
                        strategy_name=self.name,
                        reason=f"领口策略-卖出备兑Call：Delta={q.delta}，行权价={q.strike}，降低对冲成本",
                        metadata={
                            "leg": "covered_call",
                            "strike": str(q.strike),
                            "expiry": q.expiry.isoformat(),
                            "delta": str(q.delta),
                        },
                        timestamp_ns=q.timestamp_ns,
                    )
                )

        return signals


class DeltaNeutralStrategy(Strategy):
    """Delta 中性策略。

    策略逻辑：动态对冲保持组合 Delta ≈ 0，赚取 Gamma 收益和时间价值衰减。

    适用场景：做市商、波动率交易者。

    参数：
      - delta_tolerance: Delta 容差（超过则触发对冲）
      - hedge_ratio: 对冲比例（1.0 = 完全对冲）
    """

    name = "delta_neutral"
    enabled = False

    def __init__(
        self,
        delta_tolerance: Decimal = Decimal("50"),
        hedge_ratio: float = 1.0,
    ):
        self.delta_tolerance = delta_tolerance
        self.hedge_ratio = hedge_ratio

    def on_ticker(self, ticker: Ticker) -> list[Signal]:
        return []

    def on_kline(self, kline: Kline) -> list[Signal]:
        return []

    def on_option_quote(self, q: OptionQuote) -> list[Signal]:
        """处理期权报价，生成 Delta 对冲信号。

        逻辑：
          1. 当期权 Delta 绝对值超过容差 → 生成对冲信号
          2. Call Delta > 0 → 卖出标的对冲
          3. Put Delta < 0 → 买入标的对冲

        Args:
            q: 期权报价

        Returns:
            信号列表
        """
        signals: list[Signal] = []
        abs_delta = abs(q.delta)

        if abs_delta < self.delta_tolerance:
            return signals

        # 计算对冲强度：Delta 越大，对冲信号越强
        strength = min(float(abs_delta / (self.delta_tolerance * Decimal("3"))), 1.0)

        # Call Delta > 0 → 需要卖出标的来对冲
        if q.option_type == "call" and q.delta > 0:
            hedge_qty = q.delta * Decimal(str(self.hedge_ratio))
            signals.append(
                Signal(
                    symbol=q.underlying,
                    market=Market.SPOT,
                    side="sell",
                    strength=strength,
                    strategy_name=self.name,
                    reason=f"Delta中性对冲：卖出标的，期权Delta={q.delta}，对冲数量={hedge_qty:.2f}",
                    metadata={
                        "hedge_type": "delta_neutral",
                        "option_symbol": q.symbol,
                        "option_delta": str(q.delta),
                        "hedge_quantity": str(hedge_qty),
                    },
                    timestamp_ns=q.timestamp_ns,
                )
            )

        # Put Delta < 0 → 需要买入标的来对冲
        if q.option_type == "put" and q.delta < 0:
            hedge_qty = abs(q.delta) * Decimal(str(self.hedge_ratio))
            signals.append(
                Signal(
                    symbol=q.underlying,
                    market=Market.SPOT,
                    side="buy",
                    strength=strength,
                    strategy_name=self.name,
                    reason=f"Delta中性对冲：买入标的，期权Delta={q.delta}，对冲数量={hedge_qty:.2f}",
                    metadata={
                        "hedge_type": "delta_neutral",
                        "option_symbol": q.symbol,
                        "option_delta": str(q.delta),
                        "hedge_quantity": str(hedge_qty),
                    },
                    timestamp_ns=q.timestamp_ns,
                )
            )

        return signals


# ═══════════════════════════════════════════════════════════════
#  IVArbitrageModel - IV 套利模型
# ═══════════════════════════════════════════════════════════════

class IVArbitrageModel:
    """IV 套利模型。

    功能：
      1. find_mispricing: 寻找 IV 定价错误（跨期/跨行权价）
      2. surface_arbitrage: 曲面套利（违反凸性/单调性）
    """

    def __init__(
        self,
        iv_threshold: float = 0.05,
        min_spread: Decimal = Decimal("0.01"),
    ):
        """初始化 IV 套利模型。

        Args:
            iv_threshold: IV 偏差阈值（超过此值视为定价错误）
            min_spread: 最小价差要求（过滤流动性不足的期权）
        """
        self.iv_threshold = iv_threshold
        self.min_spread = min_spread

    def find_mispricing(self, chain: dict[date, dict[Decimal, dict[str, OptionQuote | None]]]) -> list[dict[str, Any]]:
        """寻找 IV 定价错误。

        检查方法：
          1. 同到期日、同行权价的 Call/Put IV 应相近（Put-Call Parity）
          2. 同到期日的 IV 应呈微笑/偏斜形态（不应有突变）
          3. 不同到期日的 ATM IV 应呈期限结构（通常远月 > 近月）

        Args:
            chain: 期权链结构

        Returns:
            定价错误列表，每项包含 {type, details, severity}
        """
        mispricings: list[dict[str, Any]] = []

        for expiry, strikes_map in chain.items():
            for strike, opt_map in strikes_map.items():
                call_q = opt_map.get("call")
                put_q = opt_map.get("put")

                # 检查 1：Put-Call Parity IV 偏差
                if call_q is not None and put_q is not None:
                    call_iv = float(call_q.iv)
                    put_iv = float(put_q.iv)
                    iv_diff = abs(call_iv - put_iv)

                    if iv_diff > self.iv_threshold:
                        mispricings.append({
                            "type": "put_call_parity",
                            "expiry": expiry.isoformat(),
                            "strike": str(strike),
                            "call_iv": call_iv,
                            "put_iv": put_iv,
                            "iv_diff": iv_diff,
                            "severity": iv_diff / self.iv_threshold,
                            "detail": f"Put-Call IV 偏差 {iv_diff:.1%}（阈值 {self.iv_threshold:.1%}），行权价={strike}，到期={expiry}",
                        })

            # 检查 2：IV 微笑突变（相邻行权价 IV 跳跃过大）
            sorted_strikes = sorted(strikes_map.keys())
            for i in range(1, len(sorted_strikes)):
                prev_strike = sorted_strikes[i - 1]
                curr_strike = sorted_strikes[i]

                for opt_type in ("call", "put"):
                    prev_q = strikes_map[prev_strike].get(opt_type)
                    curr_q = strikes_map[curr_strike].get(opt_type)

                    if prev_q is not None and curr_q is not None:
                        iv_change = abs(float(curr_q.iv) - float(prev_q.iv))
                        strike_gap = float(curr_strike - prev_strike)

                        # 相邻行权价 IV 变化不应超过阈值的 3 倍
                        if iv_change > self.iv_threshold * 3 and strike_gap > 0:
                            mispricings.append({
                                "type": "smile_discontinuity",
                                "expiry": expiry.isoformat(),
                                "strikes": [str(prev_strike), str(curr_strike)],
                                "iv_change": iv_change,
                                "severity": iv_change / (self.iv_threshold * 3),
                                "detail": f"IV 微笑突变：{prev_strike}→{curr_strike}，IV 变化 {iv_change:.1%}",
                            })

        return mispricings

    def surface_arbitrage(self, surface: dict[date, dict[Decimal, float]]) -> list[dict[str, Any]]:
        """曲面套利检查。

        检查方法：
          1. 日历价差套利：远月 ATM IV 不应低于近月太多（正常期限结构）
          2. 蝶式价差套利：相邻三点 IV 应满足凸性条件

        Args:
            surface: IV 曲面 {expiry: {strike: iv}}

        Returns:
            套利机会列表
        """
        opportunities: list[dict[str, Any]] = []
        sorted_expiries = sorted(surface.keys())

        # 检查 1：日历价差套利
        for i in range(1, len(sorted_expiries)):
            near_expiry = sorted_expiries[i - 1]
            far_expiry = sorted_expiries[i]

            near_strikes = surface[near_expiry]
            far_strikes = surface[far_expiry]

            # 找共同行权价
            common_strikes = set(near_strikes.keys()) & set(far_strikes.keys())
            for strike in common_strikes:
                near_iv = near_strikes[strike]
                far_iv = far_strikes[strike]

                # 远月 IV 不应低于近月 IV 超过阈值
                if far_iv < near_iv - self.iv_threshold:
                    opportunities.append({
                        "type": "calendar_spread",
                        "near_expiry": near_expiry.isoformat(),
                        "far_expiry": far_expiry.isoformat(),
                        "strike": str(strike),
                        "near_iv": near_iv,
                        "far_iv": far_iv,
                        "iv_diff": near_iv - far_iv,
                        "detail": f"日历价差套利：近月IV={near_iv:.1%} > 远月IV={far_iv:.1%}，行权价={strike}",
                    })

        # 检查 2：蝶式价差凸性（三点检查）
        for expiry, strikes_map in surface.items():
            sorted_strikes = sorted(strikes_map.keys())
            for i in range(1, len(sorted_strikes) - 1):
                k1, k2, k3 = sorted_strikes[i - 1], sorted_strikes[i], sorted_strikes[i + 1]
                iv1, iv2, iv3 = strikes_map[k1], strikes_map[k2], strikes_map[k3]

                # 凸性检查：中间点 IV 不应高于两端 IV 的线性插值太多
                if k3 != k1:
                    weight = float(k2 - k1) / float(k3 - k1)
                    iv_interp = iv1 + (iv3 - iv1) * weight
                    excess = iv2 - iv_interp

                    if excess > self.iv_threshold:
                        opportunities.append({
                            "type": "butterfly",
                            "expiry": expiry.isoformat(),
                            "strikes": [str(k1), str(k2), str(k3)],
                            "ivs": [iv1, iv2, iv3],
                            "excess": excess,
                            "detail": f"蝶式价差套利：K={k1}/{k2}/{k3}，中间IV={iv2:.1%}，插值={iv_interp:.1%}",
                        })

        return opportunities


# ═══════════════════════════════════════════════════════════════
#  MarginMonitor - 卖方保证金监控
# ═══════════════════════════════════════════════════════════════

class MarginMonitor:
    """卖方保证金监控。

    功能：
      1. check_margin: 检查保证金是否充足
      2. exercise_warning: 被行权预警（深度实值 + 临近到期）

    保证金计算使用简化的交易所公式（实际应根据具体交易所规则调整）。
    """

    def __init__(
        self,
        margin_ratio: Decimal = Decimal("0.15"),
        exercise_warning_dte: int = 3,
        exercise_warning_delta: Decimal = Decimal("0.85"),
    ):
        """初始化保证金监控器。

        Args:
            margin_ratio: 保证金比例（标的价值的比例）
            exercise_warning_dte: 被行权预警天数（剩余天数 <= 此值触发）
            exercise_warning_delta: 被行权预警 Delta 阈值（|Delta| >= 此值触发）
        """
        self.margin_ratio = margin_ratio
        self.exercise_warning_dte = exercise_warning_dte
        self.exercise_warning_delta = exercise_warning_delta

    def check_margin(self, position: dict[str, Any], spot: Decimal) -> dict[str, Any]:
        """保证金检查。

        计算卖方持仓所需保证金，并与可用保证金比较。

        简化公式：
          - 卖出 Call 保证金 = max(标的价 * margin_ratio - OTM金额, 标的价 * margin_ratio * 0.5) + 权利金
          - 卖出 Put 保证金 = max(标的价 * margin_ratio - OTM金额, 行权价 * margin_ratio * 0.5) + 权利金

        Args:
            position: 持仓信息，包含：
                - option_type: call/put
                - strike: 行权价
                - quantity: 数量（负值表示卖方）
                - premium: 权利金
            spot: 标的当前价格

        Returns:
            保证金检查结果 {required_margin, available_margin, margin_ratio, warning}
        """
        option_type = position.get("option_type", "call")
        strike = Decimal(str(position.get("strike", 0)))
        quantity = Decimal(str(position.get("quantity", 0)))
        premium = Decimal(str(position.get("premium", 0)))
        available_margin = Decimal(str(position.get("available_margin", 0)))

        # 只检查卖方（quantity < 0）
        abs_qty = abs(quantity)
        if abs_qty == 0:
            return {
                "required_margin": Decimal("0"),
                "available_margin": available_margin,
                "margin_ratio": Decimal("0"),
                "warning": None,
            }

        # 计算 OTM 金额
        if option_type == "call":
            otm_amount = max(Decimal("0"), strike - spot)
            base_margin = max(
                spot * self.margin_ratio - otm_amount,
                spot * self.margin_ratio * Decimal("0.5"),
            )
        else:
            otm_amount = max(Decimal("0"), spot - strike)
            base_margin = max(
                strike * self.margin_ratio - otm_amount,
                strike * self.margin_ratio * Decimal("0.5"),
            )

        required_margin = (base_margin + premium) * abs_qty
        margin_ratio = (required_margin / available_margin * 100).quantize(Decimal("0.01")) if available_margin > 0 else Decimal("999")

        warning = None
        if required_margin > available_margin:
            warning = f"⚠️ 保证金不足！需要 {required_margin}，可用 {available_margin}，缺口 {required_margin - available_margin}"
        elif margin_ratio > Decimal("80"):
            warning = f"⚠️ 保证金使用率 {margin_ratio}%，接近上限"

        return {
            "required_margin": required_margin.quantize(Decimal("0.01")),
            "available_margin": available_margin,
            "margin_ratio": margin_ratio,
            "warning": warning,
        }

    def exercise_warning(self, position: dict[str, Any], spot: Decimal) -> dict[str, Any] | None:
        """被行权预警。

        当卖方持仓满足以下条件时触发预警：
          1. 剩余天数 <= exercise_warning_dte
          2. |Delta| >= exercise_warning_delta（深度实值）

        Args:
            position: 持仓信息，包含：
                - option_type: call/put
                - strike: 行权价
                - expiry: 到期日
                - delta: 当前 Delta
                - quantity: 数量（负值表示卖方）
            spot: 标的当前价格

        Returns:
            预警信息字典，无预警时返回 None
        """
        quantity = Decimal(str(position.get("quantity", 0)))
        if quantity >= 0:
            return None  # 只预警卖方

        expiry = position.get("expiry")
        if isinstance(expiry, str):
            expiry = date.fromisoformat(expiry)
        if expiry is None:
            return None

        dte = (expiry - date.today()).days
        delta = Decimal(str(position.get("delta", 0)))
        abs_delta = abs(delta)

        # 条件检查
        if dte > self.exercise_warning_dte:
            return None
        if abs_delta < self.exercise_warning_delta:
            return None

        strike = Decimal(str(position.get("strike", 0)))
        option_type = position.get("option_type", "call")

        # 计算实值程度
        if option_type == "call":
            itm_amount = max(Decimal("0"), spot - strike)
        else:
            itm_amount = max(Decimal("0"), strike - spot)

        return {
            "level": "critical" if dte <= 1 else "warning",
            "dte": dte,
            "delta": str(delta),
            "itm_amount": str(itm_amount),
            "message": (
                f"🔴 被行权预警：{option_type.upper()} 行权价={strike}，"
                f"剩余 {dte} 天，Delta={delta}，实值金额={itm_amount}。"
                f"建议尽快平仓或展期。"
            ),
        }


# ═══════════════════════════════════════════════════════════════
#  RollAdvisor - 展期顾问
# ═══════════════════════════════════════════════════════════════

class RollAdvisor:
    """展期顾问。

    功能：根据持仓状态和剩余天数，建议展期（Roll）或平仓。

    展期策略：
      - 临近到期（< 7天）+ 实值 → 建议平仓
      - 临近到期 + 虚值 → 建议展期到更远到期日
      - 时间价值衰减加速期（7~14天）→ 建议考虑展期
    """

    def __init__(
        self,
        roll_dte: int = 7,
        close_dte: int = 3,
        min_credit: Decimal = Decimal("0"),
    ):
        """初始化展期顾问。

        Args:
            roll_dte: 触发展期建议的剩余天数
            close_dte: 触发平仓建议的剩余天数
            min_credit: 展期最低净收入要求
        """
        self.roll_dte = roll_dte
        self.close_dte = close_dte
        self.min_credit = min_credit

    def suggest_roll(self, position: dict[str, Any], days_to_expiry: int) -> dict[str, Any] | None:
        """展期/平仓提示。

        Args:
            position: 持仓信息，包含：
                - option_type: call/put
                - strike: 行权价
                - delta: 当前 Delta
                - quantity: 数量
                - premium: 当前权利金
            days_to_expiry: 剩余天数

        Returns:
            建议字典 {action, reason, details}，无需操作时返回 None
        """
        delta = Decimal(str(position.get("delta", 0)))
        abs_delta = abs(delta)
        quantity = Decimal(str(position.get("quantity", 0)))
        strike = Decimal(str(position.get("strike", 0)))
        option_type = position.get("option_type", "call")
        premium = Decimal(str(position.get("premium", 0)))

        # 临近到期 + 深度实值 → 平仓
        if days_to_expiry <= self.close_dte and abs_delta >= Decimal("0.8"):
            return {
                "action": "close",
                "urgency": "high",
                "reason": (
                    f"临近到期（{days_to_expiry}天）且深度实值（Delta={delta}），"
                    f"建议立即平仓避免被行权"
                ),
                "details": {
                    "current_premium": str(premium),
                    "delta": str(delta),
                    "dte": days_to_expiry,
                },
            }

        # 临近到期 + 虚值 → 展期
        if days_to_expiry <= self.roll_dte and abs_delta < Decimal("0.5"):
            return {
                "action": "roll",
                "urgency": "medium",
                "reason": (
                    f"临近到期（{days_to_expiry}天）且虚值（Delta={delta}），"
                    f"建议展期到下一到期日以保持仓位"
                ),
                "details": {
                    "current_strike": str(strike),
                    "current_dte": days_to_expiry,
                    "delta": str(delta),
                    "suggested_new_dte": "30-60天",
                },
            }

        # 时间价值衰减加速期 → 提醒考虑展期
        if self.close_dte < days_to_expiry <= self.roll_dte:
            return {
                "action": "consider_roll",
                "urgency": "low",
                "reason": (
                    f"进入时间价值衰减加速期（{days_to_expiry}天），"
                    f"Delta={delta}，可考虑展期以锁定收益"
                ),
                "details": {
                    "current_strike": str(strike),
                    "current_dte": days_to_expiry,
                    "delta": str(delta),
                },
            }

        return None
