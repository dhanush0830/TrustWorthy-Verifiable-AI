"""Tests for authentication and boundary isolation (SEC-01, Design Rule 2)."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.scoped import scoped_query, AuthorizationError
from app.models.payment import Payment
from app.models.policy import Policy
from app.models.user import User


def test_customer_isolation_scoped_query(db_session: Session):
    """SEC-01: scoped_query strictly confines customer queries to own records."""
    customer_a = db_session.query(User).filter(User.id == "USR-CUST-A").first()
    customer_b = db_session.query(User).filter(User.id == "USR-CUST-B").first()

    # Query for payments under Customer A scope
    a_payments = scoped_query(db_session, Payment, customer_a).all()
    a_ids = [p.id for p in a_payments]
    assert set(a_ids) == {"PAY-101", "PAY-102"}
    assert "PAY-201" not in a_ids

    # Query for payments under Customer B scope
    b_payments = scoped_query(db_session, Payment, customer_b).all()
    b_ids = [p.id for p in b_payments]
    assert set(b_ids) == {"PAY-201", "PAY-202"}
    assert "PAY-101" not in b_ids


def test_customer_cannot_read_other_customer_payment_via_api(
    client: TestClient,
    token_customer_a: str
):
    """SEC-01 & Design Rule 2: Customer A cannot read Customer B's payment by knowing payment_id."""
    headers = {"Authorization": f"Bearer {token_customer_a}"}

    # Customer A can read their own payment
    resp_own = client.get("/api/v1/payments/PAY-101", headers=headers)
    assert resp_own.status_code == 200
    assert resp_own.json()["id"] == "PAY-101"

    # Customer A attempts to access Customer B's payment (PAY-201)
    resp_other = client.get("/api/v1/payments/PAY-201", headers=headers)
    assert resp_other.status_code == 404
    assert "not found" in resp_other.json()["detail"].lower()


def test_customer_list_is_strictly_scoped(
    client: TestClient,
    token_customer_a: str
):
    """Customer A listing payments sees ONLY Customer A payments."""
    headers = {"Authorization": f"Bearer {token_customer_a}"}
    response = client.get("/api/v1/payments", headers=headers)
    assert response.status_code == 200
    items = response.json()
    assert len(items) == 2
    ids = {item["id"] for item in items}
    assert ids == {"PAY-101", "PAY-102"}


def test_merchant_roles_can_inspect_all_payments(
    client: TestClient,
    token_agent: str,
    token_reviewer: str
):
    """Agents and Reviewers have merchant-scoped access to review customer records."""
    for token in [token_agent, token_reviewer]:
        headers = {"Authorization": f"Bearer {token}"}
        
        # Can inspect Customer A's payment
        resp_a = client.get("/api/v1/payments/PAY-101", headers=headers)
        assert resp_a.status_code == 200
        assert resp_a.json()["id"] == "PAY-101"

        # Can inspect Customer B's payment
        resp_b = client.get("/api/v1/payments/PAY-201", headers=headers)
        assert resp_b.status_code == 200
        assert resp_b.json()["id"] == "PAY-201"


def test_deny_by_default_unscoped_model(db_session: Session):
    """Customer role attempting to query a model without customer context is denied by default."""
    customer_a = db_session.query(User).filter(User.id == "USR-CUST-A").first()
    
    with pytest.raises(AuthorizationError) as exc_info:
        scoped_query(db_session, Policy, customer_a)
    assert "access denied" in str(exc_info.value).lower()


def test_unauthenticated_request_rejected(client: TestClient):
    """Missing Authorization header returns 401."""
    resp = client.get("/api/v1/payments/PAY-101")
    assert resp.status_code == 401


def test_tampered_token_rejected(client: TestClient, token_customer_a: str):
    """Tampered token signature returns 401."""
    tampered = token_customer_a[:-4] + "fake"
    headers = {"Authorization": f"Bearer {tampered}"}
    resp = client.get("/api/v1/payments/PAY-101", headers=headers)
    assert resp.status_code == 401
