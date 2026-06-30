"""
ONE量化 - 量价结构策略族

基于成交量分布、市场轮廓和 VWAP 家族的量价分析框架。

包含：
  - VPVR: 成交量分布（Volume Profile Visible Range）— POC/VAH/VAL/HVN/LVN
  - TPOChart: 市场轮廓 TPO（Time Price Opportunity）— 字母图/价值区
  - VWAPFamily: VWAP 家族 — 锚定VWAP/标准差带/机构成本线

全中文注释，Decimal 精确计算。
"""

from __future__ import annotations

from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal

from one_quant.core.types import Kline

# ──────────────────────────── 成交量分布 VPVR ────────────────────────────


class VPVR:
    """成交量分布（Volume Profile Visible Range）。

    将成交量按价格区间聚合，识别：
    - POC (Point of Control): 成交量最大的价格水平 → 最公允的价格
    - VAH (Value Area High): 价值区上沿 → 70% 成交量的上边界
    - VAL (Value Area Low): 价值区下沿 → 70% 成交量的下边界
    - HVN (High Volume Node): 高成交量节点 → 支撑/压力位
    - LVN (Low Volume Node): 低成交量节点 → 价格快速穿越区域

    Args:
        bins: 价格分箱数量（默认 50）
    """

    def __init__(self, bins: int = 50) -> None:
        if bins < 5:
            raise ValueError("分箱数量必须 >= 5")
        self._bins = bins

    def compute(self, klines: list[Kline], bins: int | None = None) -> dict:
        """计算成交量分布。

        Args:
            klines: K线序列
            bins: 价格分箱数量（覆盖默认值）

        Returns:
            {
                "poc": str,          # Point of Control 价格
                "vah": str,          # Value Area High
                "val": str,          # Value Area Low
                "hvn": [str, ...],   # High Volume Nodes
                "lvn": [str, ...],   # Low Volume Nodes
                "profile": {price_str: volume_str, ...},  # 完整分布
                "total_volume": str,
            }
        """
        if not klines:
            return {}

        num_bins = bins or self._bins

        # 确定价格范围
        all_highs = [k.high for k in klines]
        all_lows = [k.low for k in klines]
        price_min = min(all_lows)
        price_max = max(all_highs)

        if price_min == price_max:
            return {
                "poc": str(price_min),
                "vah": str(price_min),
                "val": str(price_min),
                "hvn": [],
                "lvn": [],
                "profile": {str(price_min): str(sum(k.volume for k in klines))},
                "total_volume": str(sum(k.volume for k in klines)),
            }

        # 创建价格分箱
        bin_size = (price_max - price_min) / Decimal(num_bins)
        if bin_size == 0:
            return {}

        # 成交量分布：{bin_price: total_volume}
        volume_profile: dict[Decimal, Decimal] = defaultdict(lambda: Decimal("0"))

        for k in klines:
            # 将每根K线的成交量按价格区间分配
            # 简化处理：假设成交量在 [low, high] 区间均匀分布
            k_low = k.low
            k_high = k.high
            k_range = k_high - k_low

            if k_range == 0:
                # 十字星：成交量全部归入该价格
                bin_idx = int((k_low - price_min) / bin_size)
                bin_idx = min(bin_idx, num_bins - 1)
                bin_price = price_min + bin_size * Decimal(bin_idx) + bin_size / 2
                volume_profile[bin_price] += k.volume
            else:
                # 将成交量分配到涉及的分箱
                low_idx = int((k_low - price_min) / bin_size)
                high_idx = int((k_high - price_min) / bin_size)
                low_idx = max(0, min(low_idx, num_bins - 1))
                high_idx = max(0, min(high_idx, num_bins - 1))

                span = high_idx - low_idx + 1
                vol_per_bin = k.volume / Decimal(span)

                for idx in range(low_idx, high_idx + 1):
                    bin_price = price_min + bin_size * Decimal(idx) + bin_size / 2
                    volume_profile[bin_price] += vol_per_bin

        if not volume_profile:
            return {}

        # POC: 成交量最大的价格
        poc = max(volume_profile.keys(), key=lambda p: volume_profile[p])

        # 计算 Value Area（70% 成交量区域）
        total_volume = sum(volume_profile.values())
        va_target = total_volume * Decimal("0.70")

        # 从 POC 向两侧扩展，直到覆盖 70% 成交量
        sorted_prices = sorted(volume_profile.keys())
        poc_idx = sorted_prices.index(poc)

        va_volume = volume_profile[poc]
        left_idx = poc_idx
        right_idx = poc_idx

        while va_volume < va_target and (left_idx > 0 or right_idx < len(sorted_prices) - 1):
            # 比较左右两侧的成交量，选择较大的一侧扩展
            left_vol = volume_profile[sorted_prices[left_idx - 1]] if left_idx > 0 else Decimal("0")
            right_vol = (
                volume_profile[sorted_prices[right_idx + 1]]
                if right_idx < len(sorted_prices) - 1
                else Decimal("0")
            )

            if left_vol >= right_vol and left_idx > 0:
                left_idx -= 1
                va_volume += volume_profile[sorted_prices[left_idx]]
            elif right_idx < len(sorted_prices) - 1:
                right_idx += 1
                va_volume += volume_profile[sorted_prices[right_idx]]
            else:
                break

        val = sorted_prices[left_idx]
        vah = sorted_prices[right_idx]

        # HVN: 高成交量节点（前 20% 的分箱）
        sorted_by_vol = sorted(volume_profile.items(), key=lambda x: x[1], reverse=True)
        hvn_count = max(1, len(sorted_by_vol) // 5)
        hvn = [str(p) for p, _ in sorted_by_vol[:hvn_count]]

        # LVN: 低成交量节点（后 20% 的分箱）
        lvn = [str(p) for p, _ in sorted_by_vol[-hvn_count:]]

        return {
            "poc": str(poc.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "vah": str(vah.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "val": str(val.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "hvn": hvn,
            "lvn": lvn,
            "profile": {
                str(p.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)): str(
                    v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                )
                for p, v in sorted(volume_profile.items())
            },
            "total_volume": str(total_volume.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        }


# ──────────────────────────── 市场轮廓 TPO ────────────────────────────


class TPOChart:
    """市场轮廓 TPO（Time Price Opportunity）。

    TPO 以时间维度分析价格分布：
    - 每个时间窗口用字母标记（A, B, C, ...）
    - 价格区间内出现的字母数 = TPO 计数
    - 价值区 = TPO 计数最多的 70% 区域
    - 单一打印 = 只出现一次的字母（可能代表机构行为）

    Args:
        interval: TPO 时间窗口（默认 "30m"）
    """

    # 时间窗口映射（秒）
    INTERVAL_SECONDS = {
        "1m": 60,
        "5m": 300,
        "15m": 900,
        "30m": 1800,
        "1h": 3600,
        "4h": 14400,
    }

    LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"

    def __init__(self, interval: str = "30m") -> None:
        if interval not in self.INTERVAL_SECONDS:
            raise ValueError(
                f"不支持的时间窗口: {interval}，支持: {list(self.INTERVAL_SECONDS.keys())}"
            )
        self._interval = interval
        self._interval_sec = self.INTERVAL_SECONDS[interval]

    def compute(self, klines: list[Kline], bins: int = 20) -> dict:
        """计算 TPO 市场轮廓。

        Args:
            klines: K线序列（应为较小周期，如 1m 或 5m）
            bins: 价格分箱数量

        Returns:
            {
                "letters": {price_str: "ABC...", ...},  # 每个价格区间的字母
                "tpo_counts": {price_str: int, ...},     # 每个价格区间的 TPO 计数
                "poc": str,                               # TPO POC
                "vah": str,                               # Value Area High
                "val": str,                               # Value Area Low
                "single_prints": [str, ...],              # 单一打印价格
                "opening_range": {"high": str, "low": str},  # 开盘区间
            }
        """
        if not klines:
            return {}

        # 确定价格范围
        all_highs = [k.high for k in klines]
        all_lows = [k.low for k in klines]
        price_min = min(all_lows)
        price_max = max(all_highs)

        if price_min == price_max:
            return {}

        bin_size = (price_max - price_min) / Decimal(bins)

        # 将K线按时间窗口分组，每组分配一个字母
        # 假设K线按时间排序，每 interval_sec 秒一个字母
        letter_idx = 0
        window_start_ns = klines[0].timestamp_ns
        window_letter = self.LETTERS[0]

        # {bin_price: set of letters}
        tpo_map: dict[Decimal, set[str]] = defaultdict(set)

        for k in klines:
            # 检查是否需要切换到下一个时间窗口
            elapsed_ns = k.timestamp_ns - window_start_ns
            if elapsed_ns >= self._interval_sec * 1_000_000_000:
                letter_idx += 1
                window_start_ns = k.timestamp_ns
                if letter_idx < len(self.LETTERS):
                    window_letter = self.LETTERS[letter_idx]
                else:
                    window_letter = f"W{letter_idx}"  # 超过字母表

            # 将该K线的价格区间映射到分箱
            low_idx = max(0, int((k.low - price_min) / bin_size))
            high_idx = min(bins - 1, int((k.high - price_min) / bin_size))

            for idx in range(low_idx, high_idx + 1):
                bin_price = price_min + bin_size * Decimal(idx) + bin_size / 2
                tpo_map[bin_price].add(window_letter)

        if not tpo_map:
            return {}

        # TPO 计数
        tpo_counts = {p: len(letters) for p, letters in tpo_map.items()}

        # POC: TPO 计数最多的价格
        poc = max(tpo_counts.keys(), key=lambda p: tpo_counts[p])

        # Value Area（70% TPO）
        total_tpo = sum(tpo_counts.values())
        va_target = total_tpo * 0.7

        sorted_prices = sorted(tpo_counts.keys())
        poc_idx = sorted_prices.index(poc)
        va_tpo = tpo_counts[poc]
        left_idx = poc_idx
        right_idx = poc_idx

        while va_tpo < va_target and (left_idx > 0 or right_idx < len(sorted_prices) - 1):
            left_tpo = tpo_counts[sorted_prices[left_idx - 1]] if left_idx > 0 else 0
            right_tpo = (
                tpo_counts[sorted_prices[right_idx + 1]]
                if right_idx < len(sorted_prices) - 1
                else 0
            )

            if left_tpo >= right_tpo and left_idx > 0:
                left_idx -= 1
                va_tpo += tpo_counts[sorted_prices[left_idx]]
            elif right_idx < len(sorted_prices) - 1:
                right_idx += 1
                va_tpo += tpo_counts[sorted_prices[right_idx]]
            else:
                break

        val = sorted_prices[left_idx]
        vah = sorted_prices[right_idx]

        # 单一打印（TPO 计数为 1 的价格）
        single_prints = [str(p) for p, c in tpo_counts.items() if c == 1]

        # 开盘区间（第一个字母覆盖的价格范围）
        opening_prices = [p for p, letters in tpo_map.items() if self.LETTERS[0] in letters]
        opening_range = {}
        if opening_prices:
            opening_range = {
                "high": str(max(opening_prices).quantize(Decimal("0.01"))),
                "low": str(min(opening_prices).quantize(Decimal("0.01"))),
            }

        return {
            "letters": {
                str(p.quantize(Decimal("0.01"))): "".join(sorted(letters))
                for p, letters in sorted(tpo_map.items())
            },
            "tpo_counts": {
                str(p.quantize(Decimal("0.01"))): c for p, c in sorted(tpo_counts.items())
            },
            "poc": str(poc.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "vah": str(vah.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "val": str(val.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "single_prints": single_prints,
            "opening_range": opening_range,
        }


# ──────────────────────────── VWAP 家族 ────────────────────────────


class VWAPFamily:
    """VWAP 家族 — 成交量加权平均价格及其衍生指标。

    - Anchored VWAP: 从指定时间锚点开始计算的 VWAP
    - VWAP Bands: VWAP 标准差带（类似布林带但以成交量加权）
    - 机构成本线: 基于大成交量K线加权的平均成本
    """

    def anchored_vwap(self, klines: list[Kline], anchor_time: int) -> list[Decimal]:
        """锚定 VWAP — 从指定时间开始计算。

        VWAP = Σ(典型价格 × 成交量) / Σ(成交量)
        典型价格 = (high + low + close) / 3

        Args:
            klines: K线序列（按时间排序）
            anchor_time: 锚定起始时间（纳秒时间戳）

        Returns:
            从锚定点开始的 VWAP 序列
        """
        # 过滤锚定点之后的K线
        anchored = [k for k in klines if k.timestamp_ns >= anchor_time]

        if not anchored:
            return []

        vwap_series: list[Decimal] = []
        cum_tp_vol = Decimal("0")  # 累计(典型价格 × 成交量)
        cum_vol = Decimal("0")  # 累计成交量

        for k in anchored:
            typical_price = (k.high + k.low + k.close) / Decimal("3")
            cum_tp_vol += typical_price * k.volume
            cum_vol += k.volume

            if cum_vol > 0:
                vwap = cum_tp_vol / cum_vol
                vwap_series.append(vwap.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
            else:
                vwap_series.append(k.close)

        return vwap_series

    def vwap_bands(self, klines: list[Kline], num_std: float = 2.0) -> dict:
        """VWAP 标准差带。

        类似布林带，但标准差基于成交量加权：
        - Upper Band = VWAP + num_std × σ_vwap
        - Lower Band = VWAP - num_std × σ_vwap
        - σ_vwap = √(Σ(vol_i × (tp_i - VWAP)²) / Σ(vol_i))

        Args:
            klines: K线序列
            num_std: 标准差倍数（默认 2.0）

        Returns:
            {
                "vwap": str,
                "upper": str,
                "lower": str,
                "std": str,
                "bandwidth": str,  # 带宽百分比
            }
        """
        if not klines:
            return {}

        # 计算 VWAP
        cum_tp_vol = Decimal("0")
        cum_vol = Decimal("0")

        for k in klines:
            tp = (k.high + k.low + k.close) / Decimal("3")
            cum_tp_vol += tp * k.volume
            cum_vol += k.volume

        if cum_vol == 0:
            return {}

        vwap = cum_tp_vol / cum_vol

        # 计算加权标准差
        cum_var_vol = Decimal("0")
        for k in klines:
            tp = (k.high + k.low + k.close) / Decimal("3")
            diff = tp - vwap
            cum_var_vol += k.volume * diff * diff

        variance = cum_var_vol / cum_vol
        # Decimal 不支持 sqrt，用 float 近似
        std = Decimal(str(float(variance) ** 0.5))

        num_std_d = Decimal(str(num_std))
        upper = vwap + num_std_d * std
        lower = vwap - num_std_d * std

        # 带宽 = (upper - lower) / vwap
        bandwidth = ((upper - lower) / vwap * 100) if vwap > 0 else Decimal("0")

        return {
            "vwap": str(vwap.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "upper": str(upper.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "lower": str(lower.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "std": str(std.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "bandwidth": str(bandwidth.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        }

    def institutional_cost(self, klines: list[Kline]) -> Decimal:
        """机构成本线。

        机构成本线的逻辑：机构倾向于在大成交量时段建仓，
        因此用成交量的平方加权（放大成交量大的K线的影响），
        得到的加权平均价格更接近机构的真实持仓成本。

        公式：机构成本 = Σ(tp × vol²) / Σ(vol²)

        Args:
            klines: K线序列

        Returns:
            机构成本价格（Decimal）
        """
        if not klines:
            return Decimal("0")

        cum_tp_vol2 = Decimal("0")
        cum_vol2 = Decimal("0")

        for k in klines:
            tp = (k.high + k.low + k.close) / Decimal("3")
            vol_sq = k.volume * k.volume
            cum_tp_vol2 += tp * vol_sq
            cum_vol2 += vol_sq

        if cum_vol2 == 0:
            return Decimal("0")

        cost = cum_tp_vol2 / cum_vol2
        return cost.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
