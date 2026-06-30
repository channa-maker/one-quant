"""
ONE量化 - 行情网关模块

提供多交易所 WebSocket 行情接入能力，支持:
- 币安 (Binance) 现货 & 合约
- OKX 现货 & 合约

核心组件:
- MarketGateway: 行情网关抽象基类
- EventBus: 异步事件总线，解耦数据生产与消费
- BinanceWSGateway: 币安 WebSocket 实现
- OKXWSGateway: OKX WebSocket 实现
- ReconnectManager: 断线重连管理器（指数退避）
- normalizer: 交易所原始数据 → 统一领域类型
"""

from one_quant.marketgw.base import EventBus, MarketGateway
from one_quant.marketgw.binance_ws import BinanceWSGateway
from one_quant.marketgw.okx_ws import OKXWSGateway
from one_quant.marketgw.reconnect import ReconnectManager

__all__ = [
    "EventBus",
    "MarketGateway",
    "BinanceWSGateway",
    "OKXWSGateway",
    "ReconnectManager",
]
