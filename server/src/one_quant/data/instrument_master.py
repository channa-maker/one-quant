"""标的主数据 Instrument Master — 跨交易所统一 ID + 符号映射 + ticker 变更史"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from one_quant.core.types import Instrument, InstrumentType, Market
from one_quant.infra.logging import get_logger

logger = get_logger(__name__)


class InstrumentMaster:
    """标的主数据管理器。

    职责：
    - 维护 internal_id ↔ (exchange, symbol) 双向映射
    - 记录标的变更历史（上线/下架/改名/拆分）
    - 提供 Point-in-Time 查询（回测时按历史时点构建标的池）
    - 支持从配置文件加载 + 运行时动态注册

    internal_id 命名规范：
    - 加密: binance:BTC/USDT, okx:ETH/USDT:SWAP
    - 美股: ibkr:AAPL, ibkr:TSLA
    - 期权: ibkr:AAPL240119C00150000
    """

    def __init__(self, config_path: str | None = None) -> None:
        self._instruments: dict[str, Instrument] = {}  # internal_id → Instrument
        self._exchange_index: dict[str, dict[str, str]] = {}  # {exchange:{symbol→internal_id}}
        self._history: list[dict[str, Any]] = []  # 变更历史（只增不改）
        self._config_path = Path(config_path) if config_path else None

    # ── 加载 ──────────────────────────────────────────────────────────

    def load_from_file(self, path: str | Path | None = None) -> int:
        """从 JSON 配置文件加载标的主数据。

        文件格式示例：
        [
            {
                "internal_id": "binance:BTC/USDT",
                "symbol": "BTCUSDT",
                "market": "SPOT",
                "instrument_type": "SPOT",
                "exchange": "binance",
                "base_currency": "BTC",
                "quote_currency": "USDT",
                "tick_size": "0.01",
                "lot_size": "0.00001",
                "is_active": true
            }
        ]

        Returns:
            加载的标的数量
        """
        load_path = Path(path) if path else self._config_path
        if load_path is None or not load_path.exists():
            logger.warning("标的主数据配置文件不存在", path=str(load_path))
            return 0

        with open(load_path, encoding="utf-8") as f:
            records = json.load(f)

        count = 0
        for rec in records:
            try:
                instrument = self._from_dict(rec)
                self._register(instrument)
                count += 1
            except Exception:
                logger.exception("加载标的数据失败", record=rec)

        logger.info("标的主数据已加载", count=count, path=str(load_path))
        return count

    def _from_dict(self, rec: dict[str, Any]) -> Instrument:
        """从字典构造 Instrument"""
        return Instrument(
            internal_id=rec["internal_id"],
            symbol=rec["symbol"],
            market=Market(rec["market"]),
            instrument_type=InstrumentType(rec["instrument_type"]),
            exchange=rec["exchange"],
            base_currency=rec["base_currency"],
            quote_currency=rec["quote_currency"],
            tick_size=Decimal(str(rec["tick_size"])),
            lot_size=Decimal(str(rec["lot_size"])),
            contract_multiplier=Decimal(str(rec.get("contract_multiplier", "1"))),
            is_active=rec.get("is_active", True),
        )

    # ── 注册 ──────────────────────────────────────────────────────────

    def register(self, instrument: Instrument) -> None:
        """注册标的（公开接口）"""
        self._register(instrument)
        self._record_change("register", instrument.internal_id, {
            "symbol": instrument.symbol,
            "exchange": instrument.exchange,
            "market": instrument.market.value,
        })

    def _register(self, instrument: Instrument) -> None:
        """内部注册"""
        self._instruments[instrument.internal_id] = instrument

        # 维护交易所索引
        exchange = instrument.exchange
        if exchange not in self._exchange_index:
            self._exchange_index[exchange] = {}
        self._exchange_index[exchange][instrument.symbol] = instrument.internal_id

    def deactivate(self, internal_id: str, reason: str = "") -> bool:
        """下架标的（标记为不活跃，不删除）"""
        inst = self._instruments.get(internal_id)
        if inst is None:
            return False

        # Pydantic frozen，创建新实例
        deactivated = inst.model_copy(update={"is_active": False})
        self._instruments[internal_id] = deactivated
        self._record_change("deactivate", internal_id, {"reason": reason})
        logger.info("标的已下架", internal_id=internal_id, reason=reason)
        return True

    # ── 查询 ──────────────────────────────────────────────────────────

    def get(self, internal_id: str) -> Instrument | None:
        """按 internal_id 查询"""
        return self._instruments.get(internal_id)

    def get_by_exchange_symbol(self, exchange: str, symbol: str) -> Instrument | None:
        """按 (exchange, symbol) 查询"""
        idx = self._exchange_index.get(exchange, {})
        internal_id = idx.get(symbol)
        if internal_id:
            return self._instruments.get(internal_id)
        return None

    def resolve_internal_id(self, exchange: str, symbol: str) -> str:
        """将交易所符号解析为 internal_id。

        如果不存在，自动创建默认映射（适合加密现货简单场景）。
        """
        inst = self.get_by_exchange_symbol(exchange, symbol)
        if inst:
            return inst.internal_id

        # 自动创建
        internal_id = f"{exchange}:{symbol}"
        instrument = Instrument(
            internal_id=internal_id,
            symbol=symbol,
            market=Market.SPOT,
            instrument_type=InstrumentType.SPOT,
            exchange=exchange,
            base_currency=symbol.split("/")[0] if "/" in symbol else symbol,
            quote_currency=symbol.split("/")[1] if "/" in symbol else "USDT",
            tick_size=Decimal("0.01"),
            lot_size=Decimal("0.00001"),
        )
        self._register(instrument)
        self._record_change("auto_register", internal_id, {"symbol": symbol, "exchange": exchange})
        logger.info("自动注册标的", internal_id=internal_id)
        return internal_id

    def list_active(self, exchange: str | None = None, market: Market | None = None) -> list[Instrument]:
        """列出所有活跃标的，可按交易所/市场过滤"""
        results = []
        for inst in self._instruments.values():
            if not inst.is_active:
                continue
            if exchange and inst.exchange != exchange:
                continue
            if market and inst.market != market:
                continue
            results.append(inst)
        return results

    def list_all(self) -> list[Instrument]:
        """列出所有标的（含已下架）"""
        return list(self._instruments.values())

    # ── Point-in-Time 查询 ────────────────────────────────────────────

    def get_active_at(self, timestamp_ns: int, exchange: str | None = None) -> list[Instrument]:
        """获取指定时刻的活跃标的池（用于回测，避免幸存者偏差）。

        遍历变更历史，重建截止到 timestamp_ns 时的状态。
        """
        # 构建截止时刻的活跃集合
        active_ids: set[str] = set()
        deactivated_ids: set[str] = set()

        for change in self._history:
            if change["timestamp_ns"] > timestamp_ns:
                break
            action = change["action"]
            iid = change["internal_id"]
            if action in ("register", "auto_register"):
                active_ids.add(iid)
            elif action == "deactivate":
                active_ids.discard(iid)
                deactivated_ids.add(iid)

        results = []
        for iid in active_ids:
            inst = self._instruments.get(iid)
            if inst and inst.is_active:
                if exchange and inst.exchange != exchange:
                    continue
                results.append(inst)
        return results

    # ── 变更历史 ──────────────────────────────────────────────────────

    def _record_change(self, action: str, internal_id: str, details: dict[str, Any]) -> None:
        """记录变更（只增不改）"""
        self._history.append({
            "action": action,
            "internal_id": internal_id,
            "details": details,
            "timestamp_ns": time.time_ns(),
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        })

    @property
    def history(self) -> list[dict[str, Any]]:
        """变更历史（只读）"""
        return list(self._history)

    @property
    def stats(self) -> dict[str, int]:
        """统计信息"""
        active = sum(1 for i in self._instruments.values() if i.is_active)
        return {
            "total": len(self._instruments),
            "active": active,
            "deactivated": len(self._instruments) - active,
            "history_entries": len(self._history),
        }
