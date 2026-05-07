# Journey: Jordan (high school)

## Who I am

I'm Jordan. Junior at Ames High. I took intro to Python last semester, so I can write a `for` loop and a `while` loop, and that's about it. The school invited me up to ISU for some AI day thing and they said "go try the platform." I have heard the word "API" before, mostly from my CS teacher saying "we won't get to APIs this year."

## First impressions

The home page looked clean. Big "AI Arena" title, four cards for the four tracks. I liked that — felt like Discord-y, dark mode, looked legit. I understood "Track 1 — Hallucination Hunter" because I know what hallucinations are (the AI making stuff up — TikTok taught me that). The card said "Eval: macro-F1" and I had no idea what that meant. I figured it was like a percent or something.

The little badges underneath each card — "FastAPI · Cloud Run · Firestore" — yeah that's three words I don't recognize, all in a row. I just ignored them.

What I didn't get on the landing page:

- **"judge accuracy × token efficiency"** (Track 2) — what's a token, what's a judge?
- **"weighted rubric (30 / 25 / 15 / 15 / 10 / 5)"** (Track 3) — those numbers add to 100 so I guess they're percents, but percents of what?
- **"linear-weighted Cohen's κ mapped to [0, 1]"** (Track 4) — honestly this could be Latin and I would not know the difference.

![screenshot](screenshots/jordan_landing.png)

## Track 1 — Hallucination Hunter

I clicked the first card. The page has 5 tabs: Overview, Data, Code, Leaderboard, Rules. There's a yellow "First submission in 60 seconds" box at the top — I really liked that. It told me **exactly** what to do: hit the blue button, switch to "Use sample," replace your ID, submit. That box is the only reason I made it through this track.

What each tab felt like:

- **Overview**: The 60-second box was great. The "Description" was readable — supported / refuted / not_enough_info, like fact-checking. I get it. But "Macro-F1 weights every label equally" — I had to re-read three times and still don't really get it. I just trusted it would be fine.
- **Data**: Showed me a downloadable `sample_submission.json`. Then a giant block of JSON titled "Submission envelope." That word "envelope" confused me — I thought of mail. Underneath, "Sample submission (scores 1.0)" — wait, the *sample* already scores perfect? Then why am I doing anything? (I'm guessing the real test set is different and they just give you the format.)
- **Code**: I never opened this one. I figured "Code" meant I have to write code. Skipped.
- **Rules**: "5 submissions / day per `student_id`, UTC reset. Returns HTTP 429" — I know what HTTP is from networking class but **no idea what HTTP 429 means**. The rest about "anti-cheat" and "honor code" was scary but readable.

What I clicked, in order:
1. The Track 1 card on the home page.
2. Read the Overview tab (the 60-second box).
3. Hit the blue **Submit Entry** button (top right).
4. Tabbed over to **Use sample** in the modal.
5. Clicked **Load sample into editor**. JSON appeared.
6. Read the JSON. Saw `"student_id": "REPLACE_ME_with_your_id"`. The instructions said replace it with my own — I tried to type `jordan_hs_test` but the page seems to have its own idea of who I am — the leaderboard kept calling me random names like `maya_cs_test` and `priya_biz_test`. Confusing. (I think there's a "Set ID" button on the leaderboard but I didn't notice it until later.)
7. Hit **Submit Entry** at the bottom of the modal.
8. Saw the green "Submitted!" message. There's a `task_id` thing that goes on for 100 characters. I didn't read it.

![screenshot](screenshots/jordan_t1_modal.png)

Where I got stuck: nowhere really, because the sample is pre-filled. Score: **1.0000** on the leaderboard. I was like, no way I just got #1, but then I looked and **everybody** has 1.0000 because they all submitted the canonical sample. So leaderboard is currently a 5-way tie and I don't know if my score is real-real or fake-real.

![screenshot](screenshots/jordan_t1_leaderboard.png)

Did I submit? **Yes.** Score: **1.0000.**

## Track 2 — Prompt Golf

The card said "Find the shortest prompt that still answers correctly" — I sort of get this because I've seen people on Twitter try to jailbreak ChatGPT with weird prompts. So Prompt Golf = trying to be clever with words for points.

- **Overview**: "judge accuracy × token efficiency" — okay, so my score is **(how right I am) × (how short my prompt is)**. That makes sense actually! But then there's `mean(judge_score) × min(1, baseline_tokens / total_tokens)` in code font and that is straight gibberish to me. Tokens, I figured out, must be like words but smaller? They mention `chars / 4` later, so I guess every 4 letters = 1 token. Okay.
- **"You have a 50,000-judge-tokens-per-day cap"** — no idea what this means. Sounds like there's a money thing happening behind the scenes.

I hit Submit Entry → Use sample → Load sample. The JSON had a `prompt_template`: `"Answer concisely:"` and three sample questions ("What is 2+2?" / "Capital of France?" / "Hamlet"). I just submitted it.

Did I submit? **Yes.** Score: **0.0000.** 😬 The "canonical sample that scores 1.0" did NOT score 1.0 for me. Both me and another tester got zero. I don't know if the AI judge couldn't run, or if something's broken. As a kid I'd be looking around like "did I break it?"

![screenshot](screenshots/jordan_t2_submitted.png)

## Track 3 — RAG Treasure Hunt

The word "RAG" at first I thought was like a rag, like a cloth. Then I realized from the description it's "retrieval-augmented generation" — basically the AI looks stuff up in a library before it answers. Cool.

- "**weighted rubric (30 / 25 / 15 / 15 / 10 / 5)**" — yes this was overwhelming. Six different things being scored: correctness, faithfulness, retrieval, citations, cost, safety. Each with a weight. My brain just heard "you will be judged on six things at once." I gave up on understanding the rubric and just trusted the sample.
- "**Citations is F1 of cited chunk IDs vs. gold**" — F1 again. I still don't know what F1 is.
- "**baseline_tokens**" / "**estimated_cost_usd**" — okay so this involves real money behind the scenes. That's actually kind of cool but also kind of stressful.

The sample JSON for this one was HUGE. Five questions about ISU classes, each with an answer, citations like `"cs2010_c1"`, retrieved_contexts, an `estimated_cost_usd: 0.004`. I scrolled through it and hit submit.

Did I submit? **Yes.** Score: **0.0000** again. So either the judge is offline or the sample answers don't match the gold (which is weird because the page said "scores 1.0 against the in-tree gold"). Either way, as a high schooler I just see "0" and feel kind of dumb even though I literally clicked the only button.

![screenshot](screenshots/jordan_t3_submitted.png)

## Track 4 — Build Your Own AI Judge

I opened it and YES the description scared me: "You write a small evaluator function plus the rubric text it implements." The sample JSON has a field called `evaluator_source` and inside it is **actual Python code**:

```
def grade(item: dict) -> int:
    """Return a 1-5 ordinal rating."""
    text = item['response'].lower()
    ...
```

Stuff I recognize: `def`, `return`, `if`, `for`. Stuff I don't: `dict`, `-> int`, the `"""..."""` triple-quotes, list comprehensions like `sum(1 for k in item['keywords'] if k.lower() in text)`. Honestly this is past where my class got. If I had to write this from scratch I would close the tab.

But — the sample is pre-filled! So I just hit Use sample → Load → Submit, same as before. And it scored **1.0000**. I was the #1 (and only) entry on the Track 4 leaderboard. So yes, "Build Your Own AI Judge" sounds terrifying but if you only need to submit the sample, it's not actually harder than Track 1.

The "Cohen's κ mapped to [0, 1]" thing I still cannot tell you what it means. I just know my number is high so I guess I won.

![screenshot](screenshots/jordan_t4_modal_loaded.png)
![screenshot](screenshots/jordan_t4_leaderboard.png)

Did I submit? **Yes.** Score: **1.0000.**

## What I'd tell my friends

Honestly? I'd tell them, "the first track is fun, the rest of them have words you have to Google." I would probably show my one CS friend (the one who actually likes Python) — she'd vibe with it. For everyone else it's intimidating. The "Use sample" button basically saves the whole thing — without it I'd have nothing to submit and would have closed the tab in 5 minutes.

## What would actually help me

1. **A "Beginner Mode" toggle** that hides scary words like "macro-F1," "Cohen's κ," "BM25," "token budget" and shows them as a normal-English sentence ("we check how many you got right, weighted across the three categories"). Right now it feels like the page was written for grad students and I'm reading their lab notebook.
2. **A clearer "you are submitting the example, not your own work yet" warning.** When my Track 1 score said 1.0000, I felt like a champion for two seconds and then realized everyone else also has 1.0000 because they all submitted the same sample. It would help to say "this is the demo sample — your real score will differ once you submit your own predictions."
3. **The student_id thing was a mess.** I told the page my ID was `jordan_hs_test` (in the JSON), but the leaderboard kept showing my row under random other names like `maya_cs_test` and `priya_biz_test` — apparently that's whatever the page remembered from a previous tester. There's a "Set ID" button on the Leaderboard tab that I missed at first. Either show that "Set ID" prompt the **first time** I open the site, or warn me when the ID in my JSON doesn't match the one the site has stored for me.

## Final scores

| Track | Did I submit? | Score |
|---|---|---|
| 1 — Hallucination Hunter | yes | 1.0000 |
| 2 — Prompt Golf | yes | 0.0000 |
| 3 — RAG Treasure Hunt | yes | 0.0000 |
| 4 — Build Your Own AI Judge | yes | 1.0000 |
