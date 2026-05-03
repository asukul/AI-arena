# AI Arena — Public Scoring Rubrics

Every track in the Arena uses transparent, public scoring.  You should be
able to read this doc and reverse-engineer exactly what your final score
will be — there is no hidden weighting.

This page covers Track 1 in full and stubs the others; later tracks fill in
as they ship.

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

## Tracks 2, 3, 4 — coming soon

| Track | Headline metric | Doc lives at |
|---|---|---|
| Prompt Golf | judge accuracy ÷ total tokens | (Day 3) |
| RAG Treasure Hunt | weighted rubric (correctness 30 / faithfulness 25 / retrieval 15 / citations 15 / cost 10 / safety 5) | (Day 4) |
| Build Your Own AI Judge | Cohen's κ vs instructor gold | (Day 6) |

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
