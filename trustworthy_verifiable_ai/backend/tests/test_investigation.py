"""Tests for AI Investigation service, retry, evidence validation, and Audit logging (FR-05, FR-06, FR-17, SEC-04, NFR-01)."""
import hashlib
import json

from sqlalchemy.orm import Session

from app.llm.mock_client import MockLLMClient
from app.llm.service import run_case_investigation
from app.models.audit import AuditEvent
from app.models.case import Case, CaseStatus
from app.schemas.investigation import ActionType, Claim, ClaimType, InvestigationResult, ProposedAction


def test_run_case_investigation_and_audit_event_logged(db_session: Session):
    """FR-05, FR-17, Requirement 3: Case investigation must log an AuditEvent recording model_name, temperature, and prompt_version."""
    case = Case(
        id="CAS-TEST-INV-1",
        customer_id="USR-CUST-A",
        title="Double charge dispute",
        description="I was charged twice $499.00 on my card 4532 1234 5678 9012! Email me at alice@test.com.",
        status=CaseStatus.OPEN,
    )
    db_session.add(case)
    db_session.commit()

    mock_client = MockLLMClient(
        model_name="mock-qwen3-8b",
        temperature=0.0,
    )

    result = run_case_investigation(
        db=db_session,
        case_id="CAS-TEST-INV-1",
        llm_client=mock_client,
        prompt_version="2026-10-phase2-v1",
    )

    # Verify investigation output
    assert result.case_id == "CAS-TEST-INV-1"
    assert len(result.claims) > 0
    assert result.proposed_action is not None

    # Verify case status updated to INVESTIGATING
    updated_case = db_session.query(Case).filter(Case.id == "CAS-TEST-INV-1").first()
    assert updated_case is not None
    assert updated_case.status == CaseStatus.INVESTIGATING

    # FR-17 & Requirement 3: Check AuditEvent
    audit_event = db_session.query(AuditEvent).filter(
        AuditEvent.target_id == "CAS-TEST-INV-1",
        AuditEvent.action == "ai_investigation_completed",
    ).first()

    assert audit_event is not None
    assert audit_event.actor_id == "system_llm"
    assert audit_event.actor_role == "system"
    assert audit_event.target_type == "case"

    # Verify exact required fields in details_json (Requirement 3)
    details = json.loads(audit_event.details_json)
    assert details["model_name"] == "mock-qwen3-8b"
    assert details["temperature"] == 0.0
    assert details["prompt_version"] == "2026-10-phase2-v1"
    assert "latency_ms" in details
    assert "claim_count" in details
    assert details["claim_count"] == len(result.claims)
    assert "evidence_ids_referenced" in details


def test_investigation_redacts_pii_before_llm(db_session: Session):
    """SEC-04: Customer email and card numbers are redacted from untrusted text before LLM receipt."""
    case = Case(
        id="CAS-PII-TEST",
        customer_id="USR-CUST-A",
        title="Unauthorized charge",
        description="Call +1-555-123-4567 or email victim@bank.com. Card was 4111 2222 3333 4444.",
        status=CaseStatus.OPEN,
    )
    db_session.add(case)
    db_session.commit()

    received_complaint_text = []

    def mock_handler(complaint_text, evidence_items):
        received_complaint_text.append(complaint_text)
        return InvestigationResult(
            case_id="CAS-PII-TEST",
            issue_type="unauthorized_charge",
            summary="Test summary",
            claims=[],
            needs_escalation=True,
        )

    mock_client = MockLLMClient(custom_handler=mock_handler)
    run_case_investigation(db=db_session, case_id="CAS-PII-TEST", llm_client=mock_client)

    assert len(received_complaint_text) == 1
    sanitized = received_complaint_text[0]
    assert "victim@bank.com" not in sanitized
    assert "4111 2222 3333 4444" not in sanitized
    assert "[EMAIL_REDACTED]" in sanitized
    assert "[CARD_REDACTED]" in sanitized


def test_invalid_model_output_retried_once_then_escalates_and_counts_calls(db_session: Session):
    """Item 1: Invalid model output is retried exactly once, then returns needs_escalation=true.
    
    The test must count model calls (expect 2).
    """
    case = Case(
        id="CAS-RETRY-TEST",
        customer_id="USR-CUST-A",
        title="Disputed transaction",
        description="I am reporting an invalid charge.",
        status=CaseStatus.OPEN,
    )
    db_session.add(case)
    db_session.commit()

    mock_client = MockLLMClient()
    # Configure canned response with invalid JSON
    mock_client.set_raw_response("CAS-RETRY-TEST", "MALFORMED_NON_JSON_RESPONSE")

    result = run_case_investigation(
        db=db_session,
        case_id="CAS-RETRY-TEST",
        llm_client=mock_client,
    )

    # Must count model calls: initial call + exactly 1 retry = 2 calls
    assert mock_client.call_count == 2, f"Expected exactly 2 model calls, got {mock_client.call_count}"
    assert result.needs_escalation is True
    assert result.issue_type == "invalid_model_output"
    assert result.proposed_action is None


def test_claim_citing_unprovided_evidence_id_is_flagged_and_rejected(db_session: Session):
    """Item 2: A claim citing an evidence_id that is not in the provided package is flagged and cannot be accepted."""
    case = Case(
        id="CAS-UNSUPPORTED-EVD",
        customer_id="USR-CUST-A",
        title="Dispute with invalid citation",
        description="I was charged erroneously.",
        status=CaseStatus.OPEN,
    )
    db_session.add(case)
    db_session.commit()

    def mock_handler_with_hallucinated_evidence(complaint_text, evidence_items):
        return InvestigationResult(
            case_id="CAS-UNSUPPORTED-EVD",
            issue_type="hallucinated_claim",
            summary="Claim cites nonexistent evidence ID",
            claims=[
                Claim(
                    claim_type=ClaimType.PAYMENT_CHARGED,
                    statement="Payment was processed on imaginary gateway",
                    evidence_ids=["EVD-HALLUCINATED-999"],  # NOT in provided package
                    confidence=1.0,
                )
            ],
            proposed_action=ProposedAction(
                action_type=ActionType.REFUND,
                target_payment_id="PAY-UNKNOWN",
                amount=49900,
                currency="USD",
                reason="Refund based on unsupported claim",
            ),
            needs_escalation=False,
        )

    mock_client = MockLLMClient(custom_handler=mock_handler_with_hallucinated_evidence)
    result = run_case_investigation(db=db_session, case_id="CAS-UNSUPPORTED-EVD", llm_client=mock_client)

    # The claim must be flagged and NOT accepted
    assert len(result.claims) == 1
    hallucinated_claim = result.claims[0]
    assert hallucinated_claim.flagged is True
    assert hallucinated_claim.is_accepted is False
    assert "not in provided" in (hallucinated_claim.rejection_reason or "").lower()

    # The overall result must escalate due to unsupported claims
    assert result.needs_escalation is True
    assert result.has_unsupported_claims is True


def test_audit_event_stores_input_hash_not_raw_complaint(db_session: Session):
    """Item 6: Audit events store a hash of the model input, not raw customer text.
    
    Test that the raw complaint string never appears in audit_events.
    """
    raw_secret_text = "SECRET_UNTRACKED_PLAINTEXT_CUSTOMER_COMPLAINT_987654"
    case = Case(
        id="CAS-AUDIT-HASH-TEST",
        customer_id="USR-CUST-A",
        title="Confidential complaint",
        description=raw_secret_text,
        status=CaseStatus.OPEN,
    )
    db_session.add(case)
    db_session.commit()

    mock_client = MockLLMClient()
    run_case_investigation(
        db=db_session,
        case_id="CAS-AUDIT-HASH-TEST",
        llm_client=mock_client,
    )

    # Retrieve logged AuditEvent
    audit_event = db_session.query(AuditEvent).filter(
        AuditEvent.target_id == "CAS-AUDIT-HASH-TEST",
        AuditEvent.action == "ai_investigation_completed",
    ).first()

    assert audit_event is not None
    details = json.loads(audit_event.details_json)

    # Raw complaint string must NEVER appear anywhere in details_json or audit_event fields
    assert raw_secret_text not in audit_event.details_json
    assert raw_secret_text not in audit_event.target_id
    assert raw_secret_text not in audit_event.action

    # Audit event MUST store SHA-256 hash of the input
    expected_hash = hashlib.sha256(raw_secret_text.encode("utf-8")).hexdigest()
    assert details["model_input_hash"] == expected_hash
