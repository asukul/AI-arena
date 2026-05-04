"""
Canonical sample submission payloads — one per track.

Served by `GET /samples/{track_id}` and embedded in the Get Started page so
students always see a real, runnable example. Each sample is built so that
posting it to `/submit` (with a fresh `submission_id`) produces a perfect
score against the in-tree gold data — that gives students a known-good
starting point they can then mutate to learn the scoring rules.

Add a new track:
  1. Build a sample dict that aligns with the gold file at
     corpora/gold/<track_id>.json (so a fresh submit lands a 1.0).
  2. Add it to SAMPLE_PAYLOADS keyed by the TRACK_* constant.
  3. The /samples/{track_id} route picks it up automatically.
"""

from __future__ import annotations

from typing import Any

from api.schemas import (
    TRACK_HALLUCINATION,
    TRACK_META_JUDGE,
    TRACK_PROMPT_GOLF,
    TRACK_RAG,
)


# ---------- Track 1 — Hallucination Hunter ----------

SAMPLE_HALLUCINATION: dict[str, Any] = {
    "submission_id": "REPLACE_ME_with_unique_id",
    "student_id": "REPLACE_ME_with_your_id",
    "track_id": TRACK_HALLUCINATION,
    "submission_timestamp": "2026-06-15T14:32:00Z",
    "model_used": "claude-haiku-4-5",
    "prompt_version": "v1",
    "self_reported_strategy": "Few-shot prompt with 3 examples",
    "track_payload": {
        "predictions": [
            {"claim_id": "C001", "label": "supported"},
            {"claim_id": "C002", "label": "refuted"},
            {"claim_id": "C003", "label": "not_enough_info"},
            {"claim_id": "C004", "label": "supported"},
            {"claim_id": "C005", "label": "refuted"},
        ],
    },
}


# ---------- Track 2 — Prompt Golf ----------

SAMPLE_PROMPT_GOLF: dict[str, Any] = {
    "submission_id": "REPLACE_ME_with_unique_id",
    "student_id": "REPLACE_ME_with_your_id",
    "track_id": TRACK_PROMPT_GOLF,
    "submission_timestamp": "2026-06-15T14:32:00Z",
    "model_used": "claude-haiku-4-5",
    "prompt_version": "v1",
    "self_reported_strategy": "One-shot, terse system prompt",
    "track_payload": {
        "prompt_template": "Answer concisely:",
        "samples": [
            {"input": "What is 2+2?",          "output": "4"},
            {"input": "Capital of France?",     "output": "Paris"},
            {"input": "Who wrote 'Hamlet'?",    "output": "William Shakespeare"},
        ],
    },
}


# ---------- Track 3 — RAG Treasure Hunt ----------

SAMPLE_RAG: dict[str, Any] = {
    "submission_id": "REPLACE_ME_with_unique_id",
    "student_id": "REPLACE_ME_with_your_id",
    "track_id": TRACK_RAG,
    "submission_timestamp": "2026-06-15T14:32:00Z",
    "model_used": "claude-haiku-4-5",
    "prompt_version": "v1",
    "self_reported_strategy": "Hybrid BM25 + dense retrieval, top-3 chunks per question",
    "track_payload": {
        "answers": [
            {
                "question_id": "Q001",
                "answer": (
                    "CS 2010 is Introduction to Computer Science using Python. "
                    "It covers computational thinking with no prior programming "
                    "experience required. Prerequisites: none."
                ),
                "citations":          ["cs2010_c1", "cs2010_c2"],
                "retrieved_contexts": ["cs2010_c1", "cs2010_c2"],
                "estimated_cost_usd": 0.0040,
                "latency_seconds":    1.8,
            },
            {
                "question_id": "Q002",
                "answer": (
                    "CS 2280 (Introduction to Data Structures) requires CS 2010 "
                    "with a grade of C- or better. It is three credit hours."
                ),
                "citations":          ["cs2280_c2"],
                "retrieved_contexts": ["cs2280_c1", "cs2280_c2"],
                "estimated_cost_usd": 0.0035,
                "latency_seconds":    1.6,
            },
            {
                "question_id": "Q003",
                "answer": (
                    "DS 2010 covers the data analysis pipeline (collection, "
                    "cleaning, exploratory analysis with pandas, visualization, "
                    "and an intro to scikit-learn). Required statistics "
                    "prerequisite: STAT 1010 or STAT 1040."
                ),
                "citations":          ["ds2010_c1", "ds2010_c2"],
                "retrieved_contexts": ["ds2010_c1", "ds2010_c2"],
                "estimated_cost_usd": 0.0045,
                "latency_seconds":    1.9,
            },
            {
                "question_id": "Q004",
                "answer": (
                    "AI 2010 is offered in the Spring semester only. "
                    "Prerequisite: CS 2280 (data structures) or DS 2010 "
                    "(intro to data science)."
                ),
                "citations":          ["ai2010_c2"],
                "retrieved_contexts": ["ai2010_c1", "ai2010_c2"],
                "estimated_cost_usd": 0.0038,
                "latency_seconds":    1.7,
            },
            {
                "question_id": "Q005",
                "answer": (
                    "Default late-work policy is a 10% deduction per day late, "
                    "capped at 50%. Extensions are granted for documented "
                    "medical or family emergencies on request to the instructor."
                ),
                "citations":          ["policy_c2"],
                "retrieved_contexts": ["policy_c1", "policy_c2"],
                "estimated_cost_usd": 0.0030,
                "latency_seconds":    1.4,
            },
        ],
    },
}


# ---------- Track 4 — Build Your Own AI Judge ----------

SAMPLE_META_JUDGE: dict[str, Any] = {
    "submission_id": "REPLACE_ME_with_unique_id",
    "student_id": "REPLACE_ME_with_your_id",
    "track_id": TRACK_META_JUDGE,
    "submission_timestamp": "2026-06-15T14:32:00Z",
    "self_reported_strategy": "Rubric grades length + keyword presence on a 1-5 scale",
    "track_payload": {
        "evaluator_source": (
            "def grade(item: dict) -> int:\n"
            "    \"\"\"Return a 1-5 ordinal rating.\"\"\"\n"
            "    text = item['response'].lower()\n"
            "    if not text.strip():\n"
            "        return 1\n"
            "    keyword_hits = sum(1 for k in item['keywords'] if k.lower() in text)\n"
            "    base = max(1, min(5, keyword_hits))\n"
            "    return base\n"
        ),
        "rubric_text": (
            "Score each response on a 1-5 ordinal scale:\n"
            "  5 = answers correctly and cites all relevant sources.\n"
            "  4 = answers correctly with minor omissions.\n"
            "  3 = partially correct or missing a citation.\n"
            "  2 = mostly wrong but on-topic.\n"
            "  1 = irrelevant, empty, or harmful.\n"
        ),
        "self_grades": [
            {"item_id": "i01", "score": 5},
            {"item_id": "i02", "score": 4},
            {"item_id": "i03", "score": 3},
            {"item_id": "i04", "score": 2},
            {"item_id": "i05", "score": 1},
            {"item_id": "i06", "score": 5},
            {"item_id": "i07", "score": 4},
            {"item_id": "i08", "score": 3},
            {"item_id": "i09", "score": 2},
            {"item_id": "i10", "score": 1},
        ],
    },
}


# ---------- Public dispatch table ----------

SAMPLE_PAYLOADS: dict[str, dict[str, Any]] = {
    TRACK_HALLUCINATION: SAMPLE_HALLUCINATION,
    TRACK_PROMPT_GOLF:   SAMPLE_PROMPT_GOLF,
    TRACK_RAG:           SAMPLE_RAG,
    TRACK_META_JUDGE:    SAMPLE_META_JUDGE,
}
