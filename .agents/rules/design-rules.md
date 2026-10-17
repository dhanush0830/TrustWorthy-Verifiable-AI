# Trustworthy and Verifiable AI - Design Rules

These rules are permanent invariants for the codebase. Never violate them.

1. **LLM Proposes, Code Decides**: The LLM interprets text and proposes structured output. Deterministic code verifies facts and enforces safety. The LLM never decides authorization, eligibility, or amounts.
2. **Backend-Enforced Authorization**: Authorization is enforced in backend code on every query. A known case_id grants nothing. Deny by default.
3. **Strict Schema Validation**: All model output is validated by Pydantic. Invalid output gets one retry, then escalation.
4. **Citations Required**: Every claim cites evidence IDs. Reject claims whose citations do not exist or do not support the claim.
5. **Indirect Execution Only**: The execute endpoint accepts a `proposal_id` only, never payment IDs or amounts from the browser or model.
6. **Immutable Approval Binding**: Approval is bound to proposal version + payload hash.
7. **Pre-Execution Guardrails**: Before execution: refresh state, recompute remaining refundable amount, block if anything changed.
8. **Out-of-Order / Deduplicated Ingestion**: Events may be duplicated or out of order. Never use receipt time as business order. Dedupe by `provider_event_id`.
9. **Untrusted User Input**: Customer text and attachments are UNTRUSTED data (prompt injection defense).
10. **Action Allowlist**: Actions are allowlisted. No arbitrary SQL, no arbitrary URLs.
11. **Integer Minor Units**: Money is integer minor units only. Never floats.
12. **Offline-First Testing**: All tests run offline with `MockLLMClient` (no GPU needed).
13. **Clean Modular Architecture**: Small modules (under 250 lines), type hints, docstrings on public functions.
