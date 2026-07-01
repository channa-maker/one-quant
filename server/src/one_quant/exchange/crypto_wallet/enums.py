"""
加密钱包 — 枚举与常量
"""

from decimal import Decimal
from enum import StrEnum


class WalletType(StrEnum):
    """钱包类型"""

    HOT = "hot"  # 热钱包：联网，用于交易
    COLD = "cold"  # 冷钱包：离线，用于存储
    EXCHANGE = "exchange"  # 交易所钱包（子账户）


class DepositStatus(StrEnum):
    """充值确认状态"""

    PENDING = "pending"  # 等待确认
    CONFIRMING = "confirming"  # 确认中（部分确认）
    COMPLETED = "completed"  # 确认完成，已入账
    FAILED = "failed"  # 充值失败


class AlertLevel(StrEnum):
    """告警级别"""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


# 默认配置
DEFAULT_HOT_RATIO = Decimal("0.10")  # 热钱包目标比例 10%
DEFAULT_REBALANCE_THRESHOLD = Decimal("0.05")  # 再平衡触发阈值 5%
DEFAULT_MIN_CONFIRMATIONS = 6  # BTC 默认确认数
DEFAULT_ALERT_COOLDOWN_SEC = 300  # 同类告警冷却 5 分钟

# 各链默认确认数
CHAIN_CONFIRMATIONS: dict[str, int] = {
    "BTC": 6,
    "ETH": 12,
    "SOL": 32,
    "USDT_ERC20": 12,
    "USDT_TRC20": 20,
    "USDC": 12,
    "BNB": 15,
    "DOGE": 20,
    "XRP": 10,
}

# 大额转账阈值（按币种）
LARGE_TRANSFER_THRESHOLDS: dict[str, Decimal] = {
    "BTC": Decimal("1.0"),
    "ETH": Decimal("10.0"),
    "USDT": Decimal("50000"),
    "USDC": Decimal("50000"),
    "SOL": Decimal("100"),
    "BNB": Decimal("50"),
}
