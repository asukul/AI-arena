"""
Track 1 — Hallucination Hunter.

Students submit (claim_id, label) predictions on a hidden test set of claims.
The scorer reports macro-F1 as the headline metric and stashes per-class
precision/recall plus micro/weighted F1 in `judge_metadata` for transparency.

Macro-F1 is the headline because it surfaces minority-class failures (e.g. a
student who only predicts the majority class would still get high accuracy but
near-zero macro-F1 on the rare class). For a fact-verification task that
matters: 'not_enough_info' is the rare class students are most tempted to
under-predict.

No sklearn dependency on purpose: the math is short, students can read it,
and the dependency tree stays lean.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping

from api.schemas import (
    HallucinationPayload,
    ScoreDimension,
    ScoreResult,
    Submission,
    TRACK_HALLUCINATION,
)


def _per_class_prf(
    gold: Mapping[str, str],
    pred: Mapping[str, str],
    cls: str,
) -> tuple[float, float, float, int]:
    """Return (precision, recall, f1, support) for a single class label."""
    tp = sum(1 for cid in gold if pred.get(cid) == cls and gold[cid] == cls)
    fp = sum(1 for cid in gold if pred.get(cid) == cls and gold[cid] != cls)
    fn = sum(1 for cid in gold if pred.get(cid) != cls and gold[cid] == cls)
    support = sum(1 for cid in gold if gold[cid] == cls)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return precision, recall, f1, support


def score_hallucination(
    submission: Submission,
    ground_truth: Mapping[str, str],
) -> ScoreResult:
    """Score a Hallucination Hunter submission against the hidden gold labels.

    Args:
        submission: Validated student submission. Must have track_id ==
            'hallucination_hunter'.
        ground_truth: Mapping of claim_id → gold label. The set of claim_ids
            in the student's predictions must match this exactly; missing or
            extra claim_ids raise ValueError so the dispatcher can return a
            friendly error to the student.

    Returns:
        ScoreResult with final_score = macro-F1.
    """
    if submission.track_id != TRACK_HALLUCINATION:
        raise ValueError(
            f"score_hallucination called with track_id={submission.track_id!r}; "
            f"expected {TRACK_HALLUCINATION!r}"
        )

    payload = submission.track_payload
    assert isinstance(payload, HallucinationPayload)  # narrow for type checker

    # Validate alignment with the gold set.
    pred_pairs = [(p.claim_id, p.label) for p in payload.predictions]
    pred_ids = [cid for cid, _ in pred_pairs]
    duplicates = [cid for cid, n in Counter(pred_ids).items() if n > 1]
    if duplicates:
        raise ValueError(f"duplicate claim_id(s) in predictions: {sorted(duplicates)}")

    pred = dict(pred_pairs)
    gold_ids = set(ground_truth)
    pred_id_set = set(pred)
    unknown = pred_id_set - gold_ids
    missing = gold_ids - pred_id_set
    if unknown:
        raise ValueError(f"unknown claim_id(s) in predictions: {sorted(unknown)}")
    if missing:
        raise ValueError(f"missing predictions for claim_id(s): {sorted(missing)}")

    classes = sorted(set(ground_truth.values()))
    per_class: dict[str, dict[str, float]] = {}
    f1_values: list[float] = []
    weighted_f1_num = 0.0
    total_support = 0

    for cls in classes:
        precision, recall, f1, support = _per_class_prf(ground_truth, pred, cls)
        per_class[cls] = {
            "precision": round(precision, 6),
            "recall": round(recall, 6),
            "f1": round(f1, 6),
            "support": support,
        }
        f1_values.append(f1)
        weighted_f1_num += f1 * support
        total_support += support

    macro_f1 = sum(f1_values) / len(f1_values) if f1_values else 0.0
    weighted_f1 = weighted_f1_num / total_support if total_support else 0.0
    correct = sum(1 for cid in ground_truth if pred[cid] == ground_truth[cid])
    micro_f1 = correct / total_support if total_support else 0.0  # multi-class

    return ScoreResult(
        submission_id=submission.submission_id,
        student_id=submission.student_id,
        track_id=TRACK_HALLUCINATION,
        final_score=round(macro_f1, 6),
        dimensions=[
            ScoreDimension(
                name="macro_f1",
                weight=1.0,
                raw_score=round(macro_f1, 6),
                notes=f"{len(classes)} classes, {total_support} items",
            )
        ],
        judge_metadata={
            "n_predictions": len(pred),
            "classes": classes,
            "macro_f1": round(macro_f1, 6),
            "micro_f1": round(micro_f1, 6),
            "weighted_f1": round(weighted_f1, 6),
            "per_class": per_class,
        },
    )
