"""Append-only event ingestion with strict deduplication (FR-03, FR-17)."""
import json
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.evidence.projection import project_payment_state
from app.models.audit import AuditEvent
from app.models.payment import PaymentEvent
from app.schemas.evidence import EventIngestRequest, EventIngestResponse


def ingest_event(
    db: Session,
    request: EventIngestRequest,
    actor_id: str = "system_ingest"
) -> EventIngestResponse:
    """Ingest a raw provider event append-only, deduplicating by provider_event_id.

    Invariants:
    - Rejects duplicates idempotently without error.
    - Always stores raw events append-only.
    - Logs audit events for both fresh ingestion and duplicate reception.
    - Triggers payment state projection when payment_id is provided.
    """
    # 1. Deduplication check by provider_event_id (FR-03)
    existing = db.query(PaymentEvent).filter(
        PaymentEvent.provider_event_id == request.provider_event_id
    ).first()

    if existing:
        # Audit duplicate attempt
        audit = AuditEvent(
            actor_id=actor_id,
            actor_role="system",
            action="duplicate_event_ignored",
            target_type="payment_event",
            target_id=str(existing.id),
            details_json=json.dumps({
                "provider_event_id": request.provider_event_id,
                "event_type": request.event_type,
                "reason": "Duplicate provider_event_id already ingested."
            })
        )
        db.add(audit)
        db.commit()

        return EventIngestResponse(
            event_id=existing.id,
            provider_event_id=existing.provider_event_id,
            created=False,
            status="duplicate_ignored",
            projected_payment_status=None
        )

    # 2. Append-only insert of new event
    now_utc = datetime.now(UTC)
    new_event = PaymentEvent(
        provider_event_id=request.provider_event_id,
        payment_id=request.payment_id,
        event_type=request.event_type,
        amount=request.amount,
        currency=request.currency,
        occurred_at=request.occurred_at,
        received_at=now_utc,
        raw_payload=request.raw_payload or "{}"
    )
    db.add(new_event)
    db.flush()

    # 3. Project updated payment state if linked to a payment
    projected_status = None
    if request.payment_id:
        projected_status = project_payment_state(db, request.payment_id, actor_id=actor_id)

    # 4. Audit successful ingestion
    audit = AuditEvent(
        actor_id=actor_id,
        actor_role="system",
        action="event_ingested",
        target_type="payment_event",
        target_id=str(new_event.id),
        details_json=json.dumps({
            "provider_event_id": new_event.provider_event_id,
            "payment_id": new_event.payment_id,
            "event_type": new_event.event_type,
            "amount": new_event.amount,
            "occurred_at": new_event.occurred_at.isoformat(),
            "projected_status": projected_status
        })
    )
    db.add(audit)
    db.commit()

    return EventIngestResponse(
        event_id=new_event.id,
        provider_event_id=new_event.provider_event_id,
        created=True,
        status="ingested",
        projected_payment_status=projected_status
    )
