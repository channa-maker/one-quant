"""
ONE量化 - 加密钱包管理器测试 (crypto_wallet.py)

覆盖：
  - 钱包注册 (热/冷/交易所)
  - 余额更新与查询
  - 白名单管理 (添加/移除/检查)
  - 再平衡建议
  - 充值确认监控 (注册/更新/回调)
  - 转账异常告警 (白名单/大额/高频)
  - 转账预检
  - 快照统计
  - 边界值测试
"""

from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from one_quant.exchange.crypto_wallet import (
    DEFAULT_HOT_RATIO,
    DEFAULT_REBALANCE_THRESHOLD,
    LARGE_TRANSFER_THRESHOLDS,
    AlertLevel,
    CryptoWalletManager,
    DepositRecord,
    DepositStatus,
    WalletBalance,
    WalletType,
    _alert_priority,
)


class TestEnums:
    """枚举测试"""

    def test_wallet_type_values(self):
        assert WalletType.HOT == "hot"
        assert WalletType.COLD == "cold"
        assert WalletType.EXCHANGE == "exchange"

    def test_deposit_status_values(self):
        assert DepositStatus.PENDING == "pending"
        assert DepositStatus.CONFIRMING == "confirming"
        assert DepositStatus.COMPLETED == "completed"
        assert DepositStatus.FAILED == "failed"

    def test_alert_level_values(self):
        assert AlertLevel.INFO == "info"
        assert AlertLevel.WARNING == "warning"
        assert AlertLevel.CRITICAL == "critical"


class TestWalletBalance:
    """WalletBalance 数据类测试"""

    def test_total_property(self):
        balance = WalletBalance(
            wallet_type=WalletType.HOT,
            address="addr",
            asset="BTC",
            available=Decimal("1.5"),
            frozen=Decimal("0.5"),
        )
        assert balance.total == Decimal("2.0")

    def test_auto_timestamp(self):
        balance = WalletBalance(
            wallet_type=WalletType.HOT,
            address="addr",
            asset="BTC",
            available=Decimal("1"),
            frozen=Decimal("0"),
        )
        assert balance.timestamp_ns > 0

    def test_custom_timestamp(self):
        balance = WalletBalance(
            wallet_type=WalletType.HOT,
            address="addr",
            asset="BTC",
            available=Decimal("1"),
            frozen=Decimal("0"),
            timestamp_ns=12345,
        )
        assert balance.timestamp_ns == 12345


class TestDepositRecord:
    """DepositRecord 数据类测试"""

    def test_is_confirmed(self):
        record = DepositRecord(
            tx_hash="tx1",
            asset="BTC",
            chain="BTC",
            from_address="from",
            to_address="to",
            amount=Decimal("1"),
            confirmations=6,
            required_confirmations=6,
        )
        assert record.is_confirmed is True

    def test_is_not_confirmed(self):
        record = DepositRecord(
            tx_hash="tx1",
            asset="BTC",
            chain="BTC",
            from_address="from",
            to_address="to",
            amount=Decimal("1"),
            confirmations=3,
            required_confirmations=6,
        )
        assert record.is_confirmed is False

    def test_auto_timestamp(self):
        record = DepositRecord(
            tx_hash="tx1",
            asset="BTC",
            chain="BTC",
            from_address="from",
            to_address="to",
            amount=Decimal("1"),
        )
        assert record.first_seen_ns > 0


class TestAlertPriority:
    """告警优先级测试"""

    def test_critical_highest(self):
        assert _alert_priority(AlertLevel.CRITICAL) > _alert_priority(AlertLevel.WARNING)

    def test_warning_higher_than_info(self):
        assert _alert_priority(AlertLevel.WARNING) > _alert_priority(AlertLevel.INFO)

    def test_unknown_returns_zero(self):
        assert _alert_priority("unknown") == 0


class TestWalletRegistration:
    """钱包注册测试"""

    def test_register_hot_wallet(self):
        manager = CryptoWalletManager()
        manager.register_hot_wallet("addr1", "BTC")
        balances = manager.get_balance(WalletType.HOT)
        assert len(balances) == 1
        assert balances[0].address == "addr1"
        assert balances[0].asset == "BTC"

    def test_register_cold_wallet(self):
        manager = CryptoWalletManager()
        manager.register_cold_wallet("addr1", "BTC")
        balances = manager.get_balance(WalletType.COLD)
        assert len(balances) == 1

    def test_register_exchange_wallet(self):
        manager = CryptoWalletManager()
        manager.register_exchange_wallet("addr1", "BTC")
        balances = manager.get_balance(WalletType.EXCHANGE)
        assert len(balances) == 1

    def test_initial_balance_zero(self):
        manager = CryptoWalletManager()
        manager.register_hot_wallet("addr1", "BTC")
        balance = manager.get_balance(WalletType.HOT)[0]
        assert balance.available == Decimal("0")
        assert balance.frozen == Decimal("0")
        assert balance.total == Decimal("0")


class TestBalanceUpdate:
    """余额更新测试"""

    def test_update_balance(self):
        manager = CryptoWalletManager()
        manager.register_hot_wallet("addr1", "BTC")
        manager.update_balance(WalletType.HOT, "addr1", Decimal("1.5"), Decimal("0.5"))
        balance = manager.get_balance(WalletType.HOT)[0]
        assert balance.available == Decimal("1.5")
        assert balance.frozen == Decimal("0.5")

    def test_update_unregistered_wallet(self):
        """未注册钱包自动创建。"""
        manager = CryptoWalletManager()
        manager.update_balance(WalletType.HOT, "new_addr", Decimal("10"))
        balances = manager.get_balance(WalletType.HOT)
        assert len(balances) == 1

    def test_get_balance_with_asset_filter(self):
        manager = CryptoWalletManager()
        manager.register_hot_wallet("addr1", "BTC")
        manager.register_hot_wallet("addr2", "ETH")
        manager.update_balance(WalletType.HOT, "addr1", Decimal("1"))
        manager.update_balance(WalletType.HOT, "addr2", Decimal("10"))

        btc_only = manager.get_balance(WalletType.HOT, asset="BTC")
        assert len(btc_only) == 1
        assert btc_only[0].asset == "BTC"

    def test_get_total_balance(self):
        manager = CryptoWalletManager()
        manager.register_hot_wallet("addr1", "BTC")
        manager.register_cold_wallet("addr2", "BTC")
        manager.update_balance(WalletType.HOT, "addr1", Decimal("1"))
        manager.update_balance(WalletType.COLD, "addr2", Decimal("5"))

        totals = manager.get_total_balance("BTC")
        assert totals["hot"] == Decimal("1")
        assert totals["cold"] == Decimal("5")

    def test_get_total_balance_nonexistent_asset(self):
        manager = CryptoWalletManager()
        totals = manager.get_total_balance("DOGE")
        assert all(v == Decimal("0") for v in totals.values())


class TestWhitelist:
    """白名单管理测试"""

    def test_add_whitelist_address(self):
        manager = CryptoWalletManager()
        manager.add_whitelist_address("addr1", "BTC", "BTC", label="冷钱包")
        assert manager.is_whitelisted("addr1", "BTC") is True

    def test_is_whitelisted_false(self):
        manager = CryptoWalletManager()
        assert manager.is_whitelisted("addr1", "BTC") is False

    def test_remove_whitelist_address(self):
        manager = CryptoWalletManager()
        manager.add_whitelist_address("addr1", "BTC", "BTC")
        result = manager.remove_whitelist_address("addr1", "BTC")
        assert result is True
        assert manager.is_whitelisted("addr1", "BTC") is False

    def test_remove_nonexistent_address(self):
        manager = CryptoWalletManager()
        result = manager.remove_whitelist_address("addr1", "BTC")
        assert result is False

    def test_get_whitelist_all(self):
        manager = CryptoWalletManager()
        manager.add_whitelist_address("addr1", "BTC", "BTC")
        manager.add_whitelist_address("addr2", "ETH", "ETH")
        entries = manager.get_whitelist()
        assert len(entries) == 2

    def test_get_whitelist_by_asset(self):
        manager = CryptoWalletManager()
        manager.add_whitelist_address("addr1", "BTC", "BTC")
        manager.add_whitelist_address("addr2", "ETH", "ETH")
        btc_entries = manager.get_whitelist(asset="BTC")
        assert len(btc_entries) == 1
        assert btc_entries[0].asset == "BTC"

    def test_removed_address_excluded(self):
        """移除的地址不在白名单中。"""
        manager = CryptoWalletManager()
        manager.add_whitelist_address("addr1", "BTC", "BTC")
        manager.remove_whitelist_address("addr1", "BTC")
        entries = manager.get_whitelist()
        assert len(entries) == 0

    def test_whitelist_multiple_addresses(self):
        manager = CryptoWalletManager()
        for i in range(10):
            manager.add_whitelist_address(f"addr{i}", "BTC", "BTC")
        assert len(manager.get_whitelist()) == 10


class TestRebalance:
    """再平衡建议测试"""

    def test_no_suggestion_when_balanced(self):
        """平衡时无建议。"""
        manager = CryptoWalletManager(
            hot_ratio=Decimal("0.10"), rebalance_threshold=Decimal("0.05")
        )
        manager.register_hot_wallet("hot1", "BTC")
        manager.register_cold_wallet("cold1", "BTC")
        manager.update_balance(WalletType.HOT, "hot1", Decimal("1"))
        manager.update_balance(WalletType.COLD, "cold1", Decimal("9"))

        suggestions = manager.get_rebalance_suggestions("BTC")
        assert len(suggestions) == 0

    def test_suggestion_hot_too_high(self):
        """热钱包过多时建议热→冷。"""
        manager = CryptoWalletManager(
            hot_ratio=Decimal("0.10"), rebalance_threshold=Decimal("0.05")
        )
        manager.register_hot_wallet("hot1", "BTC")
        manager.register_cold_wallet("cold1", "BTC")
        manager.update_balance(WalletType.HOT, "hot1", Decimal("5"))
        manager.update_balance(WalletType.COLD, "cold1", Decimal("5"))

        suggestions = manager.get_rebalance_suggestions("BTC")
        assert len(suggestions) == 1
        assert suggestions[0].direction == "hot_to_cold"
        assert suggestions[0].asset == "BTC"

    def test_suggestion_hot_too_low(self):
        """热钱包不足时建议冷→热。"""
        manager = CryptoWalletManager(
            hot_ratio=Decimal("0.20"), rebalance_threshold=Decimal("0.05")
        )
        manager.register_hot_wallet("hot1", "BTC")
        manager.register_cold_wallet("cold1", "BTC")
        manager.update_balance(WalletType.HOT, "hot1", Decimal("0.5"))
        manager.update_balance(WalletType.COLD, "cold1", Decimal("9.5"))

        suggestions = manager.get_rebalance_suggestions("BTC")
        assert len(suggestions) == 1
        assert suggestions[0].direction == "cold_to_hot"

    def test_no_suggestion_zero_balance(self):
        """零余额无建议。"""
        manager = CryptoWalletManager()
        manager.register_hot_wallet("hot1", "BTC")
        manager.register_cold_wallet("cold1", "BTC")

        suggestions = manager.get_rebalance_suggestions("BTC")
        assert len(suggestions) == 0

    def test_suggestion_all_assets(self):
        """检查所有资产。"""
        manager = CryptoWalletManager(
            hot_ratio=Decimal("0.10"), rebalance_threshold=Decimal("0.05")
        )
        manager.register_hot_wallet("hot_btc", "BTC")
        manager.register_cold_wallet("cold_btc", "BTC")
        manager.register_hot_wallet("hot_eth", "ETH")
        manager.register_cold_wallet("cold_eth", "ETH")
        manager.update_balance(WalletType.HOT, "hot_btc", Decimal("5"))
        manager.update_balance(WalletType.COLD, "cold_btc", Decimal("5"))
        manager.update_balance(WalletType.HOT, "hot_eth", Decimal("5"))
        manager.update_balance(WalletType.COLD, "cold_eth", Decimal("5"))

        suggestions = manager.get_rebalance_suggestions()
        assert len(suggestions) == 2

    def test_suggestion_amount_positive(self):
        """建议金额为正。"""
        manager = CryptoWalletManager(
            hot_ratio=Decimal("0.10"), rebalance_threshold=Decimal("0.05")
        )
        manager.register_hot_wallet("hot1", "BTC")
        manager.register_cold_wallet("cold1", "BTC")
        manager.update_balance(WalletType.HOT, "hot1", Decimal("5"))
        manager.update_balance(WalletType.COLD, "cold1", Decimal("5"))

        suggestions = manager.get_rebalance_suggestions("BTC")
        assert suggestions[0].amount > Decimal("0")

    def test_suggestion_has_ratio_info(self):
        """建议包含比例信息。"""
        manager = CryptoWalletManager(
            hot_ratio=Decimal("0.10"), rebalance_threshold=Decimal("0.05")
        )
        manager.register_hot_wallet("hot1", "BTC")
        manager.register_cold_wallet("cold1", "BTC")
        manager.update_balance(WalletType.HOT, "hot1", Decimal("5"))
        manager.update_balance(WalletType.COLD, "cold1", Decimal("5"))

        suggestions = manager.get_rebalance_suggestions("BTC")
        s = suggestions[0]
        assert s.hot_ratio_current > Decimal("0")
        assert s.hot_ratio_target == Decimal("0.10")


class TestDepositMonitoring:
    """充值确认监控测试"""

    def test_register_deposit(self):
        manager = CryptoWalletManager()
        record = manager.register_deposit("tx1", "BTC", "BTC", "from", "to", Decimal("1"))
        assert record.tx_hash == "tx1"
        assert record.status == DepositStatus.PENDING

    def test_register_deposit_default_confirmations(self):
        """默认确认数按链配置。"""
        manager = CryptoWalletManager()
        record = manager.register_deposit("tx1", "BTC", "BTC", "from", "to", Decimal("1"))
        assert record.required_confirmations == 6  # BTC 默认

    @pytest.mark.asyncio
    async def test_update_confirmations_pending(self):
        """确认数为 0 时状态为 PENDING。"""
        manager = CryptoWalletManager()
        manager.register_deposit("tx1", "BTC", "BTC", "from", "to", Decimal("1"))
        record = await manager.update_deposit_confirmations("tx1", 0)
        assert record.status == DepositStatus.PENDING

    @pytest.mark.asyncio
    async def test_update_confirmations_confirming(self):
        """部分确认时状态为 CONFIRMING。"""
        manager = CryptoWalletManager()
        manager.register_deposit("tx1", "BTC", "BTC", "from", "to", Decimal("1"))
        record = await manager.update_deposit_confirmations("tx1", 3)
        assert record.status == DepositStatus.CONFIRMING

    @pytest.mark.asyncio
    async def test_update_confirmations_completed(self):
        """达到确认数时状态为 COMPLETED。"""
        manager = CryptoWalletManager()
        manager.register_deposit("tx1", "BTC", "BTC", "from", "to", Decimal("1"))
        record = await manager.update_deposit_confirmations("tx1", 6)
        assert record.status == DepositStatus.COMPLETED
        assert record.confirmed_ns > 0

    @pytest.mark.asyncio
    async def test_update_nonexistent_deposit(self):
        """不存在的充值记录返回 None。"""
        manager = CryptoWalletManager()
        record = await manager.update_deposit_confirmations("nonexistent", 6)
        assert record is None

    @pytest.mark.asyncio
    async def test_deposit_callback_triggered(self):
        """确认完成时触发回调。"""
        manager = CryptoWalletManager()
        callback = AsyncMock()
        manager.on_deposit_confirmed(callback)

        manager.register_deposit("tx1", "BTC", "BTC", "from", "to", Decimal("1"))
        await manager.update_deposit_confirmations("tx1", 6)
        callback.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_deposit_callback_not_triggered_on_confirming(self):
        """未完成确认时不触发回调。"""
        manager = CryptoWalletManager()
        callback = AsyncMock()
        manager.on_deposit_confirmed(callback)

        manager.register_deposit("tx1", "BTC", "BTC", "from", "to", Decimal("1"))
        await manager.update_deposit_confirmations("tx1", 3)
        callback.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_deposit_credits_wallet(self):
        """确认完成自动入账。"""
        manager = CryptoWalletManager()
        manager.register_hot_wallet("to_addr", "BTC")
        manager.register_deposit("tx1", "BTC", "BTC", "from", "to_addr", Decimal("1.5"))
        await manager.update_deposit_confirmations("tx1", 6)

        balance = manager.get_balance(WalletType.HOT)[0]
        assert balance.available == Decimal("1.5")

    @pytest.mark.asyncio
    async def test_deposit_unregistered_wallet(self):
        """目标钱包未注册时不入账。"""
        manager = CryptoWalletManager()
        manager.register_deposit("tx1", "BTC", "BTC", "from", "unknown_addr", Decimal("1"))
        record = await manager.update_deposit_confirmations("tx1", 6)
        assert record.status == DepositStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_deposit_callback_exception_handled(self):
        """回调异常不影响流程。"""
        manager = CryptoWalletManager()
        callback = AsyncMock(side_effect=RuntimeError("callback error"))
        manager.on_deposit_confirmed(callback)

        manager.register_deposit("tx1", "BTC", "BTC", "from", "to", Decimal("1"))
        record = await manager.update_deposit_confirmations("tx1", 6)
        assert record.status == DepositStatus.COMPLETED

    def test_get_pending_deposits(self):
        """获取待确认充值。"""
        manager = CryptoWalletManager()
        manager.register_deposit("tx1", "BTC", "BTC", "from", "to", Decimal("1"))
        manager.register_deposit("tx2", "ETH", "ETH", "from", "to", Decimal("10"))

        pending = manager.get_pending_deposits()
        assert len(pending) == 2

    def test_get_pending_deposits_by_asset(self):
        """按资产过滤待确认充值。"""
        manager = CryptoWalletManager()
        manager.register_deposit("tx1", "BTC", "BTC", "from", "to", Decimal("1"))
        manager.register_deposit("tx2", "ETH", "ETH", "from", "to", Decimal("10"))

        btc_pending = manager.get_pending_deposits(asset="BTC")
        assert len(btc_pending) == 1
        assert btc_pending[0].asset == "BTC"


class TestTransferAlerts:
    """转账告警测试"""

    @pytest.mark.asyncio
    async def test_whitelist_violation_alert(self):
        """非白名单地址触发 CRITICAL 告警。"""
        manager = CryptoWalletManager()
        alert = await manager.check_transfer("BTC", Decimal("1"), "from", "unknown")
        assert alert is not None
        assert alert.alert_level == AlertLevel.CRITICAL
        assert alert.alert_type == "whitelist_violation"

    @pytest.mark.asyncio
    async def test_large_transfer_alert(self):
        """大额转账触发 WARNING 告警。"""
        manager = CryptoWalletManager()
        manager.add_whitelist_address("to", "BTC", "BTC")

        alert = await manager.check_transfer("BTC", Decimal("2"), "from", "to")
        assert alert is not None
        assert alert.alert_type == "large_transfer"
        assert alert.alert_level == AlertLevel.WARNING

    @pytest.mark.asyncio
    async def test_no_alert_normal_transfer(self):
        """正常转账无告警。"""
        manager = CryptoWalletManager()
        manager.add_whitelist_address("to", "BTC", "BTC")

        alert = await manager.check_transfer("BTC", Decimal("0.1"), "from", "to")
        assert alert is None

    @pytest.mark.asyncio
    async def test_high_frequency_alert(self):
        """高频转账触发 WARNING 告警。"""
        manager = CryptoWalletManager()
        manager.add_whitelist_address("to", "BTC", "BTC")

        # 先触发几次告警
        for _ in range(3):
            await manager.check_transfer("BTC", Decimal("2"), "from", "to")  # 大额 → 告警

        # 再次转账应触发高频告警
        alert = await manager.check_transfer("BTC", Decimal("2"), "from", "to")
        assert alert is not None

    @pytest.mark.asyncio
    async def test_alert_callback_triggered(self):
        """告警触发回调。"""
        manager = CryptoWalletManager()
        callback = AsyncMock()
        manager.on_alert(callback)

        await manager.check_transfer("BTC", Decimal("1"), "from", "unknown")
        callback.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_alert_callback_exception_handled(self):
        """回调异常不影响流程。"""
        manager = CryptoWalletManager()
        callback = AsyncMock(side_effect=RuntimeError("error"))
        manager.on_alert(callback)

        alert = await manager.check_transfer("BTC", Decimal("1"), "from", "unknown")
        assert alert is not None

    @pytest.mark.asyncio
    async def test_alerts_stored(self):
        """告警记录保存。"""
        manager = CryptoWalletManager()
        await manager.check_transfer("BTC", Decimal("1"), "from", "unknown")
        alerts = manager.get_alerts()
        assert len(alerts) == 1

    @pytest.mark.asyncio
    async def test_get_alerts_by_level(self):
        """按级别过滤告警。"""
        manager = CryptoWalletManager()
        await manager.check_transfer("BTC", Decimal("1"), "from", "unknown")  # CRITICAL
        manager.add_whitelist_address("to", "BTC", "BTC")
        await manager.check_transfer("BTC", Decimal("2"), "from", "to")  # WARNING

        critical = manager.get_alerts(level=AlertLevel.CRITICAL)
        assert len(critical) == 1
        assert critical[0].alert_level == AlertLevel.CRITICAL

    @pytest.mark.asyncio
    async def test_get_alerts_limit(self):
        """告警数量限制。"""
        manager = CryptoWalletManager()
        for i in range(5):
            await manager.check_transfer("BTC", Decimal("1"), f"from{i}", f"unknown{i}")

        alerts = manager.get_alerts(limit=3)
        assert len(alerts) == 3

    @pytest.mark.asyncio
    async def test_highest_level_alert_returned(self):
        """同时多个告警时返回最高级别。"""
        manager = CryptoWalletManager()
        # 非白名单 (CRITICAL) + 大额 (WARNING) → 应返回 CRITICAL
        alert = await manager.check_transfer("BTC", Decimal("2"), "from", "unknown")
        assert alert.alert_level == AlertLevel.CRITICAL


class TestTransferValidation:
    """转账预检测试"""

    @pytest.mark.asyncio
    async def test_validate_transfer_success(self):
        """预检通过。"""
        manager = CryptoWalletManager()
        manager.register_hot_wallet("from", "BTC")
        manager.update_balance(WalletType.HOT, "from", Decimal("10"))
        manager.add_whitelist_address("to", "BTC", "BTC")

        ok, reason = await manager.validate_transfer("BTC", Decimal("1"), "from", "to")
        assert ok is True
        assert "通过" in reason

    @pytest.mark.asyncio
    async def test_validate_insufficient_balance(self):
        """余额不足。"""
        manager = CryptoWalletManager()
        manager.register_hot_wallet("from", "BTC")
        manager.update_balance(WalletType.HOT, "from", Decimal("0.5"))
        manager.add_whitelist_address("to", "BTC", "BTC")

        ok, reason = await manager.validate_transfer("BTC", Decimal("1"), "from", "to")
        assert ok is False
        assert "余额不足" in reason

    @pytest.mark.asyncio
    async def test_validate_unregistered_source(self):
        """来源钱包未注册。"""
        manager = CryptoWalletManager()
        manager.add_whitelist_address("to", "BTC", "BTC")

        ok, reason = await manager.validate_transfer("BTC", Decimal("1"), "unknown", "to")
        assert ok is False
        assert "未注册" in reason

    @pytest.mark.asyncio
    async def test_validate_not_whitelisted(self):
        """目标地址不在白名单。"""
        manager = CryptoWalletManager()
        manager.register_hot_wallet("from", "BTC")
        manager.update_balance(WalletType.HOT, "from", Decimal("10"))

        ok, reason = await manager.validate_transfer("BTC", Decimal("1"), "from", "unknown")
        assert ok is False
        assert "白名单" in reason

    @pytest.mark.asyncio
    async def test_validate_critical_alert_blocks(self):
        """CRITICAL 告警阻断转账。"""
        manager = CryptoWalletManager()
        manager.register_hot_wallet("from", "BTC")
        manager.update_balance(WalletType.HOT, "from", Decimal("10"))
        # 不添加白名单 → CRITICAL 告警

        ok, reason = await manager.validate_transfer("BTC", Decimal("1"), "from", "unknown")
        assert ok is False
        assert "白名单" in reason or "告警" in reason


class TestSnapshot:
    """快照测试"""

    def test_snapshot_empty(self):
        """空钱包快照。"""
        manager = CryptoWalletManager()
        snap = manager.snapshot()
        assert snap["hot_ratio_target"] == str(DEFAULT_HOT_RATIO)
        assert snap["rebalance_threshold"] == str(DEFAULT_REBALANCE_THRESHOLD)
        assert snap["whitelist_count"] == 0
        assert snap["pending_deposits"] == 0
        assert snap["total_alerts"] == 0
        assert snap["critical_alerts"] == 0

    def test_snapshot_with_data(self):
        """有数据的快照。"""
        manager = CryptoWalletManager()
        manager.register_hot_wallet("addr1", "BTC")
        manager.update_balance(WalletType.HOT, "addr1", Decimal("1"))
        manager.add_whitelist_address("addr2", "BTC", "BTC")

        snap = manager.snapshot()
        assert snap["whitelist_count"] == 1
        assert "BTC" in snap["balances"]

    def test_snapshot_timestamp(self):
        """快照包含时间戳。"""
        manager = CryptoWalletManager()
        snap = manager.snapshot()
        assert snap["timestamp_ns"] > 0


class TestDefaults:
    """默认配置测试"""

    def test_default_hot_ratio(self):
        assert DEFAULT_HOT_RATIO == Decimal("0.10")

    def test_default_rebalance_threshold(self):
        assert DEFAULT_REBALANCE_THRESHOLD == Decimal("0.05")

    def test_large_transfer_thresholds(self):
        assert "BTC" in LARGE_TRANSFER_THRESHOLDS
        assert "ETH" in LARGE_TRANSFER_THRESHOLDS
        assert "USDT" in LARGE_TRANSFER_THRESHOLDS

    def test_custom_hot_ratio(self):
        manager = CryptoWalletManager(hot_ratio=Decimal("0.20"))
        assert manager._hot_ratio == Decimal("0.20")

    def test_custom_rebalance_threshold(self):
        manager = CryptoWalletManager(rebalance_threshold=Decimal("0.10"))
        assert manager._rebalance_threshold == Decimal("0.10")
