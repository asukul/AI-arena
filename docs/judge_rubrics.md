# AI Arena — Public Scoring Rubrics

Every track in the Arena uses transparent, public scoring.  You should be
able to read this doc and reverse-engineer exactly what your final score
will be — there is no hidden weighting.

This is the long-form companion to the **Overview** tab on each
`/competitions/{track_id}` page. Same metrics, more detail, version-controlled.

| # | Track | Headline metric | Live page |
|---|---|---|---|
| 1 | Hallucination Hunter | macro-F1 | [/competitions/hallucination_hunter](https://d4-arena-api-77646749251.us-central1.run.app/competitions/hallucination_hunter) |
| 2 | Prompt Golf | judge accuracy × token efficiency | [/competitions/prompt_golf](https://d4-arena-api-77646749251.us-central1.run.app/competitions/prompt_golf) |
| 3 | RAG Treasure Hunt | weighted rubric (30/25/15/15/10/5) | [/competitions/rag_treasure_hunt](https://d4-arena-api-77646749251.us-central1.run.app/competitions/rag_treasure_hunt) |
| 4 | Build Your Own AI Judge | linear-weighted Cohen's κ → [0, 1] | [/competitions/meta_judge](https://d4-arena-api-77646749251.us-central1.run.app/competitions/meta_judge) |

---

## Track 1 — Hallucination Hunter

**You submit:** A `(claim_id, label)` prediction for every claim in the
test set.  Labels are one of `supported`, `refuted`, `not_enough_info`.

**Headline metric:** **macro-F1** across the three classes.

### Why macro-F1 (not accuracy)?

Accuracy hides minority-class failure.  In a test set that's mostly
`supported` claims, a model that predicts `supported` for everything can hit
70% accuracy while being useless on the other two classes.  Macro-F1 takes
the unweighted mean of per-class F1 — so getting `not_enough_info` wrong
costs you just as much as getting `supported` wrong, regardless of how
many of each appear.

This is the same scoring philosophy used in the FEVER and SciFact
fact-verification benchmarks.

### How macro-F1 is computed

For each class `c ∈ {supported, refuted, not_enough_info}`:

| Term | Meaning |
|---|---|
| TP | predicted `c` and the gold label is `c` |
| FP | predicted `c` but the gold label is something else |
| FN | predicted something else but the gold label is `c` |

Then per class:

```
precision_c = TP / (TP + FP)
recall_c    = TP / (TP + FN)
F1_c        = 2 * precision_c * recall_c / (precision_c + recall_c)
```

And the headline:

```
macro_F1 = mean(F1_supported, F1_refuted, F1_not_enough_info)
```

### What you'll see in your score response

```json
{
  "submission_id": "...",
  "final_score": 0.7333,
  "dimensions": [
    {"name": "macro_f1", "weight": 1.0, "raw_score": 0.7333,
     "notes": "3 classes, 50 items"}
  ],
  "judge_metadata": {
    "macro_f1": 0.7333,
    "micro_f1": 0.74,
    "weighted_f1": 0.7402,
    "per_class": {
      "supported":      {"precision": 0.81, "recall": 0.79, "f1": 0.80, "support": 28},
      "refuted":        {"precision": 0.74, "recall": 0.71, "f1": 0.72, "support": 17},
      "not_enough_info":{"precision": 0.62, "recall": 0.71, "f1": 0.66, "support":  5}
    }
  }
}
```

`per_class` is the diagnostic — if your macro-F1 is low, look here to see
which class is dragging you down.

### Submission rules

- You must submit a prediction for **every** `claim_id` in the test set.
  Missing any → 422 validation error, not partial credit.
- Extra `claim_id`s (not in the test set) → 422 validation error.
- Duplicate `claim_id`s → 422 validation error.
- Predicting a label not in `{supported, refuted, not_enough_info}` is
  legal but counts as wrong against every gold class — it's not a free
  "abstain."
- Rate limit: 5 submissions per student per UTC day.

---

## Track 2 — Prompt Golf

**You submit:** Your `prompt_template` plus the `(input, output)` samples
your prompt produced when run against the gold inputs.

**Headline metric:** **`mean(judge_score) × min(1, baseline_tokens / total_tokens)`**

### How the score is built

1. The harness loops over every gold input, finds the matching `output` in
   your `samples`, and asks the judge ([`prompts/judge_correctness.txt`](../prompts/judge_correctness.txt))
   to score that answer 0.0–1.0 against the hidden gold answer.
2. `mean(judge_score)` is the average across all gold inputs.
3. `total_tokens` is the sum of `chars/4` over your `prompt_template` and
   every `output` (the standard rule-of-thumb estimate).
4. `baseline_tokens` is a fixed budget the harness publishes per-track.
   If you stay at or below baseline, the multiplier is exactly `1.0` and
   your accuracy carries the score. Going over baseline shrinks the score
   linearly.
5. `final_score = mean(judge_score) × min(1, baseline_tokens / total_tokens)`,
   clamped to `[0, 1]`.

### Why "min(1, ...)" and not just "baseline / total"?

So accuracy is the ceiling. A short prompt that gets every answer right
scores 1.0. A two-character prompt that gets every answer wrong still
scores 0.0. Length is the tiebreaker among equally-correct prompts, not a
free win for compression.

### What you'll see in your score response

```json
{
  "submission_id": "...",
  "final_score": 0.84,
  "dimensions": [
    {"name": "judge_accuracy",  "weight": 1.0, "raw_score": 0.91, "notes": "11/12 judged correct"},
    {"name": "token_efficiency","weight": 0.0, "raw_score": 0.92, "notes": "1842 / 2000 baseline"}
  ],
  "judge_metadata": {
    "prompt_tokens":     12,
    "completion_tokens": 1830,
    "total_tokens":      1842,
    "baseline_tokens":   2000,
    "per_sample": [
      {"input": "...", "judge_score": 1.0, "output_tokens": 152},
      {"input": "...", "judge_score": 0.5, "output_tokens": 191}
    ]
  }
}
```

`per_sample` tells you exactly which inputs the judge marked down, so you
can rewrite the prompt for those without losing the wins.

### Submission rules

- Every gold input must be covered exactly once. Missing or extra → 422.
- Token count is approximated as `chars/4`. Don't game the approximation —
  the cost dimension on Track 3 actually charges per-token-by-tokenizer.
- Judge calls run at `temperature=0` (anti-cheat).
- Daily limits: 5 submissions + 50,000 judge tokens per UTC day.

---

## Track 3 — RAG Treasure Hunt

**You submit:** One answer per question in the public set, plus the
`chunk_id`s you retrieved and the `chunk_id`s you actually cited.

**Headline metric:** weighted rubric across six dimensions:

| Dimension | Weight | Computed by |
|---|---|---|
| Correctness | **30%** | LLM judge ([`prompts/judge_correctness.txt`](../prompts/judge_correctness.txt)) — does your answer match the hidden gold? |
| Faithfulness | **25%** | LLM judge ([`prompts/judge_faithfulness.txt`](../prompts/judge_faithfulness.txt)) — is your answer grounded in the chunks you cited? |
| Retrieval | **15%** | Recall: `|retrieved_contexts ∩ gold_relevant| / |gold_relevant|` |
| Citations | **15%** | F1 of `citations` vs. `gold_citations` for that question |
| Cost | **10%** | `min(1.0, baseline_cost / your_estimated_cost_usd)` |
| Safety | **5%** | LLM judge ([`prompts/judge_safety.txt`](../prompts/judge_safety.txt)) — refuses harmful, off-topic, or made-up content |

```
final_score = 0.30·correctness + 0.25·faithfulness + 0.15·retrieval
            + 0.15·citations   + 0.10·cost         + 0.05·safety
```

Each dimension is scored independently per question, then averaged across
all questions before weighting.

### Why retrieval and citations are graded separately

`retrieved_contexts` answers "what did your retriever surface?" — it's
graded on **recall** so you're rewarded for casting a wide-enough net.
`citations` answers "what did the LLM actually use?" — it's graded on
**F1** so you're penalized for citing chunks that didn't really matter.
Optimizing one will hurt the other unless your pipeline is genuinely good.

### Cost dimension

Spending less than baseline saturates at `1.0` — there's no extra credit
for being absurdly cheap. The baseline is set so a reasonable retrieval
+ small-LLM pipeline lands at ~1.0; an expensive long-context shot with
no retrieval lands well below. `latency_seconds` is logged but **not**
scored on Track 3.

### What you'll see in your score response

```json
{
  "final_score": 0.78,
  "dimensions": [
    {"name": "correctness",  "weight": 0.30, "raw_score": 0.86},
    {"name": "faithfulness", "weight": 0.25, "raw_score": 0.81},
    {"name": "retrieval",    "weight": 0.15, "raw_score": 0.71},
    {"name": "citations",    "weight": 0.15, "raw_score": 0.62},
    {"name": "cost",         "weight": 0.10, "raw_score": 1.00},
    {"name": "safety",       "weight": 0.05, "raw_score": 1.00}
  ],
  "judge_metadata": {
    "per_question": [
      {"question_id": "Q001", "correctness": 0.9, "faithfulness": 0.8, ...}
    ]
  }
}
```

If your weak dimension is **citations**, you're probably citing every
chunk you retrieved instead of just the ones that justify the answer.
If it's **retrieval**, your retriever is missing relevant chunks — go
read the gold-relevant set on a few specific questions to see what you
missed.

### Submission rules

- Every question in `corpora/isu_course_catalog/questions.json` must
  appear exactly once.
- `citations` and `retrieved_contexts` must reference `chunk_id`s that
  actually exist in `index.json`.
- Daily limits: 5 submissions + 50,000 judge tokens per UTC day.

---

## Track 4 — Build Your Own AI Judge

**You submit:** Your `evaluator_source` (a short Python function), the
`rubric_text` you used as a prompt, and your `self_grades` for every gold
item on a 1–5 ordinal scale.

**Headline metric:** **`final_score = (κ + 1) / 2`** where κ is
linear-weighted Cohen's κ between your grades and the instructor's gold.

### What linear-weighted κ rewards

Cohen's κ is "agreement above chance" on categorical labels. The
**linear-weighted** variant treats ordinal off-by-one disagreements as
better than off-by-two — perfect for 1-to-5 ratings where "4 vs 3" is
defensible but "5 vs 1" is a serious miss.

```
κ_linear ∈ [-1, 1]    where:
   1.0  = perfect agreement
   0.0  = chance
  -1.0  = perfectly inverted

final_score = (κ + 1) / 2     so:
   1.0  = perfect
   0.5  = chance
   0.0  = perfectly wrong
```

The map to `[0, 1]` is just so the leaderboard sorts the same direction
as every other track.

### Why the source code is required if it's not executed

You write a small `grade(item) -> int` function plus a rubric. Both go
into your submission. The platform **does not** execute the function —
your `self_grades` array is what we score on. The source + rubric are
graded artifacts: instructors and peers can read them in the bootcamp
retrospective and learn what worked.

This keeps the platform simple (no sandboxing) while still making the
"build a judge" exercise meaningful.

### What you'll see in your score response

```json
{
  "final_score": 0.83,
  "dimensions": [
    {"name": "kappa", "weight": 1.0, "raw_score": 0.66,
     "notes": "linear-weighted, mapped to [0,1] as (κ+1)/2"}
  ],
  "judge_metadata": {
    "kappa_linear": 0.66,
    "n_items":      10,
    "confusion": {
      "1": {"1": 2, "2": 0, "3": 0, "4": 0, "5": 0},
      "2": {"1": 0, "2": 1, "3": 1, "4": 0, "5": 0},
      ...
    }
  }
}
```

The `confusion` matrix is your diagnostic — rows are gold ratings, columns
are your ratings. Lots of off-diagonal mass two cells away from the
diagonal means your rubric needs sharper thresholds.

### Submission rules

- Every item in `corpora/gold/meta_judge.json` must appear in `self_grades`
  exactly once.
- `score` is treated as ordinal — fractional scores work but integers
  1–5 align with the rubric levels.
- This track does **not** call the judge model, so no token budget applies.
- Daily limits: 5 submissions per UTC day.

---

## Anti-cheat in plain language

- The hidden test set never appears in API responses.  You cannot see the
  gold labels.
- The judge runs at temperature 0 — same input always gives the same score.
- The top 10% of submissions are re-graded by a different model family
  (Gemini Flash) as a sanity check.  If the two judges disagree by more
  than 10 points, your submission goes to manual review before it counts.

---

*This document is version-controlled in `docs/judge_rubrics.md`.  PRs welcome.*
