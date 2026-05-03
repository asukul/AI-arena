"""Tests for the judge wrapper — score parsing and the FakeJudge stub."""

from __future__ import annotations

from evaluator.judge import FakeJudge, JudgeResponse, _parse_score


# ---------- _parse_score ----------

def test_parses_clean_json() -> None:
    score, reasoning = _parse_score('{"score": 0.85, "reasoning": "Looks good."}')
    assert score == 0.85
    assert reasoning == "Looks good."


def test_parses_json_in_code_fence() -> None:
    text = '```json\n{"score": 0.42, "reasoning": "Mostly off."}\n```'
    score, reasoning = _parse_score(text)
    assert score == 0.42
    assert reasoning == "Mostly off."


def test_parses_json_with_prose_fallback() -> None:
    """If model wraps JSON in prose, regex still extracts the score."""
    text = 'Here is my evaluation: {"score": 0.7, "reasoning": "Close."}'
    score, _ = _parse_score(text)
    assert score == 0.7


def test_clamps_above_one() -> None:
    score, _ = _parse_score('{"score": 1.5}')
    assert score == 1.0


def test_clamps_below_zero() -> None:
    score, _ = _parse_score('{"score": -0.3}')
    assert score == 0.0


def test_unparseable_returns_zero() -> None:
    score, raw = _parse_score("the model went off-rails entirely")
    assert score == 0.0
    assert raw == "the model went off-rails entirely"


# ---------- FakeJudge ----------

def test_fake_judge_returns_canned_response_on_substring_match() -> None:
    fake = FakeJudge()
    fake.add("question 7", JudgeResponse(
        score=0.9, reasoning="seven", raw_text="...",
        model="fake", tokens_in=5, tokens_out=2,
    ))
    response = fake.call(system="rubric", user="The answer to question 7 is X.")
    assert response.score == 0.9
    assert response.reasoning == "seven"


def test_fake_judge_default_when_no_match() -> None:
    fake = FakeJudge()
    response = fake.call(system="rubric", user="anything else")
    assert response.score == 0.5
    assert response.tokens_in == 20


def test_fake_judge_records_calls_for_assertion() -> None:
    fake = FakeJudge()
    fake.call(system="sys", user="user1")
    fake.call(system="sys", user="user2", model="claude-opus-4-7")
    assert len(fake.calls) == 2
    assert fake.calls[1]["model"] == "claude-opus-4-7"
