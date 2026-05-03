"""
Tests for the submission/result schemas. These tests are the contract for
what a valid student submission looks like — they double as documentation.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from api.schemas import (
    HallucinationPayload,
    MetaJudgePayload,
    PromptGolfPayload,
    RagPayload,
    ScoreDimension,
    ScoreResult,
    Submission,
)


# ---------- Helpers ----------

def _envelope(track_id: str, payload: dict) -> dict:
    return {
        "submission_id": "sub_d4_test_001",
        "student_id": "asukul",
        "track_id": track_id,
        "submission_timestamp": "2026-06-15T14:32:00Z",
        "model_used": "claude-haiku-4-5",
        "prompt_version": "v1",
        "self_reported_strategy": "test",
        "track_payload": payload,
    }


# ---------- Track 1 ----------

def test_hallucination_payload_happy_path() -> None:
    sub = Submission.model_validate(
        _envelope(
            "hallucination_hunter",
            {"predictions": [{"claim_id": "C001", "label": "supported"}]},
        )
    )
    assert isinstance(sub.track_payload, HallucinationPayload)
    assert sub.track_payload.predictions[0].label == "supported"


def test_hallucination_rejects_empty_predictions() -> None:
    with pytest.raises(ValidationError):
        Submission.model_validate(
            _envelope("hallucination_hunter", {"predictions": []})
        )


# ---------- Track 2 ----------

def test_prompt_golf_payload_happy_path() -> None:
    sub = Submission.model_validate(
        _envelope(
            "prompt_golf",
            {"prompt_template": "You are a {role}. Answer: {question}"},
        )
    )
    assert isinstance(sub.track_payload, PromptGolfPayload)
    assert "{role}" in sub.track_payload.prompt_template


def test_prompt_golf_rejects_empty_template() -> None:
    with pytest.raises(ValidationError):
        Submission.model_validate(
            _envelope("prompt_golf", {"prompt_template": ""})
        )


# ---------- Track 3 ----------

def test_rag_payload_happy_path_matches_spec_example() -> None:
    """The literal example from spec section 4 must validate cleanly."""
    sub = Submission.model_validate(
        _envelope(
            "rag_treasure_hunt",
            {
                "answers": [
                    {
                        "question_id": "Q001",
                        "answer": "Generated answer text here",
                        "citations": ["doc3_chunk12", "doc8_chunk2"],
                        "retrieved_contexts": ["doc3_chunk12", "doc1_chunk4"],
                        "estimated_cost_usd": 0.0042,
                        "latency_seconds": 3.8,
                    }
                ]
            },
        )
    )
    assert isinstance(sub.track_payload, RagPayload)
    answer = sub.track_payload.answers[0]
    assert answer.question_id == "Q001"
    assert answer.estimated_cost_usd == pytest.approx(0.0042)


def test_rag_rejects_negative_cost() -> None:
    with pytest.raises(ValidationError):
        Submission.model_validate(
            _envelope(
                "rag_treasure_hunt",
                {
                    "answers": [
                        {
                            "question_id": "Q1",
                            "answer": "x",
                            "estimated_cost_usd": -0.01,
                        }
                    ]
                },
            )
        )


# ---------- Track 4 ----------

def test_meta_judge_payload_happy_path() -> None:
    sub = Submission.model_validate(
        _envelope(
            "meta_judge",
            {
                "evaluator_source": "def grade(item):\n    return 1.0\n",
                "rubric_text": "Score 0..1 for correctness.",
            },
        )
    )
    assert isinstance(sub.track_payload, MetaJudgePayload)


# ---------- Cross-cutting envelope behavior ----------

def test_track_id_mismatch_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Submission.model_validate(
            {
                "submission_id": "s1",
                "student_id": "asukul",
                "track_id": "rag_treasure_hunt",
                "submission_timestamp": "2026-06-15T14:32:00Z",
                "track_payload": {
                    "kind": "hallucination_hunter",
                    "predictions": [{"claim_id": "C1", "label": "x"}],
                },
            }
        )


def test_unknown_track_id_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Submission.model_validate(
            _envelope("not_a_real_track", {"predictions": []})
        )


def test_extra_envelope_fields_are_rejected() -> None:
    """extra='forbid' protects against silently dropping unknown fields."""
    payload = _envelope(
        "hallucination_hunter",
        {"predictions": [{"claim_id": "C1", "label": "x"}]},
    )
    payload["sneaky_extra_field"] = "danger"
    with pytest.raises(ValidationError):
        Submission.model_validate(payload)


def test_timestamp_parses_iso_8601() -> None:
    sub = Submission.model_validate(
        _envelope(
            "hallucination_hunter",
            {"predictions": [{"claim_id": "C1", "label": "x"}]},
        )
    )
    assert isinstance(sub.submission_timestamp, datetime)
    assert sub.submission_timestamp.year == 2026


# ---------- ScoreResult ----------

def test_score_result_with_dimensions() -> None:
    result = ScoreResult(
        submission_id="s1",
        student_id="asukul",
        track_id="rag_treasure_hunt",
        final_score=0.78,
        dimensions=[
            ScoreDimension(name="correctness", weight=0.30, raw_score=0.85),
            ScoreDimension(name="faithfulness", weight=0.25, raw_score=0.70),
        ],
    )
    assert result.final_score == pytest.approx(0.78)
    assert len(result.dimensions) == 2


def test_score_result_rejects_out_of_range_final_score() -> None:
    with pytest.raises(ValidationError):
        ScoreResult(
            submission_id="s1",
            student_id="asukul",
            track_id="hallucination_hunter",
            final_score=1.5,
        )
