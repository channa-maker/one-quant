"""
ONE量化 - 策略注册表

提供全局策略注册表和 register_strategy 装饰器，
用于管理所有已注册的策略类。

使用方式::

    from one_quant.strategy.registry import register_strategy, STRATEGY_REGISTRY

    @register_strategy
    class MyStrategy(Strategy):
        name = "my_strategy"
        enabled = True
        ...

    # 获取已注册策略
    strategy_cls = STRATEGY_REGISTRY.get("my_strategy")
"""

from __future__ import annotations

from one_quant.strategy.contracts import Strategy

# 全局策略注册表：{策略名称: 策略类}
STRATEGY_REGISTRY: dict[str, type[Strategy]] = {}


def register_strategy(cls: type[Strategy]) -> type[Strategy]:
    """策略注册装饰器。

    将策略类注册到全局注册表中。策略类必须有 ``name`` 属性。

    Args:
        cls: 策略类（必须继承 Strategy）

    Returns:
        原始策略类（不修改）

    Raises:
        ValueError: 策略名称已注册或策略类缺少 name 属性

    Example::

        @register_strategy
        class MyStrategy(Strategy):
            name = "my_strategy"
            ...
    """
    if not hasattr(cls, "name") or not cls.name:
        raise ValueError(f"策略类 {cls.__name__} 缺少 'name' 属性")

    if cls.name in STRATEGY_REGISTRY:
        existing = STRATEGY_REGISTRY[cls.name]
        if existing is not cls:
            raise ValueError(
                f"策略名称 '{cls.name}' 已注册（{existing.__name__}），无法注册 {cls.__name__}"
            )

    STRATEGY_REGISTRY[cls.name] = cls
    return cls


def get_strategy(name: str) -> type[Strategy] | None:
    """根据名称获取已注册的策略类。

    Args:
        name: 策略名称

    Returns:
        策略类，未找到返回 None
    """
    return STRATEGY_REGISTRY.get(name)


def list_strategies() -> list[str]:
    """列出所有已注册的策略名称。

    Returns:
        策略名称列表
    """
    return list(STRATEGY_REGISTRY.keys())
