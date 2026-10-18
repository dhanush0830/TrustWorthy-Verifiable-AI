"""Tests for investigate API endpoint: tenant isolation and input size enforcement (Items 3 & 5)."""
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.llm.service import get_llm_client
from app.models.case import Case, CaseStatus


def test_customer_cannot_investigate_other_customer_case_model_never_called(
    client: TestClient,
    db_session: Session,
    token_customer_a: str,
):
    """Item 3: A customer calling /investigate on another customer's case is denied,
    and the model is never called (assert call count is 0).
    """
    # Create case belonging strictly to Customer B
    case_b = Case(
        id="CAS-CUST-B-SECRET",
        customer_id="USR-CUST-B",
        title="Customer B Private Complaint",
        description="Double charge on my corporate card.",
        status=CaseStatus.OPEN,
    )
    db_session.add(case_b)
    db_session.commit()

    # Track baseline call count
    mock_llm = get_llm_client(force_mock=True)
    initial_call_count = mock_llm.call_count

    # Customer A attempts to call /investigate on Customer B's case
    response = client.post(
        f"/api/v1/cases/{case_b.id}/investigate",
        headers={"Authorization": f"Bearer {token_customer_a}"},
    )

    # Denied with 403 Forbidden
    assert response.status_code == 403
    assert "Access denied" in response.json()["detail"]

    # Model was NEVER called
    assert mock_llm.call_count == initial_call_count == 0


def test_investigate_oversized_complaint_rejected(
    client: TestClient,
    db_session: Session,
    token_customer_a: str,
):
    """Item 5: Add an input size limit on the investigate endpoint, with a test that an oversized complaint is rejected."""
    settings = get_settings()
    case_a = Case(
        id="CAS-SIZE-LIMIT-TEST",
        customer_id="USR-CUST-A",
        title="Customer A Complaint",
        description="Initial short complaint.",
        status=CaseStatus.OPEN,
    )
    db_session.add(case_a)
    db_session.commit()

    # Create oversized payload exceeding MAX_COMPLAINT_CHARS (4000)
    oversized_text = "A" * (settings.MAX_COMPLAINT_CHARS + 100)
    response = client.post(
        f"/api/v1/cases/{case_a.id}/investigate",
        headers={"Authorization": f"Bearer {token_customer_a}"},
        json={"complaint": oversized_text},
    )

    # Must be rejected due to length limit
    assert response.status_code == 400
    assert "exceeds maximum allowed length" in response.json()["detail"].lower()
