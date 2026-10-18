"""Tests for LLM parser and <think>...</think> block stripping (Phase 2 Requirement 2)."""
import pytest

from app.llm.base import parse_and_validate, strip_thinking_tags
from app.schemas.investigation import ActionType, ClaimType, InvestigationResult


def test_strip_thinking_tags_basic():
    """Requirement 2: parse_and_validate() must strip any <think>...</think> block before parsing."""
    raw = """<think>
Here is my thinking:
1. Customer mentions duplicate charge.
2. Evidence shows PAY-101 and PAY-102 both settled.
3. Therefore, issue is duplicate_charge.
</think>
{
  "case_id": "CAS-100",
  "issue_type": "duplicate_charge",
  "summary": "Customer was double charged.",
  "claims": [
    {
      "claim_type": "duplicate_charge",
      "statement": "Payment PAY-102 was duplicate.",
      "evidence_ids": ["EVD-01"],
      "confidence": 1.0
    }
  ],
  "proposed_action": {
    "action_type": "refund",
    "target_payment_id": "PAY-102",
    "amount": 49900,
    "currency": "USD",
    "reason": "Duplicate charge refund"
  },
  "needs_escalation": false
}"""

    cleaned = strip_thinking_tags(raw)
    assert "<think>" not in cleaned
    assert "</think>" not in cleaned
    assert "Here is my thinking" not in cleaned

    result = parse_and_validate(raw)
    assert isinstance(result, InvestigationResult)
    assert result.case_id == "CAS-100"
    assert result.issue_type == "duplicate_charge"
    assert len(result.claims) == 1
    assert result.claims[0].claim_type == ClaimType.DUPLICATE_CHARGE
    assert result.claims[0].evidence_ids == ["EVD-01"]
    assert result.proposed_action is not None
    assert result.proposed_action.action_type == ActionType.REFUND
    assert result.proposed_action.amount == 49900


def test_strip_multiple_thinking_tags_and_case_insensitivity():
    """Thinking tags with mixed case or multiple occurrences are cleanly removed."""
    raw = """<THINK>Initial thoughts</THINK>
<thought>Additional reasoning</thought>
{
  "case_id": "CAS-200",
  "issue_type": "unrecognized_charge",
  "summary": "Single unrecognized payment.",
  "claims": [],
  "needs_escalation": true
}"""
    result = parse_and_validate(raw)
    assert result.case_id == "CAS-200"
    assert result.issue_type == "unrecognized_charge"
    assert result.needs_escalation is True


def test_markdown_codeblock_enclosed_json():
    """Ensure JSON enclosed in ```json ... ``` codeblocks is correctly extracted."""
    raw = """<think>
Thinking here...
</think>
```json
{
  "case_id": "CAS-300",
  "issue_type": "order_failed_payment_captured",
  "summary": "Order failed while payment settled.",
  "claims": [
    {
      "claim_type": "order_failed",
      "statement": "Order failed",
      "evidence_ids": ["EVD-ORD-1"],
      "confidence": 1.0
    }
  ],
  "needs_escalation": false
}
```"""
    result = parse_and_validate(raw)
    assert result.case_id == "CAS-300"
    assert result.issue_type == "order_failed_payment_captured"
    assert len(result.claims) == 1


def test_missing_json_raises_value_error():
    """If model output has only thinking or non-JSON text, raise ValueError."""
    raw = "<think>I cannot decide</think>Sorry, I cannot help with that."
    with pytest.raises(ValueError, match="Failed to decode model JSON|contains no valid JSON"):
        parse_and_validate(raw)


def test_fallback_case_id_injection():
    """If LLM omits case_id in the JSON, fallback_case_id is populated."""
    raw = """{
  "issue_type": "missing_refund",
  "summary": "Customer has not received refund.",
  "claims": [],
  "needs_escalation": true
}"""
    result = parse_and_validate(raw, fallback_case_id="CAS-FALLBACK-1")
    assert result.case_id == "CAS-FALLBACK-1"
