"""
ONE量化 - 账户会计系统

管理账户余额、持仓明细、已实现/未实现盈亏。

核心概念：
  - Account: 账户实体，包含多个币种余额
  - Balance: 单币种余额（可用 + 冻结）
  - PositionLot: 持仓批次（FIFO 成本法）
  - AccountLedger: 账户总账，管理余额和持仓

规范：
  - 所有金额使用 Decimal 精确计算
  - 余额变动通过 Ledger 事务保证一致性
  - 持仓成本采用 FIFO（先进先出）法
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from one_quant.core.types import Fill

logger = logging.getLogger(__name__)


# ──────────────────── 余额 ────────────────────


@dataclass
class Balance:
    """单币种余额。

    Attributes:
        currency: 币种（如 USDT, BTC）。
        available: 可用余额（可下单）。
        frozen: 冻结余额（挂单占用）。
    """

    currency: str
    available: Decimal = Decimal("0")
    frozen: Decimal = Decimal("0")

    @property
    def total(self) -> Decimal:
        """总余额 = 可用 + 冻结。"""
        return self.available + self.frozen

    def freeze(self, amount: Decimal) -> None:
        """冻结金额（从可用转移到冻结）。

        Args:
            amount: 冻结金额。

        Raises:
            ValueError: 可用余额不足。
        """
        if amount < 0:
            raise ValueError(f"冻结金额不能为负: {amount}")
        if amount > self.available:
            raise ValueError(f"可用余额不足: 可用={self.available}, 冻结={amount}")
        self.available -= amount
        self.frozen += amount

    def unfreeze(self, amount: Decimal) -> None:
        """解冻金额（从冻结转回可用）。

        Args:
            amount: 解冻金额。

        Raises:
            ValueError: 冻结余额不足。
        """
        if amount < 0:
            raise ValueError(f"解冻金额不能为负: {amount}")
        if amount > self.frozen:
            raise ValueError(f"冻结余额不足: 冻结={self.frozen}, 解冻={amount}")
        self.frozen -= amount
        self.available += amount

    def credit(self, amount: Decimal) -> None:
        """入账（增加可用余额）。

        Args:
            amount: 入账金额。
        """
        if amount < 0:
            raise ValueError(f"入账金额不能为负: {amount}")
        self.available += amount

    def debit(self, amount: Decimal) -> None:
        """扣款（减少可用余额）。

        Args:
            amount: 扣款金额。

        Raises:
            ValueError: 可用余额不足。
        """
        if amount < 0:
            raise ValueError(f"扣款金额不能为负: {amount}")
        if amount > self.available:
            raise ValueError(f"可用余额不足: 可用={self.available}, 扣款={amount}")
        self.available -= amount


# ──────────────────── 持仓批次 ────────────────────


@dataclass
class PositionLot:
    """持仓批次（FIFO 成本法）。

    每次买入产生一个批次，卖出时按 FIFO 顺序消耗。

    Attributes:
        symbol: 标的符号。
        side: 方向（long/short）。
        quantity: 剩余数量。
        entry_price: 开仓均价。
        entry_timestamp_ns: 开仓时间戳（纳秒）。
        realized_pnl: 该批次已实现盈亏。
    """

    symbol: str
    side: str  # "long" or "short"
    quantity: Decimal
    entry_price: Decimal
    entry_timestamp_ns: int
    realized_pnl: Decimal = Decimal("0")

    @property
    def notional(self) -> Decimal:
        """名义价值。"""
        return self.quantity * self.entry_price


# ──────────────────── 账户变动记录 ────────────────────


@dataclass(frozen=True)
class LedgerEntry:
    """账本变动记录（不可变）。

    Attributes:
        entry_id: 变动ID（UUID）。
        currency: 币种。
        amount: 变动金额（正=入账，负=扣款）。
        balance_before: 变动前余额。
        balance_after: 变动后余额。
        reason: 变动原因（如 fill_buy, fill_sell, fee, funding）。
        reference_id: 关联ID（如 order_id, fill_id）。
        timestamp_ns: 纳秒时间戳。
    """

    entry_id: str
    currency: str
    amount: Decimal
    balance_before: Decimal
    balance_after: Decimal
    reason: str
    reference_id: str
    timestamp_ns: int


# ──────────────────── 账户总账 ────────────────────


class AccountLedger:
    """账户总账。

    管理所有币种余额和持仓批次，保证余额变动的事务性。

    Attributes:
        account_id: 账户ID。
        _balances: 币种余额映射。
        _positions: 持仓批次映射（symbol -> deque[PositionLot]）。
        _entries: 账本变动记录列表。

    Example::

        ledger = AccountLedger("main")
        ledger.deposit("USDT", Decimal("100000"))
        ledger.process_fill(buy_fill)
        pnl = ledger.calculate_pnl("BTC/USDT")
    """

    def __init__(self, account_id: str) -> None:
        """初始化账户总账。

        Args:
            account_id: 账户ID。
        """
        self.account_id = account_id
        self._balances: dict[str, Balance] = {}
        self._positions: dict[str, deque[PositionLot]] = defaultdict(deque)
        self._entries: list[LedgerEntry] = []
        self._entry_counter = 0

    # ──────────────── 余额管理 ────────────────

    def get_balance(self, currency: str) -> Balance:
        """获取指定币种余额。

        Args:
            currency: 币种。

        Returns:
            余额对象（不存在则自动创建零余额）。
        """
        if currency not in self._balances:
            self._balances[currency] = Balance(currency=currency)
        return self._balances[currency]

    def deposit(self, currency: str, amount: Decimal) -> LedgerEntry:
        """入金（增加可用余额）。

        Args:
            currency: 币种。
            amount: 入金金额。

        Returns:
            账本变动记录。

        Raises:
            ValueError: 金额非正。
        """
        if amount <= 0:
            raise ValueError(f"入金金额必须大于 0: {amount}")

        balance = self.get_balance(currency)
        before = balance.total
        balance.credit(amount)
        after = balance.total

        entry = self._record_entry(
            currency=currency,
            amount=amount,
            balance_before=before,
            balance_after=after,
            reason="deposit",
            reference_id="",
        )

        logger.info("入金: %s %s (余额: %s → %s)", currency, amount, before, after)
        return entry

    def withdraw(self, currency: str, amount: Decimal) -> LedgerEntry:
        """出金（减少可用余额）。

        Args:
            currency: 币种。
            amount: 出金金额。

        Returns:
            账本变动记录。

        Raises:
            ValueError: 余额不足或金额非正。
        """
        if amount <= 0:
            raise ValueError(f"出金金额必须大于 0: {amount}")

        balance = self.get_balance(currency)
        before = balance.total
        balance.debit(amount)
        after = balance.total

        entry = self._record_entry(
            currency=currency,
            amount=-amount,
            balance_before=before,
            balance_after=after,
            reason="withdrawal",
            reference_id="",
        )

        logger.info("出金: %s %s (余额: %s → %s)", currency, amount, before, after)
        return entry

    def freeze_margin(self, currency: str, amount: Decimal) -> None:
        """冻结保证金（挂单时）。

        Args:
            currency: 币种。
            amount: 冻结金额。
        """
        balance = self.get_balance(currency)
        balance.freeze(amount)
        logger.debug("冻结保证金: %s %s", currency, amount)

    def unfreeze_margin(self, currency: str, amount: Decimal) -> None:
        """解冻保证金（撤单时）。

        Args:
            currency: 币种。
            amount: 解冻金额。
        """
        balance = self.get_balance(currency)
        balance.unfreeze(amount)
        logger.debug("解冻保证金: %s %s", currency, amount)

    # ──────────────── 成交处理 ────────────────

    def process_fill(self, fill: Fill) -> LedgerEntry | None:
        """处理成交回报，更新余额和持仓。

        买入：扣款 + 创建持仓批次
        卖出：消耗持仓批次 + 入账盈亏

        Args:
            fill: 成交回报。

        Returns:
            账本变动记录（手续费）。
        """
        if fill.side == "buy":
            return self._process_buy_fill(fill)
        else:
            return self._process_sell_fill(fill)

    def _process_buy_fill(self, fill: Fill) -> LedgerEntry | None:
        """处理买入成交。

        Args:
            fill: 买入成交。

        Returns:
            手续费账本记录。
        """
        # 计算成本
        cost = fill.quantity * fill.price

        # 扣款（从 quote 货币余额扣除）
        quote_currency = self._extract_quote_currency(fill.symbol)
        balance = self.get_balance(quote_currency)

        if balance.available >= cost:
            before = balance.total
            balance.debit(cost)
            after = balance.total

            self._record_entry(
                currency=quote_currency,
                amount=-cost,
                balance_before=before,
                balance_after=after,
                reason="fill_buy",
                reference_id=fill.order_id,
            )

        # 创建持仓批次
        lot = PositionLot(
            symbol=fill.symbol,
            side="long",
            quantity=fill.quantity,
            entry_price=fill.price,
            entry_timestamp_ns=fill.timestamp_ns,
        )
        self._positions[fill.symbol].append(lot)

        # 处理手续费
        fee_entry = self._process_fee(fill)

        logger.info(
            "买入成交: %s %s @ %s，成本 %s %s",
            fill.quantity,
            fill.symbol,
            fill.price,
            cost,
            quote_currency,
        )

        return fee_entry

    def _process_sell_fill(self, fill: Fill) -> LedgerEntry | None:
        """处理卖出成交（FIFO 消耗持仓批次）。

        Args:
            fill: 卖出成交。

        Returns:
            手续费账本记录。
        """
        remaining_qty = fill.quantity
        total_realized_pnl = Decimal("0")

        # FIFO 消耗持仓批次
        lots = self._positions.get(fill.symbol, deque())
        while remaining_qty > 0 and lots:
            lot = lots[0]

            # 本批次可消耗的数量
            consume_qty = min(remaining_qty, lot.quantity)

            # 计算已实现盈亏
            if lot.side == "long":
                pnl = (fill.price - lot.entry_price) * consume_qty
            else:  # short
                pnl = (lot.entry_price - fill.price) * consume_qty

            lot.realized_pnl += pnl
            lot.quantity -= consume_qty
            remaining_qty -= consume_qty
            total_realized_pnl += pnl

            # 批次已清空，移除
            if lot.quantity <= 0:
                lots.popleft()

        # 入账卖出所得
        quote_currency = self._extract_quote_currency(fill.symbol)
        proceeds = fill.quantity * fill.price
        balance = self.get_balance(quote_currency)

        before = balance.total
        balance.credit(proceeds)
        after = balance.total

        self._record_entry(
            currency=quote_currency,
            amount=proceeds,
            balance_before=before,
            balance_after=after,
            reason="fill_sell",
            reference_id=fill.order_id,
        )

        # 处理手续费
        fee_entry = self._process_fee(fill)

        logger.info(
            "卖出成交: %s %s @ %s，所得 %s %s，已实现盈亏 %s",
            fill.quantity,
            fill.symbol,
            fill.price,
            proceeds,
            quote_currency,
            total_realized_pnl,
        )

        return fee_entry

    def _process_fee(self, fill: Fill) -> LedgerEntry | None:
        """处理手续费。

        Args:
            fill: 成交回报。

        Returns:
            手续费账本记录（手续费为 0 则返回 None）。
        """
        if fill.fee <= 0:
            return None

        balance = self.get_balance(fill.fee_currency)
        before = balance.total

        if balance.available >= fill.fee:
            balance.debit(fill.fee)
        else:
            balance.available = Decimal("0")

        after = balance.total

        entry = self._record_entry(
            currency=fill.fee_currency,
            amount=-fill.fee,
            balance_before=before,
            balance_after=after,
            reason="fee",
            reference_id=fill.order_id,
        )

        return entry

    # ──────────────── 持仓查询 ────────────────

    def get_position_lots(self, symbol: str) -> list[PositionLot]:
        """获取指定标的的所有持仓批次。

        Args:
            symbol: 标的符号。

        Returns:
            持仓批次列表。
        """
        return list(self._positions.get(symbol, deque()))

    def get_position_quantity(self, symbol: str) -> Decimal:
        """获取指定标的的总持仓数量。

        Args:
            symbol: 标的符号。

        Returns:
            总持仓数量。
        """
        return sum(lot.quantity for lot in self._positions.get(symbol, deque()))

    def get_position_cost(self, symbol: str) -> Decimal:
        """获取指定标的的总持仓成本。

        Args:
            symbol: 标的符号。

        Returns:
            总持仓成本（加权平均）。
        """
        lots = self._positions.get(symbol, deque())
        if not lots:
            return Decimal("0")
        return sum(lot.notional for lot in lots)

    def get_avg_entry_price(self, symbol: str) -> Decimal:
        """获取指定标的的加权平均开仓价。

        Args:
            symbol: 标的符号。

        Returns:
            加权平均开仓价（无持仓返回 0）。
        """
        lots = self._positions.get(symbol, deque())
        if not lots:
            return Decimal("0")

        total_notional = sum(lot.notional for lot in lots)
        total_qty = sum(lot.quantity for lot in lots)

        if total_qty <= 0:
            return Decimal("0")

        return (total_notional / total_qty).quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)

    def get_realized_pnl(self, symbol: str) -> Decimal:
        """获取指定标的的累计已实现盈亏。

        Args:
            symbol: 标的符号。

        Returns:
            累计已实现盈亏。
        """
        # 已消耗的批次
        # 注意：这里需要从历史记录中汇总，简化实现用当前批次的 realized_pnl
        total = Decimal("0")
        for lot in self._positions.get(symbol, deque()):
            total += lot.realized_pnl
        return total

    def calculate_unrealized_pnl(self, symbol: str, current_price: Decimal) -> Decimal:
        """计算未实现盈亏。

        Args:
            symbol: 标的符号。
            current_price: 当前市场价格。

        Returns:
            未实现盈亏。
        """
        total_pnl = Decimal("0")
        for lot in self._positions.get(symbol, deque()):
            if lot.side == "long":
                total_pnl += (current_price - lot.entry_price) * lot.quantity
            else:  # short
                total_pnl += (lot.entry_price - current_price) * lot.quantity
        return total_pnl

    # ──────────────── 账户总览 ────────────────

    def get_all_balances(self) -> list[Balance]:
        """获取所有非零余额。

        Returns:
            余额列表。
        """
        return [b for b in self._balances.values() if b.total > 0]

    def get_all_positions(self) -> dict[str, Decimal]:
        """获取所有持仓（symbol -> quantity）。

        Returns:
            持仓字典。
        """
        result = {}
        for symbol, lots in self._positions.items():
            total_qty = sum(lot.quantity for lot in lots)
            if total_qty > 0:
                result[symbol] = total_qty
        return result

    def get_equity(self, prices: dict[str, Decimal] | None = None) -> Decimal:
        """计算账户权益（余额 + 未实现盈亏）。

        Args:
            prices: 当前价格字典（symbol -> price），None 则只计算余额。

        Returns:
            账户权益。
        """
        # 余额部分
        equity = sum(b.total for b in self._balances.values())

        # 未实现盈亏部分
        if prices:
            for symbol, lots in self._positions.items():
                if symbol in prices:
                    equity += self.calculate_unrealized_pnl(symbol, prices[symbol])

        return equity

    @property
    def entry_count(self) -> int:
        """账本记录总数。"""
        return len(self._entries)

    @property
    def position_symbols(self) -> list[str]:
        """有持仓的标的列表。"""
        return [
            symbol
            for symbol, lots in self._positions.items()
            if any(lot.quantity > 0 for lot in lots)
        ]

    # ──────────────── 内部方法 ────────────────

    def _record_entry(
        self,
        currency: str,
        amount: Decimal,
        balance_before: Decimal,
        balance_after: Decimal,
        reason: str,
        reference_id: str,
    ) -> LedgerEntry:
        """记录账本变动。

        Args:
            currency: 币种。
            amount: 变动金额。
            balance_before: 变动前余额。
            balance_after: 变动后余额。
            reason: 变动原因。
            reference_id: 关联ID。

        Returns:
            账本变动记录。
        """
        import uuid

        self._entry_counter += 1
        entry = LedgerEntry(
            entry_id=str(uuid.uuid4()),
            currency=currency,
            amount=amount,
            balance_before=balance_before,
            balance_after=balance_after,
            reason=reason,
            reference_id=reference_id,
            timestamp_ns=time.time_ns(),
        )
        self._entries.append(entry)
        return entry

    @staticmethod
    def _extract_quote_currency(symbol: str) -> str:
        """从标的符号中提取计价货币。

        Args:
            symbol: 标的符号（如 "BTC/USDT"）。

        Returns:
            计价货币（如 "USDT"）。
        """
        if "/" in symbol:
            return symbol.split("/")[-1]
        return "USDT"  # 默认


# ──────────────────── 账户快照 ────────────────────


@dataclass(frozen=True)
class AccountSnapshot:
    """账户快照（用于报告和持久化）。

    Attributes:
        account_id: 账户ID。
        balances: 各币种余额。
        positions: 各标的持仓数量。
        equity: 账户权益。
        timestamp_ns: 快照时间戳。
    """

    account_id: str
    balances: dict[str, Decimal]
    positions: dict[str, Decimal]
    equity: Decimal
    timestamp_ns: int
