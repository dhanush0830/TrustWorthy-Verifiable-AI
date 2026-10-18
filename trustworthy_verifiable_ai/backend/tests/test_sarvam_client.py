"""Mocked HTTP tests for SarvamClient: success, malformed, timeout, errors, and circuit breaker."""
from datetime import UTC, datetime
import json
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.core.config import Settings
from app.llm.circuit_breaker import CircuitBreaker
from app.llm.sarvam_client import SarvamClient
from app.llm.service import get_llm_client
from app.models.evidence import FreshnessIndicator
from app.schemas.evidence import EvidenceItemRead


def make_sample_evidence() -> list[EvidenceItemRead]:
    now = datetime.now(UTC)
    return [
        EvidenceItemRead(
            id="EVD-SARVAM-1",
            case_id="CAS-SARVAM-1",
            customer_id="USR-CUST-1",
            source_system="payment_gateway",
            source_record_id="PAY-201",
            occurred_at=now,
            received_at=now,
            fetched_at=now,
            record_version=1,
            freshness_indicator=FreshnessIndicator.CURRENT_STATE_CONFIRMED,
            data_payload='{"status": "settled", "amount": 49900, "currency": "USD"}',
        )
    ]


VALID_INVESTIGATION_JSON = json.dumps({
    "case_id": "CAS-SARVAM-1",
    "issue_type": "double_charge",
    "summary": "Customer was charged twice for a single transaction.",
    "claims": [
        {
            "claim_type": "duplicate_charge",
            "statement": "Two identical charges were captured on payment gateway.",
            "evidence_ids": ["EVD-SARVAM-1"],
            "confidence": 1.0,
        }
    ],
    "proposed_action": {
        "action_type": "refund",
        "target_payment_id": "PAY-201",
        "amount": 49900,
        "currency": "USD",
        "reason": "Duplicate charge verified against payment gateway records.",
    },
    "needs_escalation": False,
})


def make_mock_sarvam_response(content: str | None = None, reasoning_content: str | None = None) -> dict:
    msg: dict = {"role": "assistant"}
    if content is not None:
        msg["content"] = content
    if reasoning_content is not None:
        msg["reasoning_content"] = reasoning_content
    return {
        "id": "chatcmpl-test-12345",
        "object": "chat.completion",
        "created": 1710000000,
        "model": "sarvam-105b",
        "choices": [
            {
                "index": 0,
                "message": msg,
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 100,
            "completion_tokens": 150,
            "total_tokens": 250,
        },
    }


def test_sarvam_request_payload_and_headers_structure():
    """Verify endpoint URL, headers, and request payload structure."""
    client = SarvamClient(
        api_key="mock-sarvam-key-12345",
        base_url="https://api.sarvam.ai",
        model="sarvam-105b",
        temperature=0.0,
    )

    assert client.endpoint_url == "https://api.sarvam.ai/v1/chat/completions"

    payload = client.build_payload(
        prompt="User prompt here",
        system_prompt="System prompt here",
        temperature=0.0,
    )

    assert payload["model"] == "sarvam-105b"
    assert payload["temperature"] == 0.0
    assert payload["max_tokens"] == 4096
    assert payload["reasoning_effort"] is None
    assert payload["response_format"] == {"type": "json_object"}
    assert len(payload["messages"]) == 2
    assert payload["messages"][0] == {"role": "system", "content": "System prompt here"}
    assert payload["messages"][1] == {"role": "user", "content": "User prompt here"}


def test_sarvam_successful_response_mocked():
    """Mocked HTTP 200 response parsed correctly without making real requests."""
    client = SarvamClient(api_key="mock-key-valid")
    evidence = make_sample_evidence()
    mock_body = make_mock_sarvam_response(content=VALID_INVESTIGATION_JSON)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_body
    mock_resp.raise_for_status.return_value = None

    with patch("httpx.Client.post", return_value=mock_resp) as mock_post:
        result = client.investigate(
            case_id="CAS-SARVAM-1",
            complaint_text="I was charged twice.",
            evidence_items=evidence,
        )

        assert mock_post.called
        # Check call arguments
        call_kwargs = mock_post.call_args.kwargs
        headers = call_kwargs.get("headers", {})
        assert headers.get("api-subscription-key") == "mock-key-valid"
        assert headers.get("Content-Type") == "application/json"

        assert result.case_id == "CAS-SARVAM-1"
        assert result.issue_type == "double_charge"
        assert result.needs_escalation is False
        assert len(result.claims) == 1
        assert result.claims[0].evidence_ids == ["EVD-SARVAM-1"]
        assert result.proposed_action is not None
        assert result.proposed_action.amount == 49900
        assert result.model_metadata.model_name == "sarvam-105b"
        assert client.circuit_breaker.state == "CLOSED"


def test_sarvam_response_with_thinking_tags_stripped():
    """Thinking tags <think>...</think> or markdown blocks inside content are properly stripped."""
    client = SarvamClient(api_key="mock-key-valid")
    evidence = make_sample_evidence()

    content_with_think = f"<think>Internal model reasoning trace</think>\n```json\n{VALID_INVESTIGATION_JSON}\n```"
    mock_body = make_mock_sarvam_response(content=content_with_think)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_body
    mock_resp.raise_for_status.return_value = None

    with patch("httpx.Client.post", return_value=mock_resp):
        result = client.investigate(
            case_id="CAS-SARVAM-1",
            complaint_text="Double charge complaint",
            evidence_items=evidence,
        )

        assert result.case_id == "CAS-SARVAM-1"
        assert result.issue_type == "double_charge"
        assert result.needs_escalation is False


def test_sarvam_malformed_empty_choices():
    """Malformed API response with missing or empty choices triggers safe escalation."""
    client = SarvamClient(api_key="mock-key-valid")
    evidence = make_sample_evidence()

    # Empty choices array
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"choices": []}
    mock_resp.raise_for_status.return_value = None

    with patch("httpx.Client.post", return_value=mock_resp):
        with pytest.raises(ValueError, match="Malformed Sarvam API response"):
            client.generate(prompt="test prompt")


def test_sarvam_malformed_non_json_content():
    """Non-JSON content in assistant message triggers safe escalation in investigate."""
    client = SarvamClient(api_key="mock-key-valid")
    evidence = make_sample_evidence()

    mock_body = make_mock_sarvam_response(content="This is plain text with no json payload anywhere.")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_body
    mock_resp.raise_for_status.return_value = None

    with patch("httpx.Client.post", return_value=mock_resp):
        with pytest.raises(ValueError):
            client.investigate(
                case_id="CAS-SARVAM-1",
                complaint_text="My money disappeared.",
                evidence_items=evidence,
            )


def test_sarvam_token_limit_length_finish_reason_error():
    """When finish_reason is 'length' and content is None (token exhausted), raises descriptive ValueError."""
    client = SarvamClient(api_key="mock-key-valid")
    mock_body = {
        "id": "chatcmpl-test-len",
        "object": "chat.completion",
        "created": 1710000000,
        "model": "sarvam-105b",
        "choices": [
            {
                "index": 0,
                "finish_reason": "length",
                "message": {
                    "role": "assistant",
                    "content": None,
                    "reasoning_content": None,
                    "refusal": None,
                },
            }
        ],
    }
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_body
    mock_resp.raise_for_status.return_value = None

    with patch("httpx.Client.post", return_value=mock_resp):
        with pytest.raises(ValueError, match="token limit reached"):
            client.generate(prompt="test prompt")


def test_sarvam_refusal_error():
    """When refusal is set in assistant message, raises descriptive ValueError."""
    client = SarvamClient(api_key="mock-key-valid")
    mock_body = {
        "id": "chatcmpl-test-refusal",
        "object": "chat.completion",
        "created": 1710000000,
        "model": "sarvam-105b",
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": None,
                    "refusal": "I cannot answer this request under safety guidelines",
                },
            }
        ],
    }
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_body
    mock_resp.raise_for_status.return_value = None

    with patch("httpx.Client.post", return_value=mock_resp):
        with pytest.raises(ValueError, match="refused request"):
            client.generate(prompt="test prompt")


def test_sarvam_content_filter_error():
    """When finish_reason is 'content_filter' and content is None, raises descriptive ValueError."""
    client = SarvamClient(api_key="mock-key-valid")
    mock_body = {
        "id": "chatcmpl-test-filter",
        "object": "chat.completion",
        "created": 1710000000,
        "model": "sarvam-105b",
        "choices": [
            {
                "index": 0,
                "finish_reason": "content_filter",
                "message": {
                    "role": "assistant",
                    "content": None,
                },
            }
        ],
    }
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_body
    mock_resp.raise_for_status.return_value = None

    with patch("httpx.Client.post", return_value=mock_resp):
        with pytest.raises(ValueError, match="content filter"):
            client.generate(prompt="test prompt")



def test_sarvam_timeout_returns_safe_escalation():
    """HTTP timeout safely escalates and records circuit breaker failure."""
    breaker = CircuitBreaker()
    client = SarvamClient(api_key="mock-key-valid", circuit_breaker=breaker)
    evidence = make_sample_evidence()

    with patch("httpx.Client.post", side_effect=httpx.TimeoutException("Connection timed out")):
        result = client.investigate(
            case_id="CAS-TIMEOUT",
            complaint_text="Investigate timeout",
            evidence_items=evidence,
        )

        assert result.needs_escalation is True
        assert result.issue_type == "model_timeout"
        assert result.proposed_action is None
        assert "timed out" in result.summary.lower()
        assert breaker.failure_count == 1


def test_sarvam_api_error_returns_safe_escalation():
    """HTTP 403 or 500 error safely escalates with model_unavailable and does not guess."""
    breaker = CircuitBreaker()
    client = SarvamClient(api_key="mock-key-invalid", circuit_breaker=breaker)
    evidence = make_sample_evidence()

    request = httpx.Request("POST", "https://api.sarvam.ai/v1/chat/completions")
    http_error = httpx.HTTPStatusError("403 Forbidden", request=request, response=httpx.Response(403, request=request))

    with patch("httpx.Client.post", side_effect=http_error):
        result = client.investigate(
            case_id="CAS-ERROR-403",
            complaint_text="Complaint on error",
            evidence_items=evidence,
        )

        assert result.needs_escalation is True
        assert result.issue_type == "model_unavailable"
        assert result.proposed_action is None
        assert "unavailable" in result.summary.lower() or "403" in result.summary.lower()
        assert breaker.failure_count == 1


def test_sarvam_circuit_breaker_tripping():
    """After threshold failures, circuit breaker trips to OPEN and blocks further HTTP calls."""
    breaker = CircuitBreaker(failure_threshold=3, recovery_time=60.0)
    client = SarvamClient(api_key="mock-key-valid", circuit_breaker=breaker)
    evidence = make_sample_evidence()

    request = httpx.Request("POST", "https://api.sarvam.ai/v1/chat/completions")
    conn_error = httpx.ConnectError("Connection refused", request=request)

    with patch("httpx.Client.post", side_effect=conn_error) as mock_post:
        for i in range(3):
            res = client.investigate(
                case_id=f"CAS-CB-{i}",
                complaint_text="Fail complaint",
                evidence_items=evidence,
            )
            assert res.needs_escalation is True
            assert res.issue_type == "model_unavailable"

        assert breaker.state == "OPEN"
        assert breaker.can_execute() is False
        assert mock_post.call_count == 3

    # Next call with breaker OPEN should short-circuit without attempting network post
    with patch("httpx.Client.post") as mock_post2:
        res_blocked = client.investigate(
            case_id="CAS-CB-BLOCKED",
            complaint_text="Should not call API",
            evidence_items=evidence,
        )
        assert res_blocked.needs_escalation is True
        assert res_blocked.issue_type == "model_unavailable"
        assert "circuit breaker is open" in res_blocked.summary.lower()
        mock_post2.assert_not_called()


def test_sarvam_missing_api_key_safe_escalation():
    """Client instantiated with empty or missing API key raises ValueError on generate and escalates on investigate."""
    client = SarvamClient(api_key="")
    evidence = make_sample_evidence()

    with pytest.raises(ValueError, match="SARVAM_API_KEY is not configured"):
        client.generate("test")

    res = client.investigate(
        case_id="CAS-NO-KEY",
        complaint_text="No key complaint",
        evidence_items=evidence,
    )
    assert res.needs_escalation is True
    assert res.issue_type == "model_unavailable"
    assert "missing" in res.summary.lower()


def test_provider_selection_logic():
    """Verify provider selection through get_llm_client."""
    # Force mock
    mock_c = get_llm_client(force_mock=True)
    assert mock_c.__class__.__name__ == "MockLLMClient"

    # Explicit provider 'mock'
    mock_c2 = get_llm_client(provider="mock")
    assert mock_c2.__class__.__name__ == "MockLLMClient"

    # Explicit provider 'ollama'
    ollama_c = get_llm_client(provider="ollama")
    assert ollama_c.__class__.__name__ == "OllamaClient"

    # Explicit provider 'sarvam' with valid key
    with patch("app.llm.service.get_settings") as mock_settings:
        mock_settings.return_value = Settings(
            SARVAM_API_KEY="test-key",
            SARVAM_MODEL="sarvam-105b",
            LLM_PROVIDER="sarvam",
        )
        sarvam_c = get_llm_client(provider="sarvam")
        assert sarvam_c.__class__.__name__ == "SarvamClient"
        assert sarvam_c.model == "sarvam-105b"

    # Explicit provider 'sarvam' without key raises ValueError (no silent fallback!)
    with patch("app.llm.service.get_settings") as mock_settings:
        mock_settings.return_value = Settings(
            SARVAM_API_KEY=None,
            LLM_PROVIDER="sarvam",
        )
        with pytest.raises(ValueError, match="SARVAM_API_KEY is not configured"):
            get_llm_client(provider="sarvam")

    # Invalid provider raises ValueError
    with pytest.raises(ValueError, match="Unknown LLM provider"):
        get_llm_client(provider="nonexistent_provider")
