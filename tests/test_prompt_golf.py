"""
Track 2 — Prompt Golf. judge_accuracy / total_tokens (higher is better).

Mirrors the test layout from the other tracks: happy path, empty / boundary,
malformed, edge case at scoring boundary. Judge calls are stubbed via FakeJudge
so the suite never hits the real Anthropic API.
"""

from __future__ import annotations

import pytest

from api.schemas import Submission
from evaluator.judge import FakeJudge, JudgeResponse
from evaluator.tracks.prompt_golf import (
    _estimate_tokens,
    score_prompt_golf,
)


# ---------- Helpers ----------

def _submission(
    prompt_template: str,
    samples: list[tuple[str, str]],
) -> Submission:
    return Submission.model_validate(
        {
            "submission_id": "sub_test",
            "student_id": "asukul",
            "track_id": "prompt_golf",
            "submission_timestamp": "2026-06-15T14:32:00Z",
            "track_payload": {
                "prompt_template": prompt_template,
                "samples": [
                    {"input": inp, "output": out} for inp, out in samples
                ],
            },
        }
    )


def _judge_returning(scores_by_substring: dict[str, float]) -> FakeJudge:
    """Build a FakeJudge that emits a given score whenever a substring appears
    in the user message. Token counts are fixed-and-small so they don't dominate
    the efficiency component in the metric."""
    fake = FakeJudge()
    for needle, score in scores_by_substring.items():
        fake.add(
            needle,
            JudgeResponse(
                score=score,
                reasoning=f"score={score}",
                raw_text=f'{{"score": {score}, "reasoning": "..."}}',
                model="fake-haiku",
                tokens_in=10,
                tokens_out=5,
            ),
        )
    return fake


def _gold(items: list[tuple[str, str]], baseline_tokens_per_sample: int = 200) -> dict:
    return {
        "items": [
            {"input": inp, "expected_output": exp} for inp, exp in items
        ],
        "baseline_tokens_per_sample": baseline_tokens_per_sample,
    }


# ---------- _estimate_tokens ----------

def test_token_estimate_is_roughly_chars_over_four() -> None:
    # ~4 chars per token is the standard English rule-of-thumb. A 400-char
    # string should land around 100 tokens.
    assert 90 <= _estimate_tokens("x" * 400) <= 110


def test_token_estimate_floor_is_one_for_nonempty() -> None:
    assert _estimate_tokens("hi") >= 1
    assert _estimate_tokens("") == 0


# ---------- Happy paths ----------

def test_perfect_judges_at_baseline_tokens_score_one() -> None:
    """Judge returns 1.0 for every sample, prompt+output uses exactly the
    baseline budget, so final_score should pin at 1.0."""
    gold = _gold(
        [("What is 2+2?", "4"), ("Capital of France?", "Paris")],
        baseline_tokens_per_sample=60,  # tuned so the test data hits ~baseline
    )
    sub = _submission(
        prompt_template="Answer concisely:",
        samples=[("What is 2+2?", "4"), ("Capital of France?", "Paris")],
    )
    judge = _judge_returning({"What is 2+2?": 1.0, "Capital of France?": 1.0})
    result = score_prompt_golf(sub, gold, judge=judge)
    assert result.final_score == pytest.approx(1.0)
    assert result.judge_metadata["judge_accuracy"] == pytest.approx(1.0)


def test_efficient_prompt_beats_verbose_one_at_same_accuracy() -> None:
    # Tight baseline so the verbose template breaks past it and the clamp
    # doesn't hide the difference.
    gold = _gold(
        [("What is 2+2?", "4"), ("Capital of France?", "Paris")],
        baseline_tokens_per_sample=20,
    )
    judge = _judge_returning({"What is 2+2?": 1.0, "Capital of France?": 1.0})

    short = _submission("Answer:", [("What is 2+2?", "4"), ("Capital of France?", "Paris")])
    long_ = _submission(
        "Please answer the following question with as much care as possible "
        "and provide your best answer in a single concise word or phrase " * 4,
        [("What is 2+2?", "4"), ("Capital of France?", "Paris")],
    )

    short_score = score_prompt_golf(short, gold, judge=judge).final_score
    long_score = score_prompt_golf(long_, gold, judge=judge).final_score

    assert short_score > long_score, "shorter prompt at same accuracy should win"


def test_partial_judge_scores_propagate_to_accuracy() -> None:
    gold = _gold([("Q1", "A1"), ("Q2", "A2"), ("Q3", "A3")], baseline_tokens_per_sample=50)
    sub = _submission("Answer:", [("Q1", "A1"), ("Q2", "WRONG"), ("Q3", "A3")])
    judge = _judge_returning({"Q1": 1.0, "Q2": 0.0, "Q3": 1.0})
    result = score_prompt_golf(sub, gold, judge=judge)
    assert result.judge_metadata["judge_accuracy"] == pytest.approx(2.0 / 3.0, abs=1e-6)


def test_one_judge_call_per_sample() -> None:
    gold = _gold([("Q1", "A1"), ("Q2", "A2"), ("Q3", "A3")])
    sub = _submission("Answer:", [("Q1", "A1"), ("Q2", "A2"), ("Q3", "A3")])
    judge = _judge_returning({"Q1": 1.0, "Q2": 1.0, "Q3": 1.0})
    score_prompt_golf(sub, gold, judge=judge)
    assert len(judge.calls) == 3


def test_judge_metadata_includes_per_sample_scores() -> None:
    gold = _gold([("Q1", "A1"), ("Q2", "A2")], baseline_tokens_per_sample=50)
    sub = _submission("Answer:", [("Q1", "A1"), ("Q2", "WRONG")])
    judge = _judge_returning({"Q1": 0.9, "Q2": 0.1})
    result = score_prompt_golf(sub, gold, judge=judge)
    per_sample = result.judge_metadata["per_sample"]
    assert {p["input"]: p["score"] for p in per_sample} == {"Q1": 0.9, "Q2": 0.1}


# ---------- Boundary / numeric edges ----------

def test_minimal_inputs_do_not_crash() -> None:
    """Smallest inputs the schema permits (1-char strings everywhere) should
    score without dividing by zero or producing NaN."""
    gold = _gold([("a", "b")], baseline_tokens_per_sample=50)
    sub = _submission("p", [("a", "b")])
    judge = _judge_returning({"a": 1.0})
    result = score_prompt_golf(sub, gold, judge=judge)
    assert 0.0 <= result.final_score <= 1.0


def test_efficiency_clamps_when_below_baseline() -> None:
    """Spending fewer tokens than baseline shouldn't push final_score above
    judge_accuracy — that would invite degenerate one-word prompts."""
    gold = _gold([("Q1", "A1")], baseline_tokens_per_sample=10_000)  # huge baseline
    sub = _submission("Answer:", [("Q1", "A1")])
    judge = _judge_returning({"Q1": 0.5})
    result = score_prompt_golf(sub, gold, judge=judge)
    assert result.final_score == pytest.approx(0.5)


def test_efficiency_penalizes_when_above_baseline() -> None:
    """Spending much more than baseline should drag the score down even at
    perfect accuracy."""
    gold = _gold([("Q1", "A1")], baseline_tokens_per_sample=50)
    sub = _submission("Answer: " + ("x " * 500), [("Q1", "A1")])  # huge prompt
    judge = _judge_returning({"Q1": 1.0})
    result = score_prompt_golf(sub, gold, judge=judge)
    assert result.final_score < 0.5


# ---------- Malformed input ----------

def test_missing_samples_raise() -> None:
    gold = _gold([("Q1", "A1"), ("Q2", "A2")])
    sub = _submission("Answer:", [("Q1", "A1")])  # missing Q2
    judge = _judge_returning({"Q1": 1.0})
    with pytest.raises(ValueError, match="missing samples"):
        score_prompt_golf(sub, gold, judge=judge)


def test_unknown_input_raises() -> None:
    gold = _gold([("Q1", "A1")])
    sub = _submission("Answer:", [("Q1", "A1"), ("Q_PHANTOM", "X")])
    judge = _judge_returning({"Q1": 1.0, "Q_PHANTOM": 1.0})
    with pytest.raises(ValueError, match="unknown sample input"):
        score_prompt_golf(sub, gold, judge=judge)


def test_duplicate_sample_input_raises() -> None:
    gold = _gold([("Q1", "A1"), ("Q2", "A2")])
    sub = _submission("Answer:", [("Q1", "A1"), ("Q1", "A1"), ("Q2", "A2")])
    judge = _judge_returning({"Q1": 1.0, "Q2": 1.0})
    with pytest.raises(ValueError, match="duplicate sample input"):
        score_prompt_golf(sub, gold, judge=judge)


def test_wrong_track_id_raises() -> None:
    sub = Submission.model_validate(
        {
            "submission_id": "sub_x",
            "student_id": "asukul",
            "track_id": "hallucination_hunter",
            "submission_timestamp": "2026-06-15T14:32:00Z",
            "track_payload": {"predictions": [{"claim_id": "C1", "label": "x"}]},
        }
    )
    judge = _judge_returning({})
    with pytest.raises(ValueError, match="prompt_golf"):
        score_prompt_golf(sub, _gold([("Q1", "A1")]), judge=judge)


def test_no_judge_supplied_raises() -> None:
    sub = _submission("Answer:", [("Q1", "A1")])
    with pytest.raises(ValueError, match="judge"):
        score_prompt_golf(sub, _gold([("Q1", "A1")]), judge=None)


# ---------- Score result shape ----------

def test_result_carries_through_submission_metadata() -> None:
    gold = _gold([("Q1", "A1")], baseline_tokens_per_sample=50)
    sub = _submission("Answer:", [("Q1", "A1")])
    judge = _judge_returning({"Q1": 1.0})
    result = score_prompt_golf(sub, gold, judge=judge)
    assert result.submission_id == "sub_test"
    assert result.student_id == "asukul"
    assert result.track_id == "prompt_golf"
    assert result.dimensions[0].name == "judge_accuracy_per_token"
