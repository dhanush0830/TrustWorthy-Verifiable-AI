"""Pydantic schemas for event ingestion, evidence items, contradictions, and snapshots."""
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.evidence import FreshnessIndicator


class EventIngestRequest(BaseModel):
    """Schema for ingesting raw provider events."""
    provider_event_id: str = Field(..., description="Unique provider event ID for deduplication")
    payment_id: str | None = Field(None, description="Target payment ID if known")
    event_type: str = Field(..., description="Provider event name, e.g. payment.settled")
    amount: int = Field(..., description="Transaction amount in integer minor units")
    currency: str = Field("USD", description="Currency code (USD)")
    occurred_at: datetime = Field(..., description="Business timestamp when event occurred at provider")
    raw_payload: str | None = Field("{}", description="Raw serialized payload from provider")


class EventIngestResponse(BaseModel):
    """Result of event ingestion."""
    event_id: int
    provider_event_id: str
    created: bool
    status: str
    projected_payment_status: str | None = None


class EvidenceItemRead(BaseModel):
    """Normalized evidence item read schema."""
    id: str
    case_id: str | None = None
    customer_id: str
    source_system: str
    source_record_id: str
    provider_event_id: str | None = None
    occurred_at: datetime
    received_at: datetime
    fetched_at: datetime
    record_version: int
    freshness_indicator: FreshnessIndicator
    data_payload: str

    class Config:
        from_attributes = True


class Contradiction(BaseModel):
    """Structured report of a detected discrepancy between evidence items."""
    conflict_type: str
    description: str
    conflicting_record_ids: list[str]
    detected_at: datetime


class EvidenceSnapshotRead(BaseModel):
    """Canonical snapshot metadata schema."""
    id: str
    case_id: str
    snapshot_hash: str
    canonical_json: str
    evidence_count: int
    created_at: datetime

    class Config:
        from_attributes = True
