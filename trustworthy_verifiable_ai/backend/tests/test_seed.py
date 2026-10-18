"""Tests for deterministic seed data and idempotency (NFR-02, NFR-03, Scenarios a-f)."""
from sqlalchemy.orm import Session

from app.db.seed import seed_database
from app.models.order import Order
from app.models.payment import Payment, PaymentEvent, PaymentStatus
from app.models.refund import Refund, RefundStatus
from app.models.user import User


def test_seed_idempotency(db_session: Session):
    """Seed execution must be idempotent; running it a second time adds 0 records."""
    second_run_counts = seed_database(db_session)
    assert second_run_counts["users"] == 0
    assert second_run_counts["policies"] == 0
    assert second_run_counts["orders"] == 0
    assert second_run_counts["payments"] == 0
    assert second_run_counts["refunds"] == 0
    assert second_run_counts["payment_events"] == 0


def test_scenario_a_two_settled_payments(db_session: Session):
    """Scenario a: Customer A has two distinct settled payments."""
    payments = db_session.query(Payment).filter(Payment.customer_id == "USR-CUST-A").all()
    assert len(payments) == 2
    pay_map = {p.id: p for p in payments}
    
    assert "PAY-101" in pay_map
    assert pay_map["PAY-101"].status == PaymentStatus.SETTLED
    assert pay_map["PAY-101"].amount == 49900  # minor units: $499.00
    assert isinstance(pay_map["PAY-101"].amount, int)

    assert "PAY-102" in pay_map
    assert pay_map["PAY-102"].status == PaymentStatus.SETTLED
    assert pay_map["PAY-102"].amount == 29900  # minor units: $299.00
    assert isinstance(pay_map["PAY-102"].amount, int)


def test_scenario_b_settled_and_auth_hold(db_session: Session):
    """Scenario b: Customer B has one settled payment and one authorized hold."""
    payments = db_session.query(Payment).filter(Payment.customer_id == "USR-CUST-B").all()
    assert len(payments) == 2
    pay_map = {p.id: p for p in payments}

    assert "PAY-201" in pay_map
    assert pay_map["PAY-201"].status == PaymentStatus.SETTLED
    assert pay_map["PAY-201"].amount == 10000

    assert "PAY-202" in pay_map
    assert pay_map["PAY-202"].status == PaymentStatus.AUTHORIZED
    assert pay_map["PAY-202"].amount == 10000


def test_scenario_c_settled_and_pending_refund(db_session: Session):
    """Scenario c: Customer C has a settled payment and a pending refund."""
    payment = db_session.query(Payment).filter(Payment.id == "PAY-301").first()
    assert payment is not None
    assert payment.status == PaymentStatus.SETTLED
    assert payment.amount == 15000

    refund = db_session.query(Refund).filter(Refund.id == "REF-301").first()
    assert refund is not None
    assert refund.payment_id == "PAY-301"
    assert refund.status == RefundStatus.PENDING
    assert refund.amount == 15000


def test_scenario_d_failed_order_successful_payment(db_session: Session):
    """Scenario d: Customer D has a failed order with a successful settled payment."""
    order = db_session.query(Order).filter(Order.id == "ORD-401").first()
    assert order is not None
    assert order.status == "failed"

    payment = db_session.query(Payment).filter(Payment.id == "PAY-401").first()
    assert payment is not None
    assert payment.order_id == "ORD-401"
    assert payment.status == PaymentStatus.SETTLED


def test_scenario_e_duplicate_event_deduplication(db_session: Session):
    """Scenario e: Events with identical provider_event_id are deduplicated."""
    events = db_session.query(PaymentEvent).filter(
        PaymentEvent.provider_event_id == "evt_dup_provider_101"
    ).all()
    assert len(events) == 1
    assert events[0].payment_id == "PAY-501"


def test_scenario_f_out_of_order_events(db_session: Session):
    """Scenario f: Events preserve business occurred_at vs ingestion received_at."""
    evt_settled = db_session.query(PaymentEvent).filter(
        PaymentEvent.provider_event_id == "evt_ooo_settled_01"
    ).first()
    evt_auth = db_session.query(PaymentEvent).filter(
        PaymentEvent.provider_event_id == "evt_ooo_auth_02"
    ).first()

    assert evt_settled is not None
    assert evt_auth is not None

    # evt_auth occurred BEFORE evt_settled, but was received AFTER evt_settled
    assert evt_auth.occurred_at < evt_settled.occurred_at
    assert evt_auth.received_at > evt_settled.received_at


def test_sec_05_no_card_credential_fields(db_session: Session):
    """SEC-05: Ensure no raw card credentials or secret fields exist on models."""
    for model in [User, Order, Payment, Refund, PaymentEvent]:
        column_names = [col.name.lower() for col in model.__table__.columns]
        for forbidden in ["pan", "card_number", "cvv", "cvc", "exp_date", "secret", "pin"]:
            assert forbidden not in column_names, f"Forbidden field '{forbidden}' found in {model.__name__}"
