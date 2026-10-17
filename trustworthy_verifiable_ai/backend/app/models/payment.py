"""Payment and append-only PaymentEvent models.

Enforces:
- NFR-03: Integer minor units for amounts.
- SEC-05: Zero card numbers, CVVs, or card credentials stored.
- FR-03: Append-only events with UNIQUE provider_event_id for deduplication.
"""
from datetime import datetime, timezone
import enum
from sqlalchemy import String, Integer, DateTime, Enum, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class PaymentStatus(str, enum.Enum):
    """Payment transaction states."""
    AUTHORIZED = "authorized"
    SETTLED = "settled"
    FAILED = "failed"
    VOIDED = "voided"


class Payment(Base):
    """Payment record."""
    __tablename__ = "payments"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    customer_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id"), nullable=False, index=True)
    order_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("orders.id"), nullable=True, index=True)
    
    # Minor units (NFR-03)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    status: Mapped[PaymentStatus] = mapped_column(Enum(PaymentStatus), nullable=False)
    
    provider: Mapped[str] = mapped_column(String(64), default="simulated_provider", nullable=False)
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
    customer = relationship("User", back_populates="payments")
    order = relationship("Order", back_populates="payments")
    refunds = relationship("Refund", back_populates="payment")
    events = relationship("PaymentEvent", back_populates="payment")


class PaymentEvent(Base):
    """Append-only raw payment event log from payment provider.
    
    provider_event_id is strictly UNIQUE to ensure idempotency and deduplication (FR-03).
    """
    __tablename__ = "payment_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider_event_id: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    payment_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("payments.id"), nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    
    # Business timestamp vs ingestion timestamp for out-of-order handling
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )
    
    raw_payload: Mapped[str] = mapped_column(Text, nullable=False)

    # Relationships
    payment = relationship("Payment", back_populates="events")
