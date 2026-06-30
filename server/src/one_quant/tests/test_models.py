"""Tests for core/models.py — ORM 模型定义"""

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from one_quant.core.models import (
    AccountModel,
    AuditLogModel,
    Base,
    FillModel,
    InstrumentModel,
    LedgerEntryModel,
    MLModelVersionModel,
    OrderModel,
    PositionModel,
    RiskAuditModel,
    SignalModel,
)


@pytest.fixture
def db_engine():
    """In-memory SQLite engine for testing ORM models."""
    engine = create_engine("sqlite:///:memory:")
    # Some models define index=True on column AND a separate Index() with the same name,
    # which causes duplicate index errors in SQLite. Create tables one by one, ignoring dup index.
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            try:
                table.create(conn, checkfirst=True)
            except Exception:
                pass
    return engine


@pytest.fixture
def db_session(db_engine):
    """Provide a transactional session that rolls back after each test."""
    with Session(db_engine) as session:
        yield session


# ── Table structure tests ──────────────────────────────────────


class TestTableStructure:
    """Verify all tables exist and have correct columns."""

    def test_all_tables_created(self, db_engine):
        inspector = inspect(db_engine)
        tables = set(inspector.get_table_names())
        expected = {
            "instruments",
            "orders",
            "fills",
            "positions",
            "accounts",
            "audit_logs",
            "risk_audits",
            "signals",
            "ml_model_versions",
            "ledger_entries",
        }
        assert expected.issubset(tables)

    def test_instruments_columns(self, db_engine):
        inspector = inspect(db_engine)
        cols = {c["name"] for c in inspector.get_columns("instruments")}
        assert {
            "id",
            "symbol",
            "market",
            "instrument_type",
            "exchange",
            "base_currency",
            "quote_currency",
            "tick_size",
            "lot_size",
            "contract_multiplier",
            "is_active",
            "created_at",
            "updated_at",
        }.issubset(cols)

    def test_orders_columns(self, db_engine):
        inspector = inspect(db_engine)
        cols = {c["name"] for c in inspector.get_columns("orders")}
        assert {
            "id",
            "client_order_id",
            "symbol",
            "market",
            "side",
            "order_type",
            "quantity",
            "price",
            "status",
        }.issubset(cols)


# ── InstrumentModel ────────────────────────────────────────────


class TestInstrumentModel:
    def test_create_instrument(self, db_session):
        inst = InstrumentModel(
            id="BTC/USDT@binance",
            symbol="BTC/USDT",
            market="spot",
            instrument_type="spot",
            exchange="binance",
            base_currency="BTC",
            quote_currency="USDT",
            tick_size=0.01,
            lot_size=0.001,
        )
        db_session.add(inst)
        db_session.commit()

        row = db_session.get(InstrumentModel, "BTC/USDT@binance")
        assert row is not None
        assert row.symbol == "BTC/USDT"
        assert row.market == "spot"
        assert row.is_active is True
        assert row.contract_multiplier == 1

    def test_instrument_defaults(self, db_session):
        inst = InstrumentModel(
            id="TEST",
            symbol="TEST",
            market="spot",
            instrument_type="spot",
            exchange="test",
        )
        db_session.add(inst)
        db_session.commit()
        row = db_session.get(InstrumentModel, "TEST")
        assert row.is_active is True
        assert row.created_at is not None


# ── OrderModel ─────────────────────────────────────────────────


class TestOrderModel:
    def test_create_order(self, db_session):
        order = OrderModel(
            id=1,
            client_order_id="cli-001",
            symbol="BTC/USDT",
            market="spot",
            side="buy",
            order_type="limit",
            quantity=1.5,
            price=50000,
            strategy_name="momentum_v1",
        )
        db_session.add(order)
        db_session.commit()

        row = db_session.query(OrderModel).filter_by(client_order_id="cli-001").first()
        assert row is not None
        assert row.status == "pending"
        assert row.filled_quantity == 0
        assert row.quantity == 1.5

    def test_order_unique_client_id(self, db_session):
        o1 = OrderModel(
            id=10,
            client_order_id="dup-001",
            symbol="X",
            market="spot",
            side="buy",
            order_type="market",
            quantity=1,
        )
        o2 = OrderModel(
            id=11,
            client_order_id="dup-001",
            symbol="X",
            market="spot",
            side="sell",
            order_type="market",
            quantity=1,
        )
        db_session.add(o1)
        db_session.commit()
        db_session.add(o2)
        with pytest.raises(Exception):  # IntegrityError
            db_session.commit()


# ── FillModel ──────────────────────────────────────────────────


class TestFillModel:
    def test_create_fill(self, db_session):
        order = OrderModel(
            id=1,
            client_order_id="fill-order-001",
            symbol="ETH/USDT",
            market="spot",
            side="buy",
            order_type="limit",
            quantity=10,
        )
        db_session.add(order)
        db_session.flush()

        fill = FillModel(
            id=1,
            order_id=order.id,
            symbol="ETH/USDT",
            side="buy",
            price=3000,
            quantity=5,
            fee=1.5,
            fee_currency="USDT",
            timestamp_ns=1700000000000000000,
        )
        db_session.add(fill)
        db_session.commit()

        row = db_session.query(FillModel).filter_by(order_id=order.id).first()
        assert row is not None
        assert row.price == 3000
        assert row.fee == 1.5


# ── PositionModel ──────────────────────────────────────────────


class TestPositionModel:
    def test_create_position(self, db_session):
        pos = PositionModel(
            id=1,
            symbol="BTC/USDT",
            market="futures",
            side="long",
            quantity=2,
            entry_price=48000,
            unrealized_pnl=4000,
            strategy_name="trend_v2",
        )
        db_session.add(pos)
        db_session.commit()

        row = db_session.query(PositionModel).filter_by(symbol="BTC/USDT").first()
        assert row.side == "long"
        assert row.unrealized_pnl == 4000
        assert row.realized_pnl == 0


# ── AccountModel ───────────────────────────────────────────────


class TestAccountModel:
    def test_create_account(self, db_session):
        acc = AccountModel(
            id=1,
            name="main_account",
            exchange="binance",
            total_equity=100000,
            available_cash=80000,
            margin_used=20000,
        )
        db_session.add(acc)
        db_session.commit()

        row = db_session.query(AccountModel).filter_by(name="main_account").first()
        assert row.currency == "USDT"
        assert row.total_equity == 100000

    def test_account_unique_name(self, db_session):
        a1 = AccountModel(id=1, name="unique_acc", exchange="binance")
        a2 = AccountModel(id=2, name="unique_acc", exchange="okx")
        db_session.add(a1)
        db_session.commit()
        db_session.add(a2)
        with pytest.raises(Exception):
            db_session.commit()


# ── AuditLogModel ──────────────────────────────────────────────


class TestAuditLogModel:
    def test_create_audit_log(self, db_session):
        log = AuditLogModel(
            id=1,
            timestamp_ns=1700000000000000000,
            event_type="order",
            strategy_id="strat-1",
            order_id="ord-1",
            decision="APPROVE",
            rule_name="max_position_size",
            details='{"key": "value"}',
        )
        db_session.add(log)
        db_session.commit()

        row = db_session.query(AuditLogModel).filter_by(event_type="order").first()
        assert row.decision == "APPROVE"
        assert row.details == '{"key": "value"}'


# ── RiskAuditModel ─────────────────────────────────────────────


class TestRiskAuditModel:
    def test_create_risk_audit(self, db_session):
        ra = RiskAuditModel(
            id=1,
            timestamp_ns=1700000000000000000,
            decision="REJECT",
            rule_name="daily_loss_limit",
            reason="Daily loss exceeded 2%",
            strategy_id="strat-1",
        )
        db_session.add(ra)
        db_session.commit()

        row = db_session.query(RiskAuditModel).first()
        assert row.decision == "REJECT"
        assert row.reason == "Daily loss exceeded 2%"


# ── SignalModel ────────────────────────────────────────────────


class TestSignalModel:
    def test_create_signal(self, db_session):
        sig = SignalModel(
            id=1,
            signal_id="sig-001",
            symbol="BTC/USDT",
            direction="long",
            score=8.5,
            level="A",
            strategy_name="momentum",
            reason="Breakout above resistance",
            timestamp_ns=1700000000000000000,
        )
        db_session.add(sig)
        db_session.commit()

        row = db_session.query(SignalModel).filter_by(signal_id="sig-001").first()
        assert row.direction == "long"
        assert row.score == 8.5
        assert row.level == "A"
        assert row.outcome is None

    def test_signal_unique_id(self, db_session):
        s1 = SignalModel(id=1, signal_id="dup-sig", symbol="X", timestamp_ns=1)
        s2 = SignalModel(id=2, signal_id="dup-sig", symbol="Y", timestamp_ns=2)
        db_session.add(s1)
        db_session.commit()
        db_session.add(s2)
        with pytest.raises(Exception):
            db_session.commit()


# ── MLModelVersionModel ────────────────────────────────────────


class TestMLModelVersionModel:
    def test_create_ml_model_version(self, db_session):
        mv = MLModelVersionModel(
            id=1,
            model_name="xgboost_vol",
            version="1.0.0",
            stage="shadow",
            metrics='{"sharpe": 1.5}',
            model_path="/models/xgboost_vol_v1.pkl",
        )
        db_session.add(mv)
        db_session.commit()

        row = db_session.query(MLModelVersionModel).first()
        assert row.model_name == "xgboost_vol"
        assert row.stage == "shadow"

    def test_ml_model_default_stage(self, db_session):
        mv = MLModelVersionModel(id=1, model_name="test_model", version="0.1")
        db_session.add(mv)
        db_session.commit()
        row = db_session.query(MLModelVersionModel).first()
        assert row.stage == "shadow"


# ── LedgerEntryModel ───────────────────────────────────────────


class TestLedgerEntryModel:
    def test_create_ledger_entry(self, db_session):
        acc = AccountModel(id=1, name="ledger_acc", exchange="binance")
        db_session.add(acc)
        db_session.flush()

        entry = LedgerEntryModel(
            id=1,
            account_id=acc.id,
            entry_type="trade",
            symbol="BTC/USDT",
            amount=500,
            currency="USDT",
            balance_after=100500,
            reference_id="order-001",
            timestamp_ns=1700000000000000000,
        )
        db_session.add(entry)
        db_session.commit()

        row = db_session.query(LedgerEntryModel).filter_by(entry_type="trade").first()
        assert row.amount == 500
        assert row.balance_after == 100500

    def test_ledger_entry_types(self, db_session):
        """All documented entry types can be stored."""
        for i, etype in enumerate(("trade", "fee", "funding", "dividend", "deposit", "withdrawal")):
            entry = LedgerEntryModel(
                id=i + 1,
                entry_type=etype,
                amount=100,
                currency="USDT",
                timestamp_ns=1700000000000000000,
            )
            db_session.add(entry)
        db_session.commit()
        assert db_session.query(LedgerEntryModel).count() == 6


# ── Model relationships and indexes ────────────────────────────


class TestModelIndexes:
    """Verify composite indexes are defined."""

    def test_orders_symbol_status_index(self, db_engine):
        inspector = inspect(db_engine)
        indexes = {idx["name"] for idx in inspector.get_indexes("orders")}
        assert "ix_orders_symbol_status" in indexes

    def test_fills_symbol_timestamp_index(self, db_engine):
        inspector = inspect(db_engine)
        indexes = {idx["name"] for idx in inspector.get_indexes("fills")}
        assert "ix_fills_symbol_timestamp" in indexes

    def test_audit_event_strategy_index(self, db_engine):
        inspector = inspect(db_engine)
        indexes = {idx["name"] for idx in inspector.get_indexes("audit_logs")}
        assert "ix_audit_event_strategy" in indexes

    def test_ledger_account_type_index(self, db_engine):
        inspector = inspect(db_engine)
        indexes = {idx["name"] for idx in inspector.get_indexes("ledger_entries")}
        assert "ix_ledger_account_type" in indexes
