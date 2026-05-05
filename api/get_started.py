"""
Static "Get Started" page for AI Arena.

A self-contained HTML walkthrough of how to submit to each of the four
tracks: explanation, sample payload, copy-pasteable curl/PowerShell/Python,
expected response shape, and a link to the live leaderboard.

The page is built once at import time from the same SAMPLE_PAYLOADS dict
the `/samples/{track_id}` endpoint serves, so the worked examples and
the downloadable starter JSON can never drift apart.

Kept in its own module so api/main.py doesn't grow into a wall of HTML.
"""

from __future__ import annotations

import json
from html import escape

from api.sample_payloads import (
    SAMPLE_HALLUCINATION,
    SAMPLE_META_JUDGE,
    SAMPLE_PROMPT_GOLF,
    SAMPLE_RAG,
)


# ---------- Section data (single source of truth) ----------

_TRACKS: list[dict] = [
    {
        "id": "hallucination_hunter",
        "anchor": "track-1",
        "number": 1,
        "name": "Hallucination Hunter",
        "tagline": "Classify each claim as supported / refuted / not_enough_info.",
        "metric_label": "macro-F1",
        "metric_explainer": (
            "Macro-F1 weights every class equally, so under-predicting the rare "
            "<code>not_enough_info</code> class drags your score down even if your "
            "overall accuracy is high. Predict each class honestly."
        ),
        "what_to_submit": (
            "A list of <code>(claim_id, label)</code> pairs covering every claim in "
            "the test set. Labels must be one of the three strings above."
        ),
        "tips": [
            "Every claim_id in the gold set must appear exactly once.",
            "Unknown labels (e.g. \"maybe\") count as wrong but do not get their own class.",
            "Schema rejects empty <code>predictions</code> arrays — submit at least one.",
        ],
        "sample": SAMPLE_HALLUCINATION,
    },
    {
        "id": "prompt_golf",
        "anchor": "track-2",
        "number": 2,
        "name": "Prompt Golf",
        "tagline": "Find the shortest prompt that still answers correctly.",
        "metric_label": "judge accuracy &times; token efficiency",
        "metric_explainer": (
            "Each sample is judged for correctness against the hidden gold answer. "
            "Your score is the average judge score, then multiplied by "
            "<code>min(1.0, baseline_tokens / total_tokens)</code> — efficiency saturates "
            "at 1.0 so accuracy is the ceiling. A short prompt that scores 0.8 beats "
            "a long prompt that scores 0.8."
        ),
        "what_to_submit": (
            "Your <code>prompt_template</code> plus the (input, output) samples it "
            "produced when you ran it against the gold inputs. The <code>input</code> "
            "field of each sample must match a gold question exactly."
        ),
        "tips": [
            "All gold inputs must be covered. Missing samples raise a clean error.",
            "Token count is approximated as <code>chars / 4</code> per the standard rule of thumb.",
            "Free judge tokens for testing — but you have a 50,000 / day cap across all judge calls.",
        ],
        "sample": SAMPLE_PROMPT_GOLF,
    },
    {
        "id": "rag_treasure_hunt",
        "anchor": "track-3",
        "number": 3,
        "name": "RAG Treasure Hunt",
        "tagline": "Build a retrieval pipeline over the ISU course catalog.",
        "metric_label": "weighted rubric (correctness 30 / faithfulness 25 / retrieval 15 / citations 15 / cost 10 / safety 5)",
        "metric_explainer": (
            "Six dimensions per question, weighted-averaged. <strong>Correctness</strong>, "
            "<strong>faithfulness</strong>, and <strong>safety</strong> are LLM-judged. "
            "<strong>Retrieval</strong> is recall against gold-relevant chunks. "
            "<strong>Citations</strong> is F1 of cited chunk IDs vs. gold. "
            "<strong>Cost</strong> is your <code>estimated_cost_usd</code> against the baseline; "
            "spending less than baseline saturates at 1.0."
        ),
        "what_to_submit": (
            "One answer per question, plus the chunk IDs you retrieved and the chunk IDs "
            "you actually cited. Get the public corpus from "
            "<code>corpora/isu_course_catalog/index.json</code> in the repo and the public "
            "questions from <code>corpora/isu_course_catalog/questions.json</code>. The hidden "
            "gold answers and gold citations stay on the server."
        ),
        "tips": [
            "Cite chunks that justify your answer — <code>citations</code> is graded against gold.",
            "Surface every relevant chunk in <code>retrieved_contexts</code> — recall is graded too.",
            "Lower <code>estimated_cost_usd</code> earns you cost credit; clamps at 1.0 below baseline.",
        ],
        "sample": SAMPLE_RAG,
    },
    {
        "id": "meta_judge",
        "anchor": "track-4",
        "number": 4,
        "name": "Build Your Own AI Judge",
        "tagline": "Write an evaluator and prove it agrees with the instructor.",
        "metric_label": "linear-weighted Cohen's &kappa; mapped to [0, 1]",
        "metric_explainer": (
            "You submit your evaluator's source plus the 1-5 ordinal grades it produced "
            "on a calibration set. We compute linear-weighted Cohen's &kappa; against the "
            "instructor's gold ratings. <code>final_score = (&kappa; + 1) / 2</code>, so a "
            "perfect agreement scores 1.0, chance scores 0.5, and reverse agreement scores 0."
        ),
        "what_to_submit": (
            "Your <code>evaluator_source</code> (a short Python function), the "
            "<code>rubric_text</code> you used as a prompt, and your "
            "<code>self_grades</code> for every gold item. Linear weighting means an "
            "off-by-one rating is much better than off-by-three."
        ),
        "tips": [
            "Cover every gold item — missing items raise a clean error.",
            "Ordinal scale; integer ratings 1-5 work best.",
            "Source is grading-only material — the platform does not execute it.",
        ],
        "sample": SAMPLE_META_JUDGE,
    },
]


# ---------- Builders ----------

def _pretty(payload: dict) -> str:
    return escape(json.dumps(payload, indent=2))


def _powershell_block(track_id: str, sample: dict) -> str:
    body = json.dumps(sample, indent=2).replace("'", "''")
    return f"""$body = @'
{body}
'@
Invoke-RestMethod -Uri "{{BASE_URL}}/submit" -Method POST `\
  -ContentType "application/json" -Body $body
"""


def _bash_block(track_id: str, _sample: dict) -> str:
    return (
        f"# Download the starter sample, edit submission_id + student_id, then post:\n"
        f"curl -sS {{BASE_URL}}/samples/{track_id} > my_submission.json\n"
        f"# ... edit my_submission.json ...\n"
        f"curl -X POST {{BASE_URL}}/submit \\\n"
        f"  -H \"Content-Type: application/json\" \\\n"
        f"  --data-binary @my_submission.json\n"
    )


def _python_block(track_id: str, _sample: dict) -> str:
    return (
        f"import requests, json, uuid\n"
        f"\n"
        f"BASE_URL = \"{{BASE_URL}}\"\n"
        f"sample = requests.get(f\"{{BASE_URL}}/samples/{track_id}\").json()\n"
        f"sample[\"submission_id\"] = f\"sub_{{uuid.uuid4().hex[:8]}}\"\n"
        f"sample[\"student_id\"] = \"your_student_id\"\n"
        f"# ... edit sample[\"track_payload\"] to reflect YOUR work ...\n"
        f"r = requests.post(f\"{{BASE_URL}}/submit\", json=sample)\n"
        f"print(r.status_code, json.dumps(r.json(), indent=2))\n"
    )


def _track_section(t: dict) -> str:
    sample = t["sample"]
    pretty_sample = _pretty(sample)
    ps_block = escape(_powershell_block(t["id"], sample))
    bash_block = escape(_bash_block(t["id"], sample))
    py_block = escape(_python_block(t["id"], sample))
    tips = "".join(f"<li>{tip}</li>\n" for tip in t["tips"])

    return f"""
<section id="{t['anchor']}" class="track">
  <header class="track-header">
    <span class="track-num">Track {t['number']}</span>
    <h2>{escape(t['name'])}</h2>
    <p class="tagline">{escape(t['tagline'])}</p>
  </header>

  <div class="card">
    <h3>What you submit</h3>
    <p>{t['what_to_submit']}</p>
  </div>

  <div class="card">
    <h3>How you're scored</h3>
    <p><span class="metric">{t['metric_label']}</span></p>
    <p>{t['metric_explainer']}</p>
  </div>

  <div class="card">
    <h3>Tips</h3>
    <ul class="tips">{tips}</ul>
  </div>

  <div class="card">
    <h3>Sample submission &mdash; <a href="/samples/{t['id']}" class="dl">download JSON</a></h3>
    <p>This sample is built to score 1.0 against the in-tree gold data. Replace
    <code>submission_id</code> and <code>student_id</code>, then mutate the
    payload to reflect your own work.</p>
    <pre><code>{pretty_sample}</code></pre>
  </div>

  <div class="card">
    <h3>Submit it &mdash; PowerShell</h3>
    <pre><code>{ps_block}</code></pre>
  </div>

  <div class="card">
    <h3>Submit it &mdash; bash + curl</h3>
    <pre><code>{bash_block}</code></pre>
  </div>

  <div class="card">
    <h3>Submit it &mdash; Python</h3>
    <pre><code>{py_block}</code></pre>
  </div>

  <div class="card">
    <h3>Where to see your score</h3>
    <p>The worker scores your submission asynchronously (typically within ~5
    seconds). Check the leaderboard at:</p>
    <pre><code>GET {{BASE_URL}}/leaderboard/{t['id']}</code></pre>
    <p><a href="/leaderboard/{t['id']}" class="cta">Open this track's leaderboard &rarr;</a></p>
  </div>
</section>
"""


# ---------- Page assembly ----------

_HEAD_AND_NAV = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Get Started — AI Arena</title>
  <style>
    :root { color-scheme: dark; }
    body {
      margin: 0; padding: 0; min-height: 100vh;
      font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
      background: #0c1017; color: #f5f5f7; line-height: 1.55;
    }
    .accent  { color: #ffc107; }
    a        { color: #75c2ff; text-decoration: none; border-bottom: 1px dotted #4d8bd1; }
    a:hover  { color: #a4d6ff; border-bottom-style: solid; }
    code     { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
               font-size: 13px; background: #232c3d; padding: 2px 6px; border-radius: 4px; }
    pre      { background: #0a0d14; border: 1px solid #232c3d; border-radius: 8px;
               padding: 16px; overflow-x: auto; }
    pre code { background: transparent; padding: 0; font-size: 13px; line-height: 1.45; color: #d6dde6; }
    header.page {
      max-width: 1080px; margin: 0 auto; padding: 56px 24px 24px;
    }
    header.page h1   { font-size: 48px; margin: 0 0 8px 0; letter-spacing: -1px; }
    header.page p    { color: #a8b1bf; margin: 0; font-size: 18px; }
    .banner {
      max-width: 1080px; margin: 0 auto 8px; padding: 14px 22px;
      background: linear-gradient(135deg, #1c3654 0%, #1d2434 100%);
      border: 1px solid #2a4d77; border-radius: 12px;
      display: flex; align-items: center; justify-content: space-between;
      gap: 16px; flex-wrap: wrap;
    }
    .banner p { color: #d6dde6; margin: 0; font-size: 14px; }
    .banner a {
      background: #2c80ff; color: white; padding: 8px 16px; border-radius: 6px;
      font-weight: 600; font-size: 14px; border-bottom: none;
      white-space: nowrap; text-decoration: none;
    }
    .banner a:hover { background: #4592ff; border-bottom: none; }
    nav.toc {
      max-width: 1080px; margin: 0 auto; padding: 0 24px 16px;
      display: flex; gap: 12px; flex-wrap: wrap;
    }
    nav.toc a {
      background: #151c28; border: 1px solid #232c3d; border-radius: 999px;
      padding: 6px 14px; font-size: 13px; border-bottom: none;
    }
    main     { max-width: 1080px; margin: 0 auto; padding: 0 24px 56px; }
    section.track { margin: 32px 0 56px; }
    .track-header { margin: 0 0 16px; }
    .track-num    { color: #ffc107; font-size: 13px; font-weight: 700;
                    text-transform: uppercase; letter-spacing: 1px; }
    .track-header h2 { margin: 4px 0 4px; font-size: 30px; }
    .tagline      { color: #a8b1bf; margin: 0 0 8px; font-size: 16px; }
    .card {
      background: #151c28; border: 1px solid #232c3d; border-radius: 12px;
      padding: 18px 22px; margin: 12px 0;
    }
    .card h3   { margin: 0 0 8px 0; font-size: 16px; color: #ffd460;
                 text-transform: uppercase; letter-spacing: 0.6px; }
    .card p, .card li { color: #c9d1de; }
    .card .metric { display: inline-block; background: #232c3d; color: #a4d6ff;
                    padding: 6px 12px; border-radius: 6px; font-size: 14px;
                    font-family: ui-monospace, Menlo, Consolas, monospace; }
    .tips        { margin: 8px 0 0 18px; padding: 0; }
    .tips li     { margin: 6px 0; }
    .dl          { font-size: 13px; }
    .cta         { display: inline-block; margin-top: 6px; padding: 8px 14px;
                   background: #1d4d2b; color: #a6e8b6; border: 1px solid #2a6d3f;
                   border-radius: 6px; border-bottom: none; font-weight: 600; }
    .pill {
      display: inline-block; padding: 2px 10px; border-radius: 999px;
      background: #1d4d2b; color: #a6e8b6; font-size: 12px; font-weight: 600;
    }
    .preamble {
      background: #151c28; border: 1px solid #232c3d; border-radius: 12px;
      padding: 18px 22px; margin: 12px 0 24px;
    }
    .preamble h3 { margin: 0 0 8px 0; font-size: 16px; color: #ffd460;
                   text-transform: uppercase; letter-spacing: 0.6px; }
    footer {
      max-width: 1080px; margin: 0 auto; padding: 24px;
      color: #6d7787; font-size: 12px; text-align: center;
    }
  </style>
</head>
<body>
  <header class="page">
    <h1>Get <span class="accent">Started</span></h1>
    <p>How to submit to each AI Arena track. Pick a track below, copy the sample, edit it, post.</p>
  </header>
  <div class="banner">
    <p>
      <strong>Prefer the Kaggle-style UI?</strong> Each track now has its own
      page with an in-browser submit button, live leaderboard, and a "first
      submission in 60 seconds" path &mdash; no curl required.
    </p>
    <a href="/">Browse competitions &rarr;</a>
  </div>
  <nav class="toc" aria-label="Tracks">
    <a href="/">&larr; Home</a>
    <a href="#preamble">The submission envelope</a>
    <a href="#track-1">Track 1 &middot; Hallucination Hunter</a>
    <a href="#track-2">Track 2 &middot; Prompt Golf</a>
    <a href="#track-3">Track 3 &middot; RAG Treasure Hunt</a>
    <a href="#track-4">Track 4 &middot; Build Your Own Judge</a>
  </nav>
  <main>
"""

_PREAMBLE = """
    <section id="preamble" class="preamble">
      <h3>The submission envelope (every track)</h3>
      <p>All four tracks share the same outer envelope. Only <code>track_payload</code> changes:</p>
      <pre><code>{
  "submission_id": "your_unique_id",         // any string unique to this submission
  "student_id":    "your_student_id",        // same across all your submissions
  "track_id":      "&lt;one of the four ids&gt;",
  "submission_timestamp": "2026-06-15T14:32:00Z",
  "model_used":    "claude-haiku-4-5",       // optional, free-text
  "prompt_version": "v3",                    // optional, free-text
  "self_reported_strategy": "...",           // optional, free-text
  "track_payload": { /* track-specific fields below */ }
}</code></pre>
      <p>POST to <code>/submit</code>. You'll get back <code>submission_id</code>,
      a Cloud Tasks <code>task_id</code>, and your daily-submission counter.
      The worker scores asynchronously and writes to the leaderboard.</p>
      <p><span class="pill">Daily limits</span> 5 submissions per <code>student_id</code>
      per UTC day &middot; 50,000 judge tokens per <code>student_id</code> per UTC day.</p>
    </section>
"""

_TAIL = """
  </main>
  <footer>
    Iowa State University &middot; Department of Computer Science &middot;
    <a href="mailto:adisak.sukul@gmail.com">Adisak Sukul</a>
  </footer>
</body>
</html>
"""


def render_get_started_html(*, base_url: str = "") -> str:
    """Build the page. `base_url` is substituted into every code sample.

    Pass an empty string for relative samples (the default — works locally
    and in production without knowing the deploy URL); pass a full URL when
    rendering for offline distribution.
    """
    body = _HEAD_AND_NAV + _PREAMBLE
    for t in _TRACKS:
        body += _track_section(t)
    body += _TAIL
    return body.replace("{BASE_URL}", base_url)
