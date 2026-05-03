"""Tests for Track 4 — Cohen's κ meta-judge."""

from __future__ import annotations

import pytest

from api.schemas import Submission
from evaluator.tracks.meta_judge import cohen_kappa_linear, score_meta_judge


# ---------- cohen_kappa_linear ----------

def test_perfect_agreement_kappa_one() -> None:
    assert cohen_kappa_linear([1, 2, 3, 4, 5], [1, 2, 3, 4, 5]) == pytest.approx(1.0)


def test_complete_disagreement_negative_kappa() -> None:
    # Reverse the order — strong systematic disagreement.
    k = cohen_kappa_linear([1, 2, 3, 4, 5], [5, 4, 3, 2, 1])
    assert k < 0


def test_off_by_one_better_than_off_by_two() -> None:
    """Linear weighting should distinguish near misses from far ones."""
    near = cohen_kappa_linear([1, 2, 3, 4, 5], [2, 3, 4, 5, 4])  # off-by-one mostly
    far  = cohen_kappa_linear([1, 2, 3, 4, 5], [3, 4, 5, 1, 2])  # off-by-two
    assert near > far


def test_chance_level_yields_low_kappa() -> None:
    # Two raters who both guess 1 or 2 with 50/50 will get ~50% chance
    # agreement; weighted κ should be close to 0.
    rater1 = [1, 2] * 50
    rater2 = [1, 1, 2, 2] * 25
    k = cohen_kappa_linear(rater1, rater2)
    assert -0.2 < k < 0.2


def test_single_class_used_treated_as_perfect() -> None:
    """Degenerate case: both raters always say the same number."""
    assert cohen_kappa_linear([3, 3, 3], [3, 3, 3]) == 1.0


def test_mismatched_lengths_raises() -> None:
    with pytest.raises(ValueError, match="same length"):
        cohen_kappa_linear([1, 2], [1, 2, 3])


def test_empty_input_raises() -> None:
    with pytest.raises(ValueError, match="zero items"):
        cohen_kappa_linear([], [])


# ---------- score_meta_judge ----------

def _submission(self_grades: list[tuple[str, float]]) -> Submission:
    return Submission.model_validate(
        {
            "submission_id": "sub_test",
            "student_id": "asukul",
            "track_id": "meta_judge",
            "submission_timestamp": "2026-06-15T14:32:00Z",
            "track_payload": {
                "evaluator_source": "def grade(item):\n    return 1.0\n",
                "rubric_text": "Test rubric.",
                "self_grades": [
                    {"item_id": iid, "score": s} for iid, s in self_grades
                ],
            },
        }
    )


def test_perfect_self_judge_scores_one() -> None:
    gold = {"i1": 5, "i2": 4, "i3": 3, "i4": 2, "i5": 1}
    sub = _submission([(iid, s) for iid, s in gold.items()])
    result = score_meta_judge(sub, gold)
    assert result.final_score == pytest.approx(1.0)
    assert result.judge_metadata["kappa_linear"] == pytest.approx(1.0)
    assert result.judge_metadata["exact_agreement"] == 5


def test_systematic_disagreement_scores_low() -> None:
    gold = {"i1": 5, "i2": 4, "i3": 3, "i4": 2, "i5": 1}
    sub = _submission([(iid, 6 - gold[iid]) for iid in gold])  # reversed
    result = score_meta_judge(sub, gold)
    assert result.final_score < 0.3


def test_close_but_imperfect_scores_above_chance() -> None:
    gold = {f"i{i}": (i % 5) + 1 for i in range(20)}
    # Mostly correct, one or two items off-by-one.
    student = {iid: g if iid != "i3" else (g + 1 if g < 5 else g - 1) for iid, g in gold.items()}
    sub = _submission(list(student.items()))
    result = score_meta_judge(sub, gold)
    assert result.final_score > 0.8


def test_missing_items_raise() -> None:
    gold = {"i1": 5, "i2": 4}
    sub = _submission([("i1", 5)])  # missing i2
    with pytest.raises(ValueError, match="missing student grades"):
        score_meta_judge(sub, gold)


def test_no_overlap_raises() -> None:
    gold = {"i1": 5}
    sub = _submission([("zzz", 5)])
    with pytest.raises(ValueError, match="no overlap"):
        score_meta_judge(sub, gold)


def test_wrong_track_raises() -> None:
    sub = Submission.model_validate(
        {
            "submission_id": "x", "student_id": "asukul",
            "track_id": "hallucination_hunter",
            "submission_timestamp": "2026-06-15T14:32:00Z",
            "track_payload": {"predictions": [{"claim_id": "C1", "label": "x"}]},
        }
    )
    with pytest.raises(ValueError, match="meta_judge"):
        score_meta_judge(sub, {"i1": 5})
