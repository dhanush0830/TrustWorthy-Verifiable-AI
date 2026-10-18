"""Tests for PII redaction before model input (SEC-04)."""
from app.core.redaction import redact_pii


def test_redact_email_addresses():
    """SEC-04: Customer email addresses must be redacted."""
    text = "Please reach me at alice@example.com or bob.smith+test@sub.domain.org regarding this charge."
    redacted = redact_pii(text)
    assert "alice@example.com" not in redacted
    assert "bob.smith+test@sub.domain.org" not in redacted
    assert "[EMAIL_REDACTED]" in redacted


def test_redact_card_numbers():
    """SEC-04: Card numbers (13-19 digits) must be redacted."""
    # 16-digit card formatted with spaces
    text1 = "My Visa card 4532 1234 5678 9012 was charged twice."
    # 16-digit card formatted with hyphens
    text2 = "Card ending in 5555-4444-3333-2222 was billed."
    # 16-digit raw sequence
    text3 = "Card 4111111111111111 had an unauthorized fee."

    r1 = redact_pii(text1)
    r2 = redact_pii(text2)
    r3 = redact_pii(text3)

    assert "4532 1234 5678 9012" not in r1
    assert "5555-4444-3333-2222" not in r2
    assert "4111111111111111" not in r3
    assert "[CARD_REDACTED]" in r1
    assert "[CARD_REDACTED]" in r2
    assert "[CARD_REDACTED]" in r3


def test_redact_phone_numbers():
    """SEC-04: Phone numbers must be redacted."""
    text = "Call me at +1 (555) 234-5678 or 555-876-5432 to confirm."
    redacted = redact_pii(text)
    assert "555" not in redacted or "[PHONE_REDACTED]" in redacted
    assert "[PHONE_REDACTED]" in redacted


def test_preserve_system_ids_and_monetary_amounts():
    """PII redactor must NOT redact standard identifiers, dates, or monetary amounts."""
    text = "Payment PAY-101 for Order ORD-201 on 2026-10-17 was $499.00 (minor units 49900)."
    redacted = redact_pii(text)
    assert "PAY-101" in redacted
    assert "ORD-201" in redacted
    assert "49900" in redacted
