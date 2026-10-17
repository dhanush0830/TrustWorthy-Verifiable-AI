"""Payments API with strict tenant boundary enforcement (SEC-01, Design Rule 2)."""
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.db.scoped import scoped_query, get_scoped_record
from app.models.user import User
from app.models.payment import Payment
from app.schemas.payment import PaymentRead

router = APIRouter(prefix="/payments", tags=["payments"])


@router.get("", response_model=List[PaymentRead])
def list_payments(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Retrieve payments strictly within the user's authorized scope."""
    query = scoped_query(db, Payment, user)
    return query.all()


@router.get("/{payment_id}", response_model=PaymentRead)
def get_payment(
    payment_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Retrieve a single payment. Knowing payment_id grants zero access if out-of-scope."""
    payment = get_scoped_record(db, Payment, payment_id, user)
    if not payment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Payment '{payment_id}' not found.",
        )
    return payment
