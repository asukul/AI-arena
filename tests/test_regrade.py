"""
Cross-family re-grade pass.

The platform's primary judge is Claude Haiku 4.5. To catch judges that
systematically over- or under-grade in a model-family-specific way, the
top 10% of submissions per track are re-scored by a second judge from a
different family (Gemini Flash in production). When the two judges
disagree by more than the threshold (default 10 percentage points), the
submission is flagged for instructor review.

Tests use FakeJudge instances so CI stays free; the abstraction does not
care which model family backs each judge.
"""

from __future__ import annotations

import pytest

from evaluator.judge import FakeJudge, JudgeResponse
from evaluator.regrade import (
    Disagreement,
    RegradeOptions,
    select_top_n_pct,
    cross_family_regrade,
)


# ---------- Helpers ----------

def _judge_returning(score: float) -> FakeJudge:
    fake = FakeJudge()
    # Single canned response for any call. Substring "DIMENSION" matches the
    # rag.py user-message convention; for plain-text user msgs, the FakeJudge
    # default-responds at 0.5 — so callers either match a real substring or
    # accept the default.
    fake.add("", JudgeResponse(
        score=score, reasoning="canned",
        raw_text=f'{{"score": {score}}}',
        model="fake-secondary",
        tokens_in=10, tokens_out=5,
    ))
    return fake


def _entries(*scores: float) -> list[dict]:
    """Build a leaderboard entries slice with synthetic submission_ids and
    descending final_scores. Callers pass scores in descending order to
    mirror what /leaderboard/{track} actually returns."""
    return [
        {
            "submission_id": f"sub_{i:03d}",
            "student_id":    f"student_{i}",
            "final_score":   s,
            "judge_metadata": {
                # Echoed back to the secondary judge so it has the same
                # context the primary judge saw. In production this comes
                # from Firestore.
                "user_msg": f"primary judge user message #{i}",
                "system_msg": "primary judge system prompt",
            },
        }
        for i, s in enumerate(scores)
    ]


# ---------- select_top_n_pct ----------

def test_select_top_decile_of_ten() -> None:
    entries = _entries(*[1.0 - i * 0.05 for i in range(10)])
    top = select_top_n_pct(entries, pct=10)
    assert len(top) == 1
    assert top[0]["submission_id"] == "sub_000"


def test_select_top_quartile_rounds_up() -> None:
    entries = _entries(*[1.0 - i * 0.1 for i in range(7)])
    # 25% of 7 = 1.75 → round up to 2 (so the cutoff is generous, not stingy).
    top = select_top_n_pct(entries, pct=25)
    assert len(top) == 2


def test_select_top_with_few_entries_always_returns_at_least_one() -> None:
    entries = _entries(0.9, 0.8)
    top = select_top_n_pct(entries, pct=10)
    assert len(top) == 1


def test_select_empty_returns_empty() -> None:
    assert select_top_n_pct([], pct=10) == []


# ---------- cross_family_regrade ----------

def test_no_disagreements_when_judges_agree() -> None:
    entries = _entries(0.9, 0.8, 0.7)
    secondary = _judge_returning(0.9)  # always 0.9
    # Primary scores in entries: 0.9, 0.8, 0.7
    # Threshold 0.1 → 0.9-0.9=0 ok, 0.8-0.9=0.1 ok (boundary), 0.7-0.9=0.2 flag
    # But we only re-grade the top decile → just sub_000 (0.9) which agrees.
    flagged = cross_family_regrade(entries, secondary_judge=secondary,
                                   options=RegradeOptions(top_pct=10, threshold=0.1))
    assert flagged == []


def test_flags_when_secondary_disagrees_above_threshold() -> None:
    entries = _entries(0.95, 0.90, 0.85, 0.80, 0.75)
    secondary = _judge_returning(0.5)  # large disagreement on every entry
    # Top 40% = 2 entries. Both should flag.
    flagged = cross_family_regrade(entries, secondary_judge=secondary,
                                   options=RegradeOptions(top_pct=40, threshold=0.1))
    assert len(flagged) == 2
    assert all(isinstance(d, Disagreement) for d in flagged)
    assert all(abs(d.delta) > 0.1 for d in flagged)
    # Highest-scoring submission should be the first reported.
    assert flagged[0].submission_id == "sub_000"


def test_does_not_flag_at_or_below_threshold() -> None:
    entries = _entries(0.90)
    secondary = _judge_returning(0.80)  # delta = 0.10 exactly
    flagged = cross_family_regrade(entries, secondary_judge=secondary,
                                   options=RegradeOptions(top_pct=100, threshold=0.10))
    assert flagged == []


def test_empty_leaderboard_yields_no_disagreements() -> None:
    secondary = _judge_returning(0.5)
    assert cross_family_regrade([], secondary_judge=secondary,
                                options=RegradeOptions()) == []


def test_disagreement_carries_both_scores_and_metadata() -> None:
    entries = _entries(1.0)
    secondary = _judge_returning(0.4)
    flagged = cross_family_regrade(entries, secondary_judge=secondary,
                                   options=RegradeOptions(top_pct=100, threshold=0.1))
    assert len(flagged) == 1
    d = flagged[0]
    assert d.primary_score == pytest.approx(1.0)
    assert d.secondary_score == pytest.approx(0.4)
    assert d.delta == pytest.approx(0.6)
    assert d.submission_id == "sub_000"
    assert d.student_id == "student_0"


def test_secondary_judge_called_once_per_top_entry() -> None:
    entries = _entries(*[1.0 - i * 0.05 for i in range(10)])
    secondary = _judge_returning(0.6)
    cross_family_regrade(entries, secondary_judge=secondary,
                         options=RegradeOptions(top_pct=20, threshold=0.99))
    # Top 20% of 10 = 2 → exactly 2 secondary calls.
    assert len(secondary.calls) == 2
