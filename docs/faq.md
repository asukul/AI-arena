# AI Arena — FAQ

## "Why did I get this score?"

Every track is documented in [`judge_rubrics.md`](judge_rubrics.md).  Read
the Track 1 / 2 / 3 / 4 sections for the exact metric and how the
per-dimension breakdown is computed.

If your score still seems wrong:

1. Check the `judge_metadata` field of your `/submit` response.  It contains
   the per-class or per-dimension breakdown — usually the answer is right
   there ("I scored 0 on `not_enough_info` because I didn't predict it
   anywhere").
2. Re-read your submission JSON.  Validation errors return 422 with
   `problems[]` — make sure none of those slipped through silently.
3. Open an issue / DM the instructor with your `submission_id`.  We can
   pull the full evaluation trace from Cloud Logging.

## "Can I submit again to improve my score?"

Yes — up to **5 submissions per UTC day** (this resets at 00:00 UTC).
Your leaderboard entry is your **best score**, not your latest, so a
worse re-submission won't hurt you.

The 429 response body tells you exactly when your counter resets.

## "Why doesn't my submission match the schema?"

Check the response body — `problems[]` lists every field with a problem.
The most common mistakes:

| Problem | Fix |
|---|---|
| `track_payload.predictions: List should have at least 1 item` | You sent an empty `predictions` list. |
| `track_payload.predictions.0.label: Field required` | One of your predictions is missing a `label`. |
| `extra_forbidden` on the envelope | You added a field not in the spec — typo or stale schema. |
| `track_id 'X' does not match track_payload.kind 'Y'` | Your envelope's `track_id` and your inner payload disagree. |

## "What model should I use to generate my answers?"

Your choice.  The platform records `model_used` for diagnostics but doesn't
constrain you.  Common picks:

- **Claude Haiku 4.5** — cheap, fast, good baseline.
- **Claude Sonnet 4.6** — best quality-per-dollar for tougher reasoning.
- **Gemini 2.0 Flash** — free tier covers most student usage.
- **A local model via Ollama** — fully free, slower.

Some tracks (Prompt Golf) penalize verbose prompts.  Track 2 specifically
rewards getting more accuracy out of fewer tokens.

## "Can I see the test data?"

No.  The hidden test set is on the server; you only see your score and the
per-dimension breakdown.  This is what makes the leaderboard meaningful.

You can see *sample* / *practice* data in the starter notebook — those are
NOT in the hidden test set.

## "My grade in Canvas doesn't match the leaderboard."

The leaderboard shows your **best** score.  Canvas shows your **most
recent** submission's grade.  This mismatch is intentional: the leaderboard
is for competition; Canvas is for tracking effort.

If your Canvas grade and the platform's most-recent score still disagree,
it's a bug — please report.

## "Is anything cached or memoized?"

The judge prompts are cached at the API level (the rubric is the same for
every student, so we save tokens on repeated grading calls).  Your
submissions are *not* cached — each one runs through the scorer fresh.

## "What happens to my submission data?"

- Stored in Firestore at `submissions/{submission_id}` for the duration of
  the bootcamp.
- The `student_id` in submissions IS your Canvas/NetID — it's used to
  reconcile leaderboard entries with grade passback.
- Public leaderboard shows pseudonymous entries by default.  Real names
  stay in Canvas only.
- After the bootcamp ends, all per-student data is deleted; aggregate
  statistics (anonymized) may be published.

## "I think I found a bug / cheat / unfair scoring."

Please open an issue — anti-cheat is a feature, not an embarrassment.
Quick triage path:

1. Pull your `submission_id` from the response or Canvas comment.
2. Email `adisak.sukul@gmail.com` with what you observed and what you
   expected.
3. We have full Cloud Logging — replay is fast.
