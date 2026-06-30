"""ONE量化 CLI — 策略开发工具

命令:
    one create strategy <name>  — 创建新策略模板
    one create factor <name>    — 创建新因子模板
    one backtest <strategy> --data <path> — 运行回测
    one test                    — 运行测试
"""

from __future__ import annotations
import argparse
import sys
import os
from pathlib import Path


def cmd_create(args: argparse.Namespace) -> None:
    """创建策略/因子模板"""
    name = args.name
    template_type = args.type

    if template_type == "strategy":
        filepath = Path(f"strategy/{name}.py")
        filepath.parent.mkdir(parents=True, exist_ok=True)
        content = f'''"""ONE量化策略 — {name}

自动生成的策略模板。请根据需要修改。
"""

from one_quant.strategy.contracts import Strategy
from one_quant.core.types import Ticker, Kline, Signal, Market
from decimal import Decimal
import time


class {name.title().replace("_", "")}Strategy(Strategy):
    """{name} 策略"""
    name = "{name}"
    enabled = False  # 回测+评审通过后启用

    def __init__(self):
        self._prices: dict[str, list[Decimal]] = {{}}

    def on_ticker(self, ticker: Ticker) -> list[Signal]:
        """处理实时行情"""
        symbol = ticker.symbol
        if symbol not in self._prices:
            self._prices[symbol] = []
        self._prices[symbol].append(ticker.last_price)

        # TODO: 实现你的策略逻辑
        return []

    def on_kline(self, kline: Kline) -> list[Signal]:
        """处理K线更新"""
        # TODO: 实现你的策略逻辑
        return []
'''
        filepath.write_text(content)
        print(f"✅ 策略模板已创建: {filepath}")

    elif template_type == "factor":
        filepath = Path(f"factors/{name}.py")
        filepath.parent.mkdir(parents=True, exist_ok=True)
        content = f'''"""ONE量化因子 — {name}

自动生成的因子模板。请根据需要修改。
"""

from decimal import Decimal
from typing import Any


def compute_{name}(data: list[Decimal], **params: Any) -> Decimal | None:
    """计算 {name} 因子

    Args:
        data: 价格/成交量数据
        **params: 参数

    Returns:
        因子值，数据不足返回 None
    """
    if len(data) < 2:
        return None

    # TODO: 实现你的因子计算逻辑
    return Decimal("0")
'''
        filepath.write_text(content)
        print(f"✅ 因子模板已创建: {filepath}")


def cmd_backtest(args: argparse.Namespace) -> None:
    """运行回测"""
    print(f"🔬 运行回测: {args.strategy}")
    print(f"📁 数据路径: {args.data}")
    # TODO: 接入回测引擎
    print("⚠️ 回测功能开发中...")


def cmd_test(args: argparse.Namespace) -> None:
    """运行测试"""
    print("🧪 运行测试...")
    os.system("pytest src/one_quant/tests/ -v")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="ONE量化策略开发工具",
        prog="one",
    )
    subparsers = parser.add_subparsers(dest="command")

    # one create
    create_parser = subparsers.add_parser("create", help="创建新策略/因子")
    create_parser.add_argument(
        "type",
        choices=["strategy", "factor"],
        help="创建类型",
    )
    create_parser.add_argument("name", help="策略/因子名称")

    # one backtest
    backtest_parser = subparsers.add_parser("backtest", help="运行回测")
    backtest_parser.add_argument("strategy", help="策略名称")
    backtest_parser.add_argument("--data", required=True, help="数据路径")

    # one test
    subparsers.add_parser("test", help="运行测试")

    args = parser.parse_args()

    if args.command == "create":
        cmd_create(args)
    elif args.command == "backtest":
        cmd_backtest(args)
    elif args.command == "test":
        cmd_test(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
