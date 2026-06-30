"""
ONE量化 - 行情网关模块 (marketgw)

提供多交易所 WebSocket 行情接入能力。

与 ``exchange/`` 模块的关系:
- ``exchange/`` 是底层交易所适配器（含下单、账户等）
- ``marketgw/`` 专注于行情数据采集、归一化、分发

核心组件:
- MarketGateway: 行情网关抽象基类（定义标准生命周期）
- BinanceMarketGateway: 币安行情接入
- OKXMarketGateway: OKX 行情接入
- ReconnectManager: 断线重连管理器（指数退避）
- normalizer: 交易所原始数据 → 统一领域类型
"""

from one_quant.marketgw.base import MarketGateway
from one_quant.marketgw.binance_ws import BinanceMarketGateway
from one_quant.marketgw.okx_ws import OKXMarketGateway
from one_quant.marketgw.reconnect import ReconnectManager

__all__ = [
    "MarketGateway",
    "BinanceMarketGateway",
    "OKXMarketGateway",
    "ReconnectManager",
]
