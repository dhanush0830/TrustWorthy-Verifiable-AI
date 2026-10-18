# Verification Rules & Specification (Phase 3)

This document defines the deterministic rules, check algorithms, active reservation accounting, and escalation reason codes for **Trustworthy and Verifiable AI**.

---

## 1. Claim Types and Parameter Contracts

All claims processed by the verification engine must carry structured parameters. Free-text statements are display text only and are never treated as proof.

| Claim Type | Meaning | Required Parameters |
| :--- | :--- | :--- |
| `duplicate_settlement` | Customer was billed more than once for the same transaction | $\ge 2$ payment IDs in `payment_ids`, `amount_minor`, `currency` |
| `authorization_hold_not_charge` | Disputed item is an uncaptured authorization hold, not settled funds | $\ge 1$ payment ID in `payment_ids` |
| `refund_already_pending` | A refund has already been initiated and is pending processing | $\ge 1$ payment ID, $\ge 1$ refund ID |
| `refund_completed` | A refund has already successfully completed | $\ge 1$ payment ID, $\ge 1$ refund ID, `amount_minor` |
| `order_failed_payment_captured` | The customer's order failed or cancelled, but payment settled | `order_id`, $\ge 1$ payment ID, `amount_minor` |
| `insufficient_evidence` | Evidence is inadequate or inconclusive; triggers safe abstention | None |

---

## 2. Check Catalogue (FR-07)

Every check returns a `CheckResult(check_id, passed, reason, evidence_ids, claim_id)`. Checks are pure deterministic Python functions without model dependencies.

### CHK-01: `evidence_exists`
- **Rule**: Every `evidence_id` cited by the claim must exist in the canonical `EvidenceSnapshot` for the case.
- **Failure**: Returns `passed=False` with the list of missing evidence IDs.

### CHK-02: `evidence_supports`
- **Rule**: Cited evidence records must corroborate the claimed facts (status, amount, currency, record IDs). A real record that contains contradictory or mismatched details fails this check even if it exists.
- **Failure**: Returns `passed=False` indicating field-level mismatches.

### CHK-03: `ownership`
- **Rule**: Every cited record (`payment`, `order`, `refund`) must belong to the authorized `customer_id` and the merchant domain.
- **Failure**: Returns `passed=False` if any record belongs to another customer or fails scoped lookup.

### CHK-04: `distinct_settled_payments`
- **Rule**: For `duplicate_settlement`, there must be at least two distinct payment records (`id_1 != id_2`), and **both** must have status `settled`. An authorization hold does NOT count as settled.
- **Failure**: Returns `passed=False` if payments share the same ID or if either payment is in `authorized`, `failed`, or `voided` state.

### CHK-05: `same_currency`
- **Rule**: All payments and refunds cited must share the exact same currency code (`USD`).
- **Failure**: Returns `passed=False` on currency mismatch.

### CHK-06: `existing_refunds_checked`
- **Rule**: The system must have queried the database for prior refunds associated with the target payments and included them in the evidence package.
- **Failure**: Returns `passed=False` if refund records were omitted from the snapshot.

### CHK-07: `amount_within_remaining`
- **Rule**: Any proposed refund amount must satisfy $0 < \text{proposed} \le \text{remaining}$.
- **Formula**:
  $$\text{remaining} = \text{captured\_amount} - \text{succeeded\_refund\_amount} - \text{active\_reservations}$$
- **Integer Math Only (NFR-03)**: All calculations operate in integer minor units (e.g. cents). Zero or negative amounts fail immediately.

### CHK-08: `policy_conditions`
- **Rule**: Evaluates merchant policies configured in the `policies` table (e.g. 30-day refund window, maximum transaction limit).
- **Audit**: Must record the exact `policy_version` used.

### CHK-09: `freshness`
- **Rule**: All required evidence items must have `freshness_indicator == CURRENT_STATE_CONFIRMED`.
- **Invariance**: Evidence marked `CONFLICTING_RECORDS`, `SOURCE_UNAVAILABLE`, or `CURRENT_STATE_NOT_CONFIRMED` fails freshness. Contradictions are never resolved silently.

---

## 3. Active Reservations Definition (FR-07, FR-12)

To prevent double-refunding or race conditions:
- **Definition**: Any synthetic `Refund` record in the database with `status == "pending"` constitutes an active reservation against the payment's captured amount.
- **Calculation**:
  $$\text{active\_reservations} = \sum_{r \in \text{refunds}, r.\text{status} == \text{PENDING}} r.\text{amount}$$
- Phase 4 will introduce dedicated reservation locks; Phase 3 establishes the exact arithmetic invariant.

---

## 4. Claim Type to Required Checks Mapping

| Claim Type | Required Checks |
| :--- | :--- |
| `duplicate_settlement` | `CHK-01`, `CHK-02`, `CHK-03`, `CHK-04`, `CHK-05`, `CHK-06`, `CHK-07`, `CHK-08`, `CHK-09` |
| `authorization_hold_not_charge` | `CHK-01`, `CHK-02`, `CHK-03`, `CHK-05`, `CHK-09` |
| `refund_already_pending` | `CHK-01`, `CHK-02`, `CHK-03`, `CHK-05`, `CHK-06`, `CHK-09` |
| `refund_completed` | `CHK-01`, `CHK-02`, `CHK-03`, `CHK-05`, `CHK-06`, `CHK-09` |
| `order_failed_payment_captured` | `CHK-01`, `CHK-02`, `CHK-03`, `CHK-05`, `CHK-06`, `CHK-07`, `CHK-08`, `CHK-09` |
| `insufficient_evidence` | None (immediately safe abstention) |

---

## 5. Machine-Readable Escalation Reason Codes (FR-09)

When verification fails, the controller escalates with one of these structured codes:
- `ESC_REVISION_EXHAUSTED`: Output failed check verification after the single allowed revision.
- `ESC_MODEL_UNAVAILABLE`: Model timed out, failed, or circuit breaker tripped during revision.
- `ESC_UNRESOLVABLE_CONTRADICTION`: Evidence contains unresolvable conflicting records.
- `ESC_CROSS_TENANT_VIOLATION`: Claim cited resources outside authorized customer boundary.
- `ESC_INSUFFICIENT_EVIDENCE`: Required business prerequisites cannot be supplied by internal tools or customer.
- `ESC_POLICY_DISALLOWED`: Proposed action violates merchant refund policy constraints.
