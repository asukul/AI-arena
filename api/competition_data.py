"""
Per-track metadata — single source of truth for the public-facing UI.

Both the landing card grid (`api/landing.py`) and the per-track competition
shell (`api/competition.py`) read from `TRACKS_META` so a track's name,
metric, sample payload, public data files, and rules are described in one
place. The Get Started page (`api/get_started.py`) also pulls from here.

Adding or renaming a track is a one-file change: append a `TrackMeta` to
`TRACKS_META`, ensure a sample exists in `api.sample_payloads.SAMPLE_PAYLOADS`
keyed by the same `id`, and ensure a gold file exists at
`corpora/gold/<id>.json` so the seed sample scores 1.0.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from api.sample_payloads import SAMPLE_PAYLOADS
from api.schemas import (
    TRACK_HALLUCINATION,
    TRACK_META_JUDGE,
    TRACK_PROMPT_GOLF,
    TRACK_RAG,
)


@dataclass(frozen=True)
class DataFile:
    name: str
    purpose: str
    public: bool = True
    href: str | None = None


@dataclass(frozen=True)
class TrackMeta:
    id: str
    number: int
    name: str
    tagline: str
    accent: str          # CSS color used for the track's accent in the card grid + header
    metric_label: str    # short label, fits in a pill
    metric_formula: str  # one-line formula (HTML allowed)
    metric_explainer: str  # 2-3 sentence prose explanation (HTML allowed)
    what_to_submit: str  # HTML-safe (uses <code> tags)
    description: str     # Overview-tab body — multi-paragraph HTML
    tips: list[str]
    data_files: list[DataFile]
    judge_tokens_per_day: int      # 0 if track doesn't call the judge
    rate_limit_per_day: int = 5    # current platform default; overrides per-track if needed

    @property
    def sample(self) -> dict[str, Any]:
        return SAMPLE_PAYLOADS[self.id]


# ---------- Track metadata ----------

# Each .description block is rendered verbatim into the Overview tab. Use
# semantic HTML (<p>, <ul>, <strong>) — no raw text. Keep it readable end
# to end in under five minutes.

_T1 = TrackMeta(
    id=TRACK_HALLUCINATION,
    number=1,
    name="Hallucination Hunter",
    tagline="Classify each claim as supported, refuted, or not_enough_info against a hidden gold set.",
    accent="#5cd1ff",
    metric_label="macro-F1",
    metric_formula="(F1<sub>supported</sub> + F1<sub>refuted</sub> + F1<sub>not_enough_info</sub>) / 3",
    metric_explainer=(
        "Macro-F1 weights every label equally. Under-predicting the rare "
        "<code>not_enough_info</code> class drags your score down even if "
        "your overall accuracy looks high &mdash; predict each class honestly."
    ),
    what_to_submit=(
        "A list of <code>(claim_id, label)</code> pairs covering every claim "
        "in the test set. Labels must be one of "
        "<code>supported</code>, <code>refuted</code>, or "
        "<code>not_enough_info</code>."
    ),
    description=(
        "<p>You're given a small batch of claims. For each one, decide whether "
        "the source documents <em>support</em> it, <em>refute</em> it, or whether "
        "there's <em>not enough info</em> to tell. The hidden test set has "
        "balanced labels &mdash; predicting one class for everything will not "
        "score well.</p>"
        "<p>This track validates the whole submission &rarr; queue &rarr; "
        "score &rarr; leaderboard pipeline using simple classification, with "
        "no LLM judge in the loop. It's the cheapest track to iterate on.</p>"
    ),
    tips=[
        "Every <code>claim_id</code> in the gold set must appear exactly once.",
        "Unknown labels (e.g. \"maybe\") count as wrong and don't get their own class.",
        "Schema rejects empty <code>predictions</code> arrays &mdash; submit at least one.",
    ],
    data_files=[
        DataFile(
            name="sample_submission.json",
            purpose="Canonical example payload that scores 1.0 against the in-tree gold set.",
            href="/samples/hallucination_hunter",
        ),
    ],
    judge_tokens_per_day=0,
)

_T2 = TrackMeta(
    id=TRACK_PROMPT_GOLF,
    number=2,
    name="Prompt Golf",
    tagline="Find the shortest prompt that still answers correctly.",
    accent="#a6e8b6",
    metric_label="judge accuracy &times; token efficiency",
    metric_formula=(
        "<code>mean(judge_score) &times; min(1, baseline_tokens / total_tokens)</code>"
    ),
    metric_explainer=(
        "Each sample is judged for correctness against the hidden gold answer. "
        "Your score is the average judge score, then multiplied by token efficiency. "
        "Efficiency saturates at 1.0, so accuracy is always the ceiling &mdash; a "
        "short prompt that scores 0.8 beats a long prompt that scores 0.8."
    ),
    what_to_submit=(
        "Your <code>prompt_template</code> plus the <code>(input, output)</code> "
        "samples it produced when you ran it against the gold inputs. Each "
        "<code>input</code> must match a gold question exactly."
    ),
    description=(
        "<p>You're given a set of gold questions. Write the shortest prompt "
        "that still produces correct answers for each one. Submit the "
        "prompt template plus the (input, output) samples it generated.</p>"
        "<p>The judge grades each output against the hidden gold answer. "
        "Your token budget includes both the prompt tokens and the model's "
        "completion tokens, so concision compounds.</p>"
    ),
    tips=[
        "All gold inputs must be covered. Missing samples raise a clean error.",
        "Token count is approximated as <code>chars / 4</code> per the standard rule of thumb.",
        "You have a 50,000-judge-tokens-per-day cap across all submissions.",
    ],
    data_files=[
        DataFile(
            name="sample_submission.json",
            purpose="Canonical example payload that scores 1.0 against the in-tree gold set.",
            href="/samples/prompt_golf",
        ),
    ],
    judge_tokens_per_day=50000,
)

_T3 = TrackMeta(
    id=TRACK_RAG,
    number=3,
    name="RAG Treasure Hunt",
    tagline="Build a retrieval pipeline over the ISU course catalog.",
    accent="#ffc107",
    metric_label="weighted rubric (30 / 25 / 15 / 15 / 10 / 5)",
    metric_formula=(
        "0.30 &middot; correctness "
        "+ 0.25 &middot; faithfulness "
        "+ 0.15 &middot; retrieval "
        "+ 0.15 &middot; citations "
        "+ 0.10 &middot; cost "
        "+ 0.05 &middot; safety"
    ),
    metric_explainer=(
        "Six dimensions per question, weighted-averaged. <strong>Correctness</strong>, "
        "<strong>faithfulness</strong>, and <strong>safety</strong> are LLM-judged. "
        "<strong>Retrieval</strong> is recall against gold-relevant chunks. "
        "<strong>Citations</strong> is F1 of cited chunk IDs vs. gold. "
        "<strong>Cost</strong> compares your <code>estimated_cost_usd</code> against the baseline; "
        "spending less than baseline saturates at 1.0."
    ),
    what_to_submit=(
        "One answer per question in the public set, plus the chunk IDs you "
        "retrieved and the chunk IDs you actually cited."
    ),
    description=(
        "<p>You build a retrieval-augmented generation pipeline over the public "
        "ISU course catalog corpus. For each question, retrieve relevant chunks, "
        "ground your answer in them, and cite the specific chunks you used.</p>"
        "<p>Faithfulness, citations, and retrieval recall all get scored "
        "independently &mdash; you can't game one without hurting the others.</p>"
    ),
    tips=[
        "Cite chunks that justify your answer &mdash; <code>citations</code> is graded against gold.",
        "Surface every relevant chunk in <code>retrieved_contexts</code> &mdash; recall is graded too.",
        "Lower <code>estimated_cost_usd</code> earns you cost credit; clamps at 1.0 below baseline.",
    ],
    data_files=[
        DataFile(
            name="index.json",
            purpose="Public chunked corpus. Stable <code>chunk_id</code> keys you cite from.",
            href="https://github.com/asukul/AI-arena/blob/main/corpora/isu_course_catalog/index.json",
        ),
        DataFile(
            name="questions.json",
            purpose="Public test questions. Each <code>question_id</code> must appear in your submission.",
            href="https://github.com/asukul/AI-arena/blob/main/corpora/isu_course_catalog/questions.json",
        ),
        DataFile(
            name="sample_submission.json",
            purpose="Canonical example payload that scores 1.0 against the in-tree gold set.",
            href="/samples/rag_treasure_hunt",
        ),
        DataFile(
            name="gold answers + gold citations",
            purpose="Hidden &mdash; never returned in API responses, only used by the scorer.",
            public=False,
        ),
    ],
    judge_tokens_per_day=50000,
)

_T4 = TrackMeta(
    id=TRACK_META_JUDGE,
    number=4,
    name="Build Your Own AI Judge",
    tagline="Write an evaluator and prove it agrees with the instructor.",
    accent="#d8a4ff",
    metric_label="linear-weighted Cohen's &kappa; mapped to [0, 1]",
    metric_formula="<code>final_score = (&kappa; + 1) / 2</code> &mdash; perfect agreement = 1.0, chance = 0.5, reverse = 0.",
    metric_explainer=(
        "You submit your evaluator's source plus the 1&ndash;5 ordinal grades it produced "
        "on a calibration set. We compute linear-weighted Cohen's &kappa; against the "
        "instructor's gold ratings. Linear weighting means an off-by-one rating is much "
        "better than off-by-three."
    ),
    what_to_submit=(
        "Your <code>evaluator_source</code> (a short Python function), the "
        "<code>rubric_text</code> you used as a prompt, and your "
        "<code>self_grades</code> for every gold item."
    ),
    description=(
        "<p>The pedagogical capstone. You write a small evaluator function plus "
        "the rubric text it implements. Then you grade a calibration set, and "
        "we measure how well your grades agree with the instructor's gold "
        "ratings using linear-weighted Cohen's &kappa;.</p>"
        "<p>The platform does not execute your code &mdash; the source is "
        "submitted for documentation and grading material only. You're rated "
        "on the agreement of the grades you produced.</p>"
    ),
    tips=[
        "Cover every gold item &mdash; missing items raise a clean error.",
        "Ordinal scale &mdash; integer ratings 1&ndash;5 work best.",
        "Source is grading-only material; the platform does not execute it.",
    ],
    data_files=[
        DataFile(
            name="sample_submission.json",
            purpose="Canonical example with rubric, evaluator source, and 10 self-grades.",
            href="/samples/meta_judge",
        ),
        DataFile(
            name="instructor gold ratings",
            purpose="Hidden &mdash; the kappa baseline you're scored against.",
            public=False,
        ),
    ],
    judge_tokens_per_day=0,
)


TRACKS_META: list[TrackMeta] = [_T1, _T2, _T3, _T4]


# Lookup helpers — both forms get used in different places.

def get_track(track_id: str) -> TrackMeta | None:
    for t in TRACKS_META:
        if t.id == track_id:
            return t
    return None


TRACKS_BY_ID: dict[str, TrackMeta] = {t.id: t for t in TRACKS_META}
