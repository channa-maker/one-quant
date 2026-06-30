"""加密钱包冷热分离模块

交易所资金与自托管钱包分离，热钱包仅留交易所需最小额（默认10%），余下冷存。
充值/提币地址白名单（交易所侧）。
链上充值确认数监控 + 异常转账告警。

铁律：
- 系统不自动提现、不自动转账（人工执行）
- 交易所 API key 仅交易权限，禁用提现
- 充提地址白名单在交易所侧配置
"""

from __future__ import annotations

import time
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from one_quant.infra.logging import get_logger

logger = get_logger("crypto_wallet")


class WalletType(str, Enum):
    """钱包类型"""
    HOT = "hot"      # 热钱包（交易所）
    COLD = "cold"    # 冷钱包（自托管）


class WalletBalance(BaseModel, frozen=True):
    """钱包余额快照"""
    wallet_type: WalletType
    address: str
    currency: str
    balance: Decimal
    timestamp_ns: int = Field(default_factory=time.time_ns)


class TransferRecord(BaseModel, frozen=True):
    """转账记录"""
    from_address: str
    to_address: str
    currency: str
    amount: Decimal
    tx_hash: str
    confirmations: int
    status: str  # pending / confirmed / failed
    timestamp_ns: int = Field(default_factory=time.time_ns)


class RebalanceSuggestion(BaseModel, frozen=True):
    """再平衡建议"""
    action: str  # "hot_to_cold" / "cold_to_hot"
    currency: str
    amount: Decimal
    reason: str


class AbnormalTransfer(BaseModel, frozen=True):
    """异常转账告警"""
    transfer: TransferRecord
    alert_type: str  # large_amount / high_frequency / unknown_address
    severity: str    # P0 / P1 / P2
    message: str


class CryptoWalletManager:
    """加密钱包管理器 — 冷热分离

    核心原则：
    - 热钱包仅留交易所需最小额（默认 10%）
    - 余下资金冷存
    - 充提地址白名单
    - 异常转账实时告警
    """

    def __init__(
        self,
        hot_wallet_ratio: Decimal = Decimal("0.10"),
        large_amount_threshold: Decimal = Decimal("10000"),
        high_frequency_window_sec: int = 3600,
        high_frequency_count: int = 5,
    ) -> None:
        self._hot_ratio = hot_wallet_ratio
        self._large_threshold = large_amount_threshold
        self._freq_window = high_frequency_window_sec
        self._freq_count = high_frequency_count
        self._whitelist: set[str] = set()
        self._balances: dict[str, WalletBalance] = {}
        self._transfers: list[TransferRecord] = []

    # ── 白名单 ──

    def register_whitelist(self, address: str) -> None:
        """注册提币地址白名单

        Args:
            address: 钱包地址
        """
        self._whitelist.add(address)
        logger.info("地址已加入白名单", address=address[:8] + "...")

    def remove_whitelist(self, address: str) -> None:
        """移除白名单地址"""
        self._whitelist.discard(address)

    def check_whitelist(self, address: str) -> bool:
        """检查地址是否在白名单

        Args:
            address: 钱包地址

        Returns:
            是否在白名单中
        """
        return address in self._whitelist

    def get_whitelist(self) -> set[str]:
        """获取白名单"""
        return self._whitelist.copy()

    # ── 余额管理 ──

    def update_balance(self, balance: WalletBalance) -> None:
        """更新钱包余额"""
        key = f"{balance.wallet_type}:{balance.currency}"
        self._balances[key] = balance

    def get_balance(self, wallet_type: WalletType, currency: str) -> Decimal:
        """获取指定钱包余额

        Args:
            wallet_type: 钱包类型
            currency: 币种

        Returns:
            余额
        """
        key = f"{wallet_type}:{currency}"
        balance = self._balances.get(key)
        return balance.balance if balance else Decimal("0")

    def get_total_balance(self, currency: str) -> Decimal:
        """获取总余额（热+冷）

        Args:
            currency: 币种

        Returns:
            总余额
        """
        hot = self.get_balance(WalletType.HOT, currency)
        cold = self.get_balance(WalletType.COLD, currency)
        return hot + cold

    # ── 再平衡 ──

    def check_rebalance_needed(self, currency: str) -> RebalanceSuggestion | None:
        """检查是否需要再平衡

        Args:
            currency: 币种

        Returns:
            再平衡建议，不需要则返回 None
        """
        total = self.get_total_balance(currency)
        if total <= 0:
            return None

        hot = self.get_balance(WalletType.HOT, currency)
        current_ratio = hot / total
        target_hot = total * self._hot_ratio

        # 热钱包过多（>目标比例+5%缓冲）
        if current_ratio > self._hot_ratio + Decimal("0.05"):
            excess = hot - target_hot
            return RebalanceSuggestion(
                action="hot_to_cold",
                currency=currency,
                amount=excess,
                reason=f"热钱包比例 {current_ratio:.1%} 超过目标 {self._hot_ratio:.1%}，建议转 {excess} 到冷钱包",
            )

        # 热钱包不足（<目标比例-5%缓冲）
        if current_ratio < self._hot_ratio - Decimal("0.05"):
            deficit = target_hot - hot
            return RebalanceSuggestion(
                action="cold_to_hot",
                currency=currency,
                amount=deficit,
                reason=f"热钱包比例 {current_ratio:.1%} 低于目标 {self._hot_ratio:.1%}，建议从冷钱包转入 {deficit}",
            )

        return None

    # ── 链上监控 ──

    def record_transfer(self, transfer: TransferRecord) -> None:
        """记录转账"""
        self._transfers.append(transfer)
        logger.info(
            "转账记录",
            from_addr=transfer.from_address[:8] + "...",
            to_addr=transfer.to_address[:8] + "...",
            amount=str(transfer.amount),
            currency=transfer.currency,
            status=transfer.status,
        )

    def monitor_deposit(self, tx_hash: str, expected_confirmations: int = 6) -> dict[str, Any]:
        """监控链上充值确认数

        Args:
            tx_hash: 交易哈希
            expected_confirmations: 期望确认数（默认6）

        Returns:
            监控状态
        """
        for transfer in self._transfers:
            if transfer.tx_hash == tx_hash:
                return {
                    "tx_hash": tx_hash,
                    "confirmations": transfer.confirmations,
                    "expected": expected_confirmations,
                    "confirmed": transfer.confirmations >= expected_confirmations,
                    "status": transfer.status,
                }
        return {"tx_hash": tx_hash, "status": "not_found"}

    def check_abnormal_transfer(self, recent_window_sec: int = 3600) -> list[AbnormalTransfer]:
        """检查异常转账

        Args:
            recent_window_sec: 检查窗口（秒）

        Returns:
            异常转账告警列表
        """
        now_ns = time.time_ns()
        window_ns = recent_window_sec * 1_000_000_000
        recent = [t for t in self._transfers if (now_ns - t.timestamp_ns) < window_ns]

        alerts: list[AbnormalTransfer] = []

        # 1. 大额转账
        for transfer in recent:
            if transfer.amount >= self._large_threshold:
                alerts.append(AbnormalTransfer(
                    transfer=transfer,
                    alert_type="large_amount",
                    severity="P1",
                    message=f"大额转账: {transfer.amount} {transfer.currency}",
                ))

        # 2. 高频转账
        if len(recent) >= self._freq_count:
            alerts.append(AbnormalTransfer(
                transfer=recent[-1],
                alert_type="high_frequency",
                severity="P0",
                message=f"{recent_window_sec}秒内 {len(recent)} 笔转账，疑似异常",
            ))

        # 3. 陌生地址
        for transfer in recent:
            if transfer.to_address not in self._whitelist:
                alerts.append(AbnormalTransfer(
                    transfer=transfer,
                    alert_type="unknown_address",
                    severity="P0",
                    message=f"向非白名单地址转账: {transfer.to_address[:8]}...",
                ))

        return alerts
