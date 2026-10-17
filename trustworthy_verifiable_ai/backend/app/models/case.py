"""Complaint case model."""
from datetime import datetime, timezone
import enum
from sqlalchemy import String, DateTime, Enum, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class CaseStatus(str, enum.Enum):
    """Lifecycle stages of a complaint investigation case."""
    OPEN = "open"
    INVESTIGATING = "investigating"
    VERIFYING = "verifying"
    AWAITING_APPROVAL = "awaiting_approval"
    CLOSED = "closed"


class Case(Base):
    """Customer complaint investigation case."""
    __tablename__ = "cases"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    customer_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    
    # Untrusted raw customer complaint input (SEC-02, SEC-07)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[CaseStatus] = mapped_column(Enum(CaseStatus), default=CaseStatus.OPEN, nullable=False)
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    # Relationships
    customer = relationship("User", back_populates="cases")
