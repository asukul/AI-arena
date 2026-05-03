"""Tests for the in-memory leaderboard store (the dev/test substitute)."""

from __future__ import annotations

from api.schemas import ScoreResult
from leaderboard.firestore_client import InMemoryLeaderboard


def _result(student: str, track: str, score: float, sub_id: str) -> ScoreResult:
    return ScoreResult(
        submission_id=sub_id,
        student_id=student,
        track_id=track,  # type: ignore[arg-type]
        final_score=score,
    )


def test_first_submission_lands_on_leaderboard() -> None:
    lb = InMemoryLeaderboard()
    lb.write_result(_result("asukul", "hallucination_hunter", 0.7, "s1"))
    top = lb.top("hallucination_hunter")
    assert len(top) == 1
    assert top[0]["student_id"] == "asukul"
    assert top[0]["final_score"] == 0.7


def test_higher_score_replaces_lower_for_same_student() -> None:
    lb = InMemoryLeaderboard()
    lb.write_result(_result("asukul", "hallucination_hunter", 0.6, "s1"))
    lb.write_result(_result("asukul", "hallucination_hunter", 0.8, "s2"))
    top = lb.top("hallucination_hunter")
    assert len(top) == 1
    assert top[0]["final_score"] == 0.8
    assert top[0]["submission_id"] == "s2"


def test_lower_score_does_not_replace_prior_best() -> None:
    lb = InMemoryLeaderboard()
    lb.write_result(_result("asukul", "hallucination_hunter", 0.8, "s1"))
    lb.write_result(_result("asukul", "hallucination_hunter", 0.5, "s2"))
    top = lb.top("hallucination_hunter")
    assert top[0]["final_score"] == 0.8
    assert top[0]["submission_id"] == "s1"


def test_full_submission_archive_keeps_all_attempts() -> None:
    lb = InMemoryLeaderboard()
    lb.write_result(_result("asukul", "hallucination_hunter", 0.6, "s1"))
    lb.write_result(_result("asukul", "hallucination_hunter", 0.5, "s2"))
    assert "s1" in lb.submissions and "s2" in lb.submissions


def test_top_orders_descending_across_students() -> None:
    lb = InMemoryLeaderboard()
    lb.write_result(_result("alice", "hallucination_hunter", 0.4, "a1"))
    lb.write_result(_result("bob", "hallucination_hunter", 0.9, "b1"))
    lb.write_result(_result("carol", "hallucination_hunter", 0.7, "c1"))
    top = lb.top("hallucination_hunter")
    assert [r["student_id"] for r in top] == ["bob", "carol", "alice"]


def test_per_track_isolation() -> None:
    lb = InMemoryLeaderboard()
    lb.write_result(_result("asukul", "hallucination_hunter", 0.9, "h1"))
    lb.write_result(_result("asukul", "prompt_golf", 0.3, "g1"))
    h_top = lb.top("hallucination_hunter")
    g_top = lb.top("prompt_golf")
    assert h_top[0]["final_score"] == 0.9
    assert g_top[0]["final_score"] == 0.3
