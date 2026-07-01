"""
ONE量化 - one-collector 进程入口 (marketgw 版本)

负责启动行情采集进程，连接交易所 WebSocket 网关，
将归一化后的行情数据通过 EventBus 分发给下游消费者。

与 ``data/collector_main.py`` 的关系:
- ``data/collector_main.py`` 是完整的数据落湖流程（含质检、Bronze 层存储）
- ``marketgw/collector_main.py`` 聚焦于行情网关的启动和管理

使用方式::

    # 直接运行
    python -m one_quant.marketgw.collector_main

    # 指定参数
    python -m one_quant.marketgw.collector_main --symbols BTC/USDT,ETH/USDT --exchanges binance
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import signal
import time
from pathlib import Path
from typing import Any

from one_quant.infra.event_bus import EventBus, InMemoryEventBus
from one_quant.marketgw.binance_ws import BinanceMarketGateway
from one_quant.marketgw.okx_ws import OKXMarketGateway

logger = logging.getLogger("one-collector")


# ──────────────────────────── 默认配置 ────────────────────────────

DEFAULT_SYMBOLS = [
    "BTC/USDT",
    "ETH/USDT",
    "BNB/USDT",
    "SOL/USDT",
    "XRP/USDT",
]


# ──────────────────────────── 采集统计 ────────────────────────────


class CollectorStats:
    """采集器统计信息"""

    def __init__(self) -> None:
        self._counters: dict[str, int] = {
            "ticker": 0,
            "kline": 0,
            "orderbook": 0,
            "trade": 0,
        }
        self._start_ns: int = time.time_ns()

    def record(self, channel: str) -> None:
        key = channel.split(".")[-1]
        if key in self._counters:
            self._counters[key] += 1

    def snapshot(self) -> dict[str, Any]:
        elapsed_s = (time.time_ns() - self._start_ns) / 1e9
        return {
            "elapsed_s": round(elapsed_s, 1),
            "counters": dict(self._counters),
            "total": sum(self._counters.values()),
        }


# ──────────────────────────── 调试消费者 ────────────────────────────


async def _make_counter(channel: str, stats: CollectorStats) -> Any:
    """创建统计计数器回调"""

    async def handler(data: Any) -> None:
        stats.record(channel)

    return handler


async def _print_ticker(data: Any) -> None:
    """打印 Ticker（调试用）"""
    logger.info(
        "[Ticker] %s %s | 最新=%s 买=%s 卖=%s 量=%s",
        data.get("exchange"),
        data.get("symbol"),
        data.get("last_price"),
        data.get("bid"),
        data.get("ask"),
        data.get("volume_24h"),
    )


async def _print_trade(data: Any) -> None:
    """打印 Trade（调试用）"""
    logger.info(
        "[Trade] %s %s | %s %s @ %s",
        data.get("exchange"),
        data.get("symbol"),
        data.get("side"),
        data.get("quantity"),
        data.get("price"),
    )


# ──────────────────────────── 配置加载 ────────────────────────────


def load_config(config_path: str | None = None) -> dict[str, Any]:
    """
    加载采集器配置。

    Args:
        config_path: JSON 配置文件路径

    Returns:
        配置字典
    """
    default: dict[str, Any] = {
        "symbols": DEFAULT_SYMBOLS,
        "exchanges": {
            "binance": {"enabled": True, "is_futures": False},
            "okx": {"enabled": True},
        },
        "kline_interval": "1m",
        "orderbook_depth": 20,
        "enable_print": True,
    }

    if config_path is None:
        return default

    path = Path(config_path)
    if not path.exists():
        logger.warning("配置文件不存在: %s，使用默认配置", config_path)
        return default

    with open(path, encoding="utf-8") as f:
        user_config = json.load(f)
    default.update(user_config)
    return default


# ──────────────────────────── 主流程 ────────────────────────────


async def run_collector(config: dict[str, Any]) -> None:
    """
    运行行情采集器。

    Args:
        config: 配置字典
    """
    # 创建事件总线
    event_bus: EventBus = InMemoryEventBus()
    await event_bus.start()

    stats = CollectorStats()

    # 注册调试消费者
    if config.get("enable_print", True):
        event_bus.subscribe("market.ticker", _print_ticker)
        event_bus.subscribe("market.trade", _print_trade)

    # 注册统计计数器
    for ch in ("market.ticker", "market.kline", "market.orderbook", "market.trade"):
        handler = await _make_counter(ch, stats)
        event_bus.subscribe(ch, handler)

    symbols = config.get("symbols", DEFAULT_SYMBOLS)
    kline_interval = config.get("kline_interval", "1m")
    orderbook_depth = config.get("orderbook_depth", 20)

    # 创建网关
    gateways: list[Any] = []
    exch_config = config.get("exchanges", {})

    if exch_config.get("binance", {}).get("enabled", True):
        gw = BinanceMarketGateway(
            event_bus=event_bus,
            is_futures=exch_config.get("binance", {}).get("is_futures", False),
        )
        gateways.append(("binance", gw))

    if exch_config.get("okx", {}).get("enabled", True):
        gw_okx: Any = OKXMarketGateway(event_bus=event_bus)
        gateways.append(("okx", gw_okx))

    if not gateways:
        logger.error("没有启用任何交易所网关")
        return

    # 停止事件
    stop_event = asyncio.Event()

    # 启动网关的协程
    async def _run_gateway(name: str, gw: Any) -> None:
        """启动网关并订阅数据"""
        try:
            await gw.connect()
            await gw.subscribe_ticker(symbols)
            await gw.subscribe_kline(symbols, kline_interval)
            await gw.subscribe_orderbook(symbols, orderbook_depth)
            await gw.subscribe_trades(symbols)
            logger.info("%s 网关: 已订阅 %d 个交易对", name, len(symbols))
            # 阻塞直到停止
            await stop_event.wait()
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("%s 网关异常", name)
        finally:
            await gw.stop()

    # 启动所有网关
    tasks = [
        asyncio.create_task(_run_gateway(name, gw), name=f"gw-{name}") for name, gw in gateways
    ]

    # 信号处理
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            pass

    # 定期打印统计
    async def _stats_loop() -> None:
        while not stop_event.is_set():
            await asyncio.sleep(60)
            snap = stats.snapshot()
            logger.info(
                "采集统计: %.1fs | 总消息 %d | Ticker=%d Kline=%d OrderBook=%d Trade=%d",
                snap["elapsed_s"],
                snap["total"],
                snap["counters"]["ticker"],
                snap["counters"]["kline"],
                snap["counters"]["orderbook"],
                snap["counters"]["trade"],
            )

    stats_task = asyncio.create_task(_stats_loop())

    logger.info("采集器已启动，按 Ctrl+C 停止")
    await stop_event.wait()

    # 清理
    logger.info("正在关闭...")
    stats_task.cancel()
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    await event_bus.stop()

    snap = stats.snapshot()
    logger.info("采集器已停止 | 运行 %.1fs | 总消息 %d", snap["elapsed_s"], snap["total"])


def main() -> None:
    """命令行入口"""
    parser = argparse.ArgumentParser(description="ONE量化 - 行情采集器")
    parser.add_argument("--config", type=str, help="配置文件路径（JSON）")
    parser.add_argument("--symbols", type=str, help="交易对列表，逗号分隔")
    parser.add_argument("--exchanges", type=str, help="启用的交易所，逗号分隔")
    parser.add_argument("--futures", action="store_true", help="使用合约端点")
    parser.add_argument("--interval", type=str, default="1m", help="K线周期")
    parser.add_argument("--depth", type=int, default=20, help="盘口深度")
    parser.add_argument("--debug", action="store_true", help="调试日志")
    parser.add_argument("--no-print", action="store_true", help="不打印行情")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    config = load_config(args.config)

    if args.symbols:
        symbols = [s.strip() for s in args.symbols.split(",")]
        config["symbols"] = symbols
    if args.exchanges:
        enabled = [e.strip() for e in args.exchanges.split(",")]
        for name in config.get("exchanges", {}):
            config["exchanges"][name]["enabled"] = name in enabled
    if args.futures:
        config.setdefault("exchanges", {}).setdefault("binance", {})["is_futures"] = True
    config["kline_interval"] = args.interval
    config["orderbook_depth"] = args.depth
    config["enable_print"] = not args.no_print

    try:
        asyncio.run(run_collector(config))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
