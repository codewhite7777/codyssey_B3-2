"""Mask known secret values before text is used in an AI prompt."""


def redact(text: str, secret: str) -> str:
    """Replace exact secret matches, preserving text when secret is empty."""
    if not secret:
        return text
    return text.replace(secret, "[REDACTED]")
