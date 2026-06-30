"""
ONE量化 - one-collector 进程入口

负责启动行情采集进程，连接所有配置的交易所 WebSocket 网关，
将归一化后的行情数据通过 EventBus 分发给下游消费者。

使用方式::

    # 直接运行
    python -m one_quant.marketgw.collector_main

    # 或通过命令行
    one-collector

进程行为:
1. 初始化 EventBus
2. 根据配置启动各交易所网关
3. 注册信号处理（SIGINT/SIGTERM）优雅退出
4. 主循环等待直到收到停止信号
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

from one_quant.marketgw.base import EventBus
from one_quant.marketgw.binance_ws import BinanceWSGateway
from one_quant.marketgw.okx_ws import OKXWSGateway
from one_quant.marketgw.reconnect import ReconnectManager

logger = logging.getLogger("one-collector")


# ──────────────────────────── 默认配置 ────────────────────────────

# 默认订阅的交易对
DEFAULT_SYMBOLS = [
    "BTC/USDT",
    "ETH/USDT",
    "BNB/USDT",
    "SOL/USDT",
    "XRP/USDT",
]

# 默认 K 线周期
DEFAULT_KLINE_INTERVAL = "1m"

# 默认盘口深度
DEFAULT_ORDERBOOK_DEPTH = 20


# ──────────────────────────── 数据打印消费者 ────────────────────────────


async def print_ticker(data: Any) -> None:
    """打印实时行情（调试用）"""
    logger.info(
        "[Ticker] %s %s | 最新=%s 买=%s 卖=%s 量=%s",
        data.exchange,
        data.symbol,
        data.last_price,
        data.bid,
        data.ask,
        data.volume_24h,
    )


async def print_kline(data: Any) -> None:
    """打印 K 线数据（调试用）"""
    logger.info(
        "[Kline] %s %s %s | O=%s H=%s L=%s C=%s V=%s",
        data.exchange,
        data.symbol,
        data.interval,
        data.open,
        data.high,
        data.low,
        data.close,
        data.volume,
    )


async def print_orderbook(data: Any) -> None:
    """打印盘口数据（调试用）"""
    best_bid = data.bids[0].price if data.bids else "N/A"
    best_ask = data.asks[0].price if data.asks else "N/A"
    logger.info(
        "[OrderBook] %s %s | 最佳买=%s 最佳卖=%s (买%d档/卖%d档)",
        data.exchange,
        data.symbol,
        best_bid,
        best_ask,
        len(data.bids),
        len(data.asks),
    )


async def print_trade(data: Any) -> None:
    """打印逐笔成交（调试用）"""
    logger.info(
        "[Trade] %s %s | %s %s @ %s (ID: %s)",
        data.exchange,
        data.symbol,
        data.side,
        data.quantity,
        data.price,
        data.trade_id,
    )


# ──────────────────────────── 统计信息 ────────────────────────────


class CollectorStats:
    """
    采集器统计信息。

    记录各通道的消息计数和最后更新时间，用于监控和健康检查。
    """

    def __init__(self) -> None:
        self._counters: dict[str, int] = {
            "ticker": 0,
            "kline": 0,
            "orderbook": 0,
            "trade": 0,
        }
        self._last_update_ns: dict[str, int] = {}
        self._start_ns: int = time.time_ns()

    def record(self, channel: str) -> None:
        """记录一条消息"""
        key = channel.split(".")[-1]  # "market.ticker" -> "ticker"
        if key in self._counters:
            self._counters[key] += 1
            self._last_update_ns[key] = time.time_ns()

    def snapshot(self) -> dict[str, Any]:
        """获取统计快照"""
        elapsed_s = (time.time_ns() - self._start_ns) / 1e9
        return {
            "elapsed_s": round(elapsed_s, 1),
            "counters": dict(self._counters),
            "total": sum(self._counters.values()),
            "last_update": {
                k: time.strftime("%H:%M:%S", time.localtime(v / 1e9)) if v else "N/A"
                for k, v in self._last_update_ns.items()
            },
        }


# ──────────────────────────── 配置加载 ────────────────────────────


def load_config(config_path: str | None = None) -> dict[str, Any]:
    """
    加载采集器配置。

    配置文件为 JSON 格式，示例::

        {
            "symbols": ["BTC/USDT", "ETH/USDT"],
            "exchanges": {
                "binance": {
                    "enabled": true,
                    "is_futures": false,
                    "symbols": ["BTC/USDT", "ETH/USDT"]
                },
                "okx": {
                    "enabled": true,
                    "symbols": ["BTC/USDT", "ETH/USDT"]
                }
            },
            "kline_interval": "1m",
            "orderbook_depth": 20,
            "enable_print": true
        }

    Args:
        config_path: 配置文件路径，为 None 时使用默认配置

    Returns:
        配置字典
    """
    default_config: dict[str, Any] = {
        "symbols": DEFAULT_SYMBOLS,
        "exchanges": {
            "binance": {
                "enabled": True,
                "is_futures": False,
                "symbols": DEFAULT_SYMBOLS,
            },
            "okx": {
                "enabled": True,
                "symbols": DEFAULT_SYMBOLS,
            },
        },
        "kline_interval": DEFAULT_KLINE_INTERVAL,
        "orderbook_depth": DEFAULT_ORDERBOOK_DEPTH,
        "enable_print": True,
    }

    if config_path is None:
        return default_config

    path = Path(config_path)
    if not path.exists():
        logger.warning("配置文件不存在: %s，使用默认配置", config_path)
        return default_config

    try:
        with open(path, "r", encoding="utf-8") as f:
            user_config = json.load(f)
        # 合并用户配置到默认配置
        for key, value in user_config.items():
            default_config[key] = value
        logger.info("已加载配置: %s", config_path)
        return default_config
    except Exception as exc:
        logger.error("加载配置失败: %s，使用默认配置", exc)
        return default_config


# ──────────────────────────── 主流程 ────────────────────────────


async def run_collector(config: dict[str, Any]) -> None:
    """
    运行采集器主流程。

    1. 创建 EventBus
    2. 启动各交易所网关
    3. 订阅配置的数据类型
    4. 等待停止信号

    Args:
        config: 配置字典
    """
    # 创建事件总线
    event_bus = EventBus()

    # 统计器
    stats = CollectorStats()

    # 如果启用打印，注册调试消费者
    if config.get("enable_print", True):
        event_bus.subscribe("market.ticker", print_ticker)
        event_bus.subscribe("market.kline", print_kline)
        event_bus.subscribe("market.orderbook", print_orderbook)
        event_bus.subscribe("market.trade", print_trade)

    # 注册统计计数器
    async def _count_ticker(data: Any) -> None:
        stats.record("market.ticker")

    async def _count_kline(data: Any) -> None:
        stats.record("market.kline")

    async def _count_orderbook(data: Any) -> None:
        stats.record("market.orderbook")

    async def _count_trade(data: Any) -> None:
        stats.record("market.trade")

    event_bus.subscribe("market.ticker", _count_ticker)
    event_bus.subscribe("market.kline", _count_kline)
    event_bus.subscribe("market.orderbook", _count_orderbook)
    event_bus.subscribe("market.trade", _count_trade)

    # 网关列表
    gateways = []

    # 创建币安网关
    binance_config = config.get("exchanges", {}).get("binance", {})
    if binance_config.get("enabled", True):
        binance_gw = BinanceWSGateway(
            event_bus=event_bus,
            is_futures=binance_config.get("is_futures", False),
        )
        gateways.append(("binance", binance_gw, binance_config.get("symbols", config.get("symbols", []))))

    # 创建 OKX 网关
    okx_config = config.get("exchanges", {}).get("okx", {})
    if okx_config.get("enabled", True):
        okx_gw = OKXWSGateway(event_bus=event_bus)
        gateways.append(("okx", okx_gw, okx_config.get("symbols", config.get("symbols", []))))

    if not gateways:
        logger.error("没有启用任何交易所网关，退出")
        return

    # 统一停止事件
    stop_event = asyncio.Event()

    # 启动所有网关的任务
    gateway_tasks: list[asyncio.Task[None]] = []

    def _make_run_gateway(
        gw_name: str,
        gateway: Any,
        syms: list[str],
    ) -> Any:
        """
        为指定网关创建运行协程。

        使用 ReconnectManager.run_forever 实现断线自动重连。
        首次连接成功后立即订阅所有数据类型，重连后也会重新订阅。
        """
        async def _subscribe_all() -> None:
            """订阅所有数据类型"""
            if not syms:
                return
            await gateway.subscribe_ticker(syms)
            await gateway.subscribe_kline(
                syms, config.get("kline_interval", "1m")
            )
            await gateway.subscribe_orderbook(
                syms, config.get("orderbook_depth", 20)
            )
            await gateway.subscribe_trades(syms)
            logger.info("%s 网关: 已订阅 %d 个交易对", gw_name, len(syms))

        async def _run() -> None:
            """运行网关主循环"""
            try:
                reconnect = ReconnectManager(
                    initial_delay=1.0, max_delay=60.0
                )

                async def _connect_and_run() -> None:
                    """连接并进入接收循环"""
                    await gateway.connect()
                    if gateway._recv_task:
                        await gateway._recv_task

                async def _on_reconnect() -> None:
                    """连接成功后订阅数据"""
                    await _subscribe_all()

                await reconnect.run_forever(
                    connect_fn=_connect_and_run,
                    on_reconnect=_on_reconnect,
                    should_continue=lambda: gateway.is_running,
                )
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception("%s 网关运行异常", gw_name)

        return _run()

    # 启动所有网关任务
    for name, gw, symbols in gateways:
        gw._running = True  # 标记为运行状态
        task = asyncio.create_task(_make_run_gateway(name, gw, symbols))
        gateway_tasks.append(task)

    # 注册信号处理（优雅退出）
    loop = asyncio.get_running_loop()

    def _signal_handler() -> None:
        logger.info("收到停止信号，正在关闭...")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            # Windows 不支持 add_signal_handler
            pass

    # 定期打印统计信息
    async def _stats_reporter() -> None:
        """每 60 秒打印一次统计信息"""
        while not stop_event.is_set():
            try:
                await asyncio.sleep(60)
                snap = stats.snapshot()
                logger.info(
                    "采集统计: 运行 %.1fs | 总消息 %d | Ticker=%d Kline=%d OrderBook=%d Trade=%d",
                    snap["elapsed_s"],
                    snap["total"],
                    snap["counters"]["ticker"],
                    snap["counters"]["kline"],
                    snap["counters"]["orderbook"],
                    snap["counters"]["trade"],
                )
            except asyncio.CancelledError:
                break

    stats_task = asyncio.create_task(_stats_reporter())

    # 等待停止信号
    logger.info("采集器已启动，按 Ctrl+C 停止")
    await stop_event.wait()

    # 清理
    logger.info("正在关闭所有网关...")
    stats_task.cancel()

    for name, gw, _ in gateways:
        try:
            gw._running = False  # 停止重连循环
            await gw.stop()
        except Exception:
            logger.exception("关闭 %s 网关时异常", name)

    for task in gateway_tasks:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    # 打印最终统计
    snap = stats.snapshot()
    logger.info(
        "采集器已停止 | 运行 %.1fs | 总消息 %d",
        snap["elapsed_s"],
        snap["total"],
    )


def main() -> None:
    """
    命令行入口。

    命令行参数:
    - --config: 配置文件路径（JSON）
    - --symbols: 逗号分隔的交易对列表
    - --exchanges: 启用的交易所（binance,okx）
    - --futures: 是否使用合约端点
    - --interval: K 线周期
    - --depth: 盘口深度
    - --debug: 启用调试日志
    """
    parser = argparse.ArgumentParser(
        description="ONE量化 - 行情采集器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 使用默认配置
  python -m one_quant.marketgw.collector_main

  # 指定交易对和交易所
  python -m one_quant.marketgw.collector_main --symbols BTC/USDT,ETH/USDT --exchanges binance

  # 使用配置文件
  python -m one_quant.marketgw.collector_main --config collector.json

  # 启用合约行情
  python -m one_quant.marketgw.collector_main --futures
        """,
    )
    parser.add_argument("--config", type=str, help="配置文件路径（JSON）")
    parser.add_argument("--symbols", type=str, help="交易对列表，逗号分隔（如 BTC/USDT,ETH/USDT）")
    parser.add_argument("--exchanges", type=str, help="启用的交易所，逗号分隔（如 binance,okx）")
    parser.add_argument("--futures", action="store_true", help="使用合约端点（仅币安）")
    parser.add_argument("--interval", type=str, default="1m", help="K线周期（默认 1m）")
    parser.add_argument("--depth", type=int, default=20, help="盘口深度（默认 20）")
    parser.add_argument("--debug", action="store_true", help="启用调试日志")
    parser.add_argument("--no-print", action="store_true", help="不打印行情数据")

    args = parser.parse_args()

    # 配置日志
    log_level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 加载配置
    config = load_config(args.config)

    # 命令行参数覆盖配置文件
    if args.symbols:
        symbols = [s.strip() for s in args.symbols.split(",")]
        config["symbols"] = symbols
        # 同步更新各交易所的 symbols
        for exch in config.get("exchanges", {}).values():
            exch["symbols"] = symbols

    if args.exchanges:
        enabled = [e.strip() for e in args.exchanges.split(",")]
        for name in config.get("exchanges", {}):
            config["exchanges"][name]["enabled"] = name in enabled

    if args.futures:
        binance_conf = config.get("exchanges", {}).get("binance", {})
        binance_conf["is_futures"] = True

    config["kline_interval"] = args.interval
    config["orderbook_depth"] = args.depth
    config["enable_print"] = not args.no_print

    # 运行采集器
    try:
        asyncio.run(run_collector(config))
    except KeyboardInterrupt:
        logger.info("用户中断，退出")


if __name__ == "__main__":
    main()
