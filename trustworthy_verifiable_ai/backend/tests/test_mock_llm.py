"""Tests for MockLLMClient and offline deterministic investigation (FR-05, FR-06, NFR-01)."""
from datetime import UTC, datetime

from app.llm.mock_client import MockLLMClient
from app.models.evidence import FreshnessIndicator
from app.schemas.evidence import EvidenceItemRead
from app.schemas.investigation import ActionType, ClaimType


def make_evidence_item(item_id: str, system: str, record_id: str, payload: str) -> EvidenceItemRead:
    now = datetime.now(UTC)
    return EvidenceItemRead(
        id=item_id,
        case_id="CAS-TEST-1",
        customer_id="USR-CUST-A",
        source_system=system,
        source_record_id=record_id,
        occurred_at=now,
        received_at=now,
        fetched_at=now,
        record_version=1,
        freshness_indicator=FreshnessIndicator.CURRENT_STATE_CONFIRMED,
        data_payload=payload,
    )


def test_mock_llm_duplicate_charge_investigation():
    """FR-05, FR-06: MockLLMClient detects duplicate payment and links claims to evidence IDs."""
    client = MockLLMClient()
    e1 = make_evidence_item("EVD-PAY-1", "payment_gateway", "PAY-101", '{"status": "settled"}')
    e2 = make_evidence_item("EVD-PAY-2", "payment_gateway", "PAY-102", '{"status": "settled"}')

    res = client.investigate(
        case_id="CAS-DUP-1",
        complaint_text="I was charged twice!",
        evidence_items=[e1, e2],
    )

    assert res.case_id == "CAS-DUP-1"
    assert res.issue_type == "duplicate_charge"
    assert len(res.claims) == 2
    
    # FR-06: All claims link back to valid evidence IDs
    claim_evidence_ids = [eid for c in res.claims for eid in c.evidence_ids]
    assert "EVD-PAY-1" in claim_evidence_ids
    assert "EVD-PAY-2" in claim_evidence_ids

    # Proposed action
    assert res.proposed_action is not None
    assert res.proposed_action.action_type == ActionType.REFUND
    assert res.proposed_action.target_payment_id == "PAY-102"
    assert res.proposed_action.amount == 49900

    # Model metadata
    assert res.model_metadata is not None
    assert res.model_metadata.model_name == "mock-qwen3-8b"
    assert res.model_metadata.temperature == 0.0


def test_mock_llm_order_failed_payment_captured():
    """FR-05: Single payment with failed order produces order_failed_payment_captured."""
    client = MockLLMClient()
    e_pay = make_evidence_item("EVD-PAY-1", "payment_gateway", "PAY-101", '{"status": "settled"}')
    e_ord = make_evidence_item("EVD-ORD-1", "order_service", "ORD-201", '{"status": "failed"}')

    res = client.investigate(
        case_id="CAS-ORD-FAIL",
        complaint_text="My order failed but money was deducted.",
        evidence_items=[e_pay, e_ord],
    )

    assert res.issue_type == "order_failed_payment_captured"
    assert any(c.claim_type == ClaimType.ORDER_FAILED for c in res.claims)
    assert res.proposed_action is not None
    assert res.proposed_action.action_type == ActionType.REFUND


def test_mock_llm_no_evidence_escalation():
    """FR-09: No evidence leads to safe abstention (needs_escalation = True)."""
    client = MockLLMClient()
    res = client.investigate(
        case_id="CAS-EMPTY",
        complaint_text="Where is my refund?",
        evidence_items=[],
    )

    assert res.needs_escalation is True
    assert res.proposed_action is None


def test_mock_llm_canned_raw_response_with_think_block():
    """Requirement 2: MockLLMClient can feed raw output with <think> tag to verify pipeline."""
    client = MockLLMClient()
    canned = """<think>Model thinking internal notes</think>
    {
      "case_id": "CAS-CANNED-1",
      "issue_type": "refund_missing",
      "summary": "Canned summary",
      "claims": [],
      "needs_escalation": true
    }"""
    client.set_raw_response("CAS-CANNED-1", canned)

    res = client.investigate(
        case_id="CAS-CANNED-1",
        complaint_text="My refund didn't arrive.",
        evidence_items=[],
    )
    assert res.case_id == "CAS-CANNED-1"
    assert res.issue_type == "refund_missing"
    assert res.needs_escalation is True
