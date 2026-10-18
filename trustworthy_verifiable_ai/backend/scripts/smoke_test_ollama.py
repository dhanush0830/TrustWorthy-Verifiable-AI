"""Manual smoke-test script for testing real Ollama connectivity and model generation.

NOTE: This script is for manual smoke testing only and is NOT part of the automated pytest suite (NFR-01).

Usage:
    python scripts/smoke_test_ollama.py
"""
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

# Ensure backend root is on sys.path
backend_root = Path(__file__).resolve().parents[1]
if str(backend_root) not in sys.path:
    sys.path.insert(0, str(backend_root))

import httpx

from app.core.config import get_settings
from app.llm.ollama_client import OllamaClient
from app.models.evidence import FreshnessIndicator
from app.schemas.evidence import EvidenceItemRead


def main():
    settings = get_settings()
    print("=" * 60)
    print("OLLAMA REAL-MODEL SMOKE TEST (PHASE 2)")
    print("=" * 60)
    print(f"Base URL:         {settings.OLLAMA_BASE_URL}")
    print(f"Configured Model: {settings.OLLAMA_MODEL}")
    print(f"Timeout (sec):    {settings.OLLAMA_TIMEOUT_SECONDS}")
    print(f"Temperature:      {settings.LLM_TEMPERATURE}")
    print(f"Prompt Version:   {settings.LLM_PROMPT_VERSION}")
    print("-" * 60)

    # 1. Connectivity check
    print("\n[1/3] Checking Ollama server availability...")
    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(f"{settings.OLLAMA_BASE_URL}/api/tags")
            if resp.status_code == 200:
                models = [m.get("name") for m in resp.json().get("models", [])]
                print(f"[OK] Ollama is running. Available models: {models}")
                if settings.OLLAMA_MODEL not in models and not any(settings.OLLAMA_MODEL in m for m in models):
                    print(f"[WARNING] Model '{settings.OLLAMA_MODEL}' was not found in `ollama list`.")
                    print(f"  Make sure `ollama pull {settings.OLLAMA_MODEL}` has completed.")
            else:
                print(f"[ERROR] Ollama returned status {resp.status_code}: {resp.text}")
                sys.exit(1)
    except Exception as e:
        print(f"[ERROR] Could not connect to Ollama at {settings.OLLAMA_BASE_URL}.")
        print(f"  Error details: {e}")
        print("  Make sure `ollama serve` is running in another terminal.")
        sys.exit(1)

    # 2. Test generation with sample evidence
    print("\n[2/3] Executing real-model investigation test...")
    sample_evidence = [
        EvidenceItemRead(
            id="EVD-TEST-001",
            case_id="CAS-SMOKE-1",
            customer_id="USR-CUST-A",
            source_system="payment_gateway",
            source_record_id="PAY-101",
            provider_event_id="evt_smoke_1",
            occurred_at=datetime.now(UTC),
            received_at=datetime.now(UTC),
            fetched_at=datetime.now(UTC),
            record_version=1,
            freshness_indicator=FreshnessIndicator.CURRENT_STATE_CONFIRMED,
            data_payload='{"payment_id": "PAY-101", "status": "settled", "amount": 49900, "currency": "USD"}',
        ),
        EvidenceItemRead(
            id="EVD-TEST-002",
            case_id="CAS-SMOKE-1",
            customer_id="USR-CUST-A",
            source_system="payment_gateway",
            source_record_id="PAY-102",
            provider_event_id="evt_smoke_2",
            occurred_at=datetime.now(UTC),
            received_at=datetime.now(UTC),
            fetched_at=datetime.now(UTC),
            record_version=1,
            freshness_indicator=FreshnessIndicator.CURRENT_STATE_CONFIRMED,
            data_payload='{"payment_id": "PAY-102", "status": "settled", "amount": 49900, "currency": "USD"}',
        ),
    ]

    complaint = "I was charged twice $499.00 for my order! Please refund the duplicate payment."

    client = OllamaClient()
    start_time = time.perf_counter()
    try:
        result = client.investigate(
            case_id="CAS-SMOKE-1",
            complaint_text=complaint,
            evidence_items=sample_evidence,
            prompt_version=settings.LLM_PROMPT_VERSION,
        )
        elapsed = time.perf_counter() - start_time
        print(f"[OK] Response received in {elapsed:.2f}s!")
    except Exception as exc:
        print(f"[FAILED] Model investigation call failed: {exc}")
        sys.exit(1)

    # 3. Validation inspection
    print("\n[3/3] Validating parsed output & schema compliance:")
    print(f"  Case ID:           {result.case_id}")
    print(f"  Issue Type:        {result.issue_type}")
    print(f"  Summary:           {result.summary}")
    print(f"  Claims Count:      {len(result.claims)}")
    for i, claim in enumerate(result.claims, 1):
        print(f"    Claim {i}: [{claim.claim_type.value}] {claim.statement} (evidence: {claim.evidence_ids})")
    if result.proposed_action:
        print(f"  Proposed Action:   {result.proposed_action.action_type.value} on {result.proposed_action.target_payment_id}")
        print(f"  Proposed Amount:   {result.proposed_action.amount} {result.proposed_action.currency}")
    print(f"  Needs Escalation:  {result.needs_escalation}")
    if result.model_metadata:
        print(f"  Model Metadata:    {result.model_metadata.model_dump()}")

    print("\n" + "=" * 60)
    print("SUCCESS: Ollama real-model smoke test PASSED.")
    print("=" * 60)


if __name__ == "__main__":
    main()
