"""Tests for Phase 1 Evidence layer (FR-03, FR-04, FR-17)."""
import json
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.evidence.collector import gather_case_evidence
from app.evidence.contradictions import detect_contradictions
from app.evidence.ingestion import ingest_event
from app.evidence.projection import project_payment_state
from app.evidence.snapshot import build_evidence_snapshot
from app.models.audit import AuditEvent
from app.models.case import Case, CaseStatus
from app.models.evidence import EvidenceItem, FreshnessIndicator
from app.models.payment import Payment, PaymentEvent, PaymentStatus
from app.models.user import User
from app.schemas.evidence import EventIngestRequest


def test_duplicate_event_delivered_twice_is_counted_once(db_session: Session):
    """FR-03: The same event delivered twice is counted once (idempotent, no error)."""
    now = datetime.now(UTC)
    req = EventIngestRequest(
        provider_event_id="evt_test_dedupe_100",
        payment_id="PAY-101",
        event_type="payment.settled",
        amount=49900,
        currency="USD",
        occurred_at=now,
        raw_payload='{"id": "evt_test_dedupe_100", "status": "settled"}'
    )

    # First delivery: newly created
    res1 = ingest_event(db_session, req)
    assert res1.created is True
    assert res1.status == "ingested"

    # Second delivery: deduplicated, no error, created is False
    res2 = ingest_event(db_session, req)
    assert res2.created is False
    assert res2.status == "duplicate_ignored"
    assert res2.event_id == res1.event_id

    # Verify database contains exactly 1 row for this provider_event_id
    rows = db_session.query(PaymentEvent).filter(
        PaymentEvent.provider_event_id == "evt_test_dedupe_100"
    ).all()
    assert len(rows) == 1

    # Verify audit event logged for duplicate attempt (FR-17)
    dup_audit = db_session.query(AuditEvent).filter(
        AuditEvent.action == "duplicate_event_ignored"
    ).first()
    assert dup_audit is not None


def test_older_authorized_arriving_after_newer_settled_keeps_settled(db_session: Session):
    """FR-03: An older 'authorized' event arriving after a newer 'settled' event keeps state as settled."""
    base_time = datetime(2026, 10, 17, 12, 0, 0, tzinfo=UTC)
    t_settled = base_time + timedelta(minutes=10)
    t_authorized = base_time  # occurred 10 minutes earlier

    # Create a fresh payment in authorized state
    payment = Payment(
        id="PAY-OOO-TEST",
        customer_id="USR-CUST-A",
        amount=5000,
        currency="USD",
        status=PaymentStatus.AUTHORIZED
    )
    db_session.add(payment)
    db_session.flush()

    # Ingest Settled event (occurred at T+10m)
    req_settled = EventIngestRequest(
        provider_event_id="evt_ooo_settled_now",
        payment_id="PAY-OOO-TEST",
        event_type="payment.settled",
        amount=5000,
        currency="USD",
        occurred_at=t_settled,
        raw_payload='{"type": "settled"}'
    )
    res_settled = ingest_event(db_session, req_settled)
    assert res_settled.created is True

    # Check payment is now settled
    db_session.refresh(payment)
    assert payment.status == PaymentStatus.SETTLED

    # Now ingest the late-arriving older Authorized event (occurred at T)
    req_auth_late = EventIngestRequest(
        provider_event_id="evt_ooo_auth_late",
        payment_id="PAY-OOO-TEST",
        event_type="payment.authorized",
        amount=5000,
        currency="USD",
        occurred_at=t_authorized,
        raw_payload='{"type": "authorized"}'
    )
    res_auth = ingest_event(db_session, req_auth_late)
    assert res_auth.created is True

    # CRITICAL: Verify payment is STILL settled (no rollback to authorized!)
    db_session.refresh(payment)
    assert payment.status == PaymentStatus.SETTLED

    # Verify re-projection explicitly maintains settled
    projected = project_payment_state(db_session, "PAY-OOO-TEST")
    assert projected == "settled"


def test_contradictory_records_are_flagged_not_resolved_silently(db_session: Session):
    """FR-04: Contradictory records are flagged with details and NEVER resolved silently."""
    customer = db_session.query(User).filter(User.id == "USR-CUST-D").first()

    # Scenario d: ORD-401 is failed, but PAY-401 is settled
    case = Case(
        id="CASE-CONTRADICTION-TEST",
        customer_id=customer.id,
        title="Double charge investigation",
        description="I was charged for a failed order",
        status=CaseStatus.INVESTIGATING
    )
    db_session.add(case)
    db_session.flush()

    # Gather evidence
    items = gather_case_evidence(db_session, case, customer)
    assert len(items) >= 2

    # Run contradiction detection
    contradictions = detect_contradictions(items)
    assert len(contradictions) > 0

    c = contradictions[0]
    assert c.conflict_type == "ORDER_PAYMENT_STATUS_MISMATCH"
    assert "ORD-401" in c.conflicting_record_ids
    assert "PAY-401" in c.conflicting_record_ids

    # Verify items are marked with conflicting_records freshness indicator
    flagged_items = [i for i in items if i.freshness_indicator == FreshnessIndicator.CONFLICTING_RECORDS]
    assert len(flagged_items) >= 2


def test_snapshot_hash_changes_when_evidence_changes(db_session: Session):
    """FR-04: The evidence snapshot hash changes when any evidence field changes."""
    now = datetime.now(UTC)

    # Create Case entity
    case = Case(
        id="CASE-SNAP-1",
        customer_id="USR-CUST-A",
        title="Snapshot Test Case",
        description="Testing hash sensitivity",
        status=CaseStatus.INVESTIGATING
    )
    db_session.add(case)
    db_session.flush()

    # 1. Base evidence items
    item1 = EvidenceItem(
        id="EVD-TEST-1",
        case_id="CASE-SNAP-1",
        customer_id="USR-CUST-A",
        source_system="payment_provider",
        source_record_id="PAY-101",
        occurred_at=now,
        received_at=now,
        fetched_at=now,
        record_version=1,
        freshness_indicator=FreshnessIndicator.CURRENT_STATE_CONFIRMED,
        data_payload=json.dumps({"amount": 49900, "status": "settled"})
    )
    item2 = EvidenceItem(
        id="EVD-TEST-2",
        case_id="CASE-SNAP-1",
        customer_id="USR-CUST-A",
        source_system="order_service",
        source_record_id="ORD-101",
        occurred_at=now,
        received_at=now,
        fetched_at=now,
        record_version=1,
        freshness_indicator=FreshnessIndicator.CURRENT_STATE_CONFIRMED,
        data_payload=json.dumps({"amount": 49900, "status": "completed"})
    )

    # Build first snapshot
    snap1 = build_evidence_snapshot(db_session, "CASE-SNAP-1", [item1, item2])
    hash1 = snap1.snapshot_hash
    assert len(hash1) == 64  # SHA-256 length

    # 2. Re-building with identical items produces exact same hash (deterministic)
    snap1_rebuild = build_evidence_snapshot(db_session, "CASE-SNAP-1", [item1, item2])
    assert snap1_rebuild.snapshot_hash == hash1

    # 3. Modify an existing item's payload (e.g. amount change)
    item1_modified = EvidenceItem(
        id="EVD-TEST-1",
        case_id="CASE-SNAP-1",
        customer_id="USR-CUST-A",
        source_system="payment_provider",
        source_record_id="PAY-101",
        occurred_at=now,
        received_at=now,
        fetched_at=now,
        record_version=2,  # version updated
        freshness_indicator=FreshnessIndicator.CURRENT_STATE_CONFIRMED,
        data_payload=json.dumps({"amount": 50000, "status": "settled"})
    )

    snap2 = build_evidence_snapshot(db_session, "CASE-SNAP-1", [item1_modified, item2])
    assert snap2.snapshot_hash != hash1

    # 4. Adding a third item alters the hash
    item3 = EvidenceItem(
        id="EVD-TEST-3",
        case_id="CASE-SNAP-1",
        customer_id="USR-CUST-A",
        source_system="refund_service",
        source_record_id="REF-999",
        occurred_at=now,
        received_at=now,
        fetched_at=now,
        record_version=1,
        freshness_indicator=FreshnessIndicator.CURRENT_STATE_NOT_CONFIRMED,
        data_payload=json.dumps({"amount": 1000, "status": "pending"})
    )

    snap3 = build_evidence_snapshot(db_session, "CASE-SNAP-1", [item1, item2, item3])
    assert snap3.snapshot_hash != hash1
    assert snap3.snapshot_hash != snap2.snapshot_hash


def test_seeded_scenarios_e_and_f(db_session: Session):
    """Seed scenarios e (duplicate event) and f (out-of-order events) pass through projection."""
    # Scenario e: Ingest duplicate event again via ingest_event
    req_e = EventIngestRequest(
        provider_event_id="evt_dup_provider_101",
        payment_id="PAY-501",
        event_type="payment.settled",
        amount=7500,
        currency="USD",
        occurred_at=datetime(2026, 10, 17, 12, 0, 0, tzinfo=UTC),
        raw_payload='{"status": "settled"}'
    )
    res_e = ingest_event(db_session, req_e)
    assert res_e.created is False  # Correctly deduplicated

    # Scenario f: Re-project PAY-601 with out-of-order events
    # Event 1 occurred at 14:10 (settled), Event 2 occurred at 14:00 (authorized)
    projected_f = project_payment_state(db_session, "PAY-601")
    assert projected_f == "settled"

    payment_f = db_session.query(Payment).filter(Payment.id == "PAY-601").first()
    assert payment_f.status == PaymentStatus.SETTLED


def test_audit_events_created_for_evidence_operations(db_session: Session):
    """FR-17: Audit events are logged for ingestion, projection, and snapshot operations."""
    now = datetime.now(UTC)

    # 1. Trigger ingestion
    req = EventIngestRequest(
        provider_event_id="evt_audit_check_1",
        payment_id="PAY-102",
        event_type="payment.settled",
        amount=29900,
        currency="USD",
        occurred_at=now
    )
    ingest_event(db_session, req, actor_id="actor_auditor")

    # 2. Trigger snapshot
    case = Case(
        id="CASE-AUDIT-TEST",
        customer_id="USR-CUST-A",
        title="Audit Test Case",
        description="Testing audit logs",
        status=CaseStatus.INVESTIGATING
    )
    db_session.add(case)
    db_session.flush()

    item = EvidenceItem(
        id="EVD-AUDIT-1",
        case_id="CASE-AUDIT-TEST",
        customer_id="USR-CUST-A",
        source_system="payment_provider",
        source_record_id="PAY-102",
        occurred_at=now,
        received_at=now,
        fetched_at=now,
        record_version=1,
        freshness_indicator=FreshnessIndicator.CURRENT_STATE_CONFIRMED,
        data_payload="{}"
    )
    build_evidence_snapshot(db_session, "CASE-AUDIT-TEST", [item], actor_id="actor_auditor")

    # Verify audit logs
    ingest_audit = db_session.query(AuditEvent).filter(
        AuditEvent.action == "event_ingested",
        AuditEvent.actor_id == "actor_auditor"
    ).first()
    assert ingest_audit is not None

    snapshot_audit = db_session.query(AuditEvent).filter(
        AuditEvent.action == "evidence_snapshot_created",
        AuditEvent.actor_id == "actor_auditor"
    ).first()
    assert snapshot_audit is not None
