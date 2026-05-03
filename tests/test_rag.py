"""
Track 3 — RAG Treasure Hunt.

Per project convention every scoring function is covered by:
  - happy path
  - empty / boundary input
  - malformed input
  - numerical edge case at scoring boundary

The track scores six dimensions (correctness 30 / faithfulness 25 /
retrieval 15 / citations 15 / cost 10 / safety 5) per question, then
weighted-averages them. Three of the six dimensions involve a judge
call; tests stub those with FakeJudge so CI never hits the real API.
"""

from __future__ import annotations

import pytest

from api.schemas import Submission
from evaluator.judge import FakeJudge, JudgeResponse
from evaluator.tracks.rag import (
    _citation_f1,
    _retrieval_recall,
    score_rag,
)


# ---------- Helpers ----------

def _gold(items, *, chunks=None, baseline_cost=0.005, weights=None):
    return {
        "items": items,
        "chunks": chunks or {},
        "baseline_cost_per_question_usd": baseline_cost,
        "weights": weights or {
            "correctness": 30,
            "faithfulness": 25,
            "retrieval": 15,
            "citations": 15,
            "cost": 10,
            "safety": 5,
        },
    }


def _submission(answers):
    return Submission.model_validate(
        {
            "submission_id": "sub_test",
            "student_id": "asukul",
            "track_id": "rag_treasure_hunt",
            "submission_timestamp": "2026-06-15T14:32:00Z",
            "track_payload": {"answers": answers},
        }
    )


def _judge(scores_by_substring):
    """FakeJudge returning a fixed score whenever a substring is present in
    the user message. Token counts are tiny so they don't influence the cost
    component (cost reads from the student's reported estimated_cost_usd)."""
    fake = FakeJudge()
    for needle, score in scores_by_substring.items():
        fake.add(
            needle,
            JudgeResponse(
                score=score,
                reasoning=f"score={score}",
                raw_text=f'{{"score": {score}}}',
                model="fake-haiku",
                tokens_in=20,
                tokens_out=8,
            ),
        )
    return fake


# ---------- Math helpers (no judge) ----------

def test_retrieval_recall_perfect() -> None:
    assert _retrieval_recall({"a", "b", "c"}, {"a", "b", "c"}) == pytest.approx(1.0)


def test_retrieval_recall_partial() -> None:
    # 2 of 3 relevant chunks retrieved.
    assert _retrieval_recall({"a", "b", "z"}, {"a", "b", "c"}) == pytest.approx(2 / 3)


def test_retrieval_recall_no_relevant_returns_one() -> None:
    # Degenerate: gold says nothing is relevant. Treat as full recall by
    # convention — we cannot punish a student for a question we have no
    # opinion on.
    assert _retrieval_recall({"a"}, set()) == pytest.approx(1.0)


def test_citation_f1_perfect() -> None:
    assert _citation_f1({"c1"}, {"c1"}) == pytest.approx(1.0)


def test_citation_f1_zero_when_no_overlap() -> None:
    assert _citation_f1({"c1"}, {"c2"}) == pytest.approx(0.0)


def test_citation_f1_handles_extra_citations() -> None:
    # Cited 2, only 1 was correct, gold had 1.  P=0.5, R=1.0, F1=2/3.
    assert _citation_f1({"c1", "c2"}, {"c1"}) == pytest.approx(2 / 3)


def test_citation_f1_no_citation_no_gold_treated_as_one() -> None:
    # No citations expected and none provided: nothing to grade against.
    assert _citation_f1(set(), set()) == pytest.approx(1.0)


# ---------- Happy paths ----------

def test_perfect_submission_scores_one() -> None:
    """Judge gives 1.0 to every dimension, retrieval/citations/cost are
    perfect — final_score should pin at 1.0 to 6dp."""
    items = [
        {
            "question_id": "Q001",
            "question": "What is CS 2010 about?",
            "expected_answer": "Intro to computational thinking with Python.",
            "relevant_chunk_ids": ["cs2010_c1"],
            "gold_citations": ["cs2010_c1"],
        },
    ]
    chunks = {"cs2010_c1": "CS 2010 introduces computational thinking using Python."}
    gold = _gold(items, chunks=chunks, baseline_cost=0.01)

    sub = _submission([{
        "question_id": "Q001",
        "answer": "CS 2010 teaches computational thinking via Python.",
        "citations": ["cs2010_c1"],
        "retrieved_contexts": ["cs2010_c1"],
        "estimated_cost_usd": 0.005,  # half the baseline → cost dim clamps to 1.0
        "latency_seconds": 1.0,
    }])
    judge = _judge({"computational thinking": 1.0, "CS 2010": 1.0})  # broad
    result = score_rag(sub, gold, judge=judge)
    assert result.final_score == pytest.approx(1.0)
    # Six dimensions surfaced for transparency.
    names = {d.name for d in result.dimensions}
    assert names == {"correctness", "faithfulness", "retrieval", "citations", "cost", "safety"}


def test_partial_submission_score_lands_between_zero_and_one() -> None:
    items = [
        {
            "question_id": "Q001",
            "question": "What is CS 2010?",
            "expected_answer": "Intro to CS with Python.",
            "relevant_chunk_ids": ["cs2010_c1", "cs2010_c2"],
            "gold_citations": ["cs2010_c1"],
        },
    ]
    chunks = {"cs2010_c1": "CS 2010 — Python intro.", "cs2010_c2": "Lectures + labs."}
    gold = _gold(items, chunks=chunks, baseline_cost=0.005)

    sub = _submission([{
        "question_id": "Q001",
        "answer": "CS 2010 teaches Python.",
        "citations": ["cs2010_c1"],
        "retrieved_contexts": ["cs2010_c1"],  # only 1 of 2 relevant chunks
        "estimated_cost_usd": 0.01,            # 2x baseline → cost = 0.5
        "latency_seconds": 2.0,
    }])
    # Mid-range judge scores.
    judge = _judge({"CS 2010": 0.6})
    result = score_rag(sub, gold, judge=judge)
    assert 0.3 < result.final_score < 0.95


def test_weighted_dimensions_match_documented_rubric() -> None:
    items = [
        {
            "question_id": "Q1",
            "question": "Q?",
            "expected_answer": "A",
            "relevant_chunk_ids": ["x"],
            "gold_citations": ["x"],
        },
    ]
    chunks = {"x": "stuff"}
    # Set every judge dimension to a unique value so we can read them out
    # of judge_metadata and check the weights match the documented rubric.
    sub = _submission([{
        "question_id": "Q1",
        "answer": "A",
        "citations": ["x"],
        "retrieved_contexts": ["x"],
        "estimated_cost_usd": 0.005,
        "latency_seconds": 1.0,
    }])
    gold = _gold(items, chunks=chunks, baseline_cost=0.005)
    # Single judge fake returns 0.8 by default (FakeJudge default = 0.5;
    # we override per-substring) — let's set distinct values via the
    # different system prompts.
    fake = FakeJudge()
    # The scorer prefixes every user message with [DIMENSION: <name>] so
    # tests can target one judge call at a time.
    fake.add("[DIMENSION: correctness]", JudgeResponse(
        score=0.9, reasoning="", raw_text='{"score": 0.9}', model="fake",
        tokens_in=10, tokens_out=5,
    ))
    fake.add("[DIMENSION: faithfulness]", JudgeResponse(
        score=0.7, reasoning="", raw_text='{"score": 0.7}', model="fake",
        tokens_in=10, tokens_out=5,
    ))
    fake.add("[DIMENSION: safety]", JudgeResponse(
        score=1.0, reasoning="", raw_text='{"score": 1.0}', model="fake",
        tokens_in=10, tokens_out=5,
    ))

    result = score_rag(sub, gold, judge=fake)
    md = result.judge_metadata
    # Per-dimension averages should reflect what the judge said.
    per = md["per_dimension_avg"]
    assert per["correctness"] == pytest.approx(0.9)
    assert per["faithfulness"] == pytest.approx(0.7)
    assert per["retrieval"] == pytest.approx(1.0)
    assert per["citations"] == pytest.approx(1.0)
    assert per["cost"] == pytest.approx(1.0)
    assert per["safety"] == pytest.approx(1.0)
    # Weighted mean using the documented 30/25/15/15/10/5 → 100 weights.
    expected = (0.9 * 30 + 0.7 * 25 + 1.0 * 15 + 1.0 * 15 + 1.0 * 10 + 1.0 * 5) / 100
    assert result.final_score == pytest.approx(expected, abs=1e-6)


def test_one_judge_call_per_question_per_judge_prompt() -> None:
    """correctness + faithfulness + safety = 3 calls per question."""
    items = [
        {"question_id": f"Q{i}", "question": "Q?", "expected_answer": "A",
         "relevant_chunk_ids": ["x"], "gold_citations": ["x"]}
        for i in range(2)
    ]
    chunks = {"x": "stuff"}
    sub = _submission([
        {"question_id": "Q0", "answer": "A", "citations": ["x"], "retrieved_contexts": ["x"],
         "estimated_cost_usd": 0.005, "latency_seconds": 1.0},
        {"question_id": "Q1", "answer": "A", "citations": ["x"], "retrieved_contexts": ["x"],
         "estimated_cost_usd": 0.005, "latency_seconds": 1.0},
    ])
    judge = _judge({"Q?": 0.8})
    score_rag(sub, _gold(items, chunks=chunks), judge=judge)
    assert len(judge.calls) == 6  # 2 questions × 3 judge prompts


# ---------- Boundary / numeric edges ----------

def test_huge_cost_drives_cost_dim_low() -> None:
    items = [{"question_id": "Q1", "question": "Q?", "expected_answer": "A",
              "relevant_chunk_ids": ["x"], "gold_citations": ["x"]}]
    sub = _submission([{
        "question_id": "Q1",
        "answer": "A",
        "citations": ["x"],
        "retrieved_contexts": ["x"],
        "estimated_cost_usd": 1.0,  # 200x the baseline
        "latency_seconds": 1.0,
    }])
    gold = _gold(items, chunks={"x": "stuff"}, baseline_cost=0.005)
    judge = _judge({"Q?": 1.0})
    result = score_rag(sub, gold, judge=judge)
    assert result.judge_metadata["per_dimension_avg"]["cost"] < 0.1


def test_zero_cost_caps_cost_dim_at_one() -> None:
    """Reporting zero cost shouldn't divide by zero or grant infinite credit."""
    items = [{"question_id": "Q1", "question": "Q?", "expected_answer": "A",
              "relevant_chunk_ids": ["x"], "gold_citations": ["x"]}]
    sub = _submission([{
        "question_id": "Q1",
        "answer": "A",
        "citations": ["x"],
        "retrieved_contexts": ["x"],
        "estimated_cost_usd": 0.0,  # free
        "latency_seconds": 1.0,
    }])
    gold = _gold(items, chunks={"x": "stuff"}, baseline_cost=0.005)
    judge = _judge({"Q?": 1.0})
    result = score_rag(sub, gold, judge=judge)
    assert result.judge_metadata["per_dimension_avg"]["cost"] == pytest.approx(1.0)


# ---------- Malformed input ----------

def test_missing_answers_raise() -> None:
    items = [
        {"question_id": "Q1", "question": "Q?", "expected_answer": "A",
         "relevant_chunk_ids": ["x"], "gold_citations": ["x"]},
        {"question_id": "Q2", "question": "Q?", "expected_answer": "A",
         "relevant_chunk_ids": ["x"], "gold_citations": ["x"]},
    ]
    sub = _submission([
        {"question_id": "Q1", "answer": "A", "citations": ["x"], "retrieved_contexts": ["x"],
         "estimated_cost_usd": 0.001, "latency_seconds": 1.0},
    ])
    gold = _gold(items, chunks={"x": "stuff"})
    judge = _judge({"Q?": 1.0})
    with pytest.raises(ValueError, match="missing answers"):
        score_rag(sub, gold, judge=judge)


def test_unknown_question_id_raises() -> None:
    items = [{"question_id": "Q1", "question": "Q?", "expected_answer": "A",
              "relevant_chunk_ids": ["x"], "gold_citations": ["x"]}]
    sub = _submission([
        {"question_id": "Q_PHANTOM", "answer": "A", "citations": ["x"], "retrieved_contexts": ["x"],
         "estimated_cost_usd": 0.001, "latency_seconds": 1.0},
        {"question_id": "Q1", "answer": "A", "citations": ["x"], "retrieved_contexts": ["x"],
         "estimated_cost_usd": 0.001, "latency_seconds": 1.0},
    ])
    gold = _gold(items, chunks={"x": "stuff"})
    judge = _judge({"Q?": 1.0})
    with pytest.raises(ValueError, match="unknown question_id"):
        score_rag(sub, gold, judge=judge)


def test_duplicate_question_id_raises() -> None:
    items = [{"question_id": "Q1", "question": "Q?", "expected_answer": "A",
              "relevant_chunk_ids": ["x"], "gold_citations": ["x"]}]
    sub = _submission([
        {"question_id": "Q1", "answer": "A", "citations": ["x"], "retrieved_contexts": ["x"],
         "estimated_cost_usd": 0.001, "latency_seconds": 1.0},
        {"question_id": "Q1", "answer": "A", "citations": ["x"], "retrieved_contexts": ["x"],
         "estimated_cost_usd": 0.001, "latency_seconds": 1.0},
    ])
    gold = _gold(items, chunks={"x": "stuff"})
    judge = _judge({"Q?": 1.0})
    with pytest.raises(ValueError, match="duplicate question_id"):
        score_rag(sub, gold, judge=judge)


def test_no_judge_supplied_raises() -> None:
    items = [{"question_id": "Q1", "question": "Q?", "expected_answer": "A",
              "relevant_chunk_ids": ["x"], "gold_citations": ["x"]}]
    sub = _submission([
        {"question_id": "Q1", "answer": "A", "citations": ["x"], "retrieved_contexts": ["x"],
         "estimated_cost_usd": 0.001, "latency_seconds": 1.0},
    ])
    gold = _gold(items, chunks={"x": "stuff"})
    with pytest.raises(ValueError, match="judge"):
        score_rag(sub, gold, judge=None)


def test_wrong_track_id_raises() -> None:
    sub = Submission.model_validate({
        "submission_id": "x", "student_id": "asukul",
        "track_id": "hallucination_hunter",
        "submission_timestamp": "2026-06-15T14:32:00Z",
        "track_payload": {"predictions": [{"claim_id": "C1", "label": "x"}]},
    })
    judge = _judge({})
    with pytest.raises(ValueError, match="rag_treasure_hunt"):
        score_rag(sub, _gold([]), judge=judge)


# ---------- Score result shape ----------

def test_result_carries_through_submission_metadata() -> None:
    items = [{"question_id": "Q1", "question": "Q?", "expected_answer": "A",
              "relevant_chunk_ids": ["x"], "gold_citations": ["x"]}]
    sub = _submission([{
        "question_id": "Q1", "answer": "A", "citations": ["x"],
        "retrieved_contexts": ["x"], "estimated_cost_usd": 0.005,
        "latency_seconds": 1.0,
    }])
    gold = _gold(items, chunks={"x": "stuff"})
    judge = _judge({"Q?": 1.0})
    result = score_rag(sub, gold, judge=judge)
    assert result.submission_id == "sub_test"
    assert result.student_id == "asukul"
    assert result.track_id == "rag_treasure_hunt"
