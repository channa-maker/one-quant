"""Gold 层 — 因子计算骨架 + 特征商店离线/在线"""

from typing import Any


class GoldFeatureEngine:
    """Gold 层特征计算引擎。

    将 Silver 层数据聚合计算为因子/特征。
    具体因子策略在 strategy 层实现，这里只提供骨架和接口。
    """

    def __init__(self) -> None:
        self._computed_count = 0

    def compute_features(self, symbol: str, window: str = "1d") -> dict[str, Any]:
        """计算指定标的的特征集。

        Args:
            symbol: 标的符号
            window: 时间窗口 (如 "1d", "4h", "1h")

        Returns:
            特征字典 {factor_name: value}
        """
        # 骨架：具体因子由策略层通过 @register_factor 注册实现
        features: dict[str, Any] = {
            "symbol": symbol,
            "window": window,
            "computed_at": None,  # 由调用方填充
        }
        self._computed_count += 1
        return features

    def compute_batch(self, symbols: list[str], window: str = "1d") -> dict[str, dict[str, Any]]:
        """批量计算特征。

        Args:
            symbols: 标的列表
            window: 时间窗口

        Returns:
            {symbol: {factor_name: value}} 字典
        """
        return {symbol: self.compute_features(symbol, window) for symbol in symbols}

    @property
    def stats(self) -> dict[str, int]:
        return {"computed": self._computed_count}
