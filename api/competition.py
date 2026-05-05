"""
Per-track Kaggle-style competition page.

Route:  GET /competitions/{track_id}

Renders a single self-contained HTML page with the familiar Kaggle layout:

  ┌──────────────────────────────────────────────────────────────┐
  │ Track 3 · RAG Treasure Hunt          [ ↑ Submit Entry ]      │
  │ Build a retrieval pipeline over the ISU course catalog        │
  │ [ Active ] [ Eval: weighted rubric ] [ N submissions ]        │
  ├──────────────────────────────────────────────────────────────┤
  │ Overview │ Data │ Code │ Leaderboard │ Rules                  │
  └──────────────────────────────────────────────────────────────┘

All five tabs are rendered server-side. Tab switching is hash-routed
(`#overview`, `#data`, `#code`, `#leaderboard`, `#rules`), implemented in a
small inline `<script>` so deep-linking works and the page is shareable.

The Leaderboard tab is also rendered server-side from the live store, then
auto-refreshes every 10 seconds against `GET /leaderboard/{track_id}` JSON.

The Submit modal posts to `/submit` via fetch and shows the response inline,
so students never leave the page. Three input modes:
  - Paste JSON
  - Upload .json file
  - "Use sample as starting point" — pre-fills the textarea with the
    canonical sample after rewriting the placeholder IDs.

This module is a renderer only — wiring is in `api/main.py`.
"""

from __future__ import annotations

import json
from html import escape
from typing import Any

from api.competition_data import TRACKS_META, TrackMeta, get_track


# ---------- Shared CSS ----------
#
# Inlined so the page is one self-contained response. Designed to look
# Kaggle-adjacent: dark theme, accent-coloured primary CTAs, clear tab nav,
# tabular leaderboard.

_PAGE_CSS = """
:root { color-scheme: dark; }
* { box-sizing: border-box; }
body {
  margin: 0; padding: 0; min-height: 100vh;
  font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  background: #0c1017; color: #f5f5f7; line-height: 1.5;
}
a { color: #75c2ff; text-decoration: none; }
a:hover { color: #a4d6ff; text-decoration: underline; }
code, pre {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 13px;
}
code { background: #1d2434; padding: 2px 6px; border-radius: 4px; color: #e6edf6; }
pre {
  background: #0a0d14; border: 1px solid #232c3d; border-radius: 8px;
  padding: 16px; overflow-x: auto; margin: 12px 0;
}
pre code { background: transparent; padding: 0; color: #d6dde6; line-height: 1.45; }

/* ---------- Top bar ---------- */
.topbar {
  background: #0a0d14; border-bottom: 1px solid #1d2434;
  padding: 0 24px; height: 48px;
  display: flex; align-items: center; gap: 24px;
  position: sticky; top: 0; z-index: 50;
}
.topbar .logo { font-weight: 700; color: #f5f5f7; }
.topbar .logo .accent { color: #ffc107; }
.topbar .topbar-nav { display: flex; gap: 18px; }
.topbar .topbar-nav a {
  color: #a8b1bf; font-size: 14px; padding: 8px 0;
  border-bottom: 2px solid transparent; text-decoration: none;
}
.topbar .topbar-nav a:hover { color: #f5f5f7; }
.topbar .topbar-nav a.active { color: #f5f5f7; border-bottom-color: #ffc107; }

/* ---------- Competition header ---------- */
.comp-header {
  background: #11161f; border-bottom: 1px solid #1d2434;
  padding: 32px 24px 0;
}
.comp-header-inner {
  max-width: 1200px; margin: 0 auto;
  display: flex; align-items: flex-start; justify-content: space-between;
  gap: 24px; flex-wrap: wrap;
}
.comp-meta { flex: 1 1 600px; min-width: 0; }
.track-num {
  font-size: 12px; font-weight: 700; letter-spacing: 1.2px;
  text-transform: uppercase; margin-bottom: 4px;
}
.comp-meta h1 {
  font-size: 32px; margin: 0 0 6px 0; letter-spacing: -0.4px;
}
.comp-meta .tagline { color: #a8b1bf; margin: 0 0 14px 0; font-size: 15px; }
.badges { display: flex; gap: 8px; flex-wrap: wrap; }
.pill {
  display: inline-flex; align-items: center; padding: 4px 11px;
  border-radius: 999px; font-size: 12px; font-weight: 600;
  background: #1d2434; color: #c9d1de;
}
.pill.pill-active { background: #1d4d2b; color: #a6e8b6; }
.pill.pill-metric { background: #1c3654; color: #a4d6ff; }
.pill.pill-count { background: #232c3d; color: #c9d1de; }

/* ---------- Submit button (top-right) ---------- */
.btn-submit {
  background: #2c80ff; color: white; font-weight: 600; font-size: 14px;
  padding: 10px 20px; border-radius: 8px; border: none; cursor: pointer;
  display: inline-flex; align-items: center; gap: 8px; white-space: nowrap;
}
.btn-submit:hover { background: #4592ff; }
.btn-submit .arrow { font-size: 16px; line-height: 1; }

/* ---------- Tab nav ---------- */
.tab-nav {
  max-width: 1200px; margin: 24px auto 0;
  display: flex; gap: 4px; border-bottom: 1px solid #232c3d;
  overflow-x: auto;
}
.tab-link {
  padding: 12px 18px; color: #a8b1bf; font-size: 14px; font-weight: 500;
  border-bottom: 2px solid transparent; cursor: pointer; white-space: nowrap;
  text-decoration: none;
}
.tab-link:hover { color: #f5f5f7; text-decoration: none; }
.tab-link.active { color: #f5f5f7; border-bottom-color: var(--accent, #ffc107); }

/* ---------- Tab panels ---------- */
main {
  max-width: 1200px; margin: 0 auto; padding: 32px 24px 64px;
}
.tab-panel { display: none; }
.tab-panel.active { display: block; }

.section-card {
  background: #151c28; border: 1px solid #232c3d; border-radius: 12px;
  padding: 22px 26px; margin: 0 0 18px 0;
}
.section-card h2 {
  margin: 0 0 12px 0; font-size: 18px; color: #ffd460;
  text-transform: uppercase; letter-spacing: 0.6px;
}
.section-card h3 { margin: 16px 0 8px; font-size: 15px; color: #f5f5f7; }
.section-card p, .section-card li { color: #c9d1de; }
.section-card ul { padding-left: 20px; margin: 8px 0; }
.section-card li { margin: 6px 0; }
.section-card .formula {
  display: block; background: #0a0d14; border: 1px solid #232c3d;
  border-radius: 8px; padding: 14px 16px; font-family: ui-monospace, Menlo, Consolas, monospace;
  font-size: 14px; color: #a4d6ff; margin: 10px 0;
}

/* ---------- Sixty-second card on Overview ---------- */
.sixty-sec {
  background: linear-gradient(135deg, #1c3654 0%, #1d2434 100%);
  border: 1px solid #2a4d77; border-radius: 12px; padding: 22px 26px;
  margin: 0 0 22px 0;
}
.sixty-sec h2 { color: #a4d6ff; margin-top: 0; }
.sixty-sec ol { padding-left: 22px; margin: 0; }
.sixty-sec li { margin: 8px 0; color: #d6dde6; }
.sixty-sec .quick-cta {
  display: inline-block; margin-top: 14px; padding: 10px 18px;
  background: #2c80ff; color: white; border-radius: 8px; font-weight: 600;
  text-decoration: none; font-size: 14px;
}
.sixty-sec .quick-cta:hover { background: #4592ff; text-decoration: none; }

/* ---------- Data tab ---------- */
table.files {
  width: 100%; border-collapse: collapse; margin: 8px 0;
}
table.files th, table.files td {
  text-align: left; padding: 10px 12px; border-bottom: 1px solid #232c3d;
  font-size: 14px;
}
table.files th {
  color: #a8b1bf; font-weight: 600; font-size: 12px;
  text-transform: uppercase; letter-spacing: 0.5px;
}
table.files .name { font-family: ui-monospace, Menlo, Consolas, monospace; color: #a4d6ff; }
table.files .badge {
  display: inline-block; padding: 2px 8px; border-radius: 999px;
  background: #232c3d; color: #c9d1de; font-size: 11px; font-weight: 600;
}
table.files .badge.public { background: #1d4d2b; color: #a6e8b6; }
table.files .badge.hidden { background: #4d1d1d; color: #f5b8b8; }

/* ---------- Code tab ---------- */
.code-tabs { display: flex; gap: 4px; margin-bottom: 0; border-bottom: 1px solid #232c3d; }
.code-tab {
  padding: 8px 16px; font-size: 13px; color: #a8b1bf; cursor: pointer;
  border: none; background: transparent;
  border-bottom: 2px solid transparent;
}
.code-tab.active { color: #f5f5f7; border-bottom-color: var(--accent, #ffc107); }
.code-block { display: none; }
.code-block.active { display: block; }
.copy-btn {
  float: right; font-size: 11px; padding: 4px 10px; background: #1d2434;
  color: #c9d1de; border: 1px solid #232c3d; border-radius: 4px; cursor: pointer;
}
.copy-btn:hover { background: #2a3447; }

/* ---------- Leaderboard tab ---------- */
table.leaderboard {
  width: 100%; border-collapse: collapse; background: #151c28;
  border: 1px solid #232c3d; border-radius: 12px; overflow: hidden;
}
table.leaderboard th, table.leaderboard td {
  padding: 12px 16px; text-align: left; border-bottom: 1px solid #1d2434;
  font-size: 14px;
}
table.leaderboard th {
  background: #11161f; color: #a8b1bf; font-weight: 600; font-size: 12px;
  text-transform: uppercase; letter-spacing: 0.5px;
}
table.leaderboard th.sortable {
  cursor: pointer; user-select: none; position: relative;
}
table.leaderboard th.sortable:hover { color: #f5f5f7; background: #14202f; }
table.leaderboard th.sortable .sort-indicator {
  margin-left: 4px; opacity: 0.4; font-size: 10px;
}
table.leaderboard th.sortable.active { color: #f5f5f7; }
table.leaderboard th.sortable.active .sort-indicator { opacity: 1; color: var(--accent, #ffc107); }
table.leaderboard tr:last-child td { border-bottom: none; }
table.leaderboard tr.is-you {
  background: rgba(44, 128, 255, 0.10);
  outline: 1px solid #2c80ff;
}
table.leaderboard tr.is-you .student::before {
  content: "👤 "; opacity: 0.7;
}
table.leaderboard .rank { color: #a8b1bf; font-family: ui-monospace, Menlo, Consolas, monospace; }
table.leaderboard .top-1 .rank { color: #ffd700; font-weight: 700; }
table.leaderboard .top-2 .rank { color: #c0c0c0; font-weight: 700; }
table.leaderboard .top-3 .rank { color: #cd7f32; font-weight: 700; }
table.leaderboard .student { font-weight: 600; color: #f5f5f7; }
table.leaderboard .score {
  font-family: ui-monospace, Menlo, Consolas, monospace;
  color: var(--accent, #ffc107); font-weight: 700;
}
table.leaderboard .empty { color: #6d7787; text-align: center; padding: 32px; font-style: italic; }
.leaderboard-meta {
  display: flex; justify-content: space-between; align-items: center;
  margin: 0 0 12px 0; flex-wrap: wrap; gap: 12px;
}
.leaderboard-meta .refresh-status { color: #a8b1bf; font-size: 12px; }
.leaderboard-meta .refresh-status.live::before {
  content: "● "; color: #4ade80;
}
.lb-controls {
  display: flex; justify-content: space-between; align-items: center;
  background: #11161f; border: 1px solid #232c3d; border-radius: 8px;
  padding: 10px 14px; margin: 0 0 12px 0; gap: 12px; flex-wrap: wrap;
  font-size: 13px;
}
.lb-controls .you-line { color: #c9d1de; }
.lb-controls .you-line .you-id {
  color: #2c80ff; font-weight: 600;
  font-family: ui-monospace, Menlo, Consolas, monospace;
}
.lb-controls .you-line .you-empty { color: #6d7787; font-style: italic; }
.lb-controls button.btn-tiny {
  background: transparent; color: #75c2ff; border: 1px solid #2a3447;
  padding: 4px 10px; border-radius: 4px; font-size: 12px; cursor: pointer;
  margin-left: 6px;
}
.lb-controls button.btn-tiny:hover { color: #a4d6ff; border-color: #4a5568; }
.lb-controls .filter-toggle {
  display: inline-flex; align-items: center; gap: 6px;
  color: #c9d1de; cursor: pointer; user-select: none;
}
.lb-controls .filter-toggle input[disabled] + span {
  color: #6d7787; cursor: not-allowed;
}
.lb-controls .filter-toggle input { cursor: pointer; }

/* ---------- Submit modal ---------- */
.modal-backdrop {
  position: fixed; inset: 0; background: rgba(0, 0, 0, 0.7);
  z-index: 100; display: none; align-items: center; justify-content: center;
}
.modal-backdrop.open { display: flex; }
.modal-card {
  background: #151c28; border: 1px solid #232c3d; border-radius: 12px;
  width: min(720px, 90vw); max-height: 90vh; overflow-y: auto;
  display: flex; flex-direction: column;
}
.modal-card header {
  padding: 18px 24px; border-bottom: 1px solid #232c3d;
  display: flex; align-items: center; justify-content: space-between;
}
.modal-card header h2 { margin: 0; font-size: 18px; color: #f5f5f7; }
.modal-card .close {
  background: transparent; border: none; color: #a8b1bf; font-size: 24px;
  cursor: pointer; line-height: 1;
}
.modal-card .body { padding: 18px 24px; }
.modal-card footer {
  padding: 14px 24px; border-top: 1px solid #232c3d;
  display: flex; justify-content: flex-end; gap: 8px;
}
.mode-tabs { display: flex; gap: 4px; margin-bottom: 14px; border-bottom: 1px solid #232c3d; }
.mode-tab {
  padding: 8px 16px; font-size: 13px; color: #a8b1bf; cursor: pointer;
  border: none; background: transparent;
  border-bottom: 2px solid transparent;
}
.mode-tab.active { color: #f5f5f7; border-bottom-color: #2c80ff; }
.mode-panel { display: none; }
.mode-panel.active { display: block; }
textarea.json-input {
  width: 100%; min-height: 220px; background: #0a0d14; color: #d6dde6;
  border: 1px solid #232c3d; border-radius: 8px; padding: 12px;
  font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 12.5px;
  line-height: 1.5; resize: vertical;
}
.dropzone {
  border: 2px dashed #2a3447; border-radius: 8px; padding: 36px 24px;
  text-align: center; color: #a8b1bf; cursor: pointer;
}
.dropzone.drag { border-color: #2c80ff; background: rgba(44, 128, 255, 0.08); color: #f5f5f7; }
.dropzone input[type="file"] { display: none; }
.btn { padding: 9px 16px; border-radius: 6px; font-size: 14px; cursor: pointer; border: 1px solid transparent; font-weight: 600; }
.btn-cancel { background: transparent; color: #a8b1bf; border-color: #2a3447; }
.btn-cancel:hover { color: #f5f5f7; border-color: #4a5568; }
.btn-primary { background: #2c80ff; color: white; }
.btn-primary:hover { background: #4592ff; }
.btn-primary:disabled { background: #2a3447; cursor: not-allowed; }
.submit-result {
  margin-top: 14px; padding: 12px 14px; border-radius: 8px;
  font-size: 13px; font-family: ui-monospace, Menlo, Consolas, monospace;
  white-space: pre-wrap; word-break: break-word;
}
.submit-result.ok { background: #102d1b; color: #a6e8b6; border: 1px solid #1d4d2b; }
.submit-result.err { background: #2d1010; color: #f5b8b8; border: 1px solid #4d1d1d; }

footer.page-footer {
  max-width: 1200px; margin: 0 auto; padding: 32px 24px;
  color: #6d7787; font-size: 12px; text-align: center; border-top: 1px solid #1d2434;
}

/* Wrap the leaderboard so it scrolls horizontally on narrow screens
   instead of clipping the Submission column. */
.lb-scroll { overflow-x: auto; -webkit-overflow-scrolling: touch; }
.lb-scroll table.leaderboard { min-width: 560px; }

/* ---------- Mobile tweaks ----------
   Targets phones (≤600px). Tightens padding, reduces the giant heading,
   stacks the header content cleanly, and lets the tab strip scroll
   instead of wrapping. */
@media (max-width: 600px) {
  .topbar { padding: 0 14px; gap: 14px; }
  .topbar .topbar-nav { gap: 14px; }

  .comp-header { padding: 18px 14px 0; }
  .comp-header-inner { gap: 12px; }
  .comp-meta h1 { font-size: 24px; letter-spacing: -0.2px; }
  .comp-meta .tagline { font-size: 14px; }
  .btn-submit { padding: 9px 16px; font-size: 13px; }
  .pill { font-size: 11px; padding: 3px 9px; }

  /* Tab strip: smaller hitboxes, but still scrollable if anything
     overflows. */
  .tab-nav { margin-top: 16px; padding-bottom: 0; }
  .tab-link { padding: 10px 12px; font-size: 13px; }

  main { padding: 20px 14px 48px; }
  .section-card { padding: 16px 18px; }
  .section-card h2 { font-size: 16px; }

  .sixty-sec { padding: 18px 18px; }
  .sixty-sec h2 { font-size: 18px; }

  /* Code-tab headers shrink so all three labels (PowerShell / bash + curl
     / Python) fit without wrapping. */
  .code-tab { padding: 7px 10px; font-size: 12px; }

  /* Modal: full-width on phone, bottom-aligned footer stays sticky-ish. */
  .modal-card { width: 96vw; max-height: 92vh; }
  .modal-card header { padding: 14px 16px; }
  .modal-card .body { padding: 14px 16px; }
  .modal-card footer { padding: 12px 16px; }

  /* Leaderboard tweaks: stack the controls and tighten the cells. */
  .leaderboard-meta { font-size: 13px; }
  .lb-controls { padding: 8px 12px; gap: 8px; }
  .lb-controls .you-line { font-size: 12.5px; }
  table.leaderboard th, table.leaderboard td { padding: 9px 10px; font-size: 13px; }
}
"""


# ---------- Per-tab renderers ----------

def _overview_panel(t: TrackMeta) -> str:
    tips = "".join(f"<li>{tip}</li>\n" for tip in t.tips)
    return f"""
<section data-tab="overview" class="tab-panel">
  <div class="sixty-sec">
    <h2>First submission in 60 seconds</h2>
    <ol>
      <li>Click the blue <strong>Submit Entry</strong> button (top-right).</li>
      <li>Switch to <strong>Use sample as starting point</strong>.</li>
      <li>Replace <code>student_id</code> with your own and hit <strong>Submit</strong>.</li>
      <li>Watch your score appear on the <a href="#leaderboard" class="quick-tab-link">Leaderboard</a> tab.</li>
    </ol>
    <a href="#" class="quick-cta" data-open-submit>Open submit dialog &rarr;</a>
  </div>

  <div class="section-card">
    <h2>Description</h2>
    {t.description}
  </div>

  <div class="section-card">
    <h2>Evaluation</h2>
    <p><strong>Metric:</strong> {t.metric_label}</p>
    <span class="formula">{t.metric_formula}</span>
    <p>{t.metric_explainer}</p>
  </div>

  <div class="section-card">
    <h2>What you submit</h2>
    <p>{t.what_to_submit}</p>
    <h3>Tips</h3>
    <ul>{tips}</ul>
  </div>
</section>
"""


def _data_panel(t: TrackMeta) -> str:
    rows = []
    for f in t.data_files:
        badge = '<span class="badge public">public</span>' if f.public else '<span class="badge hidden">hidden</span>'
        if f.public and f.href:
            name_cell = f'<a href="{escape(f.href)}" class="name">{escape(f.name)}</a>'
        else:
            name_cell = f'<span class="name">{escape(f.name)}</span>'
        rows.append(
            f"<tr><td>{name_cell}</td><td>{f.purpose}</td><td>{badge}</td></tr>"
        )
    rows_html = "\n".join(rows)

    return f"""
<section data-tab="data" class="tab-panel">
  <div class="section-card">
    <h2>Files</h2>
    <table class="files">
      <thead>
        <tr><th>Name</th><th>Purpose</th><th>Visibility</th></tr>
      </thead>
      <tbody>
        {rows_html}
      </tbody>
    </table>
  </div>

  <div class="section-card">
    <h2>Submission envelope</h2>
    <p>All four tracks share the same outer envelope. Only <code>track_payload</code> changes:</p>
    <pre><code>{{
  "submission_id":         "your_unique_id",
  "student_id":            "your_student_id",
  "track_id":              "{t.id}",
  "submission_timestamp":  "2026-06-15T14:32:00Z",
  "model_used":            "claude-haiku-4-5",
  "prompt_version":        "v3",
  "self_reported_strategy": "Hybrid BM25 + dense, top-5 chunks",
  "track_payload":         {{ /* track-specific fields */ }}
}}</code></pre>
  </div>

  <div class="section-card">
    <h2>Sample submission (scores 1.0)</h2>
    <p>This is the canonical sample for this track &mdash; replace
    <code>submission_id</code> and <code>student_id</code>, then mutate
    <code>track_payload</code> to reflect your own work.</p>
    <pre><code>{escape(json.dumps(t.sample, indent=2))}</code></pre>
    <p><a href="/samples/{t.id}">Download as JSON &rarr;</a></p>
  </div>
</section>
"""


def _code_panel(t: TrackMeta) -> str:
    sample_pretty = escape(json.dumps(t.sample, indent=2))
    sample_ps_safe = json.dumps(t.sample, indent=2).replace("'", "''")

    powershell = f"""$body = @'
{sample_ps_safe}
'@
Invoke-RestMethod -Uri "{{BASE_URL}}/submit" -Method POST `
    -ContentType "application/json" -Body $body
"""

    bash = f"""# Download the starter sample, edit submission_id + student_id, then post:
curl -sS {{BASE_URL}}/samples/{t.id} > my_submission.json
# ... edit my_submission.json ...
curl -X POST {{BASE_URL}}/submit \\
  -H "Content-Type: application/json" \\
  --data-binary @my_submission.json
"""

    python = f"""import requests, json, uuid

BASE_URL = "{{BASE_URL}}"
sample = requests.get(f"{{BASE_URL}}/samples/{t.id}").json()
sample["submission_id"] = f"sub_{{uuid.uuid4().hex[:8]}}"
sample["student_id"] = "your_student_id"
# ... edit sample["track_payload"] to reflect YOUR work ...
r = requests.post(f"{{BASE_URL}}/submit", json=sample)
print(r.status_code, json.dumps(r.json(), indent=2))
"""

    reference_block = ""
    if t.reference_notebook:
        reference_block = f"""
  <div class="section-card">
    <h2>Reference solution</h2>
    <p>A complete working baseline lives at
    <a href="{escape(t.reference_notebook)}"><code>docs/track{t.number}_reference_solution.ipynb</code></a>.
    It implements the full pipeline end-to-end &mdash; not a perfect score, but a
    fork-able floor. The notebook's last section names the dimensions where this
    baseline is weak so you know where to push first.</p>
  </div>
"""

    return f"""
<section data-tab="code" class="tab-panel">
  <div class="section-card">
    <h2>Starter notebook</h2>
    <p>The four-track Colab notebook lives in the repo at
    <a href="https://github.com/asukul/AI-arena/blob/main/docs/student_starter.ipynb">
    <code>docs/student_starter.ipynb</code></a>. It posts to this Cloud Run URL
    by default and walks through every track end-to-end &mdash;
    <strong>Copy &amp; Edit</strong> it like a Kaggle kernel.</p>
  </div>

  {reference_block}

  <div class="section-card">
    <h2>Submit from your own machine</h2>
    <div class="code-tabs">
      <button class="code-tab active" data-code-tab="ps">PowerShell</button>
      <button class="code-tab" data-code-tab="bash">bash + curl</button>
      <button class="code-tab" data-code-tab="py">Python</button>
    </div>

    <div class="code-block active" data-code-block="ps">
      <button class="copy-btn" data-copy-target="block-ps">Copy</button>
      <pre><code id="block-ps">{escape(powershell)}</code></pre>
    </div>
    <div class="code-block" data-code-block="bash">
      <button class="copy-btn" data-copy-target="block-bash">Copy</button>
      <pre><code id="block-bash">{escape(bash)}</code></pre>
    </div>
    <div class="code-block" data-code-block="py">
      <button class="copy-btn" data-copy-target="block-py">Copy</button>
      <pre><code id="block-py">{escape(python)}</code></pre>
    </div>
  </div>

  <div class="section-card">
    <h2>Sample payload</h2>
    <p>The same payload you can fetch at
    <a href="/samples/{t.id}"><code>/samples/{t.id}</code></a>:</p>
    <pre><code>{sample_pretty}</code></pre>
  </div>
</section>
"""


def _leaderboard_panel(t: TrackMeta, rows: list[dict[str, Any]]) -> str:
    if not rows:
        body = '<tr><td colspan="5" class="empty">No submissions yet for this track. Be the first!</td></tr>'
    else:
        out = []
        for i, r in enumerate(rows, start=1):
            cls = ""
            if i == 1: cls = "top-1"
            elif i == 2: cls = "top-2"
            elif i == 3: cls = "top-3"
            scored_at = escape(str(r.get("scored_at", "")))
            out.append(
                f'<tr class="{cls}">'
                f'<td class="rank">#{i}</td>'
                f'<td class="student">{escape(str(r.get("student_id", "")))}</td>'
                f'<td class="score">{float(r.get("final_score", 0)):.4f}</td>'
                f'<td><code>{escape(str(r.get("submission_id", "")))}</code></td>'
                f'<td>{scored_at}</td>'
                f'</tr>'
            )
        body = "\n".join(out)

    return f"""
<section data-tab="leaderboard" class="tab-panel">
  <div class="leaderboard-meta">
    <div>
      <strong>Best score per student</strong> &middot;
      <span id="lb-count">{len(rows)}</span> entries
    </div>
    <div class="refresh-status live" id="lb-status">Live &middot; refreshing every 10s</div>
  </div>
  <div class="lb-controls">
    <div class="you-line">
      <span id="you-line-text" class="you-empty">You aren't signed in &mdash; submit once and we'll remember your <code>student_id</code>.</span>
      <button class="btn-tiny" id="set-id-btn" type="button">Set ID</button>
    </div>
    <label class="filter-toggle">
      <input type="checkbox" id="filter-mine" disabled>
      <span>Show only my submissions</span>
    </label>
  </div>
  <div class="lb-scroll">
    <table class="leaderboard">
      <thead>
        <tr>
          <th class="sortable" data-sort="rank">Rank<span class="sort-indicator"></span></th>
          <th class="sortable" data-sort="student_id">Student<span class="sort-indicator"></span></th>
          <th class="sortable active" data-sort="final_score" data-default-dir="desc">Score<span class="sort-indicator">▼</span></th>
          <th>Submission</th>
          <th class="sortable" data-sort="scored_at">Updated<span class="sort-indicator"></span></th>
        </tr>
      </thead>
      <tbody id="lb-rows">
        {body}
      </tbody>
    </table>
  </div>
  <p style="color:#6d7787; font-size:12px; margin-top:12px;">
    Raw JSON: <a href="/leaderboard/{t.id}"><code>/leaderboard/{t.id}</code></a>
  </p>
</section>
"""


def _rules_panel(t: TrackMeta) -> str:
    judge_line = (
        f"<li><strong>{t.judge_tokens_per_day:,} judge tokens / day</strong> per "
        f"<code>student_id</code> &mdash; counts every Claude API call this track makes "
        f"on your behalf.</li>"
        if t.judge_tokens_per_day > 0
        else "<li>This track does <strong>not</strong> call the judge model, so no token budget applies.</li>"
    )
    return f"""
<section data-tab="rules" class="tab-panel">
  <div class="section-card">
    <h2>Submission limits</h2>
    <ul>
      <li><strong>{t.rate_limit_per_day} submissions / day</strong> per <code>student_id</code>,
          UTC reset. Returns HTTP 429 once exhausted.</li>
      {judge_line}
      <li>Best score wins &mdash; we keep your highest <code>final_score</code> across all submissions
          (Kaggle convention). The leaderboard shows your best, not your latest.</li>
    </ul>
  </div>

  <div class="section-card">
    <h2>Hidden test set</h2>
    <p>Gold answers, gold citations, and gold ratings live on the server and are
    never returned in API responses &mdash; only your <em>scores</em> come back.
    The platform reads gold data from <code>corpora/gold/{t.id}.json</code>
    in the running container; you cannot reach it from <code>/submit</code> or
    <code>/leaderboard</code>.</p>
  </div>

  <div class="section-card">
    <h2>Anti-cheat</h2>
    <ul>
      <li>Judge calls run at <code>temperature=0</code> across all tracks &mdash;
          two identical inputs always get identical scores.</li>
      <li>Top 10% of each leaderboard is re-graded by Gemini Flash; cross-family
          disagreement &gt; 10% triggers manual review.</li>
      <li>Submitting under a fake <code>student_id</code> to dodge the per-day cap
          violates the bootcamp honor code &mdash; this is the same student account
          that owns your Canvas grade.</li>
    </ul>
  </div>

  <div class="section-card">
    <h2>Late policy</h2>
    <p>Submissions after the bootcamp deadline still get scored and appear on
    the leaderboard with a <code>Late</code> badge, but are excluded from the
    final ranking unless an instructor extension was granted in advance.</p>
  </div>
</section>
"""


# ---------- Page assembly ----------

def _topbar() -> str:
    return """
<div class="topbar">
  <a href="/" class="logo">AI <span class="accent">Arena</span></a>
  <nav class="topbar-nav">
    <a href="/" class="active">Competitions</a>
    <a href="/get-started">Docs</a>
    <a href="https://github.com/asukul/AI-arena">GitHub</a>
  </nav>
</div>
"""


def _comp_header(t: TrackMeta, total_submissions: int, total_students: int) -> str:
    return f"""
<header class="comp-header" style="--accent: {t.accent};">
  <div class="comp-header-inner">
    <div class="comp-meta">
      <div class="track-num" style="color: {t.accent};">Track {t.number}</div>
      <h1>{escape(t.name)}</h1>
      <p class="tagline">{escape(t.tagline)}</p>
      <div class="badges">
        <span class="pill pill-active">Active</span>
        <span class="pill pill-metric">Eval: {t.metric_label}</span>
        <span class="pill pill-count" id="hdr-submission-count">{total_submissions} submission{'s' if total_submissions != 1 else ''}</span>
        <span class="pill pill-count" id="hdr-student-count">{total_students} student{'s' if total_students != 1 else ''}</span>
      </div>
    </div>
    <button class="btn-submit" data-open-submit>
      <span class="arrow">&uarr;</span> Submit Entry
    </button>
  </div>
  <nav class="tab-nav">
    <a href="#overview"     class="tab-link active" data-tab-link="overview">Overview</a>
    <a href="#data"         class="tab-link"        data-tab-link="data">Data</a>
    <a href="#code"         class="tab-link"        data-tab-link="code">Code</a>
    <a href="#leaderboard"  class="tab-link"        data-tab-link="leaderboard">Leaderboard</a>
    <a href="#rules"        class="tab-link"        data-tab-link="rules">Rules</a>
  </nav>
</header>
"""


def _submit_modal(t: TrackMeta) -> str:
    sample_json = json.dumps(t.sample, indent=2)
    return f"""
<div class="modal-backdrop" id="submit-modal" role="dialog" aria-modal="true" aria-labelledby="submit-title">
  <div class="modal-card">
    <header>
      <h2 id="submit-title">Submit to {escape(t.name)}</h2>
      <button class="close" data-close-submit aria-label="Close">&times;</button>
    </header>
    <div class="body">
      <div class="mode-tabs">
        <button class="mode-tab active" data-mode="paste">Paste JSON</button>
        <button class="mode-tab"        data-mode="upload">Upload .json</button>
        <button class="mode-tab"        data-mode="sample">Use sample</button>
      </div>

      <div class="mode-panel active" data-mode-panel="paste">
        <p style="color:#a8b1bf; font-size:13px; margin:0 0 8px 0;">
          Paste a complete submission JSON (envelope + <code>track_payload</code>).
        </p>
        <textarea class="json-input" id="paste-input" spellcheck="false" placeholder="{{ ... }}"></textarea>
      </div>

      <div class="mode-panel" data-mode-panel="upload">
        <label class="dropzone" id="dropzone">
          <strong>Click to select</strong> or drag &amp; drop a <code>.json</code> file here.
          <input type="file" accept="application/json,.json" id="file-input">
          <div id="dropzone-msg" style="margin-top:10px; font-size:12px; color:#75c2ff;"></div>
        </label>
      </div>

      <div class="mode-panel" data-mode-panel="sample">
        <p style="color:#a8b1bf; font-size:13px;">
          Loads the canonical sample for this track &mdash; the one that scores
          1.0 against the in-tree gold. Replace <code>student_id</code> with
          your own ID before submitting; the <code>submission_id</code> is
          regenerated automatically each time you load.
        </p>
        <button class="btn btn-primary" id="load-sample-btn" type="button">Load sample into editor</button>
      </div>

      <div class="submit-result" id="submit-result" style="display:none;"></div>
    </div>
    <footer>
      <button class="btn btn-cancel" data-close-submit type="button">Cancel</button>
      <button class="btn btn-primary" id="do-submit" type="button">Submit Entry</button>
    </footer>
  </div>
</div>

<script id="canonical-sample" type="application/json">{sample_json}</script>
"""


def _page_script(track_id: str) -> str:
    # All client-side behavior in one inline script: tab routing, code-tab
    # switching, copy buttons, submit modal, leaderboard auto-refresh.
    return f"""
<script>
(function () {{
  const TRACK_ID = {json.dumps(track_id)};

  // ---------- Tab routing (hash → tab) ----------
  const tabLinks  = document.querySelectorAll('[data-tab-link]');
  const tabPanels = document.querySelectorAll('[data-tab]');
  function showTab(name) {{
    if (!name) name = 'overview';
    tabLinks.forEach(a  => a.classList.toggle('active', a.dataset.tabLink === name));
    tabPanels.forEach(s => s.classList.toggle('active', s.dataset.tab === name));
  }}
  function hashTab() {{
    const h = (window.location.hash || '').replace(/^#/, '');
    return h && document.querySelector(`[data-tab="${{h}}"]`) ? h : 'overview';
  }}
  window.addEventListener('hashchange', () => showTab(hashTab()));
  showTab(hashTab());

  // Quick tab links inside Overview ("see Leaderboard tab"). Just rely on hash.
  document.querySelectorAll('.quick-tab-link').forEach(a => {{
    a.addEventListener('click', () => setTimeout(() => showTab(hashTab()), 0));
  }});

  // ---------- Code sub-tabs ----------
  const codeTabs = document.querySelectorAll('.code-tab');
  codeTabs.forEach(btn => {{
    btn.addEventListener('click', () => {{
      const name = btn.dataset.codeTab;
      document.querySelectorAll('.code-tab').forEach(b => b.classList.toggle('active', b === btn));
      document.querySelectorAll('[data-code-block]').forEach(b =>
        b.classList.toggle('active', b.dataset.codeBlock === name));
    }});
  }});

  // ---------- Copy buttons ----------
  document.querySelectorAll('.copy-btn').forEach(btn => {{
    btn.addEventListener('click', async () => {{
      const target = document.getElementById(btn.dataset.copyTarget);
      if (!target) return;
      try {{
        await navigator.clipboard.writeText(target.innerText);
        const orig = btn.textContent;
        btn.textContent = 'Copied!';
        setTimeout(() => {{ btn.textContent = orig; }}, 1200);
      }} catch (e) {{ btn.textContent = 'Copy failed'; }}
    }});
  }});

  // ---------- Submit modal ----------
  const modal     = document.getElementById('submit-modal');
  const pasteEl   = document.getElementById('paste-input');
  const fileInput = document.getElementById('file-input');
  const dropzone  = document.getElementById('dropzone');
  const dropMsg   = document.getElementById('dropzone-msg');
  const loadBtn   = document.getElementById('load-sample-btn');
  const submitBtn = document.getElementById('do-submit');
  const resultEl  = document.getElementById('submit-result');
  const sampleEl  = document.getElementById('canonical-sample');
  let uploadedText = null;
  let currentMode  = 'paste';

  function openModal()  {{ modal.classList.add('open'); }}
  function closeModal() {{
    modal.classList.remove('open');
    resultEl.style.display = 'none';
    resultEl.className = 'submit-result';
  }}
  document.querySelectorAll('[data-open-submit]').forEach(b =>
    b.addEventListener('click', e => {{ e.preventDefault(); openModal(); }}));
  document.querySelectorAll('[data-close-submit]').forEach(b =>
    b.addEventListener('click', closeModal));
  modal.addEventListener('click', e => {{ if (e.target === modal) closeModal(); }});
  document.addEventListener('keydown', e => {{
    if (e.key === 'Escape' && modal.classList.contains('open')) closeModal();
  }});

  // Mode tabs inside the modal
  document.querySelectorAll('.mode-tab').forEach(b => {{
    b.addEventListener('click', () => {{
      currentMode = b.dataset.mode;
      document.querySelectorAll('.mode-tab').forEach(x => x.classList.toggle('active', x === b));
      document.querySelectorAll('[data-mode-panel]').forEach(p =>
        p.classList.toggle('active', p.dataset.modePanel === currentMode));
    }});
  }});

  // Drag-drop
  if (dropzone) {{
    dropzone.addEventListener('dragover',  e => {{ e.preventDefault(); dropzone.classList.add('drag'); }});
    dropzone.addEventListener('dragleave', () => dropzone.classList.remove('drag'));
    dropzone.addEventListener('drop',      e => {{
      e.preventDefault();
      dropzone.classList.remove('drag');
      const f = e.dataTransfer.files && e.dataTransfer.files[0];
      if (f) readFile(f);
    }});
    fileInput.addEventListener('change', e => {{
      const f = e.target.files && e.target.files[0];
      if (f) readFile(f);
    }});
  }}
  function readFile(f) {{
    const reader = new FileReader();
    reader.onload = () => {{
      uploadedText = String(reader.result || '');
      dropMsg.textContent = `Loaded: ${{f.name}} (${{uploadedText.length}} chars)`;
    }};
    reader.readAsText(f);
  }}

  // Load sample into the paste editor with a fresh submission_id
  loadBtn.addEventListener('click', () => {{
    const sample = JSON.parse(sampleEl.textContent);
    sample.submission_id = 'sub_' + Math.random().toString(36).slice(2, 10);
    pasteEl.value = JSON.stringify(sample, null, 2);
    currentMode = 'paste';
    document.querySelectorAll('.mode-tab').forEach(x => x.classList.toggle('active', x.dataset.mode === 'paste'));
    document.querySelectorAll('[data-mode-panel]').forEach(p =>
      p.classList.toggle('active', p.dataset.modePanel === 'paste'));
    pasteEl.focus();
  }});

  // Submit
  submitBtn.addEventListener('click', async () => {{
    let text;
    if (currentMode === 'upload')      text = uploadedText;
    else if (currentMode === 'sample') text = pasteEl.value || sampleEl.textContent;
    else                                text = pasteEl.value;

    if (!text || !text.trim()) {{
      showResult('err', 'No JSON to submit. Paste, upload, or load the sample first.');
      return;
    }}
    let body;
    try {{ body = JSON.parse(text); }}
    catch (e) {{ showResult('err', 'Invalid JSON: ' + e.message); return; }}

    submitBtn.disabled = true;
    showResult('ok', 'Submitting…');
    try {{
      const r = await fetch('/submit', {{
        method: 'POST',
        headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify(body),
      }});
      const data = await r.json().catch(() => ({{ raw: '<non-json response>' }}));
      if (r.ok) {{
        // Remember the student_id we just submitted under so future page loads
        // can show the "you are X" indicator and enable the filter toggle.
        if (body && body.student_id) setMyStudentId(body.student_id);
        showResult('ok',
          'Submitted!\\n\\n' + JSON.stringify(data, null, 2)
          + '\\n\\nThe worker scores asynchronously — see the Leaderboard tab in a few seconds.');
        refreshLeaderboard();
      }} else {{
        showResult('err',
          'HTTP ' + r.status + '\\n\\n' + JSON.stringify(data, null, 2));
      }}
    }} catch (e) {{
      showResult('err', 'Network error: ' + e.message);
    }} finally {{
      submitBtn.disabled = false;
    }}
  }});

  function showResult(kind, msg) {{
    resultEl.style.display = 'block';
    resultEl.className = 'submit-result ' + kind;
    resultEl.textContent = msg;
  }}

  // ---------- Student-ID memory ("you are X") ----------
  const STUDENT_ID_KEY = 'arena_student_id';
  function getMyStudentId() {{
    try {{ return localStorage.getItem(STUDENT_ID_KEY) || ''; }}
    catch (e) {{ return ''; }}
  }}
  function setMyStudentId(id) {{
    try {{ localStorage.setItem(STUDENT_ID_KEY, id); }}
    catch (e) {{ /* no-op */ }}
    renderYouLine();
    rerenderLeaderboard();
  }}
  function renderYouLine() {{
    const el = document.getElementById('you-line-text');
    const filterCb = document.getElementById('filter-mine');
    const myId = getMyStudentId();
    if (!el) return;
    if (myId) {{
      el.innerHTML = 'You are <span class="you-id">' + esc(myId) + '</span>';
      el.className = '';
      if (filterCb) filterCb.disabled = false;
    }} else {{
      el.innerHTML = "You aren't signed in &mdash; submit once and we'll remember your <code>student_id</code>.";
      el.className = 'you-empty';
      if (filterCb) {{
        filterCb.disabled = true;
        filterCb.checked = false;
      }}
    }}
  }}
  document.getElementById('set-id-btn').addEventListener('click', () => {{
    const current = getMyStudentId();
    const next = window.prompt(
      "What's your student_id (Canvas / NetID)?",
      current
    );
    if (next === null) return;
    const trimmed = next.trim();
    if (!trimmed) {{
      try {{ localStorage.removeItem(STUDENT_ID_KEY); }} catch (e) {{}}
      renderYouLine();
      rerenderLeaderboard();
    }} else {{
      setMyStudentId(trimmed);
    }}
  }});
  renderYouLine();

  // ---------- Leaderboard state, sort, filter ----------
  // We keep the latest fetched rows in memory so toggling the filter or
  // re-sorting doesn't require a network round-trip, and the live refresh
  // doesn't fight with the user's interaction.
  let lbRows  = [];      // last-known rows from /leaderboard/{{track}}
  let lbSort  = {{ key: 'final_score', dir: 'desc' }};

  function compareByKey(a, b, key) {{
    const av = a[key];
    const bv = b[key];
    if (key === 'final_score') return (Number(av) || 0) - (Number(bv) || 0);
    if (key === 'rank') return (a._rank || 0) - (b._rank || 0);
    return String(av || '').localeCompare(String(bv || ''));
  }}
  function sortRows(rows) {{
    const sorted = rows.slice();
    sorted.sort((a, b) => {{
      const cmp = compareByKey(a, b, lbSort.key);
      return lbSort.dir === 'asc' ? cmp : -cmp;
    }});
    return sorted;
  }}
  function rerenderLeaderboard() {{
    const tbody  = document.getElementById('lb-rows');
    const count  = document.getElementById('lb-count');
    const hdrSubs = document.getElementById('hdr-submission-count');
    const hdrStud = document.getElementById('hdr-student-count');
    const filterCb = document.getElementById('filter-mine');
    const myId   = getMyStudentId();
    const filterMine = filterCb && filterCb.checked && myId;

    // Header counts always reflect the unfiltered total.
    if (hdrSubs) hdrSubs.textContent = lbRows.length + ' submission' + (lbRows.length === 1 ? '' : 's');
    if (hdrStud) {{
      const students = new Set(lbRows.map(x => x.student_id)).size;
      hdrStud.textContent = students + ' student' + (students === 1 ? '' : 's');
    }}

    // Compute global rank (against the overall best-score-desc order) before
    // filtering, so a filtered student still sees "I'm #15 out of N".
    const ranked = lbRows.slice().sort((a, b) => (Number(b.final_score) || 0) - (Number(a.final_score) || 0));
    const rankByStudent = new Map();
    ranked.forEach((r, i) => rankByStudent.set(r.student_id, i + 1));

    let visible = lbRows.slice();
    if (filterMine) visible = visible.filter(r => r.student_id === myId);
    visible.forEach(r => {{ r._rank = rankByStudent.get(r.student_id) || 0; }});
    visible = sortRows(visible);

    if (count) count.textContent = String(visible.length);

    if (!tbody) return;
    if (!visible.length) {{
      const msg = filterMine
        ? 'No submissions yet under <code>' + esc(myId) + '</code>. Hit Submit Entry to make your first.'
        : 'No submissions yet for this track. Be the first!';
      tbody.innerHTML = '<tr><td colspan="5" class="empty">' + msg + '</td></tr>';
      return;
    }}

    tbody.innerHTML = visible.map(row => {{
      const r = row._rank || 0;
      const cls = [];
      if (r === 1) cls.push('top-1');
      else if (r === 2) cls.push('top-2');
      else if (r === 3) cls.push('top-3');
      if (myId && row.student_id === myId) cls.push('is-you');
      const score = (Number(row.final_score) || 0).toFixed(4);
      return `<tr class="${{cls.join(' ')}}">`
        + `<td class="rank">#${{r}}</td>`
        + `<td class="student">${{esc(row.student_id)}}</td>`
        + `<td class="score">${{score}}</td>`
        + `<td><code>${{esc(row.submission_id)}}</code></td>`
        + `<td>${{esc(row.scored_at || '')}}</td>`
        + '</tr>';
    }}).join('');
  }}

  // Sortable column headers — click to toggle direction; click another header
  // to switch sort key (with default direction).
  document.querySelectorAll('th.sortable').forEach(th => {{
    th.addEventListener('click', () => {{
      const key = th.dataset.sort;
      const defaultDir = th.dataset.defaultDir || 'asc';
      if (lbSort.key === key) {{
        lbSort.dir = lbSort.dir === 'asc' ? 'desc' : 'asc';
      }} else {{
        lbSort.key = key;
        lbSort.dir = defaultDir;
      }}
      // Update the visual indicators across all sortable headers.
      document.querySelectorAll('th.sortable').forEach(other => {{
        const ind = other.querySelector('.sort-indicator');
        if (other === th) {{
          other.classList.add('active');
          if (ind) ind.textContent = lbSort.dir === 'asc' ? '▲' : '▼';
        }} else {{
          other.classList.remove('active');
          if (ind) ind.textContent = '';
        }}
      }});
      rerenderLeaderboard();
    }});
  }});

  // Filter toggle.
  document.getElementById('filter-mine').addEventListener('change', rerenderLeaderboard);

  async function refreshLeaderboard() {{
    try {{
      const r = await fetch('/leaderboard/' + TRACK_ID + '?limit=100');
      if (!r.ok) return;
      const data = await r.json();
      lbRows = data.entries || [];
      rerenderLeaderboard();
    }} catch (e) {{ /* swallow — best-effort refresh */ }}
  }}

  function esc(s) {{
    return String(s == null ? '' : s).replace(/[&<>"']/g, c =>
      ({{ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }})[c]);
  }}

  // Initial pull populates lbRows from the JSON endpoint so subsequent
  // sort/filter actions have data to work with even before the first
  // 10-second tick fires.
  refreshLeaderboard();
  setInterval(refreshLeaderboard, 10000);
}})();
</script>
"""


def render_competition_html(
    track_id: str,
    leaderboard_rows: list[dict[str, Any]] | None = None,
) -> str:
    """Build the per-track competition page.

    Returns a 404-shaped HTML page if `track_id` is unknown, so the
    `/competitions/{track_id}` route can return a 200 with a graceful body or
    raise; the route handler in `api/main.py` chooses the latter for
    consistency with `/samples/{track_id}`.
    """
    t = get_track(track_id)
    if t is None:
        return _not_found_html(track_id)

    rows = leaderboard_rows or []
    total_submissions = len(rows)
    total_students = len({r.get("student_id") for r in rows if r.get("student_id")})

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Track {t.number} &middot; {escape(t.name)} &mdash; AI Arena</title>
  <style>{_PAGE_CSS}</style>
</head>
<body>
  {_topbar()}
  {_comp_header(t, total_submissions, total_students)}
  <main>
    {_overview_panel(t)}
    {_data_panel(t)}
    {_code_panel(t)}
    {_leaderboard_panel(t, rows)}
    {_rules_panel(t)}
  </main>

  {_submit_modal(t)}

  <footer class="page-footer">
    Iowa State University &middot; Department of Computer Science &middot;
    <a href="mailto:adisak.sukul@gmail.com">Adisak Sukul</a>
  </footer>

  {_page_script(t.id)}
</body>
</html>
"""


def _not_found_html(track_id: str) -> str:
    valid = ", ".join(t.id for t in TRACKS_META)
    return f"""<!DOCTYPE html>
<html><head><title>Unknown track &mdash; AI Arena</title>
<style>body{{background:#0c1017;color:#f5f5f7;font-family:system-ui;padding:48px;}}</style>
</head><body>
<h1>Unknown track: <code>{escape(track_id)}</code></h1>
<p>Valid track IDs: <code>{escape(valid)}</code></p>
<p><a href="/" style="color:#75c2ff;">&larr; Back to all competitions</a></p>
</body></html>"""
