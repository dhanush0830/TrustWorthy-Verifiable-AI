"""Canonical evidence snapshot generation with SHA-256 hashing (FR-04, FR-17)."""
import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.audit import AuditEvent
from app.models.evidence import EvidenceItem, EvidenceSnapshot


def serialize_canonical(data: Any) -> str:
    """Serialize Python dictionary / list into deterministic canonical JSON (RFC 8785 style).

    - Sorted keys recursively
    - Compact separators without trailing or leading whitespace
    - Safe ASCII encoding
    """
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def build_evidence_snapshot(
    db: Session,
    case_id: str,
    evidence_items: list[EvidenceItem],
    actor_id: str = "system_snapshot"
) -> EvidenceSnapshot:
    """Build a deterministic, canonical snapshot of all evidence gathered for a case.

    Invariants:
    - Items are sorted deterministically by (source_system, source_record_id, occurred_at, id).
    - Serialized with strict canonical sorting and compact formatting.
    - Computes SHA-256 cryptographic hash.
    - Persists EvidenceSnapshot and emits an AuditEvent.
    """
    # 1. Deterministic canonical sorting of evidence items
    sorted_items = sorted(
        evidence_items,
        key=lambda item: (
            item.source_system,
            item.source_record_id,
            item.occurred_at.isoformat(),
            item.id
        )
    )

    # 2. Extract canonical representation for each item
    canonical_list: list[dict[str, Any]] = []
    for item in sorted_items:
        try:
            payload_dict = json.loads(item.data_payload)
        except Exception:
            payload_dict = {"raw": item.data_payload}

        canonical_list.append({
            "id": item.id,
            "case_id": item.case_id,
            "customer_id": item.customer_id,
            "source_system": item.source_system,
            "source_record_id": item.source_record_id,
            "provider_event_id": item.provider_event_id,
            "occurred_at": item.occurred_at.isoformat(),
            "received_at": item.received_at.isoformat(),
            "fetched_at": item.fetched_at.isoformat(),
            "record_version": item.record_version,
            "freshness_indicator": item.freshness_indicator.value,
            "data_payload": payload_dict
        })

    # 3. Canonical serialization
    canonical_json = serialize_canonical(canonical_list)

    # NOTE: This SHA-256 hash detects subsequent modification or tampering,
    # but does not prove the external ground truth of the upstream data.
    snapshot_hash = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()

    # 4. Persist EvidenceSnapshot
    snapshot = EvidenceSnapshot(
        id=f"SNP-{uuid.uuid4().hex[:12].upper()}",
        case_id=case_id,
        snapshot_hash=snapshot_hash,
        canonical_json=canonical_json,
        evidence_count=len(sorted_items),
        created_at=datetime.now(UTC)
    )
    db.add(snapshot)
    db.flush()

    # 5. Audit event emission (FR-17)
    audit = AuditEvent(
        actor_id=actor_id,
        actor_role="system",
        action="evidence_snapshot_created",
        target_type="evidence_snapshot",
        target_id=snapshot.id,
        details_json=json.dumps({
            "case_id": case_id,
            "snapshot_hash": snapshot_hash,
            "evidence_count": len(sorted_items)
        })
    )
    db.add(audit)
    db.commit()

    return snapshot
