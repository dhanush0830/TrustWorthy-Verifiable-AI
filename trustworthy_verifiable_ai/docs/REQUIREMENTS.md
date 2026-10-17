# Trustworthy and Verifiable AI - Requirements

## P0 (Must Have)
- **FR-01 Complaint intake**: create a case from customer text.
- **FR-02 Authorized lookup**: backend fetches only records in the user's scope.
- **FR-03 Event ingestion**: store raw events append-only; dedupe by `provider_event_id`; build current payment state by `occurred_at` plus a documented status-precedence rule (no rollback from late events).
- **FR-05 AI investigation**: model extracts issue type/entities and returns structured claims plus an optional proposed action (Pydantic).
- **FR-06 Evidence-linked claims**: each claim lists evidence IDs.
- **FR-07 Verification engine**: deterministic checks for evidence existence, evidence support (separate from existence), ownership, distinct settled payments, currency, existing refunds, remaining refundable amount, policy conditions, freshness.
- **FR-08 Bounded revision**: exactly one revision attempt after failed checks.
- **FR-09 Safe abstention**: unresolved evidence leads to escalation, never a guess.
- **FR-11 Approval**: reviewer approval bound to exact proposal version + hash.
- **FR-17 Audit**: every input, check, revision, approval, and execution is logged.

## P1 (Strongest Differentiators)
- **FR-04 Freshness and contradiction detection**: Per evidence item: `source_system`, `source_record_id`, `provider_event_id`, `occurred_at`, `received_at`, `fetched_at`, `record_version`. Indicators: last refreshed, source unavailable, conflicting records, current state confirmed / not confirmed. Contradictions are flagged, never silently resolved.
- **FR-10 Targeted missing-evidence questions**: a rules-based selector maps a failed prerequisite to ONE specific question. Never ask for card numbers, passwords, or OTPs.
- **FR-12 Pre-execution revalidation**: refresh state, recompute `remaining = captured - succeeded_refunds - active_reservations`, block and mark proposal stale if anything changed.
- **FR-13 Safe simulated execution**: idempotency key, UNIQUE reservation constraint, repeated execute returns the first result.
- **FR-14 Outcome tracker**: separate "conversation closed" from "operational outcome confirmed"; scheduled rechecks; simulated provider events.
- **FR-15 Customer timeline**: what is known, unknown, who owns the next step, next check time. No guaranteed completion dates.
- **FR-16 Explanation**: "Why this decision" and "What would change it", generated from the verified report only; no new facts.
- **FR-18 Evaluation harness**: 42 labeled synthetic cases, 3 configurations.
- **FR-19 UI**: customer, support agent, and reviewer views.

## P2 (Only if time remains)
- **FR-20 Appeals**: new evidence item and new decision version; history preserved.
- **FR-21 Reviewed memory**: scoped, versioned, activated only after a regression test passes (retrieval-based, not model training).
- **FR-22 Incident detection**: SQL grouping with thresholds; label as "shared pattern detected", never "root cause confirmed".

## Security Requirements
- **SEC-01**: Role-based access (customer, agent, reviewer); deny by default.
- **SEC-02**: Customer messages, tickets, and attachments are untrusted.
- **SEC-03**: Action allowlist; validate all arguments.
- **SEC-04**: Redact emails, phone numbers, and card-like numbers before model input.
- **SEC-05**: No card credentials or secrets stored anywhere.
- **SEC-06**: Execute accepts `proposal_id` only.
- **SEC-07**: Minimal logging of raw customer text; define retention.
- **SEC-08**: Prompt injection must not expand permissions, select another customer's records, override approval, or send data elsewhere. Test hostile inputs; never claim immunity.

## Non-Functional Requirements
- **NFR-01**: All tests run offline with `MockLLMClient`.
- **NFR-02**: Deterministic seed data with fixed IDs (`PAY-101`, `REF-301`, ...).
- **NFR-03**: Integer minor units for all money.
- **NFR-04**: One-command reproducibility for tests and evaluation.
- **NFR-05**: README, LICENSE, dependency/model license notes, threat model, known limitations.
- **NFR-06**: Held-out evaluation split; any case fixed after failing moves to the dev split.

## Required Seed Scenarios
- a) two genuine settled payments
- b) settled payment + authorization hold
- c) settled payment + pending refund
- d) failed order, successful payment
- e) duplicate event delivery
- f) out-of-order event pair
