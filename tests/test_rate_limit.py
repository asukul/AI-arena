"""Tests for the in-memory rate limiter (the dev/test substitute)."""

from __future__ import annotations

from datetime import UTC, datetime

from api.rate_limit import InMemoryRateLimiter


def test_first_request_allowed_and_counts_one() -> None:
    rl = InMemoryRateLimiter(limit=5)
    decision = rl.check_and_increment("asukul")
    assert decision.allowed is True
    assert decision.current == 1
    assert decision.limit == 5


def test_at_limit_then_denied() -> None:
    rl = InMemoryRateLimiter(limit=3)
    for _ in range(3):
        assert rl.check_and_increment("asukul").allowed is True
    denied = rl.check_and_increment("asukul")
    assert denied.allowed is False
    assert denied.current == 3   # counter does not advance past limit
    assert denied.limit == 3


def test_distinct_students_have_separate_counters() -> None:
    rl = InMemoryRateLimiter(limit=2)
    assert rl.check_and_increment("alice").allowed is True
    assert rl.check_and_increment("alice").allowed is True
    assert rl.check_and_increment("alice").allowed is False
    # Bob is unaffected.
    assert rl.check_and_increment("bob").allowed is True


def test_reset_at_is_tomorrow_midnight_utc() -> None:
    fixed = datetime(2026, 6, 15, 14, 32, tzinfo=UTC)
    rl = InMemoryRateLimiter(limit=1, now_fn=lambda: fixed)
    decision = rl.check_and_increment("asukul")
    assert decision.reset_at == datetime(2026, 6, 16, 0, 0, tzinfo=UTC)


def test_counter_resets_when_clock_advances_to_next_day() -> None:
    clock = {"now": datetime(2026, 6, 15, 23, 59, tzinfo=UTC)}
    rl = InMemoryRateLimiter(limit=1, now_fn=lambda: clock["now"])
    assert rl.check_and_increment("asukul").allowed is True
    assert rl.check_and_increment("asukul").allowed is False
    # Roll over to the next day.
    clock["now"] = datetime(2026, 6, 16, 0, 0, 1, tzinfo=UTC)
    assert rl.check_and_increment("asukul").allowed is True
