"""EvidenceItem and EvidenceSnapshot models with freshness indicators and audit tracking (FR-04, FR-17)."""
import enum
from datetime import UTC, datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class FreshnessIndicator(str, enum.Enum):
    """Status indicating the reliability and currency of an evidence item."""
    CURRENT_STATE_CONFIRMED = "current_state_confirmed"
    CURRENT_STATE_NOT_CONFIRMED = "current_state_not_confirmed"
    SOURCE_UNAVAILABLE = "source_unavailable"
    CONFLICTING_RECORDS = "conflicting_records"


class EvidenceItem(Base):
    """Single normalized unit of evidence gathered from a source system.
    
    Enforces:
    - Provenance tracking (source_system, source_record_id, provider_event_id).
    - Separation of business time (occurred_at), ingest time (received_at), and fetch time (fetched_at).
    - SEC-01 tenant scoping by customer_id.
    """
    __tablename__ = "evidence_items"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    case_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("cases.id"), nullable=True, index=True)
    customer_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id"), nullable=False, index=True)
    
    source_system: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_record_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    provider_event_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False
    )
    
    record_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    freshness_indicator: Mapped[FreshnessIndicator] = mapped_column(
        Enum(FreshnessIndicator),
        default=FreshnessIndicator.CURRENT_STATE_CONFIRMED,
        nullable=False
    )
    
    # Normalized canonical representation of the source record
    data_payload: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False
    )


class EvidenceSnapshot(Base):
    """Canonical cryptographic snapshot of all evidence gathered for a case.
    
    NOTE: The SHA-256 snapshot_hash detects change or tampering, but does not prove truth.
    """
    __tablename__ = "evidence_snapshots"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    case_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("cases.id"), nullable=True, index=True)
    snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    canonical_json: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False
    )
