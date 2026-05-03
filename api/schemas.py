"""
Submission and result schemas — the canonical wire format for AI Arena.

Locking this file early matters: every downstream component (FastAPI handler,
Cloud Tasks payload, evaluator dispatch, Firestore document, Canvas grade
passback) reads from these models. Schema rework cascades.

The universal envelope is the same across all four tracks; only `track_payload`
differs. The wrapper carries `track_id` once (per the published student-facing
shape) and a `model_validator` mirrors it into the payload so Pydantic's
discriminated union can pick the right payload class without forcing students
to repeat the field.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Discriminator, Field, model_validator


TRACK_HALLUCINATION: str = "hallucination_hunter"
TRACK_PROMPT_GOLF: str = "prompt_golf"
TRACK_RAG: str = "rag_treasure_hunt"
TRACK_META_JUDGE: str = "meta_judge"

TrackId = Literal[
    "hallucination_hunter",
    "prompt_golf",
    "rag_treasure_hunt",
    "meta_judge",
]


# ---------- Track 1: Hallucination Hunter ----------

class Prediction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_id: str
    label: str


class HallucinationPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["hallucination_hunter"]
    predictions: list[Prediction] = Field(min_length=1)


# ---------- Track 2: Prompt Golf ----------

class GolfSample(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input: str
    output: str


class PromptGolfPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["prompt_golf"]
    prompt_template: str = Field(min_length=1)
    samples: list[GolfSample] = Field(default_factory=list)


# ---------- Track 3: RAG Treasure Hunt ----------

class RagAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: str
    answer: str
    citations: list[str] = Field(default_factory=list)
    retrieved_contexts: list[str] = Field(default_factory=list)
    estimated_cost_usd: float = Field(default=0.0, ge=0.0)
    latency_seconds: float = Field(default=0.0, ge=0.0)


class RagPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["rag_treasure_hunt"]
    answers: list[RagAnswer] = Field(min_length=1)


# ---------- Track 4: Build Your Own AI Judge ----------

class SelfGrade(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: str
    score: float


class MetaJudgePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["meta_judge"]
    evaluator_source: str = Field(min_length=1)
    rubric_text: str = Field(min_length=1)
    self_grades: list[SelfGrade] = Field(default_factory=list)


TrackPayload = Annotated[
    HallucinationPayload | PromptGolfPayload | RagPayload | MetaJudgePayload,
    Discriminator("kind"),
]


# ---------- Universal envelope ----------

class Submission(BaseModel):
    """Every submission to AI Arena, regardless of track, takes this shape."""

    model_config = ConfigDict(extra="forbid")

    submission_id: str = Field(min_length=1)
    student_id: str = Field(min_length=1)
    track_id: TrackId
    submission_timestamp: datetime
    model_used: str | None = None
    prompt_version: str | None = None
    self_reported_strategy: str | None = None
    track_payload: TrackPayload

    @model_validator(mode="before")
    @classmethod
    def _mirror_track_id_into_payload(cls, data: Any) -> Any:
        # Students write `track_id` once at the top level. The discriminated
        # union needs a discriminator field inside the payload, so we copy it
        # in as `kind` before validation runs.
        if isinstance(data, dict):
            payload = data.get("track_payload")
            track_id = data.get("track_id")
            if isinstance(payload, dict) and track_id and "kind" not in payload:
                return {**data, "track_payload": {**payload, "kind": track_id}}
        return data

    @model_validator(mode="after")
    def _payload_kind_matches_track_id(self) -> Submission:
        # If a student supplied an inner `kind` that disagrees with the outer
        # `track_id`, surface the conflict instead of silently preferring one.
        if self.track_payload.kind != self.track_id:
            raise ValueError(
                f"track_id '{self.track_id}' does not match track_payload.kind "
                f"'{self.track_payload.kind}'"
            )
        return self


# ---------- Score result (what evaluators return) ----------

class ScoreDimension(BaseModel):
    """One scored dimension within a track's rubric (e.g. 'faithfulness').

    `weight` is a non-negative number; normalization to a unit basis is the
    responsibility of `evaluator.scoring.normalize_weights`.  This means
    rubrics can be expressed in whatever units are most readable (percentages,
    fractions, raw counts) and aggregated consistently.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    weight: float = Field(ge=0.0)
    raw_score: float = Field(ge=0.0, le=1.0)
    notes: str | None = None


class ScoreResult(BaseModel):
    """The output of any evaluator. Goes to Firestore and Canvas."""

    model_config = ConfigDict(extra="forbid")

    submission_id: str
    student_id: str
    track_id: TrackId
    final_score: float = Field(ge=0.0, le=1.0)
    dimensions: list[ScoreDimension] = Field(default_factory=list)
    judge_metadata: dict[str, Any] = Field(default_factory=dict)
    scored_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    error: str | None = None
