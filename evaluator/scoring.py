"""
Weighted-rubric aggregation.

Used by tracks whose final score is a weighted mean of per-dimension scores
(Track 3 — RAG: correctness 30 / faithfulness 25 / retrieval 15 / citations
15 / cost 10 / safety 5).  Track 1 and Track 2 don't need this — their
"rubric" has a single dimension.

Kept as a 10-line module on purpose: the math is short, students can read
it, and it lives outside any track file so multiple tracks reuse it.
"""

from __future__ import annotations

from collections.abc import Sequence

from api.schemas import ScoreDimension


def aggregate(dimensions: Sequence[ScoreDimension]) -> float:
    """Return the weighted mean of `raw_score` weighted by `weight`.

    Returns 0.0 if total weight is 0 (no dimensions, or all weights zero —
    in which case there is nothing meaningful to score against).
    """
    total_weight = sum(d.weight for d in dimensions)
    if total_weight <= 0:
        return 0.0
    weighted = sum(d.weight * d.raw_score for d in dimensions)
    return weighted / total_weight


def normalize_weights(dimensions: Sequence[ScoreDimension]) -> list[ScoreDimension]:
    """Return a copy of `dimensions` with weights summing to exactly 1.0.

    Useful when a track's weights are expressed as percentages (30, 25, 15,
    15, 10, 5 → 0.30, 0.25, 0.15, 0.15, 0.10, 0.05).
    """
    total = sum(d.weight for d in dimensions)
    if total <= 0:
        return list(dimensions)
    return [d.model_copy(update={"weight": d.weight / total}) for d in dimensions]
