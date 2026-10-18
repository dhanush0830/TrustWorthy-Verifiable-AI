"""PII Redaction utility for customer inputs (SEC-04).

Redacts email addresses, phone numbers, and payment card numbers before sending
untrusted text to any model or external API.
"""
import re

# Email regex matching standard email addresses
EMAIL_REGEX = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"
)

# Card number regex: 13-19 digits, allowing optional spaces or hyphens every 4 digits
# E.g. 4532-1234-5678-9012, 4532 1234 5678 9012, 4532123456789012
CARD_REGEX = re.compile(
    r"\b(?:\d{4}[ -]?){3}\d{1,4}\b|\b\d{13,19}\b"
)

# Phone number regex: international and standard US/EU formats
# E.g. +1-555-123-4567, (555) 123-4567, 555-123-4567, +44 20 7946 0912
PHONE_REGEX = re.compile(
    r"(?:\+?\d{1,3}[ -]?)?(?:\(?\d{2,4}\)?[ -]?)?\d{3,4}[ -]?\d{3,4}\b"
)


def redact_pii(text: str) -> str:
    """Redact email addresses, card numbers, and phone numbers from untrusted customer text.
    
    Order of operations:
    1. Redact emails
    2. Redact payment card numbers (longer digit sequences)
    3. Redact phone numbers (avoiding identifiers like PAY-101 or amounts like 49900)
    """
    if not text:
        return text

    # 1. Redact emails first
    redacted = EMAIL_REGEX.sub("[EMAIL_REDACTED]", text)

    # 2. Redact card numbers
    # We check that matches are not standard system reference IDs (PAY-101, ORD-201, etc.)
    def _mask_card(match: re.Match) -> str:
        s = match.group(0)
        digits_only = re.sub(r"\D", "", s)
        if 13 <= len(digits_only) <= 19:
            return "[CARD_REDACTED]"
        return s

    redacted = CARD_REGEX.sub(_mask_card, redacted)

    # 3. Redact phone numbers
    # Pattern must match likely phone numbers without clobbering 4-5 digit amounts or dates
    # Match patterns with explicit formatting (+, parens, hyphens) or 10-11 contiguous digits
    phone_structured_regex = re.compile(
        r"(?:\+\d{1,3}[ -]?)?(?:\(\d{2,4}\)[ -]?|\b\d{3,4}[- ])\d{3,4}[- ]\d{3,4}\b|\b\+?\d{10,12}\b"
    )
    redacted = phone_structured_regex.sub("[PHONE_REDACTED]", redacted)

    return redacted
