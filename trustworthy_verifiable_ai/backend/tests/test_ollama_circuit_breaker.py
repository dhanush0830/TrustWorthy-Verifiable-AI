"""Tests for OllamaClient timeout, circuit breaker, and payload structure (Items 4 & 7)."""
from datetime import UTC, datetime
from unittest.mock import patch

import httpx

from app.llm.ollama_client import CircuitBreaker, OllamaClient
from app.models.evidence import FreshnessIndicator
from app.schemas.evidence import EvidenceItemRead


def make_sample_evidence():
    now = datetime.now(UTC)
    return [
        EvidenceItemRead(
            id="EVD-TEST-1",
            case_id="CAS-CB-1",
            customer_id="USR-CUST-A",
            source_system="payment_gateway",
            source_record_id="PAY-101",
            occurred_at=now,
            received_at=now,
            fetched_at=now,
            record_version=1,
            freshness_indicator=FreshnessIndicator.CURRENT_STATE_CONFIRMED,
            data_payload='{"status": "settled", "amount": 49900}',
        )
    ]


def test_ollama_request_payload_top_level_and_options_structure():
    """Item 7: Assert Ollama request payload has 'think' and 'format' at the top level and 'temperature' inside 'options'."""
    client = OllamaClient(
        model="qwen3:8b",
        temperature=0.0,
    )

    payload = client.build_payload(
        prompt="Sample complaint prompt",
        system_prompt="Sample system prompt",
        temperature=0.0,
    )

    # Top-level assertions
    assert "format" in payload, "Payload must contain 'format' at top level"
    assert payload["format"] == "json"

    assert "think" in payload, "Payload must contain 'think' at top level"
    assert payload["think"] is False

    # Options dictionary assertions
    assert "options" in payload, "Payload must contain 'options' dictionary"
    assert isinstance(payload["options"], dict)
    assert "temperature" in payload["options"], "'temperature' must be inside 'options'"
    assert payload["options"]["temperature"] == 0.0


def test_ollama_timeout_returns_escalation_never_guess():
    """Item 4: Model timeout returns needs_escalation=true, never a guess (simulated timeout)."""
    client = OllamaClient(timeout_seconds=0.001)
    evidence = make_sample_evidence()

    # Simulate timeout during generate
    with patch.object(client, "generate", side_effect=httpx.TimeoutException("Read timed out")):
        result = client.investigate(
            case_id="CAS-TIMEOUT-TEST",
            complaint_text="My money disappeared.",
            evidence_items=evidence,
        )

        assert result.needs_escalation is True
        assert result.issue_type == "model_timeout"
        assert result.proposed_action is None
        assert "timed out" in result.summary.lower()


def test_ollama_circuit_breaker_opens_on_failures_and_escalates():
    """Item 4: Model unavailable triggers circuit breaker and returns needs_escalation=true."""
    breaker = CircuitBreaker(failure_threshold=3, recovery_time=60.0)
    client = OllamaClient(circuit_breaker=breaker)
    evidence = make_sample_evidence()

    # Simulate 3 consecutive connection failures
    with patch.object(client, "generate", side_effect=httpx.ConnectError("Connection refused")):
        for i in range(3):
            res = client.investigate(
                case_id=f"CAS-FAIL-{i}",
                complaint_text="Error complaint",
                evidence_items=evidence,
            )
            assert res.needs_escalation is True
            assert res.proposed_action is None

        # Circuit breaker should now be OPEN
        assert breaker.state == "OPEN"
        assert breaker.can_execute() is False

    # 4th call with circuit breaker OPEN: generate is never even attempted
    with patch.object(client, "generate") as mock_generate:
        res4 = client.investigate(
            case_id="CAS-FAIL-4",
            complaint_text="Post-trip complaint",
            evidence_items=evidence,
        )
        assert res4.needs_escalation is True
        assert res4.issue_type == "model_unavailable"
        assert "circuit breaker is open" in res4.summary.lower()
        mock_generate.assert_not_called()
