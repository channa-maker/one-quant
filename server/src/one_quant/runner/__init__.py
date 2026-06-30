"""
ONE量化 - 策略运行器

策略主循环，负责调度策略、分发行情、收集信号。
"""

from one_quant.runner.engine import StrategyRunner

__all__ = ["StrategyRunner"]
