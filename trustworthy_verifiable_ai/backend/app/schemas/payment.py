"""Pydantic schemas for orders, payments, and refunds.

Enforces:
- NFR-03: Integer minor units for amounts.
- SEC-05: No card numbers or payment credentials exposed.
"""
from datetime import datetime

from pydantic import BaseModel

from app.models.payment import PaymentStatus
from app.models.refund import RefundStatus


class OrderRead(BaseModel):
    id: str
    customer_id: str
    order_number: str
    amount: int  # integer minor units
    currency: str
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


class PaymentRead(BaseModel):
    id: str
    customer_id: str
    order_id: str | None = None
    amount: int  # integer minor units
    currency: str
    status: PaymentStatus
    provider: str
    created_at: datetime

    class Config:
        from_attributes = True


class RefundRead(BaseModel):
    id: str
    payment_id: str
    customer_id: str
    amount: int  # integer minor units
    currency: str
    status: RefundStatus
    reason: str | None = None
    created_at: datetime

    class Config:
        from_attributes = True
