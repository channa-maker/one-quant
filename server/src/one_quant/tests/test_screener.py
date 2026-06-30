"""
ONE量化 - 选股选币流水线测试
"""

import pytest
from decimal import Decimal

from one_quant.core.types import Instrument, InstrumentType, Market
from one_quant.screener.pipeline import ScreenerPipeline


@pytest.fixture
def instruments():
    return [
        Instrument(
            internal_id="binance:BTC/USDT",
            symbol="BTCUSDT",
            market=Market.SPOT,
            instrument_type=InstrumentType.SPOT,
            exchange="binance",
            base_currency="BTC",
            quote_currency="USDT",
            tick_size=Decimal("0.01"),
            lot_size=Decimal("0.00001"),
        ),
        Instrument(
            internal_id="binance:ETH/USDT",
            symbol="ETHUSDT",
            market=Market.SPOT,
            instrument_type=InstrumentType.SPOT,
            exchange="binance",
            base_currency="ETH",
            quote_currency="USDT",
            tick_size=Decimal("0.01"),
            lot_size=Decimal("0.0001"),
        ),
    ]


@pytest.mark.asyncio
async def test_screener_basic(instruments):
    """基本选股。"""
    pipeline = ScreenerPipeline(min_volume_24h=Decimal("0"), top_n=10)
    market_data = {
        "BTCUSDT": {"change_pct": 5.0, "volume_24h": "1000000"},
        "ETHUSDT": {"change_pct": -2.0, "volume_24h": "500000"},
    }
    results = await pipeline.run(instruments, market_data)
    assert len(results) == 2
    # BTC 涨幅更大，得分更高
    assert results[0].symbol == "BTCUSDT"


@pytest.mark.asyncio
async def test_screener_filter_low_volume(instruments):
    """过滤低成交量标的。"""
    pipeline = ScreenerPipeline(min_volume_24h=Decimal("1000000"), top_n=10)
    market_data = {
        "BTCUSDT": {"change_pct": 5.0, "volume_24h": "2000000"},
        "ETHUSDT": {"change_pct": 2.0, "volume_24h": "100"},  # 低成交量
    }
    results = await pipeline.run(instruments, market_data)
    assert len(results) == 1
    assert results[0].symbol == "BTCUSDT"


@pytest.mark.asyncio
async def test_screener_top_n(instruments):
    """Top-N 限制。"""
    pipeline = ScreenerPipeline(min_volume_24h=Decimal("0"), top_n=1)
    market_data = {
        "BTCUSDT": {"change_pct": 5.0, "volume_24h": "1000000"},
        "ETHUSDT": {"change_pct": 2.0, "volume_24h": "500000"},
    }
    results = await pipeline.run(instruments, market_data)
    assert len(results) == 1


def test_screener_stats():
    """统计信息。"""
    pipeline = ScreenerPipeline()
    assert pipeline.stats["run_count"] == 0
