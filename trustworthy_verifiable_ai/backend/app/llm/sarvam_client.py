"""Sarvam AI client integration compatible with BaseLLMClient."""
import time
from typing import Any

import httpx

from app.core.config import get_settings
from app.llm.base import BaseLLMClient, parse_and_validate
from app.llm.circuit_breaker import CircuitBreaker
from app.llm.prompts import SYSTEM_INVESTIGATION_PROMPT, build_investigation_user_prompt
from app.schemas.evidence import EvidenceItemRead
from app.schemas.investigation import InvestigationResult, ModelMetadata


class SarvamClient(BaseLLMClient):
    """Client for Sarvam AI Chat Completions API (sarvam-105b)."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout_seconds: float | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        reasoning_effort: str | None = None,
        circuit_breaker: CircuitBreaker | None = None,
    ):
        settings = get_settings()
        self.api_key = api_key if api_key is not None else settings.SARVAM_API_KEY
        self.base_url = (base_url or settings.SARVAM_BASE_URL).rstrip("/")
        self.model = model or settings.SARVAM_MODEL
        self.timeout_seconds = timeout_seconds if timeout_seconds is not None else settings.SARVAM_TIMEOUT_SECONDS
        self.temperature = temperature if temperature is not None else settings.LLM_TEMPERATURE
        self.max_tokens = max_tokens if max_tokens is not None else 4096
        self.reasoning_effort = reasoning_effort  # None explicitly disables thinking mode to prevent token exhaustion
        self.circuit_breaker = circuit_breaker or CircuitBreaker()
        self.call_count = 0

    @property
    def endpoint_url(self) -> str:
        """Resolve the full chat completions endpoint URL."""
        if self.base_url.endswith("/v1/chat/completions"):
            return self.base_url
        if self.base_url.endswith("/v1"):
            return f"{self.base_url}/chat/completions"
        return f"{self.base_url}/v1/chat/completions"

    def build_payload(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        """Construct Sarvam chat completions payload with OpenAI-compatible messages."""
        temp = temperature if temperature is not None else self.temperature
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        return {
            "model": self.model,
            "messages": messages,
            "temperature": temp,
            "max_tokens": self.max_tokens,
            "reasoning_effort": self.reasoning_effort,
            "response_format": {"type": "json_object"},
        }

    def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float | None = None,
    ) -> str:
        """Call Sarvam POST /v1/chat/completions returning raw content string."""
        self.call_count += 1

        if not self.api_key:
            raise ValueError("SARVAM_API_KEY is not configured")

        if not self.circuit_breaker.can_execute():
            raise ConnectionError("Circuit breaker is OPEN: Sarvam service temporarily unavailable")

        url = self.endpoint_url
        payload = self.build_payload(prompt, system_prompt=system_prompt, temperature=temperature)
        headers = {
            "Content-Type": "application/json",
            "api-subscription-key": self.api_key,
        }

        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                resp = client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                self.circuit_breaker.record_success()
        except Exception:
            self.circuit_breaker.record_failure()
            raise

        if not isinstance(data, dict) or "choices" not in data or not data["choices"]:
            raise ValueError(f"Malformed Sarvam API response: {data}")

        choice = data["choices"][0]
        if not isinstance(choice, dict) or "message" not in choice:
            raise ValueError(f"Malformed choice in Sarvam API response: {choice}")

        finish_reason = choice.get("finish_reason")
        message = choice.get("message") or {}
        content = message.get("content")

        if content is None or content == "":
            reasoning = message.get("reasoning_content")
            refusal = message.get("refusal")
            if refusal:
                raise ValueError(f"Sarvam model refused request: {refusal}")
            elif reasoning:
                content = reasoning
            elif finish_reason == "length":
                raise ValueError("Sarvam model token limit reached (finish_reason='length') before output completed")
            elif finish_reason == "content_filter":
                raise ValueError("Sarvam model output was omitted by content filter")
            else:
                raise ValueError(f"Sarvam API returned message with no content (finish_reason='{finish_reason}')")

        return content

    def investigate(
        self,
        case_id: str,
        complaint_text: str,
        evidence_items: list[EvidenceItemRead],
        prompt_version: str = "2026-10-phase2-v1",
    ) -> InvestigationResult:
        """Execute full investigation via Sarvam AI. Safely escalates on errors/timeouts (never guess)."""
        if not self.circuit_breaker.can_execute():
            return InvestigationResult(
                case_id=case_id,
                issue_type="model_unavailable",
                summary="Circuit breaker is OPEN: Sarvam service temporarily unavailable. Safe escalation triggered.",
                claims=[],
                proposed_action=None,
                needs_escalation=True,
                model_metadata=ModelMetadata(
                    model_name=self.model,
                    temperature=self.temperature,
                    prompt_version=prompt_version,
                    latency_ms=0,
                ),
            )

        if not self.api_key:
            return InvestigationResult(
                case_id=case_id,
                issue_type="model_unavailable",
                summary="SARVAM_API_KEY is missing or invalid. Safe escalation triggered.",
                claims=[],
                proposed_action=None,
                needs_escalation=True,
                model_metadata=ModelMetadata(
                    model_name=self.model,
                    temperature=self.temperature,
                    prompt_version=prompt_version,
                    latency_ms=0,
                ),
            )

        prompt = build_investigation_user_prompt(
            case_id=case_id,
            redacted_complaint=complaint_text,
            evidence_items=evidence_items,
            disable_thinking=False,
        )

        start_time = time.perf_counter()
        try:
            raw_output = self.generate(
                prompt=prompt,
                system_prompt=SYSTEM_INVESTIGATION_PROMPT,
                temperature=self.temperature,
            )
        except httpx.TimeoutException:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            return InvestigationResult(
                case_id=case_id,
                issue_type="model_timeout",
                summary=f"Model request timed out after {self.timeout_seconds}s. Safe escalation triggered (never guess).",
                claims=[],
                proposed_action=None,
                needs_escalation=True,
                model_metadata=ModelMetadata(
                    model_name=self.model,
                    temperature=self.temperature,
                    prompt_version=prompt_version,
                    latency_ms=latency_ms,
                ),
            )
        except (httpx.HTTPError, ConnectionError, OSError) as exc:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            return InvestigationResult(
                case_id=case_id,
                issue_type="model_unavailable",
                summary=f"Model service unavailable: {exc}. Safe escalation triggered (never guess).",
                claims=[],
                proposed_action=None,
                needs_escalation=True,
                model_metadata=ModelMetadata(
                    model_name=self.model,
                    temperature=self.temperature,
                    prompt_version=prompt_version,
                    latency_ms=latency_ms,
                ),
            )

        latency_ms = int((time.perf_counter() - start_time) * 1000)
        result = parse_and_validate(raw_output, fallback_case_id=case_id)
        result.model_metadata = ModelMetadata(
            model_name=self.model,
            temperature=self.temperature,
            prompt_version=prompt_version,
            latency_ms=latency_ms,
        )
        return result
