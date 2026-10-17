"""Evidence collector gathering authorized case context with freshness indicators (FR-02, FR-04)."""
import json
import uuid
from datetime import datetime, timezone
from typing import List, Optional
from sqlalchemy.orm import Session

from app.db.scoped import scoped_query
from app.models.case import Case
from app.models.order import Order
from app.models.payment import Payment, PaymentEvent
from app.models.refund import Refund
from app.models.evidence import EvidenceItem, FreshnessIndicator
from app.models.user import User
from app.evidence.contradictions import detect_contradictions


def gather_case_evidence(
    db: Session,
    case: Case,
    user: User,
    source_available: bool = True
) -> List[EvidenceItem]:
    """Gather authorized evidence items for a given case and assign freshness indicators.

    Invariants:
    - Queries are strictly scoped to the case's customer (FR-02, SEC-01).
    - Provenance and timestamps are recorded for every item.
    - If source_available is False, flags SOURCE_UNAVAILABLE.
    - Runs contradiction detection across the collection.
    """
    evidence_items: List[EvidenceItem] = []
    now = datetime.now(timezone.utc)
    cust_id = case.customer_id

    # If source systems are declared unavailable (e.g. simulated network outage)
    if not source_available:
        unavailable_item = EvidenceItem(
            id=f"EVD-UNAVAIL-{uuid.uuid4().hex[:8].upper()}",
            case_id=case.id,
            customer_id=cust_id,
            source_system="payment_provider",
            source_record_id="PROVIDER-UNAVAILABLE",
            provider_event_id=None,
            occurred_at=now,
            received_at=now,
            fetched_at=now,
            record_version=1,
            freshness_indicator=FreshnessIndicator.SOURCE_UNAVAILABLE,
            data_payload=json.dumps({"error": "Payment provider gateway timeout / unreachable"})
        )
        evidence_items.append(unavailable_item)
        return evidence_items

    # 1. Fetch authorized Orders for this customer
    orders = db.query(Order).filter(Order.customer_id == cust_id).all()
    for ord_rec in orders:
        item = EvidenceItem(
            id=f"EVD-{ord_rec.id}",
            case_id=case.id,
            customer_id=cust_id,
            source_system="order_service",
            source_record_id=ord_rec.id,
            provider_event_id=None,
            occurred_at=ord_rec.created_at,
            received_at=ord_rec.created_at,
            fetched_at=now,
            record_version=1,
            freshness_indicator=FreshnessIndicator.CURRENT_STATE_CONFIRMED,
            data_payload=json.dumps({
                "order_id": ord_rec.id,
                "order_number": ord_rec.order_number,
                "amount": ord_rec.amount,
                "currency": ord_rec.currency,
                "status": ord_rec.status
            })
        )
        evidence_items.append(item)

    # 2. Fetch authorized Payments for this customer
    payments = db.query(Payment).filter(Payment.customer_id == cust_id).all()
    for pay in payments:
        # Check corroborating events
        events_count = db.query(PaymentEvent).filter(PaymentEvent.payment_id == pay.id).count()
        freshness = (
            FreshnessIndicator.CURRENT_STATE_CONFIRMED
            if events_count > 0 or pay.status.value == "settled"
            else FreshnessIndicator.CURRENT_STATE_NOT_CONFIRMED
        )

        item = EvidenceItem(
            id=f"EVD-{pay.id}",
            case_id=case.id,
            customer_id=cust_id,
            source_system="payment_provider",
            source_record_id=pay.id,
            provider_event_id=None,
            occurred_at=pay.created_at,
            received_at=pay.created_at,
            fetched_at=now,
            record_version=1,
            freshness_indicator=freshness,
            data_payload=json.dumps({
                "payment_id": pay.id,
                "order_id": pay.order_id,
                "amount": pay.amount,
                "currency": pay.currency,
                "status": pay.status.value,
                "events_count": events_count
            })
        )
        evidence_items.append(item)

    # 3. Fetch authorized Refunds for this customer
    refunds = db.query(Refund).filter(Refund.customer_id == cust_id).all()
    for ref in refunds:
        item = EvidenceItem(
            id=f"EVD-{ref.id}",
            case_id=case.id,
            customer_id=cust_id,
            source_system="refund_service",
            source_record_id=ref.id,
            provider_event_id=None,
            occurred_at=ref.created_at,
            received_at=ref.created_at,
            fetched_at=now,
            record_version=1,
            freshness_indicator=FreshnessIndicator.CURRENT_STATE_CONFIRMED,
            data_payload=json.dumps({
                "refund_id": ref.id,
                "payment_id": ref.payment_id,
                "amount": ref.amount,
                "currency": ref.currency,
                "status": ref.status.value,
                "reason": ref.reason
            })
        )
        evidence_items.append(item)

    # 4. Check for contradictions across collected items
    detect_contradictions(evidence_items)

    return evidence_items
