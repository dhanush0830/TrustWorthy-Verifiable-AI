"""AI Investigation service orchestrating evidence gathering, redaction, LLM invocation, retry, and audit logging."""
import hashlib
import json

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.redaction import redact_pii
from app.evidence.collector import gather_case_evidence
from app.llm.base import BaseLLMClient
from app.llm.mock_client import MockLLMClient
from app.llm.ollama_client import OllamaClient
from app.models.audit import AuditEvent
from app.models.case import Case, CaseStatus
from app.models.user import User
from app.schemas.evidence import EvidenceItemRead
from app.schemas.investigation import InvestigationResult, ModelMetadata


def get_llm_client(force_mock: bool = False) -> BaseLLMClient:
    """Return an appropriate LLM client based on configuration or test mode."""
    settings = get_settings()
    if force_mock:
        return MockLLMClient(
            model_name=f"mock-{settings.OLLAMA_MODEL}",
            temperature=settings.LLM_TEMPERATURE,
        )
    return OllamaClient(
        base_url=settings.OLLAMA_BASE_URL,
        model=settings.OLLAMA_MODEL,
        timeout_seconds=settings.OLLAMA_TIMEOUT_SECONDS,
        temperature=settings.LLM_TEMPERATURE,
    )


def validate_claims_evidence(
    result: InvestigationResult,
    evidence_items: list[EvidenceItemRead],
) -> InvestigationResult:
    """Validate that every claim strictly cites evidence_ids from the provided package (Requirement 2).
    
    A claim citing an evidence_id that is not in the provided package is flagged, rejected,
    and the overall investigation is marked as needing human escalation.
    """
    provided_evidence_ids = {item.id for item in evidence_items}
    
    for claim in result.claims:
        invalid_ids = [eid for eid in claim.evidence_ids if eid not in provided_evidence_ids]
        if invalid_ids:
            claim.flagged = True
            claim.is_accepted = False
            claim.rejection_reason = f"Cites evidence_id(s) not in provided evidence package: {invalid_ids}"
            result.needs_escalation = True
            result.has_unsupported_claims = True

    return result


def run_case_investigation(
    db: Session,
    case_id: str,
    llm_client: BaseLLMClient | None = None,
    prompt_version: str | None = None,
    user: User | None = None,
) -> InvestigationResult:
    """Run end-to-end investigation for a complaint case.
    
    1. Look up case and its untrusted complaint text.
    2. Collect authorized evidence items for the case and customer (FR-02).
    3. Redact customer PII before sending to the model (SEC-04).
    4. Compute SHA-256 hash of model input for privacy-preserving audit trail (SEC-07, Requirement 6).
    5. Execute model investigation with exactly one retry on invalid output (Requirement 1).
    6. Validate claims against the provided evidence package (Requirement 2).
    7. Log comprehensive AuditEvent recording model_name, temperature, prompt_version, and input hash.
    """
    settings = get_settings()
    version = prompt_version or settings.LLM_PROMPT_VERSION

    # 1. Fetch case
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        raise ValueError(f"Case {case_id} not found")

    auth_user = user or case.customer or db.query(User).filter(User.id == case.customer_id).first()
    if not auth_user:
        raise ValueError(f"User for case {case_id} not found")

    # 2. Gather authoritative evidence
    evidence_models = gather_case_evidence(db, case=case, user=auth_user)
    evidence_items = [EvidenceItemRead.model_validate(e) for e in evidence_models]

    # 3. Redact untrusted complaint text (SEC-04)
    sanitized_complaint = redact_pii(case.description)

    # 4. Hash model input string (SEC-07, Requirement 6: store hash, never raw customer text)
    model_input_hash = hashlib.sha256(sanitized_complaint.encode("utf-8")).hexdigest()

    # 5. Invoke LLM Client with exactly one retry on invalid output (Requirement 1)
    client = llm_client or get_llm_client()
    max_attempts = 2  # initial call + exactly 1 retry
    attempts = 0
    result: InvestigationResult | None = None
    last_error: Exception | None = None

    while attempts < max_attempts:
        attempts += 1
        try:
            candidate_result = client.investigate(
                case_id=case_id,
                complaint_text=sanitized_complaint,
                evidence_items=evidence_items,
                prompt_version=version,
            )
            # If investigation result was returned successfully
            result = candidate_result
            break
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempts >= max_attempts:
                # Retried exactly once and failed; trigger safe escalation (never guess)
                result = InvestigationResult(
                    case_id=case_id,
                    issue_type="invalid_model_output",
                    summary=f"Model output invalid after {attempts} attempts: {last_error}. Safe escalation triggered.",
                    claims=[],
                    proposed_action=None,
                    needs_escalation=True,
                    model_metadata=ModelMetadata(
                        model_name=getattr(client, "model", getattr(client, "model_name", "unknown")),
                        temperature=getattr(client, "temperature", settings.LLM_TEMPERATURE),
                        prompt_version=version,
                        latency_ms=0,
                    ),
                )
                break

    if result is None:
        result = InvestigationResult(
            case_id=case_id,
            issue_type="investigation_failed",
            summary="Investigation failed to produce output. Safe escalation triggered.",
            claims=[],
            proposed_action=None,
            needs_escalation=True,
        )

    # 6. Validate evidence linkage (Requirement 2)
    result = validate_claims_evidence(result, evidence_items)

    # 7. Record AuditEvent (FR-17, Requirement 6: input hash only, no raw customer text)
    model_name = result.model_metadata.model_name if result.model_metadata else settings.OLLAMA_MODEL
    temperature = result.model_metadata.temperature if result.model_metadata else settings.LLM_TEMPERATURE
    latency_ms = result.model_metadata.latency_ms if result.model_metadata else 0

    audit_details = {
        "model_name": model_name,
        "temperature": temperature,
        "prompt_version": version,
        "latency_ms": latency_ms,
        "model_input_hash": model_input_hash,
        "issue_type": result.issue_type,
        "claim_count": len(result.claims),
        "needs_escalation": result.needs_escalation,
        "has_unsupported_claims": result.has_unsupported_claims,
        "proposed_action": result.proposed_action.model_dump() if result.proposed_action else None,
        "evidence_ids_referenced": [
            eid for claim in result.claims for eid in claim.evidence_ids
        ],
    }

    audit_event = AuditEvent(
        actor_id="system_llm",
        actor_role="system",
        action="ai_investigation_completed",
        target_type="case",
        target_id=case_id,
        details_json=json.dumps(audit_details),
    )
    db.add(audit_event)

    # Update case status to INVESTIGATING
    case.status = CaseStatus.INVESTIGATING
    db.commit()

    return result
