"""Tests for Canvas webhook HMAC signature verification."""

from __future__ import annotations

from api.auth import compute_canvas_signature, verify_canvas_signature


SECRET = "test-shared-secret-do-not-use-in-prod"
BODY = b'{"event":"submission_created","submission_id":"abc"}'


def test_round_trip_signature_verifies() -> None:
    sig = compute_canvas_signature(BODY, SECRET)
    assert verify_canvas_signature(BODY, sig, SECRET) is True


def test_signature_with_sha256_prefix() -> None:
    sig = compute_canvas_signature(BODY, SECRET)
    assert verify_canvas_signature(BODY, f"sha256={sig}", SECRET) is True


def test_signature_with_canvas_live_events_prefix() -> None:
    sig = compute_canvas_signature(BODY, SECRET)
    assert verify_canvas_signature(BODY, f"HMAC-SHA256 {sig}", SECRET) is True


def test_tampered_body_fails() -> None:
    sig = compute_canvas_signature(BODY, SECRET)
    assert verify_canvas_signature(BODY + b"x", sig, SECRET) is False


def test_wrong_secret_fails() -> None:
    sig = compute_canvas_signature(BODY, "different-secret")
    assert verify_canvas_signature(BODY, sig, SECRET) is False


def test_empty_signature_fails() -> None:
    assert verify_canvas_signature(BODY, "", SECRET) is False


def test_empty_secret_fails() -> None:
    sig = compute_canvas_signature(BODY, SECRET)
    assert verify_canvas_signature(BODY, sig, "") is False
