"""Ollama client integration with thinking-mode suppression, circuit breaker, and JSON schema enforcement."""
import time
from typing import Any

import httpx

from app.core.config import get_settings
from app.llm.base import BaseLLMClient, parse_and_validate
from app.llm.prompts import SYSTEM_INVESTIGATION_PROMPT, build_investigation_user_prompt
from app.schemas.evidence import EvidenceItemRead
from app.schemas.investigation import InvestigationResult, ModelMetadata


from app.llm.circuit_breaker import CircuitBreaker


class OllamaClient(BaseLLMClient):
    """Client for local/self-hosted Ollama server supporting Qwen3 / open weights."""

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        timeout_seconds: float | None = None,
        temperature: float | None = None,
        circuit_breaker: CircuitBreaker | None = None,
    ):
        settings = get_settings()
        self.base_url = (base_url or settings.OLLAMA_BASE_URL).rstrip("/")
        self.model = model or settings.OLLAMA_MODEL
        self.timeout_seconds = timeout_seconds if timeout_seconds is not None else settings.OLLAMA_TIMEOUT_SECONDS
        self.temperature = temperature if temperature is not None else settings.LLM_TEMPERATURE
        self.circuit_breaker = circuit_breaker or CircuitBreaker()
        self.call_count = 0

    def build_payload(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        """Construct Ollama API request payload with top-level format and think, options temperature (Requirement 7)."""
        temp = temperature if temperature is not None else self.temperature
        payload: dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "format": "json",
            "think": False,
            "stream": False,
            "options": {
                "temperature": temp,
            },
        }
        if system_prompt:
            payload["system"] = system_prompt
        return payload

    def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float | None = None,
    ) -> str:
        """Call Ollama /api/generate with format: json and think: false at top level."""
        self.call_count += 1
        if not self.circuit_breaker.can_execute():
            raise ConnectionError("Circuit breaker is OPEN: Ollama service temporarily unavailable")

        url = f"{self.base_url}/api/generate"
        payload = self.build_payload(prompt, system_prompt=system_prompt, temperature=temperature)

        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                resp = client.post(url, json=payload)
                resp.raise_for_status()
                data = resp.json()
                self.circuit_breaker.record_success()
                return data.get("response", "")
        except Exception:
            self.circuit_breaker.record_failure()
            raise

    def investigate(
        self,
        case_id: str,
        complaint_text: str,
        evidence_items: list[EvidenceItemRead],
        prompt_version: str = "2026-10-phase2-v1",
    ) -> InvestigationResult:
        """Execute full investigation. On timeout or model unavailability, returns safe escalation (Requirement 4)."""
        # Circuit breaker pre-check
        if not self.circuit_breaker.can_execute():
            return InvestigationResult(
                case_id=case_id,
                issue_type="model_unavailable",
                summary="Circuit breaker is OPEN: Ollama service temporarily unavailable. Safe escalation triggered.",
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
            disable_thinking=True,
        )

        start_time = time.perf_counter()
        try:
            raw_output = self.generate(
                prompt=prompt,
                system_prompt=SYSTEM_INVESTIGATION_PROMPT,
                temperature=self.temperature,
            )
        except httpx.TimeoutException:
            # Model request timed out
            self.circuit_breaker.record_failure()
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
            # Model service unavailable
            self.circuit_breaker.record_failure()
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
