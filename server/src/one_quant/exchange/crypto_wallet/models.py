"""
加密钱包 — 数据类定义
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from decimal import Decimal

from one_quant.exchange.crypto_wallet.enums import (
    DEFAULT_MIN_CONFIRMATIONS,
    AlertLevel,
    DepositStatus,
    WalletType,
)


@dataclass
class WalletBalance:
    """钱包余额快照

    Attributes:
        wallet_type: 钱包类型
        address: 钱包地址
        asset: 资产符号（如 BTC、ETH）
        available: 可用余额
        frozen: 冻结余额（挂单占用）
        total: 总余额 = available + frozen
        timestamp_ns: 快照时间戳（纳秒）
    """

    wallet_type: WalletType
    address: str
    asset: str
    available: Decimal
    frozen: Decimal
    timestamp_ns: int = 0

    def __post_init__(self) -> None:
        if self.timestamp_ns == 0:
            self.timestamp_ns = time.time_ns()

    @property
    def total(self) -> Decimal:
        """总余额 = 可用 + 冻结"""
        return self.available + self.frozen


@dataclass
class AddressEntry:
    """白名单地址条目

    Attributes:
        address: 链上地址
        asset: 资产符号
        chain: 链名称（如 BTC、ETH、TRX）
        label: 地址标签（如 "冷钱包-主库"）
        is_active: 是否启用
        added_at: 添加时间戳（纳秒）
        added_by: 添加人
    """

    address: str
    asset: str
    chain: str
    label: str = ""
    is_active: bool = True
    added_at: int = 0
    added_by: str = "system"

    def __post_init__(self) -> None:
        if self.added_at == 0:
            self.added_at = time.time_ns()


@dataclass
class DepositRecord:
    """充值记录

    Attributes:
        tx_hash: 链上交易哈希
        asset: 资产符号
        chain: 链名称
        from_address: 来源地址
        to_address: 目标地址
        amount: 充值金额
        confirmations: 当前确认数
        required_confirmations: 所需确认数
        status: 充值状态
        first_seen_ns: 首次发现时间戳
        confirmed_ns: 确认完成时间戳（未确认为 0）
    """

    tx_hash: str
    asset: str
    chain: str
    from_address: str
    to_address: str
    amount: Decimal
    confirmations: int = 0
    required_confirmations: int = DEFAULT_MIN_CONFIRMATIONS
    status: DepositStatus = DepositStatus.PENDING
    first_seen_ns: int = 0
    confirmed_ns: int = 0

    def __post_init__(self) -> None:
        if self.first_seen_ns == 0:
            self.first_seen_ns = time.time_ns()

    @property
    def is_confirmed(self) -> bool:
        """是否已达到确认数要求"""
        return self.confirmations >= self.required_confirmations


@dataclass
class RebalanceSuggestion:
    """再平衡建议

    Attributes:
        asset: 资产符号
        direction: 调整方向（"hot_to_cold" 或 "cold_to_hot"）
        amount: 建议转账金额
        reason: 建议原因
        hot_ratio_current: 当前热钱包比例
        hot_ratio_target: 目标热钱包比例
        timestamp_ns: 建议生成时间戳
    """

    asset: str
    direction: str
    amount: Decimal
    reason: str
    hot_ratio_current: Decimal
    hot_ratio_target: Decimal
    timestamp_ns: int = 0

    def __post_init__(self) -> None:
        if self.timestamp_ns == 0:
            self.timestamp_ns = time.time_ns()


@dataclass
class TransferAlert:
    """转账告警

    Attributes:
        alert_level: 告警级别
        alert_type: 告警类型（如 "large_transfer", "whitelist_violation"）
        asset: 资产符号
        amount: 转账金额
        from_address: 来源地址
        to_address: 目标地址
        message: 告警详情
        timestamp_ns: 告警时间戳
    """

    alert_level: AlertLevel
    alert_type: str
    asset: str
    amount: Decimal
    from_address: str
    to_address: str
    message: str
    timestamp_ns: int = 0

    def __post_init__(self) -> None:
        if self.timestamp_ns == 0:
            self.timestamp_ns = time.time_ns()
