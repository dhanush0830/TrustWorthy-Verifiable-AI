"""Evidence layer public interface."""
from app.evidence.collector import gather_case_evidence
from app.evidence.contradictions import detect_contradictions
from app.evidence.ingestion import ingest_event
from app.evidence.projection import project_payment_state
from app.evidence.snapshot import build_evidence_snapshot, serialize_canonical

__all__ = [
    "build_evidence_snapshot",
    "detect_contradictions",
    "gather_case_evidence",
    "ingest_event",
    "project_payment_state",
    "serialize_canonical",
]
