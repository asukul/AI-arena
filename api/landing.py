"""
Public landing page — Kaggle-style card grid of all four competitions.

Replaces the flat-table landing that used to live inline in `api/main.py`.
The visual model is `kaggle.com/competitions`: a grid of competition cards
where each card surfaces the most-scanned facts (name, tagline, evaluation
metric, current participation) and the whole card is the "open competition"
affordance.

Stats (submission count, student count, top student) come from the live
leaderboard store at request time. They're best-effort and decay gracefully
to zero / "—" if the store is empty.
"""

from __future__ import annotations

from html import escape
from typing import Any

from api.competition_data import TRACKS_META, TrackMeta


_LANDING_CSS = """
:root { color-scheme: dark; }
* { box-sizing: border-box; }
body {
  margin: 0; padding: 0; min-height: 100vh;
  font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  background: #0c1017; color: #f5f5f7; line-height: 1.5;
}
a { color: #75c2ff; text-decoration: none; }
a:hover { color: #a4d6ff; text-decoration: underline; }
code {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 13px; background: #1d2434; padding: 2px 6px; border-radius: 4px;
  color: #e6edf6;
}

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
.topbar .topbar-nav a.active { color: #f5f5f7; border-bottom-color: #ffc107; }

.hero {
  max-width: 1200px; margin: 0 auto; padding: 56px 24px 24px;
}
.hero h1 {
  font-size: 48px; margin: 0 0 8px 0; letter-spacing: -1px;
}
.hero h1 .accent { color: #ffc107; }
.hero p.tagline { color: #a8b1bf; margin: 0 0 18px 0; font-size: 17px; max-width: 720px; }
.hero .pill-row { display: flex; gap: 8px; flex-wrap: wrap; }
.pill {
  display: inline-flex; align-items: center; padding: 4px 12px;
  border-radius: 999px; font-size: 12px; font-weight: 600;
  background: #1d2434; color: #c9d1de;
}
.pill.live { background: #1d4d2b; color: #a6e8b6; }

.section-label {
  max-width: 1200px; margin: 32px auto 0; padding: 0 24px;
  color: #a8b1bf; font-size: 12px; font-weight: 700;
  letter-spacing: 1.5px; text-transform: uppercase;
}

.grid {
  max-width: 1200px; margin: 12px auto 0; padding: 0 24px 56px;
  display: grid; grid-template-columns: repeat(auto-fit, minmax(420px, 1fr));
  gap: 18px;
}
@media (max-width: 700px) {
  .grid { grid-template-columns: 1fr; }
}

.card {
  background: #151c28; border: 1px solid #232c3d; border-radius: 12px;
  padding: 22px 24px; display: flex; flex-direction: column; gap: 14px;
  position: relative; transition: transform 0.15s, border-color 0.15s, background 0.15s;
  text-decoration: none; color: inherit;
}
.card:hover {
  border-color: var(--accent, #ffc107);
  background: #1a2230;
  transform: translateY(-1px);
  text-decoration: none;
}
.card .row1 {
  display: flex; align-items: baseline; justify-content: space-between; gap: 12px;
}
.card .track-num {
  font-size: 12px; font-weight: 700; letter-spacing: 1.2px;
  text-transform: uppercase; color: var(--accent, #ffc107);
}
.card .arrow {
  color: var(--accent, #ffc107); font-size: 20px; line-height: 1; opacity: 0.6;
  transition: opacity 0.15s, transform 0.15s;
}
.card:hover .arrow { opacity: 1; transform: translateX(2px); }
.card h2 { font-size: 22px; margin: 0; color: #f5f5f7; letter-spacing: -0.2px; }
.card .tagline { color: #a8b1bf; font-size: 14px; margin: 0; line-height: 1.5; min-height: 42px; }
.card .metric-row {
  font-size: 12px; color: #c9d1de; display: flex; gap: 6px; align-items: center;
}
.card .metric-row .label { color: #6d7787; font-weight: 600;
  text-transform: uppercase; letter-spacing: 0.6px; font-size: 11px; }
.card .metric-row .value { color: #a4d6ff; font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 12px; }
.card .stats {
  display: flex; gap: 18px; padding-top: 12px; border-top: 1px solid #232c3d;
  font-size: 12px; color: #a8b1bf;
}
.card .stats .stat { display: flex; flex-direction: column; gap: 1px; }
.card .stats .stat .num { color: #f5f5f7; font-weight: 700; font-size: 16px; }

footer.page-footer {
  max-width: 1200px; margin: 0 auto; padding: 32px 24px;
  color: #6d7787; font-size: 12px; text-align: center; border-top: 1px solid #1d2434;
}
"""


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


def _card(t: TrackMeta, n_subs: int, n_students: int, top_student: str | None) -> str:
    top_line = (
        f'<div class="stat"><span class="num">{escape(top_student)}</span>'
        f'<span>top student</span></div>'
        if top_student else
        '<div class="stat"><span class="num">&mdash;</span><span>top student</span></div>'
    )
    return f"""
<a class="card" href="/competitions/{t.id}" style="--accent: {t.accent};">
  <div class="row1">
    <div class="track-num">Track {t.number}</div>
    <div class="arrow">&rarr;</div>
  </div>
  <h2>{escape(t.name)}</h2>
  <p class="tagline">{escape(t.tagline)}</p>
  <div class="metric-row">
    <span class="label">Eval</span>
    <span class="value">{t.metric_label}</span>
  </div>
  <div class="stats">
    <div class="stat"><span class="num">{n_subs}</span><span>submission{'s' if n_subs != 1 else ''}</span></div>
    <div class="stat"><span class="num">{n_students}</span><span>student{'s' if n_students != 1 else ''}</span></div>
    {top_line}
  </div>
</a>
"""


def render_landing_html(
    *,
    version: str,
    per_track_stats: dict[str, dict[str, Any]] | None = None,
) -> str:
    """Build the landing page.

    `per_track_stats` keys are track IDs; values look like
    `{"submissions": int, "students": int, "top_student": str | None}`.
    Missing entries render as zero / em-dash.
    """
    stats = per_track_stats or {}
    cards = []
    for t in TRACKS_META:
        s = stats.get(t.id, {})
        cards.append(_card(
            t,
            n_subs=int(s.get("submissions", 0)),
            n_students=int(s.get("students", 0)),
            top_student=s.get("top_student"),
        ))
    cards_html = "\n".join(cards)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>AI Arena &mdash; D4 Summer 2026 Bootcamp</title>
  <style>{_LANDING_CSS}</style>
</head>
<body>
  {_topbar()}

  <section class="hero">
    <h1>AI <span class="accent">Arena</span></h1>
    <p class="tagline">
      Kaggle-style competition platform for the <strong>D4 Summer 2026 Bootcamp</strong>
      &mdash; Iowa State University, Department of Computer Science.
      Four tracks &middot; LLM-as-judge scoring &middot; real-time leaderboards.
    </p>
    <div class="pill-row">
      <span class="pill live">v{escape(version)} live</span>
      <span class="pill">4 active competitions</span>
      <span class="pill">FastAPI &middot; Cloud Run &middot; Firestore</span>
    </div>
  </section>

  <div class="section-label">Active competitions</div>
  <section class="grid">
    {cards_html}
  </section>

  <footer class="page-footer">
    Iowa State University &middot; Department of Computer Science &middot;
    <a href="mailto:adisak.sukul@gmail.com">Adisak Sukul</a> &middot;
    <a href="/get-started">Docs</a> &middot;
    <a href="/docs">API reference</a>
  </footer>
</body>
</html>
"""
