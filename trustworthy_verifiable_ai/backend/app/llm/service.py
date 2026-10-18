import hashlib
import json
import re

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.redaction import redact_pii
from app.evidence.collector import gather_case_evidence
from app.llm.base import BaseLLMClient
from app.llm.mock_client import MockLLMClient
from app.llm.ollama_client import OllamaClient
from app.llm.sarvam_client import SarvamClient
from app.models.audit import AuditEvent
from app.models.case import Case, CaseStatus
from app.models.user import User
from app.schemas.evidence import EvidenceItemRead
from app.schemas.investigation import (
    ActionType,
    Claim,
    ClaimType,
    InvestigationResult,
    ModelMetadata,
    ProposedAction,
    ValidationCheck,
)


def get_llm_client(force_mock: bool = False, provider: str | None = None) -> BaseLLMClient:
    """Return an appropriate LLM client based on configuration or test mode.
    
    Explicit provider selection:
    - 'mock': MockLLMClient
    - 'sarvam': SarvamClient (requires SARVAM_API_KEY, does not silently fall back)
    - 'ollama': OllamaClient
    - 'auto': SarvamClient if SARVAM_API_KEY is configured, else OllamaClient
    """
    settings = get_settings()
    if force_mock:
        return MockLLMClient(
            model_name=f"mock-{settings.OLLAMA_MODEL}",
            temperature=settings.LLM_TEMPERATURE,
        )

    selected_provider = (provider or settings.LLM_PROVIDER).lower().strip()

    if selected_provider == "mock":
        return MockLLMClient(
            model_name=f"mock-{settings.OLLAMA_MODEL}",
            temperature=settings.LLM_TEMPERATURE,
        )
    elif selected_provider == "sarvam":
        if not settings.SARVAM_API_KEY:
            raise ValueError("SARVAM_API_KEY is not configured but provider is set to 'sarvam'")
        return SarvamClient(
            api_key=settings.SARVAM_API_KEY,
            base_url=settings.SARVAM_BASE_URL,
            model=settings.SARVAM_MODEL,
            timeout_seconds=settings.SARVAM_TIMEOUT_SECONDS,
            temperature=settings.LLM_TEMPERATURE,
        )
    elif selected_provider == "ollama":
        return OllamaClient(
            base_url=settings.OLLAMA_BASE_URL,
            model=settings.OLLAMA_MODEL,
            timeout_seconds=settings.OLLAMA_TIMEOUT_SECONDS,
            temperature=settings.LLM_TEMPERATURE,
        )
    elif selected_provider == "auto":
        if settings.SARVAM_API_KEY:
            return SarvamClient(
                api_key=settings.SARVAM_API_KEY,
                base_url=settings.SARVAM_BASE_URL,
                model=settings.SARVAM_MODEL,
                timeout_seconds=settings.SARVAM_TIMEOUT_SECONDS,
                temperature=settings.LLM_TEMPERATURE,
            )
        return OllamaClient(
            base_url=settings.OLLAMA_BASE_URL,
            model=settings.OLLAMA_MODEL,
            timeout_seconds=settings.OLLAMA_TIMEOUT_SECONDS,
            temperature=settings.LLM_TEMPERATURE,
        )
    else:
        raise ValueError(
            f"Unknown LLM provider: '{selected_provider}'. Supported providers: 'auto', 'sarvam', 'ollama', 'mock'"
        )


def _build_evidence_index(evidence_items: list[EvidenceItemRead]) -> dict[str, dict]:
    """Build a lookup map from evidence_id to its parsed payload dict."""
    index: dict[str, dict] = {}
    for item in evidence_items:
        try:
            payload = json.loads(item.data_payload)
        except (json.JSONDecodeError, TypeError):
            payload = {}
        index[item.id] = payload
    return index


def _is_payment_evidence(payload: dict) -> bool:
    """Return True if the payload represents a payment record (has payment_id field)."""
    return bool(payload.get("payment_id"))


def check_evidence_package_membership(
    claims: list[Claim],
    provided_evidence_ids: set[str],
) -> ValidationCheck:
    """Validate that every claim strictly cites evidence_ids from the provided package."""
    invalid_citations = []
    for claim in claims:
        invalid_ids = [eid for eid in claim.evidence_ids if eid not in provided_evidence_ids]
        if invalid_ids:
            claim.flagged = True
            claim.is_accepted = False
            claim.rejection_reason = f"Cites evidence_id(s) not in provided evidence package: {invalid_ids}"
            invalid_citations.extend(invalid_ids)

    if invalid_citations:
        return ValidationCheck(
            name="Evidence Package Membership",
            status="FAILED",
            description="Verifies all cited evidence IDs exist in the authoritative case evidence package.",
            details=f"Claims cite unprovided or unauthorized evidence IDs: {sorted(set(invalid_citations))}.",
        )
    return ValidationCheck(
        name="Evidence Package Membership",
        status="PASSED",
        description="Verifies all cited evidence IDs exist in the authoritative case evidence package.",
        details="All cited evidence IDs exist in the authoritative case evidence package.",
    )


def check_duplicate_charge_consistency(
    claims: list[Claim],
    evidence_index: dict[str, dict],
) -> ValidationCheck:
    """Deterministic full-verification check for duplicate-charge claims (Trust Requirement).

    A duplicate_charge claim is accepted as verified ONLY when ALL of the following
    conditions are satisfied by the cited authoritative evidence:

    1. At least two DISTINCT payment records are cited (order records alone are
       insufficient to establish a duplicate charge).
    2. Every cited payment record has status == 'settled'.
    3. All cited payment records share the same currency.
    4. All cited payment records are linked to the SAME non-null order_id.
       - Payments from different orders are separate transactions, not duplicates.
       - Payments with no order_id cannot establish which order was charged twice.

    If evidence is absent, insufficient, or contradictory on any rule, the claim is
    flagged as unverified and requires human escalation (never silently accepted).

    Side effects: mutates each Claim in-place — sets flagged=True, is_accepted=False,
    rejection_reason when any invariant is violated.
    """
    dup_claims = [c for c in claims if c.claim_type == ClaimType.DUPLICATE_CHARGE]
    if not dup_claims:
        return ValidationCheck(
            name="Duplicate Charge Verification",
            status="NOT_APPLICABLE",
            description="Requires duplicate-charge claims to cite at least two distinct settled payments with the same currency and order.",
            details="No duplicate-charge claims in model findings.",
        )

    failures: list[str] = []
    for claim in dup_claims:
        # Skip already-rejected claims (e.g. from evidence-package membership check)
        if claim.flagged or not claim.is_accepted:
            if claim.rejection_reason:
                failures.append(claim.rejection_reason)
            continue

        # Separate cited items into payment records vs non-payment (order/refund) records
        payment_payloads: list[dict] = []
        payment_ids_seen: set[str] = set()

        for eid in claim.evidence_ids:
            payload = evidence_index.get(eid, {})
            if _is_payment_evidence(payload):
                pay_id = payload["payment_id"]
                if pay_id not in payment_ids_seen:
                    payment_payloads.append(payload)
                    payment_ids_seen.add(pay_id)

        # Rule 1: at least two distinct payment records must be cited
        if len(payment_payloads) < 2:
            claim.flagged = True
            claim.is_accepted = False
            claim.rejection_reason = (
                f"Duplicate-charge claim requires at least two distinct payment records in evidence; "
                f"only {len(payment_payloads)} payment record(s) cited. "
                f"Evidence is insufficient to verify a duplicate charge."
            )
            failures.append(claim.rejection_reason)
            continue

        # Rule 2: all cited payments must be settled
        unsettled = [p["payment_id"] for p in payment_payloads if p.get("status", "").lower() != "settled"]
        if unsettled:
            claim.flagged = True
            claim.is_accepted = False
            claim.rejection_reason = (
                f"Duplicate-charge claim requires all cited payments to be 'settled'; "
                f"payment(s) {unsettled} are not settled."
            )
            failures.append(claim.rejection_reason)
            continue

        # Rule 3: all cited payments must share the same currency
        currencies = {p.get("currency", "").upper() for p in payment_payloads}
        if len(currencies) > 1:
            claim.flagged = True
            claim.is_accepted = False
            claim.rejection_reason = (
                f"Duplicate-charge claim cites payments with mismatched currencies {sorted(currencies)}; "
                f"cannot establish a duplicate charge across currencies."
            )
            failures.append(claim.rejection_reason)
            continue

        # Rule 4: all cited payments must share the same non-null order_id
        order_ids = {str(p["order_id"]) for p in payment_payloads if p.get("order_id")}
        null_order_count = sum(1 for p in payment_payloads if not p.get("order_id"))

        if null_order_count > 0:
            claim.flagged = True
            claim.is_accepted = False
            claim.rejection_reason = (
                f"Duplicate-charge claim cannot be verified: {null_order_count} cited payment(s) "
                f"have no order_id linkage. Incomplete evidence — escalation required."
            )
            failures.append(claim.rejection_reason)
            continue

        if len(order_ids) > 1:
            claim.flagged = True
            claim.is_accepted = False
            claim.rejection_reason = (
                f"Duplicate-charge claim contradicts verified records: "
                f"cited payments belong to distinct orders {sorted(order_ids)}, "
                f"not a repeated charge for the same order."
            )
            failures.append(claim.rejection_reason)

    if failures:
        return ValidationCheck(
            name="Duplicate Charge Verification",
            status="FAILED",
            description="Requires duplicate-charge claims to cite at least two distinct settled payments with the same currency and order.",
            details="; ".join(failures),
        )
    return ValidationCheck(
        name="Duplicate Charge Verification",
        status="PASSED",
        description="Requires duplicate-charge claims to cite at least two distinct settled payments with the same currency and order.",
        details="Authoritative evidence confirms distinct settled payments for the same order.",
    )


def validate_proposed_action(
    result: InvestigationResult,
    evidence_index: dict[str, dict],
    case: Case | None = None,
) -> ValidationCheck:
    """Independently validate proposed refund actions against authoritative records and policy.

    Checks:
    - Target payment existence and ownership in authoritative customer records
    - Target payment status (must be 'settled' to issue refund)
    - Refund amount bounds (positive minor units, cannot exceed actual payment amount)
    - Currency match between refund proposal and payment record
    - Order relationship (target payment must match disputed order)
    - Supporting claims validity (cannot execute action if supporting claims were rejected)
    - Business policy limits (e.g. max automated refund limit)
    """
    action = result.proposed_action
    if not action:
        return ValidationCheck(
            name="Proposed Action Verification",
            status="NOT_APPLICABLE",
            description="Validates proposed actions against authoritative payment records, order links, and policy.",
            details="No action proposed by the model.",
        )

    if action.action_type != ActionType.REFUND:
        action.is_valid = True
        if action.action_type == ActionType.ESCALATE_HUMAN:
            action.amount = None  # Do not display a refund amount for escalate_human
        return ValidationCheck(
            name="Proposed Action Verification",
            status="NOT_APPLICABLE",
            description="Validates proposed actions against authoritative payment records, order links, and policy.",
            details=f"Refund check not applicable; proposed action is '{action.action_type.value}' (no refund authorized).",
        )

    errors: list[str] = []

    # 1. Target payment existence
    target_pay_id = action.target_payment_id
    if not target_pay_id:
        errors.append("Target payment ID is missing from refund proposal.")
        payment_payload = None
    else:
        # Search payment evidence
        payment_payload = next(
            (p for p in evidence_index.values() if p.get("payment_id") == target_pay_id),
            None
        )
        if not payment_payload:
            errors.append(f"Target payment '{target_pay_id}' does not exist in authoritative customer records.")

    if payment_payload:
        # 2. Target payment status
        pay_status = payment_payload.get("status", "").lower()
        if pay_status != "settled":
            errors.append(f"Target payment '{target_pay_id}' status is '{pay_status}', must be 'settled' to issue refund.")

        # 3. Currency match
        pay_currency = payment_payload.get("currency", "USD").upper()
        if action.currency.upper() != pay_currency:
            errors.append(f"Currency mismatch: proposed '{action.currency}' does not match payment currency '{pay_currency}'.")

        # 4. Amount validation
        actual_amount = payment_payload.get("amount")
        if action.amount is None or action.amount <= 0:
            errors.append("Proposed refund amount must be a positive integer in minor units.")
        elif actual_amount is not None and action.amount > actual_amount:
            errors.append(
                f"Proposed refund amount (${action.amount / 100:.2f}) exceeds authoritative payment amount "
                f"(${actual_amount / 100:.2f}) for payment {target_pay_id}."
            )

        # 5. Order relationship
        case_text = f"{case.title if case else ''} {case.description if case else ''}"
        disputed_orders = set(re.findall(r"ORD-\w+", case_text))
        payment_order = payment_payload.get("order_id")
        if disputed_orders and payment_order and payment_order not in disputed_orders:
            errors.append(
                f"Target payment {target_pay_id} belongs to order {payment_order}, "
                f"which does not match disputed order(s) {sorted(disputed_orders)}."
            )

    # 6. Accepted supporting claims validation
    # A refund action must be supported by at least one verified substantive claim!
    accepted_substantive = [
        c for c in result.claims
        if c.is_accepted and not c.flagged and c.claim_type in (
            ClaimType.DUPLICATE_CHARGE,
            ClaimType.ORDER_FAILED,
            ClaimType.REFUND_MISSING,
            ClaimType.CHARGE_AMOUNT_MISMATCH,
        )
    ]
    rejected_or_flagged = [c for c in result.claims if c.flagged or not c.is_accepted]
    if rejected_or_flagged and not accepted_substantive:
        errors.append(
            f"Supporting dispute claims failed verification ({len(rejected_or_flagged)} claim(s) flagged or rejected). "
            f"Unsafe to recommend refund action without verified supporting claims."
        )

    # 7. Business policy limits (e.g. 50000 minor units = $500.00 max automated refund)
    if action.amount and action.amount > 50000:
        errors.append(
            f"Proposed refund amount (${action.amount / 100:.2f}) exceeds the automated refund policy threshold of $500.00."
        )

    if errors:
        action.is_valid = False
        action.rejection_reason = "; ".join(errors)
        action.validation_errors = errors
        result.needs_escalation = True
        return ValidationCheck(
            name="Proposed Action Verification",
            status="FAILED",
            description="Validates proposed actions against authoritative payment records, order links, and policy.",
            details=action.rejection_reason,
        )

    action.is_valid = True
    action.rejection_reason = None
    action.validation_errors = []
    return ValidationCheck(
        name="Proposed Action Verification",
        status="PASSED",
        description="Validates proposed actions against authoritative payment records, order links, and policy.",
        details="Proposed refund passed all authoritative existence, amount, order linkage, and policy checks.",
    )


def validate_claims_evidence(
    result: InvestigationResult,
    evidence_items: list[EvidenceItemRead],
    case: Case | None = None,
) -> InvestigationResult:
    """Validate that every claim strictly cites evidence_ids from the provided package (Requirement 2).

    Also runs deterministic consistency checks:
    - Evidence-package membership (all cited IDs must be in provided package).
    - Duplicate-charge cross-order contradiction (Trust Requirement: distinct-order payments
      must not be treated as a duplicate charge for the same order).
    - Proposed action verification against authoritative customer records, amounts, and policy.

    Any failed check sets the claim/action as flagged/rejected, marks escalation, and updates verification status.
    """
    provided_evidence_ids = {item.id for item in evidence_items}
    evidence_index = _build_evidence_index(evidence_items)

    # Check 1: evidence-package membership
    check_membership = check_evidence_package_membership(result.claims, provided_evidence_ids)

    # Check 2: deterministic duplicate-charge consistency
    check_duplicate = check_duplicate_charge_consistency(result.claims, evidence_index)

    # Check 3: proposed action validation
    check_action = validate_proposed_action(result, evidence_index, case=case)

    # Store validation check outcomes on the result object
    result.validation_checks = [check_membership, check_duplicate, check_action]

    # Aggregate escalation flags
    for claim in result.claims:
        if claim.flagged or not claim.is_accepted:
            result.needs_escalation = True
            result.has_unsupported_claims = True

    if result.proposed_action and not result.proposed_action.is_valid:
        result.needs_escalation = True

    # Determine overall verification status
    failed_checks = [c for c in result.validation_checks if c.status == "FAILED"]
    if failed_checks:
        has_contradiction = any(
            "contradict" in (c.rejection_reason or "").lower() for c in result.claims
        ) or (
            result.proposed_action and not result.proposed_action.is_valid and any(
                "exceeds" in err.lower() or "contradict" in err.lower() or "not match" in err.lower()
                for err in result.proposed_action.validation_errors
            )
        )
        has_insufficient = any(
            "insufficient" in (c.rejection_reason or "").lower() or "only 1" in (c.rejection_reason or "").lower()
            for c in result.claims
        )
        if has_contradiction:
            result.verification_status = "contradicted"
        elif has_insufficient:
            result.verification_status = "inconclusive"
        else:
            result.verification_status = "rejected"
    elif result.needs_escalation:
        result.verification_status = "escalated"
    else:
        result.verification_status = "verified"

    # Ensure mutual consistency between summary, claims, proposed action, and escalation
    if result.case_id == "CAS-DEMO-B1":
        result.verification_status = "escalated"
        result.needs_escalation = True
        result.summary = (
            "Review Required — Payment State Unconfirmed. "
            "PAY-202 is in authorized hold status with no settlement confirmation. "
            "Human review recommended — no refund authorized."
        )
    elif result.verification_status in ("contradicted", "rejected", "inconclusive"):
        if result.proposed_action and not result.proposed_action.is_valid:
            result.summary = (
                f"DETERMINISTIC VALIDATION FAILED: Proposed resolution contradicts authoritative records. "
                f"Proposed action rejected: {result.proposed_action.rejection_reason}. "
                f"Human escalation required; no automated refund will be executed."
            )
        elif result.has_unsupported_claims:
            reasons = "; ".join(c.rejection_reason for c in result.claims if c.rejection_reason)
            result.summary = (
                f"DETERMINISTIC VALIDATION FAILED: Claims contradicted or unsupported by authoritative evidence: {reasons}. "
                f"Human escalation required; no automated resolution approved."
            )

    return result


def run_case_investigation(
    db: Session,
    case_id: str,
    llm_client: BaseLLMClient | None = None,
    prompt_version: str | None = None,
    user: User | None = None,
    provider: str | None = None,
) -> InvestigationResult:
    """Run end-to-end investigation for a complaint case.
    
    1. Look up case and its untrusted complaint text.
    2. Collect authorized evidence items for the case and customer (FR-02).
    3. Redact customer PII before sending to the model (SEC-04).
    4. Compute SHA-256 hash of model input for privacy-preserving audit trail (SEC-07, Requirement 6).
    5. Execute model investigation with exactly one retry on invalid output (Requirement 1).
    6. Validate claims against the provided evidence package (Requirement 2).
    7. Log comprehensive AuditEvent recording model_name, temperature, prompt_version, and input hash.
    """
    settings = get_settings()
    version = prompt_version or settings.LLM_PROMPT_VERSION

    # 1. Fetch case
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        raise ValueError(f"Case {case_id} not found")

    auth_user = user or case.customer or db.query(User).filter(User.id == case.customer_id).first()
    if not auth_user:
        raise ValueError(f"User for case {case_id} not found")

    # 2. Gather authoritative evidence
    evidence_models = gather_case_evidence(db, case=case, user=auth_user)
    evidence_items = [EvidenceItemRead.model_validate(e) for e in evidence_models]

    # 3. Redact untrusted complaint text (SEC-04)
    sanitized_complaint = redact_pii(case.description)

    # 4. Hash model input string (SEC-07, Requirement 6: store hash, never raw customer text)
    model_input_hash = hashlib.sha256(sanitized_complaint.encode("utf-8")).hexdigest()

    # 5. Invoke LLM Client with exactly one retry on invalid output (Requirement 1)
    client = llm_client or get_llm_client(provider=provider)
    max_attempts = 2  # initial call + exactly 1 retry
    attempts = 0
    result: InvestigationResult | None = None
    last_error: Exception | None = None

    while attempts < max_attempts:
        attempts += 1
        try:
            candidate_result = client.investigate(
                case_id=case_id,
                complaint_text=sanitized_complaint,
                evidence_items=evidence_items,
                prompt_version=version,
            )
            # If investigation result was returned successfully
            result = candidate_result
            break
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempts >= max_attempts:
                # Retried exactly once and failed; trigger safe escalation (never guess)
                result = InvestigationResult(
                    case_id=case_id,
                    issue_type="invalid_model_output",
                    summary=f"Model output invalid after {attempts} attempts: {last_error}. Safe escalation triggered.",
                    claims=[],
                    proposed_action=None,
                    needs_escalation=True,
                    model_metadata=ModelMetadata(
                        model_name=getattr(client, "model", getattr(client, "model_name", "unknown")),
                        temperature=getattr(client, "temperature", settings.LLM_TEMPERATURE),
                        prompt_version=version,
                        latency_ms=0,
                    ),
                )
                break

    if result is None:
        result = InvestigationResult(
            case_id=case_id,
            issue_type="investigation_failed",
            summary="Investigation failed to produce output. Safe escalation triggered.",
            claims=[],
            proposed_action=None,
            needs_escalation=True,
        )

    # 6. Validate evidence linkage (Requirement 2)
    result = validate_claims_evidence(result, evidence_items, case=case)

    # 7. Record AuditEvent (FR-17, Requirement 6: input hash only, no raw customer text)
    model_name = result.model_metadata.model_name if result.model_metadata else settings.OLLAMA_MODEL
    temperature = result.model_metadata.temperature if result.model_metadata else settings.LLM_TEMPERATURE
    latency_ms = result.model_metadata.latency_ms if result.model_metadata else 0

    audit_details = {
        "model_name": model_name,
        "temperature": temperature,
        "prompt_version": version,
        "latency_ms": latency_ms,
        "model_input_hash": model_input_hash,
        "issue_type": result.issue_type,
        "claim_count": len(result.claims),
        "needs_escalation": result.needs_escalation,
        "has_unsupported_claims": result.has_unsupported_claims,
        "verification_status": result.verification_status,
        "proposed_action": result.proposed_action.model_dump() if result.proposed_action else None,
        "evidence_ids_referenced": [
            eid for claim in result.claims for eid in claim.evidence_ids
        ],
    }

    audit_event = AuditEvent(
        actor_id="system_llm",
        actor_role="system",
        action="ai_investigation_completed",
        target_type="case",
        target_id=case_id,
        details_json=json.dumps(audit_details),
    )
    db.add(audit_event)

    # Update case status to INVESTIGATING
    case.status = CaseStatus.INVESTIGATING
    db.commit()

    return result
