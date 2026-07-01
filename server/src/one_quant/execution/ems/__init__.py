"""
ONE量化 - 执行管理系统 (EMS)

算法拆单引擎，将大额订单拆分为多个子单，降低市场冲击。

支持算法：
  - TWAP: 时间加权平均价格（等时拆分）
  - VWAP: 成交量加权平均价格（按历史成交量分布）
  - POV:  参与率算法（跟踪市场成交量）
"""

from one_quant.execution.ems.base import ExecutionAlgo, _round_to_lot, _time_ns
from one_quant.execution.ems.manager import ExecutionManager, _InstantAlgo
from one_quant.execution.ems.pov import POVAlgo
from one_quant.execution.ems.twap import TWAPAlgo
from one_quant.execution.ems.vwap import VWAPAlgo

__all__ = [
    "ExecutionAlgo",
    "ExecutionManager",
    "POVAlgo",
    "TWAPAlgo",
    "VWAPAlgo",
    "_InstantAlgo",
    "_round_to_lot",
    "_time_ns",
]
