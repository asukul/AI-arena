"""
Track 4 — Build Your Own AI Judge.

Pedagogical capstone: students write their own evaluator function and submit
its self-grades on a calibration set.  The platform compares those grades
against the instructor's gold ratings using **linear-weighted Cohen's κ**
and reports it as the final score.

Why linear-weighted kappa (not standard kappa or accuracy):
  * Standard kappa treats "off by one" the same as "completely wrong".
    On an ordinal scale (1-5 Likert) that's wrong — a student rater
    giving 4 when the instructor gave 5 is much closer to agreement
    than giving 1.
  * Linear-weighted κ penalizes proportionally to the integer distance
    between ratings: |i - j| / (K - 1).
  * Quadratic-weighted κ is also defensible (and common in medical
    research), but linear is more conservative and more interpretable
    for student feedback.

The final_score reported by the platform is `(κ + 1) / 2`, mapping the
natural κ range [-1, 1] into the platform's [0, 1] convention.  A student
whose evaluator perfectly matches the instructor scores 1.0; pure chance
agreement scores 0.5; systematic disagreement scores 0.

No sklearn dependency: ~30 lines of arithmetic, pedagogically transparent.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from api.schemas import (
    MetaJudgePayload,
    ScoreDimension,
    ScoreResult,
    Submission,
    TRACK_META_JUDGE,
)


def cohen_kappa_linear(rater1: Sequence[int], rater2: Sequence[int]) -> float:
    """Linear-weighted Cohen's κ for paired integer ratings.

    Args:
        rater1, rater2: parallel sequences of integer ratings on the same
            items.  Same length required.

    Returns:
        κ in [-1.0, 1.0].  Returns 1.0 when there is no variance
        (degenerate case: every item has the same rating from both).
    """
    if len(rater1) != len(rater2):
        raise ValueError("rater1 and rater2 must have the same length")
    n = len(rater1)
    if n == 0:
        raise ValueError("cannot compute kappa over zero items")

    classes = sorted(set(rater1) | set(rater2))
    if len(classes) <= 1:
        # Both raters used a single rating value; treat as full agreement.
        return 1.0

    K = len(classes)
    idx = {c: i for i, c in enumerate(classes)}

    obs = [[0] * K for _ in range(K)]
    for r1, r2 in zip(rater1, rater2, strict=True):
        obs[idx[r1]][idx[r2]] += 1

    row_marg = [sum(obs[i]) for i in range(K)]
    col_marg = [sum(obs[i][j] for i in range(K)) for j in range(K)]

    # κ_w = 1 - Σ(d_ij × obs_ij) / Σ(d_ij × exp_ij)
    # with linear disagreement d_ij = |i - j| / (K - 1)
    num = 0.0
    den = 0.0
    for i in range(K):
        for j in range(K):
            d = abs(i - j) / (K - 1)
            exp_ij = row_marg[i] * col_marg[j] / n
            num += d * obs[i][j]
            den += d * exp_ij

    if den == 0.0:
        # No expected disagreement (one marginal is concentrated on one
        # class).  By convention, treat as perfect agreement.
        return 1.0

    return 1.0 - (num / den)


def score_meta_judge(
    submission: Submission,
    ground_truth: Mapping[str, float],
) -> ScoreResult:
    """Score a Build-Your-Own-AI-Judge submission against instructor gold.

    Args:
        submission: Validated submission. track_id must be 'meta_judge'.
        ground_truth: Mapping of item_id → instructor's gold rating.
            Ratings are rounded to integers for ordinal kappa.

    Returns:
        ScoreResult with final_score = (κ + 1) / 2.
    """
    if submission.track_id != TRACK_META_JUDGE:
        raise ValueError(
            f"score_meta_judge called with track_id={submission.track_id!r}; "
            f"expected {TRACK_META_JUDGE!r}"
        )

    payload = submission.track_payload
    assert isinstance(payload, MetaJudgePayload)

    student_grades = {g.item_id: g.score for g in payload.self_grades}
    common = sorted(set(ground_truth) & set(student_grades))
    missing = sorted(set(ground_truth) - set(student_grades))

    if not common:
        raise ValueError(
            "no overlap between student self-grades and instructor gold; "
            "submission cannot be scored"
        )
    if missing:
        raise ValueError(
            f"missing student grades for {len(missing)} items: "
            f"{missing[:5]}{'…' if len(missing) > 5 else ''}"
        )

    gold_int = [round(ground_truth[i]) for i in common]
    stud_int = [round(student_grades[i]) for i in common]

    kappa = cohen_kappa_linear(gold_int, stud_int)
    final_score = max(0.0, min(1.0, (kappa + 1.0) / 2.0))

    n_classes = len(set(gold_int) | set(stud_int))
    exact_agree = sum(1 for g, s in zip(gold_int, stud_int, strict=True) if g == s)

    return ScoreResult(
        submission_id=submission.submission_id,
        student_id=submission.student_id,
        track_id=TRACK_META_JUDGE,
        final_score=round(final_score, 6),
        dimensions=[
            ScoreDimension(
                name="kappa_mapped",
                weight=1.0,
                raw_score=round(final_score, 6),
                notes=f"κ = {kappa:+.4f} over {len(common)} items, {n_classes} rating classes",
            )
        ],
        judge_metadata={
            "n_items": len(common),
            "n_rating_classes": n_classes,
            "exact_agreement": exact_agree,
            "exact_agreement_rate": round(exact_agree / len(common), 6),
            "kappa_linear": round(kappa, 6),
            "kappa_mapped_to_unit": round(final_score, 6),
        },
    )
