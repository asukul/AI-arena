"""
Webhook signature verification for Canvas.

Canvas signs outgoing webhook requests with HMAC-SHA256 over the raw request
body using a shared secret.  The signature is sent in a request header (the
Live Events spec uses `Authorization: HMAC-SHA256 <hex>`; some integrations
use `X-Canvas-Signature: sha256=<hex>`).  We accept either layout: callers
hand us whatever string was in the header and we strip a recognized prefix.

Constant-time comparison via `hmac.compare_digest` is non-negotiable: naive
`==` leaks one byte at a time to a timing attack.
"""

from __future__ import annotations

import hashlib
import hmac


def _normalize(header_value: str) -> str:
    value = header_value.strip()
    for prefix in ("HMAC-SHA256 ", "sha256=", "SHA256="):
        if value.startswith(prefix):
            return value[len(prefix):]
    return value


def compute_canvas_signature(body: bytes, secret: str) -> str:
    """Return the lowercase-hex HMAC-SHA256 of `body` keyed by `secret`."""
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def verify_canvas_signature(body: bytes, header_value: str, secret: str) -> bool:
    """Constant-time check that `header_value` matches HMAC-SHA256(body, secret).

    Args:
        body: Raw request body as bytes (NOT a parsed JSON dict — recompute
            against exactly the bytes Canvas signed).
        header_value: Whatever the inbound header carried — may include a
            `sha256=` or `HMAC-SHA256 ` prefix; both are handled.
        secret: The shared secret configured in Canvas and stored in
            GCP Secret Manager (`CANVAS_WEBHOOK_SECRET`).

    Returns:
        True iff the signature matches.  False on any mismatch, including
        empty / missing inputs.
    """
    if not header_value or not secret:
        return False
    expected = compute_canvas_signature(body, secret)
    actual = _normalize(header_value)
    return hmac.compare_digest(expected, actual)
