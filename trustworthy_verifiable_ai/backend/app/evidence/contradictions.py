"""Deterministic contradiction detection engine across evidence items (FR-04)."""
import json
from datetime import UTC, datetime
from typing import Any

from app.models.evidence import EvidenceItem, FreshnessIndicator
from app.schemas.evidence import Contradiction


def detect_contradictions(evidence_items: list[EvidenceItem]) -> list[Contradiction]:
    """Detect discrepancies and contradictions across evidence records.

    Invariants:
    - Conflicts are always explicitly flagged.
    - Deterministic code NEVER silently resolves or picks one record.
    - Marks affected evidence items with freshness_indicator = CONFLICTING_RECORDS.
    """
    contradictions: list[Contradiction] = []
    now = datetime.now(UTC)

    # Index evidence by source_system and source_record_id
    items_by_record_id: dict[str, list[EvidenceItem]] = {}
    orders_by_id: dict[str, dict[str, Any]] = {}
    payments_by_id: dict[str, dict[str, Any]] = {}
    order_to_payments: dict[str, list[str]] = {}

    for item in evidence_items:
        items_by_record_id.setdefault(item.source_record_id, []).append(item)
        try:
            payload = json.loads(item.data_payload)
        except Exception:
            payload = {}

        if item.source_system == "order_service" or item.source_record_id.startswith("ORD-"):
            orders_by_id[item.source_record_id] = payload
        elif item.source_system in ("payment_provider", "payment_service") or item.source_record_id.startswith("PAY-"):
            payments_by_id[item.source_record_id] = payload
            order_id = payload.get("order_id")
            if order_id:
                order_to_payments.setdefault(order_id, []).append(item.source_record_id)

    # Check 1: Order Status vs Payment Status (e.g., Scenario d: failed order + settled payment)
    for order_id, order_payload in orders_by_id.items():
        order_status = order_payload.get("status", "").lower()
        linked_payment_ids = order_to_payments.get(order_id, [])

        for pay_id in linked_payment_ids:
            pay_payload = payments_by_id.get(pay_id, {})
            pay_status = pay_payload.get("status", "").lower()

            if order_status in ("failed", "cancelled") and pay_status == "settled":
                c = Contradiction(
                    conflict_type="ORDER_PAYMENT_STATUS_MISMATCH",
                    description=(
                        f"Order '{order_id}' has terminal status '{order_status}', "
                        f"but linked Payment '{pay_id}' is recorded as 'settled'."
                    ),
                    conflicting_record_ids=[order_id, pay_id],
                    detected_at=now
                )
                contradictions.append(c)

    # Check 2: Order Amount vs Payment Amount Discrepancy
    for order_id, order_payload in orders_by_id.items():
        order_amt = order_payload.get("amount")
        linked_payment_ids = order_to_payments.get(order_id, [])

        for pay_id in linked_payment_ids:
            pay_payload = payments_by_id.get(pay_id, {})
            pay_amt = pay_payload.get("amount")

            if order_amt is not None and pay_amt is not None and order_amt != pay_amt:
                c = Contradiction(
                    conflict_type="AMOUNT_MISMATCH",
                    description=(
                        f"Order '{order_id}' amount ({order_amt}) differs from "
                        f"Payment '{pay_id}' amount ({pay_amt})."
                    ),
                    conflicting_record_ids=[order_id, pay_id],
                    detected_at=now
                )
                contradictions.append(c)

    # Check 3: Multiple contradictory events for the same record
    for record_id, record_items in items_by_record_id.items():
        statuses_seen = set()
        for itm in record_items:
            try:
                p = json.loads(itm.data_payload)
                st = p.get("status")
                if st:
                    statuses_seen.add(st)
            except Exception:
                pass
        
        # If contradictory terminal states exist for the same record
        if "settled" in statuses_seen and "voided" in statuses_seen:
            c = Contradiction(
                conflict_type="CONTRADICTORY_RECORD_STATES",
                description=f"Record '{record_id}' has conflicting terminal statuses: {sorted(list(statuses_seen))}.",
                conflicting_record_ids=[record_id],
                detected_at=now
            )
            contradictions.append(c)

    # Mark all involved evidence items with freshness_indicator = CONFLICTING_RECORDS
    conflicting_ids = {rid for c in contradictions for rid in c.conflicting_record_ids}
    for item in evidence_items:
        if item.source_record_id in conflicting_ids:
            item.freshness_indicator = FreshnessIndicator.CONFLICTING_RECORDS

    return contradictions
