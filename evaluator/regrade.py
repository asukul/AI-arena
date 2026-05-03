"""
Cross-family re-grade pass (Day 4 deliverable per PLAN.md).

Single-judge pipelines have a known weakness: judges from one model family
can systematically over- or under-grade in ways that aren't visible until
something independent compares them. AI Arena's primary judge is Claude
Haiku 4.5; this module re-scores the top 10% of each track's leaderboard
with a second judge (Gemini Flash in production), and flags any
submission where the two judges disagree by more than the threshold so an
instructor can take a manual look.

The module deliberately knows nothing about which model families back the
two judges — it just takes two `JudgeBackend` instances. Tests use
`FakeJudge` for both. A `GeminiJudge` adapter is provided as a thin
optional shim; the `google-genai` SDK is imported lazily so this module
loads cleanly without it.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from typing import Any, Iterable

from evaluator.judge import JudgeBackend, JudgeResponse


_DEFAULT_MODEL_GEMINI = "gemini-2.5-flash"


@dataclass(frozen=True)
class Disagreement:
    """One leaderboard entry where primary and secondary judges disagree."""
    submission_id: str
    student_id: str
    primary_score: float
    secondary_score: float
    delta: float          # signed: primary - secondary

    def needs_review(self, threshold: float) -> bool:
        return abs(self.delta) > threshold


@dataclass(frozen=True)
class RegradeOptions:
    """Knobs for the re-grade pass."""
    top_pct: float = 10.0     # re-grade the top N percent by primary score
    threshold: float = 0.10   # flag if |primary - secondary| exceeds this


# ---------- Selection ----------

def select_top_n_pct(entries: list[dict], *, pct: float) -> list[dict]:
    """Return the top `pct` percent of `entries` by `final_score` desc.

    Empty in → empty out. Always returns at least one entry when the input
    is non-empty (so a tiny leaderboard still gets a sanity check).

    Rounding: ceiling — we'd rather re-grade one extra submission than
    miss a borderline case.
    """
    if not entries:
        return []
    sorted_entries = sorted(entries, key=lambda e: e["final_score"], reverse=True)
    n = max(1, math.ceil(len(sorted_entries) * pct / 100.0))
    return sorted_entries[:n]


# ---------- Re-grade pass ----------

def cross_family_regrade(
    entries: list[dict],
    *,
    secondary_judge: JudgeBackend,
    options: RegradeOptions | None = None,
) -> list[Disagreement]:
    """Re-grade the top slice of `entries` with `secondary_judge`.

    Args:
        entries: Leaderboard slice as returned by `/leaderboard/{track}`.
            Each entry must include `submission_id`, `student_id`,
            `final_score`, and a `judge_metadata` dict carrying the
            `system_msg` + `user_msg` that produced the primary score
            (so the secondary judge sees the same prompts).
        secondary_judge: A JudgeBackend from a different model family.
        options: Selection / threshold knobs. Defaults to top 10% / Δ > 0.10.

    Returns:
        Disagreements where |primary - secondary| > threshold, ordered by
        the entry's primary rank (highest first).
    """
    opts = options or RegradeOptions()
    top = select_top_n_pct(entries, pct=opts.top_pct)
    flagged: list[Disagreement] = []
    for entry in top:
        meta = entry.get("judge_metadata") or {}
        system_msg = meta.get("system_msg", "")
        user_msg = meta.get("user_msg", "")
        secondary = secondary_judge.call(system=system_msg, user=user_msg)
        d = Disagreement(
            submission_id=entry["submission_id"],
            student_id=entry["student_id"],
            primary_score=float(entry["final_score"]),
            secondary_score=float(secondary.score),
            delta=float(entry["final_score"]) - float(secondary.score),
        )
        if d.needs_review(opts.threshold):
            flagged.append(d)
    return flagged


# ---------- Optional Gemini adapter ----------

class GeminiJudge:
    """Optional secondary-judge adapter wrapping the Gemini API.

    The `google-genai` SDK is imported lazily so this module is importable
    in environments where the dependency isn't installed (CI, local-dev
    without GCP creds). Tests use `FakeJudge` instead of constructing
    this class.

    Env: `GEMINI_API_KEY` (or `GOOGLE_API_KEY`). Pass `api_key=` to override.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = _DEFAULT_MODEL_GEMINI,
        max_output_tokens: int = 1024,
    ) -> None:
        self._api_key = (
            api_key
            or os.environ.get("GEMINI_API_KEY")
            or os.environ.get("GOOGLE_API_KEY", "")
        )
        self._model = model
        self._max_output_tokens = max_output_tokens
        self._client: Any | None = None

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                from google import genai  # lazy import — keeps dep optional
            except ImportError as exc:
                raise RuntimeError(
                    "google-genai SDK not installed. Add `google-genai` to "
                    "requirements.txt and reinstall to enable GeminiJudge."
                ) from exc
            if not self._api_key:
                raise RuntimeError(
                    "GEMINI_API_KEY (or GOOGLE_API_KEY) not set; cannot "
                    "construct GeminiJudge."
                )
            self._client = genai.Client(api_key=self._api_key)
        return self._client

    def call(
        self,
        *,
        system: str,
        user: str,
        model: str | None = None,
    ) -> JudgeResponse:
        from evaluator.judge import _parse_score  # reuse the same parser

        client = self._get_client()
        chosen_model = model or self._model
        # Gemini puts the system prompt as a `system_instruction` config
        # rather than a chat-message role.
        response = client.models.generate_content(
            model=chosen_model,
            contents=user,
            config={
                "system_instruction": system,
                "temperature": 0,
                "max_output_tokens": self._max_output_tokens,
            },
        )
        raw = response.text or ""
        score, reasoning = _parse_score(raw)
        usage = getattr(response, "usage_metadata", None)
        tokens_in = int(getattr(usage, "prompt_token_count", 0) or 0)
        tokens_out = int(getattr(usage, "candidates_token_count", 0) or 0)
        return JudgeResponse(
            score=score,
            reasoning=reasoning,
            raw_text=raw,
            model=chosen_model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
        )


def iter_disagreements(
    flagged: Iterable[Disagreement], *, threshold: float
) -> list[Disagreement]:
    """Filter helper for downstream callers (Cloud Scheduler nightly job)."""
    return [d for d in flagged if d.needs_review(threshold)]
