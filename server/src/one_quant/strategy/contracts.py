"""
ONE量化 - 策略合约（基类与接口规范）

所有策略必须继承 Strategy 基类并实现抽象方法。
策略是纯函数式组件：输入行情 → 输出信号，不含副作用（除 on_fill / on_recover）。

规范：
  - 因子命名：使用 snake_case，如 `rsi_14`、`ema_cross_fast`
  - NaN 处理：因子值为 NaN / None 时必须返回空信号列表，禁止将 NaN 传入信号
  - 信号强度：取值 [0, 1]，0 表示极弱，1 表示极强
  - reason 字段：必须使用中文，便于人工审查和日志追踪
  - 默认禁用：新策略 enabled=False，需显式启用
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from one_quant.core.types import (
    Fill,
    Kline,
    OptionQuote,
    OrderBook,
    PositionState,
    Signal,
    Ticker,
)


class Strategy(ABC):
    """策略基类。

    子类必须实现 ``on_ticker`` 和 ``on_kline`` 两个核心回调，
    其余回调有默认空实现可按需覆盖。

    Attributes:
        name: 策略名称（唯一标识，用于日志和信号溯源）
        enabled: 是否启用。新策略默认禁用，需显式开启。

    Example::

        class MyStrategy(Strategy):
            name = "my_ma_cross"
            enabled = True

            def on_ticker(self, ticker: Ticker) -> list[Signal]:
                # 实现行情回调
                ...

            def on_kline(self, kline: Kline) -> list[Signal]:
                # 实现K线回调
                ...
    """

    name: str
    enabled: bool = False  # 新策略默认禁用

    @abstractmethod
    def on_ticker(self, ticker: Ticker) -> list[Signal]:
        """处理实时行情更新。

        每次收到 Ticker 快照时调用。适用于高频信号、价差监控等。

        Args:
            ticker: 最新行情快照

        Returns:
            信号列表。无信号时返回空列表。
        """
        ...

    @abstractmethod
    def on_kline(self, kline: Kline) -> list[Signal]:
        """处理K线更新。

        每次K线闭合（或实时更新）时调用。适用于技术指标、趋势跟踪等。

        Args:
            kline: 最新K线数据

        Returns:
            信号列表。无信号时返回空列表。
        """
        ...

    def on_orderbook(self, ob: OrderBook) -> list[Signal]:
        """处理盘口更新（可选）。

        默认不处理。适用于做市策略、大单检测等需要盘口深度的场景。

        Args:
            ob: 最新盘口快照

        Returns:
            信号列表。默认返回空列表。
        """
        return []

    def on_option_quote(self, q: OptionQuote) -> list[Signal]:
        """处理期权报价更新（可选）。

        默认不处理。适用于波动率策略、期权套利等。

        Args:
            q: 期权报价（含希腊字母）

        Returns:
            信号列表。默认返回空列表。
        """
        return []

    def on_fill(self, fill: Fill) -> None:
        """处理成交回报（可选）。

        当策略发出的信号对应的订单成交时调用。可用于更新内部状态、
        记录成交历史等。无需返回值。

        Args:
            fill: 成交回报
        """
        ...

    def on_recover(self, state: PositionState) -> None:
        """恢复持仓状态（可选）。

        系统重启后，对每个活跃持仓调用一次，用于恢复策略内部状态。

        Args:
            state: 当前持仓快照
        """
        ...
