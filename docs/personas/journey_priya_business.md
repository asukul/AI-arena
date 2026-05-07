# Journey: Priya (business student, no coding)

## Who I am
I'm Priya, a senior Marketing major at Iowa State. My day is Excel models, PowerPoint decks, and Canva mockups for the consulting club. A friend mentioned this AI bootcamp — every job posting I open now says "AI experience preferred." I use ChatGPT and Claude weekly, but I've never written code, and I don't have a terminal app installed.

## First impressions
The landing page is clean and serious — "Kaggle-style competition platform," ISU Department of Computer Science, four track cards. But the first row of badges says "FastAPI · Cloud Run · Firestore" and I have no idea if those are words I'm supposed to know. Every track card has an "Eval" line: `macro-F1`, `judge accuracy × token efficiency`, `weighted rubric (30 / 25 / 15 / 15 / 10 / 5)`, `linear-weighted Cohen's κ mapped to [0, 1]`. I do not know what any of those mean. Track 1 felt safest only because it had real words ("supported, refuted, or not_enough_info") instead of math.

There's no sign-up, no "Get started" CTA, no "Hi Priya" greeting. My honest first thought was, "this is a tool for someone who already knows what they're doing."

![screenshot](screenshots/priya_home.png)

## Track 1 — Hallucination Hunter
- The "First submission in 60 seconds" box is the only reason I kept going. Four numbered steps, big blue button — that's the right thing for me. The rest of the page lost me. Description was OK. But Evaluation said `(F1_supported + F1_refuted + F1_not_enough_info) / 3` — I tuned out at "F1." The sentence that fully alienated me: **"Schema rejects empty `predictions` arrays — submit at least one."** I don't know what a schema is, what an array is, or what "rejects" means here.
- I clicked Submit Entry. The modal opened on **Paste JSON** with a giant empty box telling me to paste "a complete submission JSON (envelope + `track_payload`)." Without my friend's hint to click "Use sample," I close this tab and leave.
- Use sample worked. "Load sample into editor" filled the box with a wall of curly braces. I scanned it, found `"student_id": "REPLACE_ME_with_your_id"`, changed it to `priya_biz_test`, hit Submit.
- I got **HTTP 429** — a red box of JSON about `daily_submission_limit_reached`, `current: 5`, `limit: 5`. Apparently the daily quota is shared across the whole browser, and an earlier session ate it. My Track 1 row never landed.

![screenshot](screenshots/priya_t1_429.png)

**Did I get a score?** No. Rate-limited before my row counted.

## Track 2 — Prompt Golf
- The Description was the most interesting on the whole platform: "Write the shortest prompt that still produces correct answers." That's the kind of thing I do when I tweak a ChatGPT prompt for class. I almost felt like I belonged.
- And then: `mean(judge_score) × min(1, baseline_tokens / total_tokens)`. "Token count is approximated as `chars / 4`." "50,000-judge-tokens-per-day cap." A formula turned a writing exercise into a math class.
- Use sample → Load → swap `student_id` → Submit. The leaderboard showed me with a score of **0.0000**. The Use-sample helper text literally promised "the canonical sample for this track — the one that scores 1.0 against the in-tree gold." It scored zero, and I hadn't changed anything in the payload. That destroyed any confidence I had built up.

![screenshot](screenshots/priya_t2_leaderboard.png)

**Did I get a score?** Yes — 0.0000. Which is worse than no score, because I'm now wondering if I did something wrong, or the platform is broken, or zero is normal. Nothing on the page tells me.

## Track 3 — RAG Treasure Hunt
This is where I gave up emotionally. Words on this page that meant nothing to me: "retrieval pipeline," "retrieval-augmented generation," "chunks," "faithfulness," "retrieval recall," "citations F1," "chunk IDs," "retrieved_contexts," "estimated_cost_usd." The sample JSON cites `"cs2010_c1"` and `"cs2010_c2"` — I have no model in my head for what those are or why I'm citing them. The moment that broke me was the rubric: **"0.30 · correctness + 0.25 · faithfulness + 0.15 · retrieval + 0.15 · citations + 0.10 · cost + 0.05 · safety."** That's a formula from a graduate seminar, not an explanation.

I ran the Use sample flow anyway, out of stubbornness. Score: **0.0000.** The "canonical" sample scored zero again, with no explanation.

![screenshot](screenshots/priya_t3_jargon.png)

**Did I get a score?** Yes — 0.0000. As a non-coder, this track is unambiguously not for me. I couldn't even describe to a friend what the goal is.

## Track 4 — Build Your Own AI Judge
The headline sounded fun. The Description said "you write a small evaluator function plus the rubric text it implements" — and then "The platform does not execute your code." So I'm being asked to submit Python source code that won't be run. As a non-coder, that's a hard wall.

I clicked Use sample anyway. The editor filled with a JSON containing this:

```
"evaluator_source": "def grade(item: dict) -> int:\n    \"\"\"Return a 1-5 ordinal rating.\"\"\"\n    text = item['response'].lower() ...
```

I recognized that as Python (because of `def`). I would never write that. But buried below was something I understood: a list of `{"item_id": "i01", "score": 5}` rows. I assign rubric grades on case studies — that I get. Sample loaded, `student_id` swapped to `priya_biz_test`, Submit, and I got **1.0000**.

![screenshot](screenshots/priya_t4_python_code.png)

**Did I get a score?** Yes — 1.0000, #1 on the leaderboard. The irony is I scored highest on the most coding-heavy track, because the canonical sample happened to match the gold. I didn't actually *do* anything. The score is meaningless.

## Honest take
This platform feels like it was built by CS people for other CS people. The "first submission in 60 seconds" box is doing all the heavy lifting on approachability — past those four steps, every screen had at least one sentence that made me tune out. Two tracks scored my unmodified canonical sample as 0.0000, which made *me* feel like the failure even though I hadn't touched the file. The 429 error spoke to me in JSON about queues. As a non-coder showing up to "learn AI," I do not feel welcome, and the platform never tried to teach me what its own words mean.

## What would unlock this for someone like me
1. **A track designed for me.** "Track 0: Try AI in your browser" — type a prompt in a normal text box, see the model's answer, get a score with one sentence of feedback. No JSON, no envelope, no `student_id`. That alone would hook me.
2. **Stop promising "scores 1.0" when it doesn't.** I trusted the line "the canonical sample scores 1.0" and got 0.0000 on two tracks. Either fix the samples or change the copy to "Here's the right shape — your real work decides the score."
3. **A plain-English glossary panel on every track page.** Hover on `macro-F1`, `chunks`, `Cohen's κ`, `token efficiency` and get a one-sentence explainer ending in "Don't worry — the sample handles this for you." That alone would let a non-coder walk through every page without bouncing.

## Final scores
| Track | Submitted? | Score |
|---|---|---|
| Track 1 — Hallucination Hunter | No (HTTP 429 daily limit before my row landed) | — |
| Track 2 — Prompt Golf | Yes (sample, unmodified) | 0.0000 |
| Track 3 — RAG Treasure Hunt | Yes (sample, unmodified) | 0.0000 |
| Track 4 — Build Your Own AI Judge | Yes (sample, unmodified) | 1.0000 |
