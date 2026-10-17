# Evidence Rules & Status Precedence Specification

This document defines the deterministic rules for payment state projection, out-of-order event resolution, freshness indicators, and contradiction handling for **Trustworthy and Verifiable AI**.

---

## 1. Out-of-Order Delivery & Precedence Rules (FR-03)

Payment events from external or simulated providers can arrive duplicated or out of order due to network retries, queue rebalancing, or clock drift.

### Core Invariants:
1. **Never use receipt order as business order**: `received_at` represents local system ingestion time. `occurred_at` represents the provider business timestamp.
2. **Terminal state immutability**: Once a payment transitions to a terminal or higher-precedence state (`settled`, `voided`, `failed`), an older event with an earlier `occurred_at` timestamp (such as a delayed `payment.authorized`) **cannot** rollback or alter the state.

### State Transition Precedence Matrix:

| Current Projected State | Incoming Event Type | Event `occurred_at` vs Current | Resulting Projected State | Action / Rule |
| :--- | :--- | :--- | :--- | :--- |
| `UNINITIALIZED` | `payment.authorized` | Any | `AUTHORIZED` | Initial authorization established |
| `UNINITIALIZED` | `payment.settled` | Any | `SETTLED` | Direct settlement (e.g. instant settlement) |
| `UNINITIALIZED` | `payment.failed` | Any | `FAILED` | Payment failed immediately |
| `AUTHORIZED` | `payment.settled` | $\ge$ current | `SETTLED` | Successful capture/settlement |
| `AUTHORIZED` | `payment.voided` | $\ge$ current | `VOIDED` | Authorization cancelled/released |
| `AUTHORIZED` | `payment.failed` | $\ge$ current | `FAILED` | Authorization failed |
| `SETTLED` | `payment.authorized` | < current | `SETTLED` | **NO ROLLBACK**: Late authorization ignored |
| `SETTLED` | `payment.authorized` | $\ge$ current | `SETTLED` | Contradiction logged: Re-authorization after settlement |
| `SETTLED` | `payment.voided` | Any | `SETTLED` | Contradiction logged: Void attempted on settled funds |
| `FAILED` | `payment.authorized` | < current | `FAILED` | **NO ROLLBACK**: Late authorization ignored |
| `VOIDED` | `payment.authorized` | < current | `VOIDED` | **NO ROLLBACK**: Late authorization ignored |

---

## 2. Evidence Freshness Indicators (FR-04)

Every `EvidenceItem` has an explicit freshness indicator:

1. **`current_state_confirmed`**:
   - The source system provided a corroborated record within the freshness window, and no conflicting events exist.
2. **`current_state_not_confirmed`**:
   - The record is pending verification, or the source has not published a definitive settlement event.
3. **`source_unavailable`**:
   - The upstream service was unreachable, timed out, or returned a service degradation error during evidence gathering.
4. **`conflicting_records`**:
   - Two or more records or systems assert incompatible states (e.g. Order says `failed`, Payment says `settled`).
   - **Non-negotiable**: Contradictions are ALWAYS flagged and surfaced; deterministic code NEVER guesses or silently picks a record.

---

## 3. Canonical Evidence Snapshot (FR-04, FR-17)

To ensure tamper-evidence and reproducibility:
- Every case evaluation takes an immutable snapshot of all collected evidence items.
- Items are sorted canonically by `(source_system, source_record_id, occurred_at)`.
- The snapshot payload is serialized to deterministic RFC 8785 JSON (sorted keys, no whitespace separators).
- A SHA-256 hash is computed over the canonical JSON.
- **Security & Integrity Note**: The hash detects subsequent modification or tampering; it does **not** prove the external ground truth of upstream sources.
