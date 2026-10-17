"""Evidence layer public interface."""
from app.evidence.ingestion import ingest_event
from app.evidence.projection import project_payment_state
from app.evidence.contradictions import detect_contradictions
from app.evidence.snapshot import build_evidence_snapshot, serialize_canonical
from app.evidence.collector import gather_case_evidence

__all__ = [
    "ingest_event",
    "project_payment_state",
    "detect_contradictions",
    "build_evidence_snapshot",
    "serialize_canonical",
    "gather_case_evidence",
]
