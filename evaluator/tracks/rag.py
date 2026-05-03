"""
Track 3 — RAG Treasure Hunt.

Per PLAN.md the headline rubric is:

  correctness 30 / faithfulness 25 / retrieval 15 / citations 15 / cost 10 / safety 5

The scorer reads (answer, citations, retrieved_contexts, estimated_cost_usd)
from the student's submission and computes the six dimensions per question,
then weighted-averages the per-dimension means across all questions.

Three dimensions need a Claude-as-judge call (correctness, faithfulness,
safety). The other three are computed locally:

  * retrieval = recall — how many of the gold-relevant chunks did the
    student's retriever surface? `|retrieved ∩ relevant| / |relevant|`
  * citations = F1 of cited chunk IDs against gold citations
  * cost = `min(1.0, baseline_cost / max(eps, student_cost))` — efficiency

Why no RAGAS dependency in v1: RAGAS pulls in transformers + datasets +
several other heavy dependencies, slows CI, and we'd be using it for the
same metrics this module computes in ~30 lines. RAGAS is the documented
Phase-2 swap target; the wire shape (per-dim scores → weighted mean)
matches RAGAS's output so the migration is a drop-in.

The judge is injected (FakeJudge in tests, real AnthropicJudge in prod).
Each judge call uses the dimension-specific system prompt from prompts/.
The user message starts with `[DIMENSION: <name>]` so test stubs can
disambiguate which dimension a given call is grading.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from api.schemas import (
    RagPayload,
    ScoreDimension,
    ScoreResult,
    Submission,
    TRACK_RAG,
)
from evaluator.judge import JudgeBackend
from evaluator.scoring import aggregate, normalize_weights


# Default rubric weights, used when the gold file omits a `weights` key.
_DEFAULT_WEIGHTS = {
    "correctness":  30,
    "faithfulness": 25,
    "retrieval":    15,
    "citations":    15,
    "cost":         10,
    "safety":        5,
}

# Floor for cost-efficiency division — guards against estimated_cost_usd=0.
_COST_EPS = 1e-6

_PROMPTS_DIR = Path(__file__).resolve().parent.parent.parent / "prompts"


def _load_prompt(name: str) -> str:
    return (_PROMPTS_DIR / name).read_text(encoding="utf-8")


# ---------- Local (non-judge) dimension math ----------

def _retrieval_recall(retrieved: set[str], relevant: set[str]) -> float:
    """Recall — fraction of gold-relevant chunks the student retrieved.

    No-relevant degenerate case is treated as full recall: if the gold
    has no opinion about which chunks should have been retrieved, we
    cannot fairly punish the student.
    """
    if not relevant:
        return 1.0
    return len(retrieved & relevant) / len(relevant)


def _citation_f1(cited: set[str], gold: set[str]) -> float:
    """F1 between the set of cited chunk IDs and the gold-citations set.

    No-citation-no-gold degenerate case is treated as 1.0 — there is
    nothing to grade against.
    """
    if not cited and not gold:
        return 1.0
    tp = len(cited & gold)
    fp = len(cited - gold)
    fn = len(gold - cited)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall    = tp / (tp + fn) if (tp + fn) else 0.0
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def _cost_efficiency(student_cost: float, baseline_cost: float) -> float:
    """`baseline / actual`, clamped to [0, 1].  Spending less than baseline
    saturates at 1.0 — we don't pay a bonus for racing toward $0."""
    return min(1.0, baseline_cost / max(_COST_EPS, student_cost))


# ---------- Judge user-message builders ----------

def _user_msg_correctness(question: str, expected: str, student_answer: str) -> str:
    return (
        "[DIMENSION: correctness]\n\n"
        f"QUESTION:\n{question}\n\n"
        f"GOLD REFERENCE ANSWER:\n{expected}\n\n"
        f"STUDENT'S ANSWER:\n{student_answer}\n"
    )


def _user_msg_faithfulness(question: str, contexts_text: list[str], student_answer: str) -> str:
    contexts_blob = "\n---\n".join(contexts_text) if contexts_text else "(no contexts provided)"
    return (
        "[DIMENSION: faithfulness]\n\n"
        f"QUESTION:\n{question}\n\n"
        f"RETRIEVED CONTEXTS:\n{contexts_blob}\n\n"
        f"STUDENT'S ANSWER:\n{student_answer}\n"
    )


def _user_msg_safety(question: str, student_answer: str) -> str:
    return (
        "[DIMENSION: safety]\n\n"
        f"QUESTION:\n{question}\n\n"
        f"STUDENT'S ANSWER:\n{student_answer}\n"
    )


# ---------- Main entrypoint ----------

def score_rag(
    submission: Submission,
    gold: Mapping[str, Any],
    *,
    judge: JudgeBackend | None,
) -> ScoreResult:
    """Score a RAG Treasure Hunt submission.

    Args:
        submission: Validated student submission. track_id must be 'rag_treasure_hunt'.
        gold: Mapping with keys:
            - 'items': list of {question_id, question, expected_answer,
                                relevant_chunk_ids, gold_citations}
            - 'chunks': optional dict[chunk_id → text] used to render
                        retrieved-context text for the faithfulness judge.
                        Missing entries fall back to the chunk_id literal.
            - 'baseline_cost_per_question_usd': baseline used for the cost
                        efficiency dimension (default 0.005 USD).
            - 'weights': optional override of the 30/25/15/15/10/5 rubric.
        judge: A JudgeBackend (real AnthropicJudge in prod, FakeJudge in tests).
            Required — three dimensions need it.

    Returns:
        ScoreResult with final_score = weighted mean of the six dimensions
        averaged across all questions.
    """
    if submission.track_id != TRACK_RAG:
        raise ValueError(
            f"score_rag called with track_id={submission.track_id!r}; "
            f"expected {TRACK_RAG!r}"
        )
    if judge is None:
        raise ValueError("score_rag requires a judge; got None")

    payload = submission.track_payload
    assert isinstance(payload, RagPayload)

    items = list(gold.get("items") or [])
    if not items:
        raise ValueError("gold for rag_treasure_hunt must contain at least one item")

    chunks: dict[str, str] = dict(gold.get("chunks") or {})
    baseline_cost = float(gold.get("baseline_cost_per_question_usd", 0.005))
    weights = dict(gold.get("weights") or _DEFAULT_WEIGHTS)

    items_by_qid = {it["question_id"]: it for it in items}

    answer_qids = [a.question_id for a in payload.answers]
    duplicates = [k for k, n in Counter(answer_qids).items() if n > 1]
    if duplicates:
        raise ValueError(f"duplicate question_id(s) in answers: {sorted(duplicates)}")
    answer_set = set(answer_qids)
    gold_set = set(items_by_qid)
    unknown = answer_set - gold_set
    missing = gold_set - answer_set
    if unknown:
        raise ValueError(f"unknown question_id(s) in answers: {sorted(unknown)}")
    if missing:
        raise ValueError(f"missing answers for question_id(s): {sorted(missing)}")

    sys_correctness  = _load_prompt("judge_correctness.txt")
    sys_faithfulness = _load_prompt("judge_faithfulness.txt")
    sys_safety       = _load_prompt("judge_safety.txt")

    # Per-dimension running sums (averaged at the end).
    sums = {k: 0.0 for k in _DEFAULT_WEIGHTS}
    judge_tokens_in = 0
    judge_tokens_out = 0
    per_question: list[dict[str, Any]] = []

    for ans in payload.answers:
        item = items_by_qid[ans.question_id]
        question = item["question"]
        expected = item["expected_answer"]
        relevant = set(item.get("relevant_chunk_ids") or [])
        gold_citations = set(item.get("gold_citations") or [])

        # Local (math) dimensions.
        retrieved_ids = set(ans.retrieved_contexts)
        cited_ids = set(ans.citations)
        retrieval = _retrieval_recall(retrieved_ids, relevant)
        citations = _citation_f1(cited_ids, gold_citations)
        cost = _cost_efficiency(ans.estimated_cost_usd, baseline_cost)

        # Judge dimensions.
        retrieved_texts = [chunks.get(cid, cid) for cid in ans.retrieved_contexts]
        r_correct = judge.call(system=sys_correctness,
                               user=_user_msg_correctness(question, expected, ans.answer))
        r_faithful = judge.call(system=sys_faithfulness,
                                user=_user_msg_faithfulness(question, retrieved_texts, ans.answer))
        r_safe = judge.call(system=sys_safety,
                            user=_user_msg_safety(question, ans.answer))
        for r in (r_correct, r_faithful, r_safe):
            judge_tokens_in += r.tokens_in
            judge_tokens_out += r.tokens_out

        per_q = {
            "question_id":  ans.question_id,
            "correctness":  round(r_correct.score, 6),
            "faithfulness": round(r_faithful.score, 6),
            "retrieval":    round(retrieval, 6),
            "citations":    round(citations, 6),
            "cost":         round(cost, 6),
            "safety":       round(r_safe.score, 6),
        }
        per_question.append(per_q)

        sums["correctness"]  += r_correct.score
        sums["faithfulness"] += r_faithful.score
        sums["retrieval"]    += retrieval
        sums["citations"]    += citations
        sums["cost"]         += cost
        sums["safety"]       += r_safe.score

    n = len(payload.answers)
    avgs = {k: sums[k] / n for k in sums}

    dims = [
        ScoreDimension(
            name=name,
            weight=float(weights.get(name, _DEFAULT_WEIGHTS[name])),
            raw_score=round(max(0.0, min(1.0, avgs[name])), 6),
        )
        for name in _DEFAULT_WEIGHTS
    ]

    final = aggregate(normalize_weights(dims))

    return ScoreResult(
        submission_id=submission.submission_id,
        student_id=submission.student_id,
        track_id=TRACK_RAG,
        final_score=round(max(0.0, min(1.0, final)), 6),
        dimensions=dims,
        judge_metadata={
            "n_questions":         n,
            "per_dimension_avg":   {k: round(v, 6) for k, v in avgs.items()},
            "weights_normalized":  {d.name: round(d.weight, 6) for d in normalize_weights(dims)},
            "baseline_cost_usd":   baseline_cost,
            "judge_tokens_in":     judge_tokens_in,
            "judge_tokens_out":    judge_tokens_out,
            "per_question":        per_question,
        },
    )
