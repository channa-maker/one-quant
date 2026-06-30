"""初始迁移 — 创建所有 ONE量化 核心表

修订 ID: 001_initial
创建时间: 2026-06-30

包含表:
  - instruments        交易标的
  - orders             订单
  - fills              成交明细
  - positions          持仓快照
  - accounts           账户信息
  - audit_logs         审计日志
  - risk_audits        风控审计
  - signals            交易信号
  - ml_model_versions  ML 模型版本
  - ledger_entries     资金流水
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# 修订标识
revision: str = "001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """创建所有核心表及索引。"""

    # ── 标的表 ──────────────────────────────────────────────────
    op.create_table(
        "instruments",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("symbol", sa.String(32), nullable=False, index=True),
        sa.Column("market", sa.String(16), nullable=False),
        sa.Column("instrument_type", sa.String(16), nullable=False),
        sa.Column("exchange", sa.String(32), nullable=False),
        sa.Column("base_currency", sa.String(16)),
        sa.Column("quote_currency", sa.String(16)),
        sa.Column("tick_size", sa.Numeric(20, 10)),
        sa.Column("lot_size", sa.Numeric(20, 10)),
        sa.Column("contract_multiplier", sa.Numeric(20, 10), server_default="1"),
        sa.Column("is_active", sa.Boolean, server_default="true"),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()),
    )

    # ── 订单表 ──────────────────────────────────────────────────
    op.create_table(
        "orders",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("client_order_id", sa.String(64), unique=True, nullable=False, index=True),
        sa.Column("exchange_order_id", sa.String(64), index=True),
        sa.Column("symbol", sa.String(32), nullable=False, index=True),
        sa.Column("market", sa.String(16), nullable=False),
        sa.Column("side", sa.String(8), nullable=False),
        sa.Column("order_type", sa.String(16), nullable=False),
        sa.Column("quantity", sa.Numeric(20, 10), nullable=False),
        sa.Column("price", sa.Numeric(20, 10)),
        sa.Column("stop_price", sa.Numeric(20, 10)),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending", index=True),
        sa.Column("filled_quantity", sa.Numeric(20, 10), server_default="0"),
        sa.Column("average_price", sa.Numeric(20, 10)),
        sa.Column("strategy_name", sa.String(64), index=True),
        sa.Column("exchange", sa.String(32)),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()),
    )
    # 订单复合索引：symbol + status
    op.create_index("ix_orders_symbol_status", "orders", ["symbol", "status"])

    # ── 成交表 ──────────────────────────────────────────────────
    op.create_table(
        "fills",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("order_id", sa.BigInteger, sa.ForeignKey("orders.id"), nullable=False, index=True),
        sa.Column("symbol", sa.String(32), nullable=False, index=True),
        sa.Column("side", sa.String(8), nullable=False),
        sa.Column("price", sa.Numeric(20, 10), nullable=False),
        sa.Column("quantity", sa.Numeric(20, 10), nullable=False),
        sa.Column("fee", sa.Numeric(20, 10), server_default="0"),
        sa.Column("fee_currency", sa.String(16)),
        sa.Column("exchange", sa.String(32)),
        sa.Column("timestamp_ns", sa.BigInteger, nullable=False, index=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )
    # 成交复合索引：symbol + timestamp_ns
    op.create_index("ix_fills_symbol_timestamp", "fills", ["symbol", "timestamp_ns"])

    # ── 持仓表 ──────────────────────────────────────────────────
    op.create_table(
        "positions",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(32), nullable=False, index=True),
        sa.Column("market", sa.String(16), nullable=False),
        sa.Column("side", sa.String(8), nullable=False),
        sa.Column("quantity", sa.Numeric(20, 10), nullable=False),
        sa.Column("entry_price", sa.Numeric(20, 10), nullable=False),
        sa.Column("unrealized_pnl", sa.Numeric(20, 10), server_default="0"),
        sa.Column("realized_pnl", sa.Numeric(20, 10), server_default="0"),
        sa.Column("strategy_name", sa.String(64), index=True),
        sa.Column("exchange", sa.String(32)),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()),
    )
    # 持仓复合索引：symbol
    op.create_index("ix_positions_symbol", "positions", ["symbol"])

    # ── 账户表 ──────────────────────────────────────────────────
    op.create_table(
        "accounts",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(64), unique=True, nullable=False),
        sa.Column("exchange", sa.String(32)),
        sa.Column("total_equity", sa.Numeric(20, 10), server_default="0"),
        sa.Column("available_cash", sa.Numeric(20, 10), server_default="0"),
        sa.Column("margin_used", sa.Numeric(20, 10), server_default="0"),
        sa.Column("currency", sa.String(16), server_default="USDT"),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()),
    )

    # ── 审计日志表 ──────────────────────────────────────────────
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("timestamp_ns", sa.BigInteger, nullable=False, index=True),
        sa.Column("event_type", sa.String(32), nullable=False, index=True),
        sa.Column("strategy_id", sa.String(64), index=True),
        sa.Column("order_id", sa.String(64), index=True),
        sa.Column("decision", sa.String(16)),
        sa.Column("rule_name", sa.String(64)),
        sa.Column("details", sa.Text),
        sa.Column("snapshot", sa.Text),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )
    # 审计复合索引：event_type + strategy_id
    op.create_index("ix_audit_event_strategy", "audit_logs", ["event_type", "strategy_id"])

    # ── 风控审计表 ──────────────────────────────────────────────
    op.create_table(
        "risk_audits",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("timestamp_ns", sa.BigInteger, nullable=False, index=True),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("rule_name", sa.String(64), nullable=False),
        sa.Column("reason", sa.Text),
        sa.Column("strategy_id", sa.String(64), index=True),
        sa.Column("order_id", sa.String(64)),
        sa.Column("snapshot", sa.Text),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )

    # ── 信号记录表 ──────────────────────────────────────────────
    op.create_table(
        "signals",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("signal_id", sa.String(64), unique=True, nullable=False, index=True),
        sa.Column("symbol", sa.String(32), nullable=False, index=True),
        sa.Column("direction", sa.String(8)),
        sa.Column("score", sa.Numeric(10, 4)),
        sa.Column("level", sa.String(4)),
        sa.Column("strategy_name", sa.String(64), index=True),
        sa.Column("reason", sa.Text),
        sa.Column("evidence_details", sa.Text),
        sa.Column("outcome", sa.String(16)),
        sa.Column("outcome_pnl", sa.Numeric(20, 10)),
        sa.Column("timestamp_ns", sa.BigInteger, nullable=False),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )

    # ── ML 模型版本表 ──────────────────────────────────────────
    op.create_table(
        "ml_model_versions",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("model_name", sa.String(64), nullable=False, index=True),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column("stage", sa.String(16), server_default="shadow"),
        sa.Column("metrics", sa.Text),
        sa.Column("model_path", sa.String(256)),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )

    # ── 资金流水表 ──────────────────────────────────────────────
    op.create_table(
        "ledger_entries",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("account_id", sa.BigInteger, sa.ForeignKey("accounts.id"), index=True),
        sa.Column("entry_type", sa.String(32), nullable=False),
        sa.Column("symbol", sa.String(32)),
        sa.Column("amount", sa.Numeric(20, 10), nullable=False),
        sa.Column("currency", sa.String(16), nullable=False),
        sa.Column("balance_after", sa.Numeric(20, 10)),
        sa.Column("reference_id", sa.String(64)),
        sa.Column("description", sa.Text),
        sa.Column("timestamp_ns", sa.BigInteger, nullable=False, index=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )
    # 流水复合索引：account_id + entry_type
    op.create_index("ix_ledger_account_type", "ledger_entries", ["account_id", "entry_type"])


def downgrade() -> None:
    """按依赖顺序逆序删除所有表。"""

    op.drop_table("ledger_entries")
    op.drop_table("ml_model_versions")
    op.drop_table("signals")
    op.drop_table("risk_audits")
    op.drop_table("audit_logs")
    op.drop_table("accounts")
    op.drop_table("positions")
    op.drop_table("fills")
    op.drop_table("orders")
    op.drop_table("instruments")
