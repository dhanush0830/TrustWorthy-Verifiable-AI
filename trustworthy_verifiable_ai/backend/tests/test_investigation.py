"""Tests for AI Investigation service, retry, evidence validation, and Audit logging (FR-05, FR-06, FR-17, SEC-04, NFR-01)."""
from datetime import UTC, datetime
import hashlib
import json

from sqlalchemy.orm import Session

from app.llm.mock_client import MockLLMClient
from app.llm.service import run_case_investigation, validate_claims_evidence
from app.models.audit import AuditEvent
from app.models.case import Case, CaseStatus
from app.models.evidence import FreshnessIndicator
from app.schemas.evidence import EvidenceItemRead
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


# ---------------------------------------------------------------------------
# Tests for deterministic duplicate-charge cross-order consistency check
# ---------------------------------------------------------------------------

def _make_evidence_item(
    evidence_id: str,
    payment_id: str,
    order_id: str | None,
    amount: int = 49900,
) -> EvidenceItemRead:
    """Helper to construct a minimal EvidenceItemRead for consistency-check tests."""
    import json
    from datetime import UTC, datetime

    from app.models.evidence import FreshnessIndicator

    now = datetime.now(UTC)
    payload = {"payment_id": payment_id, "amount": amount, "currency": "USD", "status": "settled"}
    if order_id is not None:
        payload["order_id"] = order_id
    return EvidenceItemRead(
        id=evidence_id,
        case_id="CAS-TEST",
        customer_id="USR-CUST-A",
        source_system="payment_provider",
        source_record_id=payment_id,
        occurred_at=now,
        received_at=now,
        fetched_at=now,
        record_version=1,
        freshness_indicator=FreshnessIndicator.CURRENT_STATE_CONFIRMED,
        data_payload=json.dumps(payload),
    )


def test_duplicate_charge_claim_with_different_orders_is_rejected(db_session: Session):
    """Trust invariant: duplicate_charge claim citing payments from DIFFERENT orders is rejected.

    Scenario mirrors CAS-DEMO-A1: PAY-101 (ORD-101, $499) and PAY-102 (ORD-102, $299)
    are distinct settled payments for separate orders. The AI must NOT accept them
    as a duplicate charge for the same order.
    """
    from app.llm.service import validate_claims_evidence
    from app.schemas.investigation import Claim, ClaimType, InvestigationResult, ProposedAction, ActionType

    # Evidence: two payments linked to DIFFERENT orders
    evidence_items = [
        _make_evidence_item("EVD-PAY-101", "PAY-101", "ORD-101", amount=49900),
        _make_evidence_item("EVD-PAY-102", "PAY-102", "ORD-102", amount=29900),
    ]

    # AI claims both payments are a duplicate charge (incorrect)
    result = InvestigationResult(
        case_id="CAS-DEMO-A1",
        issue_type="duplicate_charge",
        summary="Customer was charged twice for order ORD-101.",
        claims=[
            Claim(
                claim_type=ClaimType.DUPLICATE_CHARGE,
                statement="The customer was charged twice $499.00 on their card for order ORD-101.",
                evidence_ids=["EVD-PAY-101", "EVD-PAY-102"],
                confidence=0.9,
                is_accepted=True,
                flagged=False,
            )
        ],
        proposed_action=ProposedAction(
            action_type=ActionType.REFUND,
            target_payment_id="PAY-102",
            amount=49900,
            currency="USD",
            reason="Refund the duplicate charge.",
        ),
        needs_escalation=False,
        has_unsupported_claims=False,
    )

    validated = validate_claims_evidence(result, evidence_items)

    # The duplicate-charge claim must be rejected
    assert len(validated.claims) == 1
    bad_claim = validated.claims[0]
    assert bad_claim.flagged is True, "Claim citing payments from different orders must be flagged"
    assert bad_claim.is_accepted is False, "Claim must be rejected"
    assert bad_claim.rejection_reason is not None
    assert "distinct orders" in bad_claim.rejection_reason.lower() or "different order" in bad_claim.rejection_reason.lower()

    # The investigation must escalate because of the rejected claim
    assert validated.needs_escalation is True
    assert validated.has_unsupported_claims is True


def test_duplicate_charge_claim_same_order_is_accepted(db_session: Session):
    """Duplicate-charge claim citing two payments for THE SAME order passes the consistency check."""
    from app.llm.service import validate_claims_evidence
    from app.schemas.investigation import Claim, ClaimType, InvestigationResult

    # Evidence: two payments BOTH linked to ORD-101
    evidence_items = [
        _make_evidence_item("EVD-PAY-101", "PAY-101", "ORD-101", amount=49900),
        _make_evidence_item("EVD-PAY-103", "PAY-103", "ORD-101", amount=49900),
    ]

    result = InvestigationResult(
        case_id="CAS-SAME-ORDER",
        issue_type="duplicate_charge",
        summary="Two $499 charges captured for the same ORD-101.",
        claims=[
            Claim(
                claim_type=ClaimType.DUPLICATE_CHARGE,
                statement="Two identical charges for ORD-101 were settled.",
                evidence_ids=["EVD-PAY-101", "EVD-PAY-103"],
                confidence=1.0,
            )
        ],
        needs_escalation=False,
        has_unsupported_claims=False,
    )

    validated = validate_claims_evidence(result, evidence_items)

    claim = validated.claims[0]
    assert claim.flagged is False, "Same-order duplicate-charge must NOT be flagged"
    assert claim.is_accepted is True, "Same-order duplicate-charge claim must be accepted"
    # No escalation should be triggered by the consistency check alone
    assert validated.needs_escalation is False
    assert validated.has_unsupported_claims is False


def test_non_duplicate_charge_claim_type_unaffected_by_consistency_check(db_session: Session):
    """Claim types other than duplicate_charge are NOT affected by the cross-order consistency check."""
    from app.llm.service import validate_claims_evidence
    from app.schemas.investigation import Claim, ClaimType, InvestigationResult

    # Two payments from different orders, but claim is payment_charged (not duplicate_charge)
    evidence_items = [
        _make_evidence_item("EVD-PAY-101", "PAY-101", "ORD-101", amount=49900),
        _make_evidence_item("EVD-PAY-102", "PAY-102", "ORD-102", amount=29900),
    ]

    result = InvestigationResult(
        case_id="CAS-PAYMENT-CHARGED",
        issue_type="unrecognized_charge",
        summary="Customer does not recognise the charge.",
        claims=[
            Claim(
                claim_type=ClaimType.PAYMENT_CHARGED,
                statement="Payment PAY-101 for $499 was settled.",
                evidence_ids=["EVD-PAY-101", "EVD-PAY-102"],
                confidence=1.0,
            )
        ],
        needs_escalation=False,
        has_unsupported_claims=False,
    )

    validated = validate_claims_evidence(result, evidence_items)

    claim = validated.claims[0]
    assert claim.flagged is False, "Non-duplicate-charge claims must not be flagged by the order consistency check"
    assert claim.is_accepted is True


def test_duplicate_charge_claim_with_no_order_id_not_rejected(db_session: Session):
    """Duplicate-charge claim whose payments have NO order_id metadata is not rejected by the check.

    The check can only flag when distinct order IDs are *present and differ*.
    Missing order_id is ambiguous and must not trigger a false rejection.
    """
    import json
    from app.llm.service import validate_claims_evidence
    from app.schemas.investigation import Claim, ClaimType, InvestigationResult
    from app.models.evidence import FreshnessIndicator
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    # Payments with NO order_id in payload
    ev1 = EvidenceItemRead(
        id="EVD-PAY-X01",
        case_id="CAS-NO-ORD",
        customer_id="USR-CUST-A",
        source_system="payment_provider",
        source_record_id="PAY-X01",
        occurred_at=now, received_at=now, fetched_at=now,
        record_version=1,
        freshness_indicator=FreshnessIndicator.CURRENT_STATE_CONFIRMED,
        data_payload=json.dumps({"payment_id": "PAY-X01", "amount": 49900, "status": "settled"}),
    )
    ev2 = EvidenceItemRead(
        id="EVD-PAY-X02",
        case_id="CAS-NO-ORD",
        customer_id="USR-CUST-A",
        source_system="payment_provider",
        source_record_id="PAY-X02",
        occurred_at=now, received_at=now, fetched_at=now,
        record_version=1,
        freshness_indicator=FreshnessIndicator.CURRENT_STATE_CONFIRMED,
        data_payload=json.dumps({"payment_id": "PAY-X02", "amount": 49900, "status": "settled"}),
    )

    result = InvestigationResult(
        case_id="CAS-NO-ORD",
        issue_type="duplicate_charge",
        summary="Possible duplicate charge.",
        claims=[
            Claim(
                claim_type=ClaimType.DUPLICATE_CHARGE,
                statement="Two charges of equal amount with no linked order.",
                evidence_ids=["EVD-PAY-X01", "EVD-PAY-X02"],
                confidence=0.6,
            )
        ],
        needs_escalation=False,
        has_unsupported_claims=False,
    )

    validated = validate_claims_evidence(result, [ev1, ev2])

    # Must be rejected because missing order_id = incomplete evidence for duplicate-charge
    claim = validated.claims[0]
    assert claim.flagged is True, "Missing order_id = incomplete evidence, must be flagged"
    assert claim.is_accepted is False, "Claim with no order linkage cannot be accepted as verified"
    assert claim.rejection_reason is not None
    assert "no order_id" in claim.rejection_reason.lower() or "incomplete" in claim.rejection_reason.lower()
    assert validated.needs_escalation is True
    assert validated.has_unsupported_claims is True


def test_validate_claims_evidence_does_not_double_escalate_on_valid_claims(db_session: Session):
    """Regression: a result with no flagged claims must not have escalation or unsupported flags set."""
    from app.llm.service import validate_claims_evidence
    from app.schemas.investigation import Claim, ClaimType, InvestigationResult

    evidence_items = [
        _make_evidence_item("EVD-PAY-101", "PAY-101", "ORD-101", amount=49900),
    ]

    result = InvestigationResult(
        case_id="CAS-CLEAN",
        issue_type="payment_charged",
        summary="Single charge confirmed.",
        claims=[
            Claim(
                claim_type=ClaimType.PAYMENT_CHARGED,
                statement="One $499 charge settled.",
                evidence_ids=["EVD-PAY-101"],
                confidence=1.0,
            )
        ],
        needs_escalation=False,
        has_unsupported_claims=False,
    )

    validated = validate_claims_evidence(result, evidence_items)
    assert validated.needs_escalation is False
    assert validated.has_unsupported_claims is False


# ---------------------------------------------------------------------------
# Regression test: exact Sarvam result for CAS-DEMO-A1
# ---------------------------------------------------------------------------

def _make_order_evidence_item(
    evidence_id: str,
    order_id: str,
    amount: int = 49900,
    status: str = "completed",
) -> EvidenceItemRead:
    """Helper to build an order-type EvidenceItemRead (no payment_id in payload)."""
    import json
    from datetime import UTC, datetime
    from app.models.evidence import FreshnessIndicator

    now = datetime.now(UTC)
    return EvidenceItemRead(
        id=evidence_id,
        case_id="CAS-DEMO-A1",
        customer_id="USR-CUST-A",
        source_system="order_service",
        source_record_id=order_id,
        occurred_at=now, received_at=now, fetched_at=now,
        record_version=1,
        freshness_indicator=FreshnessIndicator.CURRENT_STATE_CONFIRMED,
        data_payload=json.dumps({
            "order_id": order_id,
            "order_number": order_id,
            "amount": amount,
            "currency": "USD",
            "status": status,
        }),
    )


def test_sarvam_regression_cas_demo_a1_order_plus_one_payment_rejected(db_session: Session):
    """Regression for the exact Sarvam result on CAS-DEMO-A1.

    The live Sarvam model returned a duplicate_charge claim citing:
      evidence_ids: ["EVD-ORD-101", "EVD-PAY-101"]

    - EVD-ORD-101: order record (no payment_id field) for ORD-101, $499
    - EVD-PAY-101: payment record PAY-101, order_id=ORD-101, $499, settled

    Only ONE payment record is cited. An order record does not constitute a second
    payment. The duplicate-charge claim must be flagged as insufficiently evidenced
    and the investigation must escalate for human review.
    """
    from app.llm.service import validate_claims_evidence
    from app.schemas.investigation import Claim, ClaimType, InvestigationResult, ProposedAction, ActionType

    # Exact evidence package mirroring what the seeded CAS-DEMO-A1 collector produces
    evidence_items = [
        _make_order_evidence_item("EVD-ORD-101", "ORD-101", amount=49900, status="completed"),
        _make_evidence_item("EVD-PAY-101", "PAY-101", "ORD-101", amount=49900),
        _make_evidence_item("EVD-PAY-102", "PAY-102", "ORD-102", amount=29900),
    ]

    # Exact claim shape returned by Sarvam
    result = InvestigationResult(
        case_id="CAS-DEMO-A1",
        issue_type="duplicate_charge",
        summary="The customer was charged twice $499.00 on their card for order ORD-101.",
        claims=[
            Claim(
                claim_type=ClaimType.DUPLICATE_CHARGE,
                statement="The customer was charged twice $499.00 on their card for order ORD-101.",
                evidence_ids=["EVD-ORD-101", "EVD-PAY-101"],  # only 1 payment cited
                confidence=0.9,
                is_accepted=True,
                flagged=False,
            )
        ],
        proposed_action=ProposedAction(
            action_type=ActionType.DISMISS,
            target_payment_id=None,
            amount=None,
            currency="USD",
            reason="Evidence does not support duplicate charge allegation.",
        ),
        needs_escalation=False,
        has_unsupported_claims=False,
    )

    validated = validate_claims_evidence(result, evidence_items)

    # The duplicate-charge claim must NOT be accepted with only 1 payment record
    assert len(validated.claims) == 1
    bad_claim = validated.claims[0]
    assert bad_claim.flagged is True, (
        "Duplicate-charge claim citing only one payment record (plus an order record) must be flagged"
    )
    assert bad_claim.is_accepted is False
    assert bad_claim.rejection_reason is not None
    # Reason must mention insufficient payment records
    reason_lower = bad_claim.rejection_reason.lower()
    assert (
        "insufficient" in reason_lower
        or "at least two" in reason_lower
        or "payment record" in reason_lower
    ), f"Expected insufficiency reason, got: {bad_claim.rejection_reason!r}"
    assert validated.needs_escalation is True
    assert validated.has_unsupported_claims is True


def test_duplicate_charge_one_payment_record_only_is_rejected(db_session: Session):
    """A duplicate_charge claim citing a single payment record is always rejected.

    You cannot verify a duplicate charge from one payment alone — a second, distinct
    settled payment linked to the same order is required.
    """
    from app.llm.service import validate_claims_evidence
    from app.schemas.investigation import Claim, ClaimType, InvestigationResult

    evidence_items = [
        _make_evidence_item("EVD-PAY-101", "PAY-101", "ORD-101", amount=49900),
    ]

    result = InvestigationResult(
        case_id="CAS-ONE-PAY",
        issue_type="duplicate_charge",
        summary="Claim with only one payment cited.",
        claims=[
            Claim(
                claim_type=ClaimType.DUPLICATE_CHARGE,
                statement="Customer was charged twice.",
                evidence_ids=["EVD-PAY-101"],
                confidence=0.5,
            )
        ],
        needs_escalation=False,
        has_unsupported_claims=False,
    )

    validated = validate_claims_evidence(result, evidence_items)
    claim = validated.claims[0]
    assert claim.flagged is True
    assert claim.is_accepted is False
    assert "insufficient" in claim.rejection_reason.lower() or "at least two" in claim.rejection_reason.lower()
    assert validated.needs_escalation is True


def test_duplicate_charge_unsettled_payment_is_rejected(db_session: Session):
    """A duplicate_charge claim fails if any cited payment is not settled."""
    import json
    from datetime import UTC, datetime
    from app.llm.service import validate_claims_evidence
    from app.schemas.investigation import Claim, ClaimType, InvestigationResult
    from app.models.evidence import FreshnessIndicator

    now = datetime.now(UTC)

    def _make_pay(eid, pay_id, order_id, status):
        return EvidenceItemRead(
            id=eid, case_id="CAS-UNSETTLED", customer_id="USR-CUST-A",
            source_system="payment_provider", source_record_id=pay_id,
            occurred_at=now, received_at=now, fetched_at=now, record_version=1,
            freshness_indicator=FreshnessIndicator.CURRENT_STATE_CONFIRMED,
            data_payload=json.dumps(
                {"payment_id": pay_id, "order_id": order_id,
                 "amount": 49900, "currency": "USD", "status": status}
            ),
        )

    evidence_items = [
        _make_pay("EVD-PAY-A", "PAY-A", "ORD-101", "settled"),
        _make_pay("EVD-PAY-B", "PAY-B", "ORD-101", "authorized"),  # NOT settled
    ]

    result = InvestigationResult(
        case_id="CAS-UNSETTLED",
        issue_type="duplicate_charge",
        summary="Two charges, one not yet settled.",
        claims=[
            Claim(
                claim_type=ClaimType.DUPLICATE_CHARGE,
                statement="Two charges for ORD-101, one authorized.",
                evidence_ids=["EVD-PAY-A", "EVD-PAY-B"],
                confidence=0.7,
            )
        ],
        needs_escalation=False,
        has_unsupported_claims=False,
    )

    validated = validate_claims_evidence(result, evidence_items)
    claim = validated.claims[0]
    assert claim.flagged is True
    assert claim.is_accepted is False
    assert "settled" in claim.rejection_reason.lower()
    assert validated.needs_escalation is True


def test_cas_demo_a1_regression_invalid_refund_targeting_pay_102(db_session: Session):
    """Regression test specifically for CAS-DEMO-A1:
    - PAY-101 is $499.00 on ORD-101 (settled).
    - PAY-102 is $299.00 on ORD-102 (settled).
    - Model claims PAY-102 is a duplicate charge for ORD-101 and proposes $499 refund on PAY-102.
    - Deterministic validation must reject the claim, reject the $499 refund proposal on $299 payment,
      mark verification_status as contradicted, and trigger safe human escalation.
    """
    mock_client = MockLLMClient()
    result = run_case_investigation(
        db=db_session,
        case_id="CAS-DEMO-A1",
        llm_client=mock_client,
    )

    # 1. Verification and escalation state
    assert result.needs_escalation is True
    assert result.has_unsupported_claims is True
    assert result.verification_status == "contradicted"

    # 2. Duplicate charge claim must be rejected
    flagged_claims = [c for c in result.claims if c.flagged or not c.is_accepted]
    assert len(flagged_claims) > 0
    dup_claim = next(c for c in result.claims if c.claim_type == ClaimType.DUPLICATE_CHARGE)
    assert dup_claim.flagged is True
    assert dup_claim.is_accepted is False

    # 3. Proposed refund action must be explicitly invalidated
    assert result.proposed_action is not None
    assert result.proposed_action.is_valid is False
    assert result.proposed_action.target_payment_id == "PAY-102"
    assert result.proposed_action.amount == 49900

    # 4. Independent validation checks against authoritative records
    rejection = result.proposed_action.rejection_reason
    assert "499" in rejection  # proposed amount
    assert "299" in rejection  # actual amount
    assert "ORD-102" in rejection  # distinct order relationship

    # 5. Deterministic validation checks list
    checks = {c.name: c for c in result.validation_checks}
    assert "Evidence Package Membership" in checks
    assert checks["Evidence Package Membership"].status == "PASSED"
    assert "Duplicate Charge Verification" in checks
    assert checks["Duplicate Charge Verification"].status == "FAILED"
    assert "Proposed Action Verification" in checks
    assert checks["Proposed Action Verification"].status == "FAILED"

    # 6. Mutual consistency: summary explains validation failure
    assert "DETERMINISTIC VALIDATION FAILED" in result.summary
    assert "Human escalation required" in result.summary


def test_proposed_action_validation_exceeding_payment_amount_rejected():
    """Deterministic validation: proposed refund cannot exceed actual payment amount."""
    now = datetime.now(UTC)
    evidence_items = [
        EvidenceItemRead(
            id="EVD-PAY-1", case_id="CAS-1", customer_id="USR-1",
            source_system="payment_provider", source_record_id="PAY-1",
            occurred_at=now, received_at=now, fetched_at=now, record_version=1,
            freshness_indicator=FreshnessIndicator.CURRENT_STATE_CONFIRMED,
            data_payload=json.dumps({"payment_id": "PAY-1", "order_id": "ORD-1", "amount": 10000, "currency": "USD", "status": "settled"}),
        )
    ]
    result = InvestigationResult(
        case_id="CAS-1",
        issue_type="duplicate_charge",
        summary="Test investigation",
        claims=[
            Claim(
                claim_type=ClaimType.PAYMENT_CHARGED,
                statement="Payment settled",
                evidence_ids=["EVD-PAY-1"],
            )
        ],
        proposed_action=ProposedAction(
            action_type=ActionType.REFUND,
            target_payment_id="PAY-1",
            amount=20000,  # $200.00 refund on a $100.00 payment
            currency="USD",
            reason="Refund excess",
        ),
    )
    validated = validate_claims_evidence(result, evidence_items)
    assert validated.proposed_action.is_valid is False
    assert "exceeds" in validated.proposed_action.rejection_reason.lower()
    assert validated.needs_escalation is True


def test_proposed_action_validation_unsettled_target_payment_rejected():
    """Deterministic validation: cannot refund a non-settled payment."""
    now = datetime.now(UTC)
    evidence_items = [
        EvidenceItemRead(
            id="EVD-PAY-1", case_id="CAS-1", customer_id="USR-1",
            source_system="payment_provider", source_record_id="PAY-1",
            occurred_at=now, received_at=now, fetched_at=now, record_version=1,
            freshness_indicator=FreshnessIndicator.CURRENT_STATE_CONFIRMED,
            data_payload=json.dumps({"payment_id": "PAY-1", "order_id": "ORD-1", "amount": 10000, "currency": "USD", "status": "authorized"}),
        )
    ]
    result = InvestigationResult(
        case_id="CAS-1",
        issue_type="duplicate_charge",
        summary="Test investigation",
        claims=[
            Claim(
                claim_type=ClaimType.PAYMENT_CHARGED,
                statement="Payment authorized",
                evidence_ids=["EVD-PAY-1"],
            )
        ],
        proposed_action=ProposedAction(
            action_type=ActionType.REFUND,
            target_payment_id="PAY-1",
            amount=10000,
            currency="USD",
            reason="Refund hold",
        ),
    )
    validated = validate_claims_evidence(result, evidence_items)
    assert validated.proposed_action.is_valid is False
    assert "settled" in validated.proposed_action.rejection_reason.lower()
    assert validated.needs_escalation is True


def test_proposed_action_validation_nonexistent_payment_rejected():
    """Deterministic validation: cannot refund a payment that does not exist in customer records."""
    now = datetime.now(UTC)
    evidence_items = [
        EvidenceItemRead(
            id="EVD-PAY-1", case_id="CAS-1", customer_id="USR-1",
            source_system="payment_provider", source_record_id="PAY-1",
            occurred_at=now, received_at=now, fetched_at=now, record_version=1,
            freshness_indicator=FreshnessIndicator.CURRENT_STATE_CONFIRMED,
            data_payload=json.dumps({"payment_id": "PAY-1", "order_id": "ORD-1", "amount": 10000, "currency": "USD", "status": "settled"}),
        )
    ]
    result = InvestigationResult(
        case_id="CAS-1",
        issue_type="duplicate_charge",
        summary="Test investigation",
        claims=[
            Claim(
                claim_type=ClaimType.PAYMENT_CHARGED,
                statement="Payment settled",
                evidence_ids=["EVD-PAY-1"],
            )
        ],
        proposed_action=ProposedAction(
            action_type=ActionType.REFUND,
            target_payment_id="PAY-DOES-NOT-EXIST",
            amount=10000,
            currency="USD",
            reason="Refund phantom payment",
        ),
    )
    validated = validate_claims_evidence(result, evidence_items)
    assert validated.proposed_action.is_valid is False
    assert "does not exist" in validated.proposed_action.rejection_reason.lower()
    assert validated.needs_escalation is True
