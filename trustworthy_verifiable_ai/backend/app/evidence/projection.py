"""Payment state projection engine with deterministic status-precedence rules (FR-03, FR-17)."""
import json
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models.audit import AuditEvent
from app.models.payment import Payment, PaymentEvent, PaymentStatus

# Precedence ranking: Higher rank cannot be downgraded by lower rank
STATUS_PRECEDENCE = {
    PaymentStatus.AUTHORIZED: 1,
    PaymentStatus.VOIDED: 2,
    PaymentStatus.SETTLED: 3,
    PaymentStatus.FAILED: 4,
}

EVENT_TYPE_TO_STATUS = {
    "payment.authorized": PaymentStatus.AUTHORIZED,
    "payment.settled": PaymentStatus.SETTLED,
    "payment.voided": PaymentStatus.VOIDED,
    "payment.failed": PaymentStatus.FAILED,
}


def project_payment_state(
    db: Session,
    payment_id: str,
    actor_id: str = "system_projection"
) -> str | None:
    """Rebuild current payment state from events using occurred_at and status-precedence rules.

    Invariants:
    - Events are strictly evaluated in occurred_at (business time) order.
    - Terminal/settled states cannot be rolled back by older late-arriving events.
    - Updates payment.status deterministically.
    - Logs an AuditEvent for every projection update.
    """
    payment = db.query(Payment).filter(Payment.id == payment_id).first()
    if not payment:
        return None

    # Fetch all append-only events for this payment sorted by business timestamp
    events = db.query(PaymentEvent).filter(
        PaymentEvent.payment_id == payment_id
    ).order_by(PaymentEvent.occurred_at.asc(), PaymentEvent.id.asc()).all()

    if not events:
        return payment.status.value

    current_projected = None

    for evt in events:
        candidate_status = EVENT_TYPE_TO_STATUS.get(evt.event_type)
        if not candidate_status:
            continue

        if current_projected is None:
            current_projected = candidate_status
            continue

        # Status precedence rule:
        # 1. Settled payments cannot roll back to Authorized (even if an event timestamp claims it)
        if current_projected == PaymentStatus.SETTLED and candidate_status == PaymentStatus.AUTHORIZED:
            continue

        # 2. Voided payments cannot roll back to Authorized
        if current_projected == PaymentStatus.VOIDED and candidate_status == PaymentStatus.AUTHORIZED:
            continue

        # 3. Failed payments are terminal
        if current_projected == PaymentStatus.FAILED:
            continue

        # 4. Standard state progression or higher precedence transition
        current_projected = candidate_status

    if current_projected and current_projected != payment.status:
        old_status = payment.status.value
        payment.status = current_projected
        payment.updated_at = datetime.now(UTC)
        db.flush()

        audit = AuditEvent(
            actor_id=actor_id,
            actor_role="system",
            action="payment_state_projected",
            target_type="payment",
            target_id=payment.id,
            details_json=json.dumps({
                "old_status": old_status,
                "new_status": payment.status.value,
                "events_evaluated": len(events)
            })
        )
        db.add(audit)
        db.commit()

    return payment.status.value
