"""ONE量化 ORM 模型 — 交易/账户/审计 表结构

使用 SQLAlchemy 2.0 async 风格定义所有数据库表。
涵盖：标的、订单、成交、持仓、账户、审计、风控、信号、模型版本、资金流水。
"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 声明式基类
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class Base(DeclarativeBase):
    """所有 ORM 模型的基类"""

    pass


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 标的 (Instrument)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class InstrumentModel(Base):
    """交易标的：股票、期货、现货、期权等可交易品种"""

    __tablename__ = "instruments"

    id = Column(String(64), primary_key=True)  # 内部唯一标识
    symbol = Column(String(32), nullable=False, index=True)  # 交易对/代码，如 BTC/USDT, 600519.SH
    market = Column(String(16), nullable=False)  # 市场类型：spot/futures/option/stock
    instrument_type = Column(String(16), nullable=False)  # 品种类型
    exchange = Column(String(32), nullable=False)  # 交易所：binance/sse/szse 等
    base_currency = Column(String(16))  # 基准币种
    quote_currency = Column(String(16))  # 报价币种
    tick_size = Column(Numeric(20, 10))  # 最小价格变动
    lot_size = Column(Numeric(20, 10))  # 最小交易数量
    contract_multiplier = Column(Numeric(20, 10), default=1)  # 合约乘数
    is_active = Column(Boolean, default=True)  # 是否活跃
    created_at = Column(DateTime, default=datetime.utcnow)  # 创建时间
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)  # 更新时间


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 订单 (Order)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class OrderModel(Base):
    """交易订单：记录所有下单指令及其状态"""

    __tablename__ = "orders"

    id = Column(BigInteger, primary_key=True, autoincrement=True)  # 自增主键
    client_order_id = Column(
        String(64), unique=True, nullable=False, index=True
    )  # 客户端订单号（幂等键）
    exchange_order_id = Column(String(64), index=True)  # 交易所返回的订单号
    symbol = Column(String(32), nullable=False, index=True)  # 交易对/代码
    market = Column(String(16), nullable=False)  # 市场类型
    side = Column(String(8), nullable=False)  # 方向：buy/sell
    order_type = Column(String(16), nullable=False)  # 订单类型：limit/market/stop_limit
    quantity = Column(Numeric(20, 10), nullable=False)  # 委托数量
    price = Column(Numeric(20, 10))  # 委托价格（市价单可为空）
    stop_price = Column(Numeric(20, 10))  # 止损触发价
    status = Column(
        String(16), nullable=False, default="pending", index=True
    )  # 状态：pending/filled/cancelled/rejected
    filled_quantity = Column(Numeric(20, 10), default=0)  # 已成交数量
    average_price = Column(Numeric(20, 10))  # 成交均价
    strategy_name = Column(String(64), index=True)  # 策略名称
    exchange = Column(String(32))  # 交易所
    created_at = Column(DateTime, default=datetime.utcnow)  # 创建时间
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)  # 更新时间


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 成交 (Fill)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class FillModel(Base):
    """成交记录：对应订单的逐笔成交明细"""

    __tablename__ = "fills"

    id = Column(BigInteger, primary_key=True, autoincrement=True)  # 自增主键
    order_id = Column(BigInteger, ForeignKey("orders.id"), nullable=False, index=True)  # 关联订单
    symbol = Column(String(32), nullable=False, index=True)  # 交易对/代码
    side = Column(String(8), nullable=False)  # 方向：buy/sell
    price = Column(Numeric(20, 10), nullable=False)  # 成交价格
    quantity = Column(Numeric(20, 10), nullable=False)  # 成交数量
    fee = Column(Numeric(20, 10), default=0)  # 手续费
    fee_currency = Column(String(16))  # 手续费币种
    exchange = Column(String(32))  # 交易所
    timestamp_ns = Column(BigInteger, nullable=False, index=True)  # 成交时间戳（纳秒）
    created_at = Column(DateTime, default=datetime.utcnow)  # 记录创建时间


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 持仓 (Position)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class PositionModel(Base):
    """持仓快照：当前各品种的持仓状态"""

    __tablename__ = "positions"

    id = Column(BigInteger, primary_key=True, autoincrement=True)  # 自增主键
    symbol = Column(String(32), nullable=False, index=True)  # 交易对/代码
    market = Column(String(16), nullable=False)  # 市场类型
    side = Column(String(8), nullable=False)  # 持仓方向：long/short/flat
    quantity = Column(Numeric(20, 10), nullable=False)  # 持仓数量
    entry_price = Column(Numeric(20, 10), nullable=False)  # 开仓均价
    unrealized_pnl = Column(Numeric(20, 10), default=0)  # 未实现盈亏
    realized_pnl = Column(Numeric(20, 10), default=0)  # 已实现盈亏
    strategy_name = Column(String(64), index=True)  # 所属策略
    exchange = Column(String(32))  # 交易所
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)  # 更新时间


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 账户 (Account)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class AccountModel(Base):
    """账户信息：各交易所的资金账户快照"""

    __tablename__ = "accounts"

    id = Column(BigInteger, primary_key=True, autoincrement=True)  # 自增主键
    name = Column(String(64), unique=True, nullable=False)  # 账户名称（唯一）
    exchange = Column(String(32))  # 交易所
    total_equity = Column(Numeric(20, 10), default=0)  # 总权益
    available_cash = Column(Numeric(20, 10), default=0)  # 可用资金
    margin_used = Column(Numeric(20, 10), default=0)  # 已用保证金
    currency = Column(String(16), default="USDT")  # 计价币种
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)  # 更新时间


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 审计日志 (AuditLog)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class AuditLogModel(Base):
    """通用审计日志：记录订单、风控、策略、系统等各类事件"""

    __tablename__ = "audit_logs"

    id = Column(BigInteger, primary_key=True, autoincrement=True)  # 自增主键
    timestamp_ns = Column(BigInteger, nullable=False, index=True)  # 事件时间戳（纳秒）
    event_type = Column(
        String(32), nullable=False, index=True
    )  # 事件类型：order/risk/strategy/system
    strategy_id = Column(String(64), index=True)  # 策略标识
    order_id = Column(String(64), index=True)  # 关联订单号
    decision = Column(String(16))  # 决策：APPROVE/REJECT/REDUCE/FLATTEN
    rule_name = Column(String(64))  # 触发规则名称
    details = Column(Text)  # 详情（JSON）
    snapshot = Column(Text)  # 状态快照（JSON）
    created_at = Column(DateTime, default=datetime.utcnow)  # 记录创建时间


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 风控审计 (RiskAudit)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class RiskAuditModel(Base):
    """风控审计：记录每次风控决策及其依据"""

    __tablename__ = "risk_audits"

    id = Column(BigInteger, primary_key=True, autoincrement=True)  # 自增主键
    timestamp_ns = Column(BigInteger, nullable=False, index=True)  # 决策时间戳（纳秒）
    decision = Column(String(16), nullable=False)  # 风控决策：APPROVE/REJECT/REDUCE/FLATTEN
    rule_name = Column(String(64), nullable=False)  # 触发的风控规则
    reason = Column(Text)  # 决策原因
    strategy_id = Column(String(64), index=True)  # 策略标识
    order_id = Column(String(64))  # 关联订单号
    snapshot = Column(Text)  # 风控状态快照（JSON）
    created_at = Column(DateTime, default=datetime.utcnow)  # 记录创建时间


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 信号记录 (Signal)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class SignalModel(Base):
    """交易信号：策略产生的买卖信号及其后续结果"""

    __tablename__ = "signals"

    id = Column(BigInteger, primary_key=True, autoincrement=True)  # 自增主键
    signal_id = Column(String(64), unique=True, nullable=False, index=True)  # 信号唯一标识
    symbol = Column(String(32), nullable=False, index=True)  # 交易对/代码
    direction = Column(String(8))  # 方向：long/short
    score = Column(Numeric(10, 4))  # 信号评分
    level = Column(String(4))  # 信号等级：S/A/B/C
    strategy_name = Column(String(64), index=True)  # 产生信号的策略
    reason = Column(Text)  # 信号理由
    evidence_details = Column(Text)  # 证据详情（JSON）
    outcome = Column(String(16))  # 结果：win/loss/pending
    outcome_pnl = Column(Numeric(20, 10))  # 结果盈亏
    timestamp_ns = Column(BigInteger, nullable=False)  # 信号时间戳（纳秒）
    created_at = Column(DateTime, default=datetime.utcnow)  # 记录创建时间


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ML 模型版本 (MLModelVersion)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class MLModelVersionModel(Base):
    """ML 模型版本管理：跟踪机器学习模型的生命周期"""

    __tablename__ = "ml_model_versions"

    id = Column(BigInteger, primary_key=True, autoincrement=True)  # 自增主键
    model_name = Column(String(64), nullable=False, index=True)  # 模型名称
    version = Column(String(32), nullable=False)  # 版本号
    stage = Column(String(16), default="shadow")  # 阶段：shadow/staging/production/archived
    metrics = Column(Text)  # 评估指标（JSON）
    model_path = Column(String(256))  # 模型文件路径
    created_at = Column(DateTime, default=datetime.utcnow)  # 创建时间


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 资金流水 (LedgerEntry)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class LedgerEntryModel(Base):
    """资金流水：记录所有资金变动（交易、手续费、资金费率、分红、出入金等）"""

    __tablename__ = "ledger_entries"

    id = Column(BigInteger, primary_key=True, autoincrement=True)  # 自增主键
    account_id = Column(BigInteger, ForeignKey("accounts.id"), index=True)  # 关联账户
    entry_type = Column(
        String(32), nullable=False
    )  # 类型：trade/fee/funding/dividend/deposit/withdrawal
    symbol = Column(String(32))  # 交易对/代码（可选）
    amount = Column(Numeric(20, 10), nullable=False)  # 变动金额（正增负减）
    currency = Column(String(16), nullable=False)  # 币种
    balance_after = Column(Numeric(20, 10))  # 变动后余额
    reference_id = Column(String(64))  # 关联业务 ID（订单号/交易哈希）
    description = Column(Text)  # 备注说明
    timestamp_ns = Column(BigInteger, nullable=False, index=True)  # 流水时间戳（纳秒）
    created_at = Column(DateTime, default=datetime.utcnow)  # 记录创建时间


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 复合索引 — 加速常用查询
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 订单：按交易对 + 状态联合查询
Index("ix_orders_symbol_status", OrderModel.symbol, OrderModel.status)

# 成交：按交易对 + 时间范围查询
Index("ix_fills_symbol_timestamp", FillModel.symbol, FillModel.timestamp_ns)

# 持仓：按交易对查询
Index("ix_positions_symbol", PositionModel.symbol)

# 审计日志：按事件类型 + 策略联合查询
Index("ix_audit_event_strategy", AuditLogModel.event_type, AuditLogModel.strategy_id)

# 资金流水：按账户 + 类型联合查询
Index("ix_ledger_account_type", LedgerEntryModel.account_id, LedgerEntryModel.entry_type)
