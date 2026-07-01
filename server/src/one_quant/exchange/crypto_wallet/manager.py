"""
加密钱包 — 核心管理器
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from decimal import ROUND_DOWN, Decimal
from typing import Any

from one_quant.exchange.crypto_wallet.enums import (
    CHAIN_CONFIRMATIONS,
    DEFAULT_ALERT_COOLDOWN_SEC,
    DEFAULT_HOT_RATIO,
    DEFAULT_MIN_CONFIRMATIONS,
    DEFAULT_REBALANCE_THRESHOLD,
    LARGE_TRANSFER_THRESHOLDS,
    AlertLevel,
    DepositStatus,
    WalletType,
)
from one_quant.exchange.crypto_wallet.models import (
    AddressEntry,
    DepositRecord,
    RebalanceSuggestion,
    TransferAlert,
    WalletBalance,
)
from one_quant.infra.logging import get_logger

logger = get_logger(__name__)


def _alert_priority(level: AlertLevel) -> int:
    """告警级别优先级排序。"""
    return {
        AlertLevel.INFO: 1,
        AlertLevel.WARNING: 2,
        AlertLevel.CRITICAL: 3,
    }.get(level, 0)


class CryptoWalletManager:
    """加密钱包冷热分离管理器。

    核心功能：
    1. 热钱包仅留交易所需最小额（默认 10%），余下冷存储
    2. 地址白名单：所有转出地址必须预先登记
    3. 再平衡建议：定时检查余额比例，偏离阈值时生成建议
    4. 充值确认数监控：按链配置确认数，达标后触发入账
    5. 异常转账告警：大额、非白名单、高频触发多级告警

    铁律：
    - 系统不自动提现、不自动转账（人工执行）
    - 交易所 API key 仅交易权限，禁用提现
    - 充提地址白名单在交易所侧配置

    使用示例::

        manager = CryptoWalletManager()
        manager.register_hot_wallet("hot_addr_001", "BTC")
        manager.register_cold_wallet("cold_addr_001", "BTC")
        manager.add_whitelist_address("cold_addr_001", "BTC", "BTC", "冷钱包-主库")

        # 获取再平衡建议
        suggestions = manager.get_rebalance_suggestions()

        # 更新充值确认数
        manager.update_deposit_confirmations("tx_hash_001", 6)
    """

    def __init__(
        self,
        hot_ratio: Decimal = DEFAULT_HOT_RATIO,
        rebalance_threshold: Decimal = DEFAULT_REBALANCE_THRESHOLD,
    ) -> None:
        """初始化钱包管理器。

        Args:
            hot_ratio: 热钱包目标比例（默认 10%）
            rebalance_threshold: 再平衡触发阈值（默认 5%）
        """
        self._hot_ratio = hot_ratio
        self._rebalance_threshold = rebalance_threshold

        # 钱包余额：{wallet_type: {address: WalletBalance}}
        self._balances: dict[str, dict[str, WalletBalance]] = {wt.value: {} for wt in WalletType}

        # 白名单：{(asset, address): AddressEntry}
        self._whitelist: dict[tuple[str, str], AddressEntry] = {}

        # 充值记录：{tx_hash: DepositRecord}
        self._deposits: dict[str, DepositRecord] = {}

        # 告警历史：列表
        self._alerts: list[TransferAlert] = []

        # 告警冷却：{alert_key: last_alert_ns}
        self._alert_cooldown: dict[str, int] = {}

        # 充值确认回调
        self._deposit_callbacks: list[Callable[[DepositRecord], Awaitable[None]]] = []

        # 告警回调
        self._alert_callbacks: list[Callable[[TransferAlert], Awaitable[None]]] = []

        logger.info(
            "钱包管理器初始化: 热钱包比例=%.2f%%, 再平衡阈值=%.2f%%",
            float(hot_ratio * 100),
            float(rebalance_threshold * 100),
        )

    # ──────────────── 钱包注册 ────────────────

    def register_hot_wallet(self, address: str, asset: str) -> None:
        """注册热钱包地址。"""
        self._balances[WalletType.HOT.value][address] = WalletBalance(
            wallet_type=WalletType.HOT,
            address=address,
            asset=asset,
            available=Decimal("0"),
            frozen=Decimal("0"),
        )
        logger.info("热钱包注册: %s (%s)", address, asset)

    def register_cold_wallet(self, address: str, asset: str) -> None:
        """注册冷钱包地址。"""
        self._balances[WalletType.COLD.value][address] = WalletBalance(
            wallet_type=WalletType.COLD,
            address=address,
            asset=asset,
            available=Decimal("0"),
            frozen=Decimal("0"),
        )
        logger.info("冷钱包注册: %s (%s)", address, asset)

    def register_exchange_wallet(self, address: str, asset: str) -> None:
        """注册交易所子钱包地址。"""
        self._balances[WalletType.EXCHANGE.value][address] = WalletBalance(
            wallet_type=WalletType.EXCHANGE,
            address=address,
            asset=asset,
            available=Decimal("0"),
            frozen=Decimal("0"),
        )
        logger.info("交易所钱包注册: %s (%s)", address, asset)

    # ──────────────── 余额更新 ────────────────

    def update_balance(
        self,
        wallet_type: WalletType,
        address: str,
        available: Decimal,
        frozen: Decimal = Decimal("0"),
    ) -> None:
        """更新钱包余额。"""
        wallets = self._balances.get(wallet_type.value, {})
        if address not in wallets:
            logger.warning("钱包未注册: %s/%s，自动创建", wallet_type.value, address)
            wallets[address] = WalletBalance(
                wallet_type=wallet_type,
                address=address,
                asset="UNKNOWN",
                available=available,
                frozen=frozen,
            )
        else:
            old = wallets[address]
            wallets[address] = WalletBalance(
                wallet_type=old.wallet_type,
                address=old.address,
                asset=old.asset,
                available=available,
                frozen=frozen,
            )

    def get_balance(self, wallet_type: WalletType, asset: str | None = None) -> list[WalletBalance]:
        """获取指定类型钱包余额列表。"""
        wallets = self._balances.get(wallet_type.value, {})
        balances = list(wallets.values())
        if asset:
            balances = [b for b in balances if b.asset == asset]
        return balances

    def get_total_balance(self, asset: str) -> dict[str, Decimal]:
        """获取某资产在各钱包类型的总余额。"""
        result: dict[str, Decimal] = {}
        for wt in WalletType:
            total = sum(
                (b.total for b in self.get_balance(wt, asset)),
                Decimal("0"),
            )
            result[wt.value] = total
        return result

    # ──────────────── 白名单管理 ────────────────

    def add_whitelist_address(
        self,
        address: str,
        asset: str,
        chain: str,
        label: str = "",
        added_by: str = "system",
    ) -> None:
        """添加白名单地址。"""
        key = (asset, address)
        self._whitelist[key] = AddressEntry(
            address=address,
            asset=asset,
            chain=chain,
            label=label,
            added_by=added_by,
        )
        logger.info("白名单添加: %s (%s/%s) by %s", address, asset, chain, added_by)

    def remove_whitelist_address(self, address: str, asset: str) -> bool:
        """移除白名单地址（软删除：标记为非活跃）。"""
        key = (asset, address)
        entry = self._whitelist.get(key)
        if entry is None:
            logger.warning("白名单地址不存在: %s (%s)", address, asset)
            return False
        entry.is_active = False
        logger.info("白名单移除: %s (%s)", address, asset)
        return True

    def is_whitelisted(self, address: str, asset: str) -> bool:
        """检查地址是否在白名单中且活跃。"""
        key = (asset, address)
        entry = self._whitelist.get(key)
        return entry is not None and entry.is_active

    def get_whitelist(self, asset: str | None = None) -> list[AddressEntry]:
        """获取白名单列表。"""
        entries = [e for e in self._whitelist.values() if e.is_active]
        if asset:
            entries = [e for e in entries if e.asset == asset]
        return entries

    # ──────────────── 再平衡建议 ────────────────

    def get_rebalance_suggestions(self, asset: str | None = None) -> list[RebalanceSuggestion]:
        """获取再平衡建议。"""
        suggestions: list[RebalanceSuggestion] = []

        assets_to_check: set[str] = set()
        if asset:
            assets_to_check.add(asset)
        else:
            for wt_balances in self._balances.values():
                for balance in wt_balances.values():
                    assets_to_check.add(balance.asset)

        for ast in assets_to_check:
            suggestion = self._check_asset_balance(ast)
            if suggestion:
                suggestions.append(suggestion)

        return suggestions

    def _check_asset_balance(self, asset: str) -> RebalanceSuggestion | None:
        """检查单个资产的冷热比例，必要时生成建议。"""
        totals = self.get_total_balance(asset)
        hot_total = totals.get(WalletType.HOT.value, Decimal("0"))
        cold_total = totals.get(WalletType.COLD.value, Decimal("0"))
        combined = hot_total + cold_total

        if combined == Decimal("0"):
            return None

        current_ratio = (hot_total / combined).quantize(Decimal("0.0001"), rounding=ROUND_DOWN)

        deviation = abs(current_ratio - self._hot_ratio)
        if deviation <= self._rebalance_threshold:
            return None

        target_hot = (combined * self._hot_ratio).quantize(
            Decimal("0.00000001"), rounding=ROUND_DOWN
        )

        if current_ratio > self._hot_ratio:
            transfer_amount = hot_total - target_hot
            direction = "hot_to_cold"
            reason = (
                f"热钱包比例 {current_ratio:.2%} 超过目标 {self._hot_ratio:.2%}，"
                f"建议将 {transfer_amount} {asset} 转入冷钱包"
            )
        else:
            transfer_amount = target_hot - hot_total
            direction = "cold_to_hot"
            reason = (
                f"热钱包比例 {current_ratio:.2%} 低于目标 {self._hot_ratio:.2%}，"
                f"建议从冷钱包转入 {transfer_amount} {asset}"
            )

        return RebalanceSuggestion(
            asset=asset,
            direction=direction,
            amount=transfer_amount,
            reason=reason,
            hot_ratio_current=current_ratio,
            hot_ratio_target=self._hot_ratio,
        )

    # ──────────────── 充值确认监控 ────────────────

    def register_deposit(
        self,
        tx_hash: str,
        asset: str,
        chain: str,
        from_address: str,
        to_address: str,
        amount: Decimal,
    ) -> DepositRecord:
        """注册新的充值记录，开始监控确认数。"""
        required = CHAIN_CONFIRMATIONS.get(chain, DEFAULT_MIN_CONFIRMATIONS)

        record = DepositRecord(
            tx_hash=tx_hash,
            asset=asset,
            chain=chain,
            from_address=from_address,
            to_address=to_address,
            amount=amount,
            required_confirmations=required,
            status=DepositStatus.PENDING,
        )

        self._deposits[tx_hash] = record
        logger.info(
            "充值注册: %s %.8f %s (所需确认数: %d)",
            tx_hash[:16],
            float(amount),
            asset,
            required,
        )
        return record

    async def update_deposit_confirmations(
        self, tx_hash: str, confirmations: int
    ) -> DepositRecord | None:
        """更新充值确认数，达标后自动入账。"""
        record = self._deposits.get(tx_hash)
        if record is None:
            logger.warning("充值记录不存在: %s", tx_hash)
            return None

        old_status = record.status
        record.confirmations = confirmations

        if confirmations <= 0:
            record.status = DepositStatus.PENDING
        elif confirmations < record.required_confirmations:
            record.status = DepositStatus.CONFIRMING
        else:
            record.status = DepositStatus.COMPLETED
            record.confirmed_ns = time.time_ns()

            if old_status != DepositStatus.COMPLETED:
                logger.info(
                    "充值确认完成: %s (%.8f %s, %d/%d 确认)",
                    tx_hash[:16],
                    float(record.amount),
                    record.asset,
                    confirmations,
                    record.required_confirmations,
                )
                self._credit_deposit(record)
                for cb in self._deposit_callbacks:
                    try:
                        await cb(record)
                    except Exception:
                        logger.exception("充值确认回调异常")

        return record

    def _credit_deposit(self, record: DepositRecord) -> None:
        """将确认完成的充值金额加入目标钱包余额。"""
        for wt_balances in self._balances.values():
            if record.to_address in wt_balances:
                balance = wt_balances[record.to_address]
                if balance.asset == record.asset:
                    wt_balances[record.to_address] = WalletBalance(
                        wallet_type=balance.wallet_type,
                        address=balance.address,
                        asset=balance.asset,
                        available=balance.available + record.amount,
                        frozen=balance.frozen,
                    )
                    logger.info(
                        "充值入账: %s +%.8f %s",
                        record.to_address[:16],
                        float(record.amount),
                        record.asset,
                    )
                    return

        logger.warning("充值目标钱包未注册: %s，金额未入账", record.to_address)

    def get_pending_deposits(self, asset: str | None = None) -> list[DepositRecord]:
        """获取待确认的充值记录。"""
        pending = [
            r
            for r in self._deposits.values()
            if r.status in (DepositStatus.PENDING, DepositStatus.CONFIRMING)
        ]
        if asset:
            pending = [r for r in pending if r.asset == asset]
        return pending

    def on_deposit_confirmed(self, callback: Callable[[DepositRecord], Awaitable[None]]) -> None:
        """注册充值确认回调。"""
        self._deposit_callbacks.append(callback)

    # ──────────────── 转账异常告警 ────────────────

    async def check_transfer(
        self,
        asset: str,
        amount: Decimal,
        from_address: str,
        to_address: str,
    ) -> TransferAlert | None:
        """检查转账是否异常，必要时触发告警。"""
        alerts: list[TransferAlert] = []

        if not self.is_whitelisted(to_address, asset):
            alert = TransferAlert(
                alert_level=AlertLevel.CRITICAL,
                alert_type="whitelist_violation",
                asset=asset,
                amount=amount,
                from_address=from_address,
                to_address=to_address,
                message=f"转出地址 {to_address[:16]}... 不在 {asset} 白名单中",
            )
            alerts.append(alert)

        threshold = LARGE_TRANSFER_THRESHOLDS.get(asset)
        if threshold and amount >= threshold:
            alert = TransferAlert(
                alert_level=AlertLevel.WARNING,
                alert_type="large_transfer",
                asset=asset,
                amount=amount,
                from_address=from_address,
                to_address=to_address,
                message=f"大额转账: {amount} {asset} (阈值: {threshold})",
            )
            alerts.append(alert)

        recent_count = self._count_recent_transfers(asset, from_address)
        if recent_count >= 3:
            alert = TransferAlert(
                alert_level=AlertLevel.WARNING,
                alert_type="high_frequency",
                asset=asset,
                amount=amount,
                from_address=from_address,
                to_address=to_address,
                message=(
                    f"高频转账: {from_address[:16]}... 5分钟内 {recent_count + 1} 次 {asset} 转账"
                ),
            )
            alerts.append(alert)

        if alerts:
            highest = max(alerts, key=lambda a: _alert_priority(a.alert_level))
            self._alerts.append(highest)
            for cb in self._alert_callbacks:
                try:
                    await cb(highest)
                except Exception:
                    logger.exception("告警回调异常")
            return highest

        return None

    def _count_recent_transfers(self, asset: str, from_address: str) -> int:
        """统计近 5 分钟内同资产同地址的告警次数。"""
        now = time.time_ns()
        cooldown_ns = DEFAULT_ALERT_COOLDOWN_SEC * 1_000_000_000
        count = 0
        for a in self._alerts:
            if (
                a.asset == asset
                and a.from_address == from_address
                and (now - a.timestamp_ns) < cooldown_ns
            ):
                count += 1
        return count

    def on_alert(self, callback: Callable[[TransferAlert], Awaitable[None]]) -> None:
        """注册告警回调。"""
        self._alert_callbacks.append(callback)

    def get_alerts(
        self,
        level: AlertLevel | None = None,
        limit: int = 100,
    ) -> list[TransferAlert]:
        """获取告警历史。"""
        alerts = list(reversed(self._alerts))
        if level:
            alerts = [a for a in alerts if a.alert_level == level]
        return alerts[:limit]

    # ──────────────── 转账预检 ────────────────

    async def validate_transfer(
        self,
        asset: str,
        amount: Decimal,
        from_address: str,
        to_address: str,
        wallet_type: WalletType = WalletType.HOT,
    ) -> tuple[bool, str]:
        """转账前预检。"""
        balances = self.get_balance(wallet_type, asset)
        source_balance = next((b for b in balances if b.address == from_address), None)
        if source_balance is None:
            return False, f"来源钱包未注册: {from_address[:16]}..."

        if source_balance.available < amount:
            return False, (
                f"余额不足: 可用 {source_balance.available} {asset}，需要 {amount} {asset}"
            )

        if not self.is_whitelisted(to_address, asset):
            return False, f"目标地址不在 {asset} 白名单中"

        alert = await self.check_transfer(asset, amount, from_address, to_address)
        if alert and alert.alert_level == AlertLevel.CRITICAL:
            return False, f"异常告警阻断: {alert.message}"

        return True, "转账预检通过"

    # ──────────────── 统计与快照 ────────────────

    def snapshot(self) -> dict[str, Any]:
        """生成钱包全景快照。"""
        asset_totals: dict[str, dict[str, str]] = {}
        all_assets: set[str] = set()
        for wt_balances in self._balances.values():
            for b in wt_balances.values():
                all_assets.add(b.asset)

        for ast in sorted(all_assets):
            totals = self.get_total_balance(ast)
            asset_totals[ast] = {k: str(v) for k, v in totals.items()}

        pending = self.get_pending_deposits()
        return {
            "hot_ratio_target": str(self._hot_ratio),
            "rebalance_threshold": str(self._rebalance_threshold),
            "balances": asset_totals,
            "whitelist_count": len([e for e in self._whitelist.values() if e.is_active]),
            "pending_deposits": len(pending),
            "total_alerts": len(self._alerts),
            "critical_alerts": len(
                [a for a in self._alerts if a.alert_level == AlertLevel.CRITICAL]
            ),
            "timestamp_ns": time.time_ns(),
        }
