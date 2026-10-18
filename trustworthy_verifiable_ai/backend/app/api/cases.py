"""Cases API with strict tenant boundary enforcement (SEC-01, Design Rule 2)."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.scoped import get_scoped_record, scoped_query
from app.db.session import get_db
from app.models.case import Case
from app.models.user import User
from app.schemas.case import CaseRead

router = APIRouter(prefix="/cases", tags=["cases"])


@router.get("", response_model=list[CaseRead])
def list_cases(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retrieve cases strictly within the user's authorized scope."""
    query = scoped_query(db, Case, user)
    return query.all()


@router.get("/{case_id}", response_model=CaseRead)
def get_case(
    case_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retrieve a single case strictly within authorized scope."""
    case = get_scoped_record(db, Case, case_id, user)
    if not case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Case '{case_id}' not found.",
        )
    return case
