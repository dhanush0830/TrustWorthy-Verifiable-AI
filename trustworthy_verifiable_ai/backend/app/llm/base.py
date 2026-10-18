"""Base LLM client interface and output parsing with thinking-tag stripping."""
import abc
import json
import re

from app.schemas.evidence import EvidenceItemRead
from app.schemas.investigation import InvestigationResult

# Regex pattern to match <think>...</think> and <thought>...</thought> blocks
THINK_BLOCK_REGEX = re.compile(r"<(think|thought)>[\s\S]*?</\1>", re.IGNORECASE)

# Regex to match markdown json codeblocks ```json ... ```
JSON_CODEBLOCK_REGEX = re.compile(r"```(?:json)?\s*([\s\S]*?)\s*```", re.IGNORECASE)


def strip_thinking_tags(text: str) -> str:
    """Remove <think>...</think> blocks and leading reasoning tags before JSON parsing.
    
    Qwen3 / DeepSeek reasoning models emit internal thinking text enclosed in
    <think>...</think> tags. This function strips those blocks completely.
    """
    if not text:
        return ""
    # Strip <think>...</think> blocks
    cleaned = THINK_BLOCK_REGEX.sub("", text).strip()
    return cleaned


def extract_json_payload(text: str) -> str:
    """Extract clean JSON string from raw text or markdown codeblocks."""
    cleaned = strip_thinking_tags(text)
    
    # Check if enclosed in ```json ... ```
    match = JSON_CODEBLOCK_REGEX.search(cleaned)
    if match:
        return match.group(1).strip()
    
    # Otherwise find outermost matching braces '{' ... '}'
    first_brace = cleaned.find("{")
    last_brace = cleaned.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        return cleaned[first_brace:last_brace + 1].strip()
    
    return cleaned.strip()


def parse_and_validate(raw_text: str, fallback_case_id: str = "") -> InvestigationResult:
    """Parse raw model output into an InvestigationResult Pydantic schema.
    
    Strips thinking tags, extracts JSON, and validates all required fields
    and claims against Pydantic models.
    """
    cleaned_json_str = extract_json_payload(raw_text)
    if not cleaned_json_str:
        raise ValueError("Model output contains no valid JSON payload")
    
    try:
        data = json.loads(cleaned_json_str)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Failed to decode model JSON: {exc}. Cleaned text: {cleaned_json_str[:200]}") from exc

    if not isinstance(data, dict):
        raise TypeError(f"Expected JSON object at top level, got {type(data).__name__}")

    # Fallback case_id if omitted by the LLM
    if ("case_id" not in data or not data["case_id"]) and fallback_case_id:
        data["case_id"] = fallback_case_id

    return InvestigationResult.model_validate(data)


class BaseLLMClient(abc.ABC):
    """Abstract interface for LLM providers (MockLLMClient, OllamaClient)."""

    call_count: int = 0

    @abc.abstractmethod
    def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.0,
    ) -> str:
        """Raw completion or chat generation returning string."""

    @abc.abstractmethod
    def investigate(
        self,
        case_id: str,
        complaint_text: str,
        evidence_items: list[EvidenceItemRead],
        prompt_version: str = "2026-10-phase2-v1",
    ) -> InvestigationResult:
        """Run complete investigation flow, returning structured InvestigationResult."""
