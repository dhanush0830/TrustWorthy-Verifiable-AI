"""Investigation API endpoints with tenant scoping and input length enforcement (FR-01, FR-02, SEC-01, SEC-04)."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.db.scoped import get_scoped_record
from app.db.session import get_db
from app.llm.service import run_case_investigation
from app.models.case import Case
from app.models.user import User
from app.schemas.investigation import InvestigateRequest, InvestigationResult

router = APIRouter(prefix="", tags=["investigation"])


@router.post("/cases/{case_id}/investigate", response_model=InvestigationResult)
@router.post("/investigate/{case_id}", response_model=InvestigationResult)
def investigate_case(
    case_id: str,
    payload: InvestigateRequest | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Investigate a complaint case strictly within the user's authorized scope.
    
    Enforces:
    - Input size limit (Requirement 5)
    - Tenant isolation: Customer calling on another's case is denied before model is invoked (Requirement 3)
    """
    settings = get_settings()

    # 1. Input size validation (Requirement 5)
    if payload and payload.complaint:
        if len(payload.complaint) > settings.MAX_COMPLAINT_CHARS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Complaint exceeds maximum allowed length of {settings.MAX_COMPLAINT_CHARS} characters.",
            )

    # 2. Tenant isolation check (Requirement 3)
    case = get_scoped_record(db, Case, case_id, user)
    if not case:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied: Case '{case_id}' not found or belongs to another customer.",
        )

    # If updated complaint was submitted, persist to case
    if payload and payload.complaint:
        case.description = payload.complaint
        db.commit()

    # 3. Execute investigation
    return run_case_investigation(db=db, case_id=case_id, user=user)
