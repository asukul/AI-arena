"""Tests for the weighted-rubric aggregator."""

from __future__ import annotations

import pytest

from api.schemas import ScoreDimension
from evaluator.scoring import aggregate, normalize_weights


def _dim(name: str, weight: float, raw: float) -> ScoreDimension:
    return ScoreDimension(name=name, weight=weight, raw_score=raw)


def test_single_dimension_returns_its_raw_score() -> None:
    assert aggregate([_dim("a", 1.0, 0.7)]) == pytest.approx(0.7)


def test_equal_weight_two_dims_is_arithmetic_mean() -> None:
    score = aggregate([_dim("a", 0.5, 1.0), _dim("b", 0.5, 0.0)])
    assert score == pytest.approx(0.5)


def test_unequal_weights_skew_toward_heavier_dim() -> None:
    # 0.9 weight on a high score, 0.1 on a low score → close to high.
    score = aggregate([_dim("hi", 0.9, 1.0), _dim("lo", 0.1, 0.0)])
    assert score == pytest.approx(0.9)


def test_rag_rubric_canonical_example() -> None:
    """The RAG weighting example from PLAN.md / spec section 5."""
    dims = [
        _dim("correctness",   0.30, 0.85),
        _dim("faithfulness",  0.25, 0.70),
        _dim("retrieval",     0.15, 0.60),
        _dim("citations",     0.15, 0.50),
        _dim("cost",          0.10, 1.00),
        _dim("safety",        0.05, 1.00),
    ]
    expected = (0.30*0.85 + 0.25*0.70 + 0.15*0.60 + 0.15*0.50
                + 0.10*1.00 + 0.05*1.00)
    assert aggregate(dims) == pytest.approx(expected)


def test_zero_weight_returns_zero_safely() -> None:
    assert aggregate([_dim("a", 0.0, 0.5)]) == 0.0


def test_empty_returns_zero() -> None:
    assert aggregate([]) == 0.0


def test_normalize_weights_brings_total_to_one() -> None:
    dims = [_dim("a", 30, 0.5), _dim("b", 70, 0.5)]
    norm = normalize_weights(dims)
    assert sum(d.weight for d in norm) == pytest.approx(1.0)
    # The aggregate is unchanged by normalization.
    assert aggregate(norm) == pytest.approx(aggregate(dims))


def test_normalize_weights_preserves_zero_total() -> None:
    dims = [_dim("a", 0.0, 0.5), _dim("b", 0.0, 0.5)]
    norm = normalize_weights(dims)
    assert sum(d.weight for d in norm) == 0.0
