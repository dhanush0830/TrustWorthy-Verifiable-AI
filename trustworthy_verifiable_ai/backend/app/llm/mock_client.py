"""Deterministic MockLLMClient for offline testing without network access (NFR-01)."""
from collections.abc import Callable

from app.llm.base import BaseLLMClient, parse_and_validate
from app.schemas.evidence import EvidenceItemRead
from app.schemas.investigation import (
    ActionType,
    Claim,
    ClaimType,
    InvestigationResult,
    ModelMetadata,
    ProposedAction,
)


class MockLLMClient(BaseLLMClient):
    """Deterministic, offline LLM mock for unit tests and reproducible evaluations."""

    def __init__(
        self,
        model_name: str = "mock-qwen3-8b",
        temperature: float = 0.0,
        custom_handler: Callable[[str, list[EvidenceItemRead]], InvestigationResult] | None = None,
    ):
        self.model_name = model_name
        self.temperature = temperature
        self.custom_handler = custom_handler
        self._canned_raw_responses: dict[str, str] = {}
        self.call_count = 0

    def set_raw_response(self, case_id: str, raw_response: str) -> None:
        """Register a specific raw string response (e.g., with <think> tags or errors)."""
        self._canned_raw_responses[case_id] = raw_response

    def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.0,
    ) -> str:
        """Deterministic raw generation."""
        self.call_count += 1
        return '{"issue_type": "general_inquiry", "summary": "Mock generation"}'

    def investigate(
        self,
        case_id: str,
        complaint_text: str,
        evidence_items: list[EvidenceItemRead],
        prompt_version: str = "2026-10-phase2-v1",
    ) -> InvestigationResult:
        """Generate structured deterministic findings linked to actual evidence IDs (FR-06)."""
        self.call_count += 1
        # If a raw canned response was registered for this case_id, parse it through standard pipeline
        if case_id in self._canned_raw_responses:
            raw_text = self._canned_raw_responses[case_id]
            result = parse_and_validate(raw_text, fallback_case_id=case_id)
            result.model_metadata = ModelMetadata(
                model_name=self.model_name,
                temperature=self.temperature,
                prompt_version=prompt_version,
                latency_ms=5,
            )
            return result

        if self.custom_handler:
            result = self.custom_handler(complaint_text, evidence_items)
            result.case_id = case_id
            result.model_metadata = ModelMetadata(
                model_name=self.model_name,
                temperature=self.temperature,
                prompt_version=prompt_version,
                latency_ms=5,
            )
            return result

        # Dynamic default deterministic generator based on evidence
        evidence_ids = [item.id for item in evidence_items]
        
        # Check for duplicate payments in evidence
        payment_items = [
            item for item in evidence_items
            if item.source_system in ("payment_gateway", "payment_provider")
        ]
        order_items = [item for item in evidence_items if item.source_system == "order_service"]

        claims: list[Claim] = []
        proposed_action: ProposedAction | None = None
        issue_type = "general_complaint"
        needs_escalation = False

        if len(payment_items) >= 2:
            issue_type = "duplicate_charge"
            p1 = payment_items[0]
            p2 = payment_items[1]
            claims.append(
                Claim(
                    claim_type=ClaimType.PAYMENT_CHARGED,
                    statement=f"First payment {p1.source_record_id} was successfully settled",
                    evidence_ids=[p1.id],
                    confidence=1.0,
                )
            )
            claims.append(
                Claim(
                    claim_type=ClaimType.DUPLICATE_CHARGE,
                    statement=f"Second payment {p2.source_record_id} settled for the same transaction",
                    evidence_ids=[p2.id],
                    confidence=1.0,
                )
            )
            proposed_action = ProposedAction(
                action_type=ActionType.REFUND,
                target_payment_id=p2.source_record_id,
                amount=49900,
                currency="USD",
                reason=f"Refund duplicate settled payment {p2.source_record_id}",
            )
        elif len(payment_items) == 1:
            p = payment_items[0]
            claims.append(
                Claim(
                    claim_type=ClaimType.PAYMENT_CHARGED,
                    statement=f"Payment {p.source_record_id} is recorded in payment gateway",
                    evidence_ids=[p.id],
                    confidence=1.0,
                )
            )
            if order_items:
                ord_item = order_items[0]
                claims.append(
                    Claim(
                        claim_type=ClaimType.ORDER_FAILED,
                        statement=f"Order {ord_item.source_record_id} failed or cancelled",
                        evidence_ids=[ord_item.id],
                        confidence=1.0,
                    )
                )
                issue_type = "order_failed_payment_captured"
                proposed_action = ProposedAction(
                    action_type=ActionType.REFUND,
                    target_payment_id=p.source_record_id,
                    amount=49900,
                    currency="USD",
                    reason=f"Order failed but payment {p.source_record_id} was captured",
                )
            else:
                issue_type = "unrecognized_transaction"
                proposed_action = ProposedAction(
                    action_type=ActionType.REFUND,
                    target_payment_id=p.source_record_id,
                    amount=49900,
                    currency="USD",
                    reason=f"Customer disputes charge on {p.source_record_id}",
                )
        else:
            issue_type = "unsupported_claim"
            needs_escalation = True
            claims.append(
                Claim(
                    claim_type=ClaimType.OTHER,
                    statement="No payment records discovered for customer dispute",
                    evidence_ids=evidence_ids if evidence_ids else ["NO_EVIDENCE"],
                    confidence=0.5,
                )
            )

        summary = f"Synthesized {len(claims)} claims for case {case_id} ({issue_type})"

        return InvestigationResult(
            case_id=case_id,
            issue_type=issue_type,
            summary=summary,
            claims=claims,
            proposed_action=proposed_action,
            needs_escalation=needs_escalation,
            model_metadata=ModelMetadata(
                model_name=self.model_name,
                temperature=self.temperature,
                prompt_version=prompt_version,
                latency_ms=5,
            ),
        )
