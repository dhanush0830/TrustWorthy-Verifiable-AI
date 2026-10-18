"""Pydantic schemas for Cases (FR-01, SEC-01)."""
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.case import CaseStatus


class CaseRead(BaseModel):
    """Schema for serializing complaint cases."""
    id: str
    customer_id: str
    title: str
    description: str
    status: CaseStatus
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
