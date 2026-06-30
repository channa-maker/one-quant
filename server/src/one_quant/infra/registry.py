"""
ONE量化 - 插件注册表

实现通用的泛型注册表模式，用于管理策略、因子、算法等可插拔组件。

使用方式::

    @register_strategy("momentum_v1")
    class MomentumStrategy:
        ...

    # 查询
    cls = STRATEGY_REGISTRY.get("momentum_v1")
"""

from __future__ import annotations

from typing import Any, Callable, Generic, Optional, TypeVar


# 泛型类型变量 —— 被注册对象的类型（通常是类）
T = TypeVar("T")


class Registry(Generic[T]):
    """
    通用泛型注册表。

    支持通过装饰器注册和按名称查询。同一名称重复注册会抛出异常。

    Attributes:
        name: 注册表名称，用于错误消息中标识来源
    """

    def __init__(self, name: str) -> None:
        """
        初始化注册表。

        Args:
            name: 注册表名称，如 ``"strategy"``, ``"factor"``
        """
        self.name = name
        self._registry: dict[str, T] = {}

    def register(self, key: str) -> Callable[[T], T]:
        """
        注册装饰器。

        用法::

            registry = Registry[str]("demo")

            @registry.register("hello")
            def greet() -> str:
                return "hello"

        Args:
            key: 注册名称，同一 Registry 内必须唯一

        Returns:
            装饰器函数

        Raises:
            ValueError: 当 key 已被注册时
        """

        def decorator(item: T) -> T:
            if key in self._registry:
                raise ValueError(
                    f"[{self.name}] '{key}' 已注册，"
                    f"不允许重复注册。已有: {self._registry[key]!r}"
                )
            self._registry[key] = item
            return item

        return decorator

    def get(self, key: str) -> Optional[T]:
        """
        按名称查询已注册项。

        Args:
            key: 注册名称

        Returns:
            已注册的对象，未找到返回 None
        """
        return self._registry.get(key)

    def get_or_raise(self, key: str) -> T:
        """
        按名称查询，不存在则抛出异常。

        Args:
            key: 注册名称

        Returns:
            已注册的对象

        Raises:
            KeyError: 当 key 不存在时
        """
        item = self._registry.get(key)
        if item is None:
            available = ", ".join(sorted(self._registry.keys())) or "(空)"
            raise KeyError(
                f"[{self.name}] '{key}' 未注册。可用: {available}"
            )
        return item

    def list_keys(self) -> list[str]:
        """返回所有已注册的键名列表"""
        return list(self._registry.keys())

    def __contains__(self, key: str) -> bool:
        return key in self._registry

    def __len__(self) -> int:
        return len(self._registry)

    def __repr__(self) -> str:
        return f"Registry(name={self.name!r}, count={len(self)})"


# ===========================================================================
# 全局注册表实例
# ===========================================================================

#: 策略注册表
STRATEGY_REGISTRY: Registry[Any] = Registry("strategy")

#: 因子注册表
FACTOR_REGISTRY: Registry[Any] = Registry("factor")

#: 算法注册表 (执行算法 / 下单算法)
ALGO_REGISTRY: Registry[Any] = Registry("algo")

#: 数据源注册表
SOURCE_REGISTRY: Registry[Any] = Registry("source")

#: AI Agent 注册表
AGENT_REGISTRY: Registry[Any] = Registry("agent")


# ===========================================================================
# 便捷装饰器
# ===========================================================================

def register_strategy(name: str) -> Callable[[T], T]:
    """
    注册策略到全局策略注册表。

    Args:
        name: 策略唯一名称

    示例::

        @register_strategy("momentum_v1")
        class MomentumStrategy(BaseStrategy):
            ...
    """
    return STRATEGY_REGISTRY.register(name)


def register_factor(name: str) -> Callable[[T], T]:
    """
    注册因子到全局因子注册表。

    Args:
        name: 因子唯一名称

    示例::

        @register_factor("rsi_14")
        class RSIFactor(BaseFactor):
            ...
    """
    return FACTOR_REGISTRY.register(name)


def register_algo(name: str) -> Callable[[T], T]:
    """
    注册算法到全局算法注册表。

    Args:
        name: 算法唯一名称

    示例::

        @register_algo("twap")
        class TWAPAlgo(BaseAlgo):
            ...
    """
    return ALGO_REGISTRY.register(name)


def register_source(name: str) -> Callable[[T], T]:
    """
    注册数据源到全局数据源注册表。

    Args:
        name: 数据源唯一名称

    示例::

        @register_source("binance_ws")
        class BinanceWSSource(BaseSource):
            ...
    """
    return SOURCE_REGISTRY.register(name)


def register_agent(name: str) -> Callable[[T], T]:
    """
    注册 AI Agent 到全局 Agent 注册表。

    Args:
        name: Agent 唯一名称

    示例::

        @register_agent("risk_sentinel")
        class RiskSentinelAgent(BaseAgent):
            ...
    """
    return AGENT_REGISTRY.register(name)
