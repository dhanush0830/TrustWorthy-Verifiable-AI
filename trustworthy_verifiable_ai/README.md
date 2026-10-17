# Trustworthy and Verifiable AI

An AI complaint-investigation platform for payment/order complaints that:
1. Gathers authorized evidence.
2. Produces evidence-linked findings.
3. Verifies findings with deterministic code.
4. Requires human approval bound to an exact action.
5. Revalidates state before executing.
6. Tracks whether the real-world outcome actually occurred.

## Scope & Constraints
- One merchant, one currency (USD).
- Synthetic data only.
- Payment/order complaints only.
- Simulated payment provider (no live Stripe/external API calls).
- Money is strictly stored and handled as integer minor units (e.g., `49900` = $499.00).

## Tech Stack
- Backend: Python 3.11+, FastAPI, Pydantic v2, SQLAlchemy 2.0, SQLite
- Testing: pytest + offline deterministic seed data
- Model: open-weight Qwen3-8B via `LLMClient` interface with `MockLLMClient`
- Frontend: React (Phase 7)

## Honest Limitations
1. Verification is only as good as the implemented deterministic checks and available database records.
2. Upstream provider records may have latency or discrepancies.
3. Synthetic evaluation does not guarantee 100% real-world accuracy across arbitrary merchant domains.
4. An executed payment action does not guarantee customer satisfaction.
5. Human reviewers may make mistakes; approvals are auditable and strictly bound to proposal hashes.
