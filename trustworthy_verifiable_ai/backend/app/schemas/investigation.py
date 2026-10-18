"""Pydantic schemas for AI investigation results, structured claims, and proposed actions (FR-05, FR-06)."""
from enum import Enum

from pydantic import BaseModel, Field


class ClaimType(str, Enum):
    """Categorization of factual claims made by the model."""
    PAYMENT_CHARGED = "payment_charged"
    PAYMENT_PENDING = "payment_pending"
    ORDER_FAILED = "order_failed"
    DUPLICATE_CHARGE = "duplicate_charge"
    REFUND_MISSING = "refund_missing"
    CHARGE_AMOUNT_MISMATCH = "charge_amount_mismatch"
    POLICY_CONDITION = "policy_condition"
    OTHER = "other"


class ActionType(str, Enum):
    """Types of actions that may be proposed by the investigation."""
    REFUND = "refund"
    DISMISS = "dismiss"
    ESCALATE_HUMAN = "escalate_human"
    REQUEST_INFO = "request_info"


class Claim(BaseModel):
    """Structured claim backed by specific evidence identifiers (FR-06)."""
    claim_type: ClaimType = Field(..., description="Category of the claim")
    statement: str = Field(..., description="Clear factual statement synthesized from evidence")
    evidence_ids: list[str] = Field(
        ...,
        description="IDs of EvidenceItem records supporting this claim. FR-06 requirement."
    )
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Confidence score from 0.0 to 1.0")
    is_accepted: bool = Field(default=True, description="Whether this claim passed evidence package validation")
    flagged: bool = Field(default=False, description="Flagged if claim cites evidence not in provided package")
    rejection_reason: str | None = Field(default=None, description="Reason if claim was flagged or rejected")


class ProposedAction(BaseModel):
    """Optional action proposed by the AI investigation, subject to deterministic verification."""
    action_type: ActionType = Field(..., description="Recommended action type")
    target_payment_id: str | None = Field(default=None, description="Payment ID subject to action")
    amount: int | None = Field(
        default=None,
        description="Transaction amount in integer minor units (USD), e.g. 49900 = $499.00 (NFR-03)"
    )
    currency: str = Field(default="USD", description="Currency fixed to USD")
    reason: str = Field(..., description="Justification synthesized from claims")


class ModelMetadata(BaseModel):
    """Metadata recorded for compliance, reproducibility, and audit (FR-17)."""
    model_name: str
    temperature: float
    prompt_version: str
    latency_ms: int | None = None


class InvestigationResult(BaseModel):
    """Complete output of the AI investigation layer (FR-05, FR-06)."""
    case_id: str = Field(..., description="Associated complaint case ID")
    issue_type: str = Field(..., description="Identified complaint category, e.g. double_charge")
    summary: str = Field(..., description="Executive summary of the case and findings")
    claims: list[Claim] = Field(default_factory=list, description="List of evidence-backed claims")
    proposed_action: ProposedAction | None = Field(
        default=None,
        description="Optional action proposed by the model (verified later in Phase 3)"
    )
    needs_escalation: bool = Field(default=False, description="Flag indicating safe abstention / human review needed")
    has_unsupported_claims: bool = Field(default=False, description="True if any claims were flagged as unsupported")
    model_metadata: ModelMetadata | None = Field(default=None, description="Model invocation metadata")


class InvestigateRequest(BaseModel):
    """Request payload for investigating a complaint case with size limit enforcement."""
    complaint: str | None = Field(
        default=None,
        description="Optional customer complaint text override (limited to MAX_COMPLAINT_CHARS)"
    )
