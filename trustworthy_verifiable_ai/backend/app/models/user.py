"""User model with role-based access control (SEC-01)."""
from datetime import datetime, timezone
import enum
from sqlalchemy import String, DateTime, Enum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class UserRole(str, enum.Enum):
    """User roles for role-based authorization."""
    CUSTOMER = "customer"
    AGENT = "agent"
    REVIEWER = "reviewer"


class User(Base):
    """System user entity.
    
    Roles:
    - customer: access restricted strictly to own records.
    - agent: can inspect scoped records and conduct investigations.
    - reviewer: can review proposals and authorize executions.
    """
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), nullable=False, default=UserRole.CUSTOMER)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    # Relationships
    orders = relationship("Order", back_populates="customer", cascade="all, delete-orphan")
    payments = relationship("Payment", back_populates="customer", cascade="all, delete-orphan")
    refunds = relationship("Refund", back_populates="customer", cascade="all, delete-orphan")
    cases = relationship("Case", back_populates="customer", cascade="all, delete-orphan")
