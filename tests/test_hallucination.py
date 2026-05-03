"""
Track 1 — Hallucination Hunter. F1 over (claim_id, label) classification.

Per project convention every scoring function is covered by:
  - happy path
  - empty / boundary input
  - malformed input
  - numerical edge case
"""

from __future__ import annotations

import pytest

from api.schemas import HallucinationPayload, Prediction, Submission
from evaluator.tracks.hallucination import score_hallucination


# ---------- Helpers ----------

def _submission(predictions: list[tuple[str, str]]) -> Submission:
    return Submission.model_validate(
        {
            "submission_id": "sub_test",
            "student_id": "asukul",
            "track_id": "hallucination_hunter",
            "submission_timestamp": "2026-06-15T14:32:00Z",
            "track_payload": {
                "predictions": [
                    {"claim_id": cid, "label": lab} for cid, lab in predictions
                ],
            },
        }
    )


# ---------- Happy paths ----------

def test_perfect_predictions_score_one() -> None:
    gold = {"C1": "supported", "C2": "refuted", "C3": "not_enough_info"}
    sub = _submission(
        [("C1", "supported"), ("C2", "refuted"), ("C3", "not_enough_info")]
    )
    result = score_hallucination(sub, gold)
    assert result.final_score == pytest.approx(1.0)
    assert result.dimensions[0].name == "macro_f1"


def test_all_wrong_predictions_score_zero() -> None:
    gold = {"C1": "supported", "C2": "refuted"}
    sub = _submission([("C1", "refuted"), ("C2", "supported")])
    result = score_hallucination(sub, gold)
    assert result.final_score == pytest.approx(0.0)


def test_known_intermediate_case_matches_hand_computed_f1() -> None:
    # Two-class problem, 4 items, hand-computed macro-F1.
    # Gold:  S, S, R, R
    # Pred:  S, R, R, R
    # Class S: TP=1, FP=0, FN=1 → P=1.0, R=0.5, F1=0.6667
    # Class R: TP=2, FP=1, FN=0 → P=0.6667, R=1.0, F1=0.8
    # macro-F1 = (0.6667 + 0.8) / 2 = 0.7333
    gold = {"C1": "S", "C2": "S", "C3": "R", "C4": "R"}
    sub = _submission([("C1", "S"), ("C2", "R"), ("C3", "R"), ("C4", "R")])
    result = score_hallucination(sub, gold)
    assert result.final_score == pytest.approx(0.7333, abs=1e-3)


# ---------- Class imbalance / boundary ----------

def test_minority_class_failure_drops_macro_f1() -> None:
    # 9 of one class, 1 of another. Predict majority for everything.
    # Macro-F1 must penalize the rare class going to zero, even though
    # accuracy is 90%.
    gold = {f"C{i}": "S" for i in range(9)} | {"C9": "R"}
    sub = _submission([(cid, "S") for cid in gold])
    result = score_hallucination(sub, gold)
    # Macro-F1 = (F1_S + F1_R) / 2 = (~0.95 + 0.0) / 2 ≈ 0.474
    assert result.final_score < 0.5
    assert result.judge_metadata["per_class"]["R"]["f1"] == pytest.approx(0.0)


def test_phantom_label_does_not_get_its_own_class() -> None:
    # Student invents "MAYBE" which isn't in gold. It must lower scores by
    # being wrong, not by inflating the class-set denominator.
    gold = {"C1": "S", "C2": "R"}
    sub = _submission([("C1", "MAYBE"), ("C2", "R")])
    result = score_hallucination(sub, gold)
    assert "MAYBE" not in result.judge_metadata["per_class"]
    # C1 wrong (S got recall=0), C2 correct (R got 1.0). Macro = 0.5.
    assert result.final_score == pytest.approx(0.5, abs=1e-6)


# ---------- Malformed input ----------

def test_missing_predictions_raise() -> None:
    gold = {"C1": "S", "C2": "S", "C3": "S"}
    sub = _submission([("C1", "S")])
    with pytest.raises(ValueError, match="missing predictions"):
        score_hallucination(sub, gold)


def test_extra_predictions_raise() -> None:
    gold = {"C1": "S"}
    sub = _submission([("C1", "S"), ("C99", "S")])
    with pytest.raises(ValueError, match="unknown claim_id"):
        score_hallucination(sub, gold)


def test_duplicate_claim_id_raises() -> None:
    gold = {"C1": "S", "C2": "R"}
    sub = _submission([("C1", "S"), ("C1", "R"), ("C2", "R")])
    with pytest.raises(ValueError, match="duplicate"):
        score_hallucination(sub, gold)


def test_wrong_track_id_raises() -> None:
    # Defensive: dispatcher should already filter, but the scorer guards too.
    sub = Submission.model_validate(
        {
            "submission_id": "sub_x",
            "student_id": "asukul",
            "track_id": "prompt_golf",
            "submission_timestamp": "2026-06-15T14:32:00Z",
            "track_payload": {"prompt_template": "x"},
        }
    )
    with pytest.raises(ValueError, match="hallucination_hunter"):
        score_hallucination(sub, {"C1": "S"})


# ---------- Score result shape ----------

def test_result_carries_through_submission_metadata() -> None:
    gold = {"C1": "S"}
    sub = _submission([("C1", "S")])
    result = score_hallucination(sub, gold)
    assert result.submission_id == "sub_test"
    assert result.student_id == "asukul"
    assert result.track_id == "hallucination_hunter"


def test_result_records_micro_and_weighted_f1_for_diagnostics() -> None:
    gold = {"C1": "S", "C2": "S", "C3": "R"}
    sub = _submission([("C1", "S"), ("C2", "S"), ("C3", "S")])
    result = score_hallucination(sub, gold)
    md = result.judge_metadata
    assert "macro_f1" in md and "micro_f1" in md and "weighted_f1" in md
    assert md["n_predictions"] == 3
    assert "per_class" in md
