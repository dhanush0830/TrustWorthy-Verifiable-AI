"""Tests for Cases API and provider override in investigate API (Priority 2 & 4)."""
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.case import Case


def test_list_cases_tenant_isolation(client: TestClient, token_customer_a: str, token_customer_b: str):
    """Customer A only sees Customer A's cases, Customer B only sees Customer B's cases."""
    resp_a = client.get("/api/v1/cases", headers={"Authorization": f"Bearer {token_customer_a}"})
    assert resp_a.status_code == 200
    cases_a = resp_a.json()
    assert len(cases_a) > 0
    for c in cases_a:
        assert c["customer_id"] == "USR-CUST-A"
        assert c["id"].startswith("CAS-")

    resp_b = client.get("/api/v1/cases", headers={"Authorization": f"Bearer {token_customer_b}"})
    assert resp_b.status_code == 200
    cases_b = resp_b.json()
    assert len(cases_b) > 0
    for c in cases_b:
        assert c["customer_id"] == "USR-CUST-B"


def test_agent_can_see_all_cases(client: TestClient, token_agent: str):
    """Support agents have unscoped visibility across all customer cases."""
    resp = client.get("/api/v1/cases", headers={"Authorization": f"Bearer {token_agent}"})
    assert resp.status_code == 200
    cases = resp.json()
    customer_ids = {c["customer_id"] for c in cases}
    assert len(customer_ids) >= 2


def test_get_single_case_authorized_and_denied(
    client: TestClient,
    token_customer_a: str,
    token_customer_b: str,
):
    """Customer A can access their own case CAS-DEMO-A1; Customer B is denied access to CAS-DEMO-A1."""
    # Customer A accesses own case
    resp_ok = client.get("/api/v1/cases/CAS-DEMO-A1", headers={"Authorization": f"Bearer {token_customer_a}"})
    assert resp_ok.status_code == 200
    assert resp_ok.json()["id"] == "CAS-DEMO-A1"

    # Customer B tries to access Customer A's case
    resp_denied = client.get("/api/v1/cases/CAS-DEMO-A1", headers={"Authorization": f"Bearer {token_customer_b}"})
    assert resp_denied.status_code == 404


def test_investigate_with_mock_provider_override(client: TestClient, token_customer_a: str):
    """Explicit MOCK provider override executes offline MockLLMClient and returns simulated metadata."""
    resp = client.post(
        "/api/v1/cases/CAS-DEMO-A1/investigate",
        headers={"Authorization": f"Bearer {token_customer_a}"},
        json={"provider": "mock"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["case_id"] == "CAS-DEMO-A1"
    assert data["model_metadata"] is not None
    assert data["model_metadata"]["model_name"].startswith("mock-")
    assert len(data["claims"]) > 0
