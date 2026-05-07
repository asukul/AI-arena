# Journey: Maya (CS student)

## Who I am
I'm Maya, third-year CS at ISU. I've shipped a Kaggle kernel for a course project, I'm comfortable on the terminal, and I read the rubric before I write code. I want to win this thing.

## First impressions
Landing page is clean. Four track cards, the right metadata on each (eval metric, submission count, top student), a v0.1.0 badge that's honest about being early. The "FastAPI · Cloud Run · Firestore" badge nerd-snipes me into knowing what I'm submitting against. Eval metrics are on each card, so I can compare without clicking in.

What felt off: the only "log in" is typing `maya_cs_test` into the leaderboard's "Set ID" prompt. `student_id` is just a self-claimed string — fine for bootcamp, but the placeholder `REPLACE_ME_with_your_id` is sitting at #5 on the Track 1 leaderboard, which says nothing's validating it.

![screenshot](screenshots/maya_landing.png)

## Track 1 — Hallucination Hunter
- **Overview**: classify claims as supported / refuted / not_enough_info, scored by macro-F1. The line "predicting one class for everything will not score well" is a pedagogical nudge I respect.
- **Data**: a single public `sample_submission.json` plus the shared envelope spec.
- **Code**: points at `docs/student_starter.ipynb` ("Copy & Edit it like a Kaggle kernel" — right framing) with PowerShell / curl / Python tabs. PowerShell first feels weird; most students will be on Mac.
- **Rules**: 5 submissions/day per `student_id`, no token budget, best-of-N kept, top 10% re-graded by Gemini Flash. Cross-family judge re-grade is a great touch.
- I clicked Submit Entry, switched to Use sample, hit Load sample into editor, replaced `student_id` with `maya_cs_test`, hit Submit. JSON came back with `status: queued`, leaderboard updated within ~5 seconds.
- **Final score: 1.0000.** Tied for #1 with the canonical sample — this track is "the pipeline works" not "I solved it," and the Description says so.

![screenshot](screenshots/maya_t1_overview.png) ![screenshot](screenshots/maya_t1_submit_modal.png) ![screenshot](screenshots/maya_t1_leaderboard.png)

**Friction:** the "Open submit dialog →" link in the 60-second box has `href="#"` and just jumps to top — only the top-right Submit Entry button works.

**Delights:** sample-as-starting-point is the right default. "You are maya_cs_test" persists locally and my row gets a person icon on the board.

## Track 2 — Prompt Golf
- **Overview**: shortest prompt that still answers correctly. Score = `mean(judge_score) × min(1, baseline_tokens / total_tokens)`. Token efficiency saturates at 1.0 so accuracy is the ceiling.
- **Data/Code**: same envelope, `prompt_template` + `(input, output)` samples. 50K judge tokens/day across all submissions.
- I hit Submit and got **HTTP 429**: `current: 5/5` exhausted. That's wrong — I'd only made one Track 1 submission today. Either the cap is global (not per-track as Rules implies) or stale from prior persona runs. The error body is great though — JSON with `limit`, `current`, `reset_at`, `message`. Retried as `maya_cs_test_t2`, succeeded.
- **Final score: 0.0000.** Expected — the canonical sample's inputs ("What is 2+2?") don't match the hidden gold inputs, so judge accuracy is 0. But the docs claim the sample "scores 1.0 against the in-tree gold," which is wrong in production. That contradiction will confuse a lot of students.

![screenshot](screenshots/maya_t2_overview.png) ![screenshot](screenshots/maya_t2_429.png) ![screenshot](screenshots/maya_t2_leaderboard.png)

**Friction:** sample-scores-1.0 promise is false here. That destroys student trust on day 1.

**Delights:** the 429 response body is exactly actionable.

## Track 3 — RAG Treasure Hunt
- **Overview**: build a RAG pipeline over the ISU course catalog. 6-dimension rubric (30/25/15/15/10/5): correctness, faithfulness, retrieval recall, citations F1, cost vs baseline, safety. Three are LLM-judged.
- **Code** is the most interesting tab — a dedicated **Reference solution** notebook (`docs/track3_reference_solution.ipynb`) framed as "a fork-able floor" with weak-dimension notes at the end. That is exactly the right move for the hardest track.
- The in-browser modal had a real glitch: clicking Use sample auto-submitted with `student_id` still set to `REPLACE_ME_with_your_id`, and that bad row landed on the leaderboard. Modal state across track navigations is buggy — after the submit, the URL flipped to Track 4 unexpectedly. I retried with curl as `maya_cs_test_t3`.
- **Final score: 0.0000** — same caveat as Track 2: sample QA pairs probably don't line up with the hidden gold.

![screenshot](screenshots/maya_t3_overview.png) ![screenshot](screenshots/maya_t3_leaderboard.png)

**Did the reference notebook help?** I didn't run it for this journey, but having it changes how I'd plan tomorrow: clone, run end-to-end to see what 0.5 looks like, then optimize the dimensions the notebook calls out as weak. Real workflow.

**Friction:** Track 3 leaderboard shows two rows with the same `submission_id` `sub_lbwfr9xb` owned by two different `student_id`s. Either dedupe or display this clearly.

**Delights:** Reference solution + named-weak-dimensions pattern. Better than Kaggle here.

## Track 4 — Build Your Own AI Judge
- **Overview**: the meta one. Write an evaluator function plus a rubric, grade the calibration set, and we measure agreement with the instructor's gold using linear-weighted Cohen's κ mapped to [0, 1] (0.5 = chance, 1 = perfect, 0 = reverse). The platform doesn't execute my code — source is grading material only. Smart, removes attack surface.
- **What you submit**: `evaluator_source` + `rubric_text` + `self_grades` for every gold item.
- I curl'd the sample, submitted under `maya_cs_test_t4`.
- **Final score: 1.0000.** Canonical sample DID score 1.0 here — clean.

![screenshot](screenshots/maya_t4_overview.png) ![screenshot](screenshots/maya_t4_leaderboard.png)

**Delights:** "platform does not execute your code" is the right call. The "prove your judge agrees with the instructor" framing is the only one that asked me to think about evaluation rather than play it.

## Cross-cutting observations

**What's clearly Kaggle-influenced and works**
- Tabs (Overview/Data/Code/Leaderboard/Rules), per-track sample, best-score-per-student rule, Copy & Edit notebook framing, structured tips boxes.
- Live leaderboard refresh every 10s.
- Rules tab carrying anti-cheat, late policy, and caps in one place.

**What feels half-baked**
- The "canonical sample scores 1.0" claim only holds on Tracks 1 and 4. Tracks 2/3 score it 0.0 because their gold doesn't include sample inputs.
- Modal state across navigations is unreliable; one navigation caused an auto-submit with the placeholder `student_id`.
- No identity/auth — `student_id` is self-claimed.

**Bugs found**
1. "Open submit dialog →" link has `href="#"` — only the top-right button opens the modal.
2. Track 3 leaderboard shows duplicate `submission_id` rows under different students.
3. Daily-limit counter showed 5/5 for `maya_cs_test` after a single Track 1 submission — cap appears global or stale; Rules text says "per `student_id`" but doesn't clarify per-track.
4. Canonical sample doesn't score 1.0 on Tracks 2 and 3 — biggest trust hit.
5. Track 1 Rules tab nav link sometimes routes elsewhere — had to use URL hash directly.

**3 suggestions, ordered by impact**
1. **Make the canonical sample actually score 1.0 on every track**, or change the docs to "1.0 against local dev gold; production scores will be lower." Current claim is false where it counts.
2. **Validate `student_id` on submit** — reject `REPLACE_ME_with_your_id` and obvious placeholders with a 422. Prevents placeholder rows on the public board.
3. **Fix the modal lifecycle** — close the modal on every navigation event, including hash changes, so opening a submit modal on Track N after one on Track N-1 doesn't cause cross-track surprises.

## Final scores
| Track | Score | Submission |
|---|---|---|
| 1 — Hallucination Hunter | 1.0000 | `sub_maya_t1_001` (student_id `maya_cs_test`) |
| 2 — Prompt Golf | 0.0000 | `sub_maya_t2_001` (student_id `maya_cs_test`) |
| 3 — RAG Treasure Hunt | 0.0000 | `sub_maya_t3_002` (student_id `maya_cs_test_t3`, via curl after modal misbehaved) |
| 4 — Build Your Own AI Judge | 1.0000 | `sub_maya_t4_001` (student_id `maya_cs_test_t4`, via curl) |
