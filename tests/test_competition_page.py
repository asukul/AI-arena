"""
Tests for the Kaggle-style per-track competition page and card-grid landing.

The competition shell is the user-facing centerpiece — these tests pin the
contract that a real student touches:

  * Landing renders four competition cards with links to per-track pages.
  * /competitions/<track_id> returns a 200 HTML shell with all five tabs.
  * The persistent submit modal carries the canonical sample JSON.
  * Track-specific rules (rate limit, judge token budget) render correctly.
  * Live submissions surface in the server-rendered leaderboard tab.
  * Unknown tracks 404 cleanly with a structured error.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.config import Settings
from api.main import create_app
from evaluator.gold import GoldProvider


REPO_ROOT = Path(__file__).resolve().parent.parent
GOLD_DIR = REPO_ROOT / "corpora" / "gold"

ALL_TRACKS = (
    "hallucination_hunter",
    "prompt_golf",
    "rag_treasure_hunt",
    "meta_judge",
)


@pytest.fixture
def client() -> TestClient:
    settings = Settings(
        project_id="test-project",
        project_number="0",
        region="us-central1",
        queue_id="test-queue",
        evaluator_target_url="",
        tasks_invoker_sa="",
        canvas_base_url="https://canvas.example",
        canvas_api_token="",
        canvas_webhook_secret="test-secret",
        rate_limit_per_day=5,
        daily_token_budget=50_000,
        local_dev=True,
        log_level="WARNING",
    )
    app = create_app(settings=settings)
    app.state.arena.eval_deps.gold_provider = GoldProvider(GOLD_DIR)
    return TestClient(app)


# ---------- Landing card grid ----------

def test_landing_renders_card_for_each_track(client: TestClient) -> None:
    """Every track has its own card on the landing, linking into the comp page."""
    body = client.get("/").text
    for track in ALL_TRACKS:
        assert f'href="/competitions/{track}"' in body, f"missing card for {track}"


def test_landing_shows_all_four_track_names(client: TestClient) -> None:
    body = client.get("/").text
    for name in (
        "Hallucination Hunter",
        "Prompt Golf",
        "RAG Treasure Hunt",
        "Build Your Own AI Judge",
    ):
        assert name in body, f"missing track name on landing: {name}"


def test_landing_stats_start_at_zero(client: TestClient) -> None:
    """Empty store → every card shows 0 submissions / 0 students."""
    body = client.get("/").text
    # Each card has a stats block. With nothing in the leaderboard, every
    # card should render four zero-counts (4 cards × 1 "0 submission" + 1 "0 student").
    assert body.count(">0<") >= 8


def test_landing_stats_reflect_real_submissions(client: TestClient) -> None:
    """After a successful submission, the relevant card's counter ticks."""
    sample = client.get("/samples/hallucination_hunter").json()
    sample["student_id"] = "alice"
    sample["submission_id"] = "sub_landing_alice"
    r = client.post("/submit", json=sample)
    assert r.status_code == 200, r.text

    body = client.get("/").text
    # Hallucination Hunter card shows alice as top student now.
    assert "alice" in body
    # And the card shows 1 submission / 1 student. (We just check the strings
    # appear in the right card by anchoring on the track URL.)
    h_card_idx = body.index('href="/competitions/hallucination_hunter"')
    h_card_end = body.index("</a>", h_card_idx)
    h_card_html = body[h_card_idx:h_card_end]
    assert ">1<" in h_card_html, "expected '1' in submissions/students stats"
    assert "alice" in h_card_html


# ---------- Per-track competition shell ----------

@pytest.mark.parametrize("track_id", ALL_TRACKS)
def test_competition_page_renders_200(client: TestClient, track_id: str) -> None:
    response = client.get(f"/competitions/{track_id}")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


@pytest.mark.parametrize("track_id", ALL_TRACKS)
def test_competition_page_has_all_five_tabs(client: TestClient, track_id: str) -> None:
    body = client.get(f"/competitions/{track_id}").text
    for tab in ("overview", "data", "code", "leaderboard", "rules"):
        assert f'data-tab-link="{tab}"' in body, f"missing tab nav: {tab} on {track_id}"
        assert f'data-tab="{tab}"' in body, f"missing tab panel: {tab} on {track_id}"


@pytest.mark.parametrize("track_id", ALL_TRACKS)
def test_competition_page_has_persistent_submit_button(
    client: TestClient, track_id: str
) -> None:
    body = client.get(f"/competitions/{track_id}").text
    # Both the header CTA and the in-overview quick-CTA carry the open hook.
    assert body.count("data-open-submit") >= 2
    # Modal markup is present.
    assert 'id="submit-modal"' in body
    assert 'id="paste-input"' in body
    assert 'id="do-submit"' in body


@pytest.mark.parametrize("track_id", ALL_TRACKS)
def test_competition_page_pins_eval_metric_in_header(
    client: TestClient, track_id: str
) -> None:
    """Kaggle convention — evaluation metric is visible from any tab."""
    body = client.get(f"/competitions/{track_id}").text
    # The .pill-metric badge sits in the header above the tab nav, so it
    # renders regardless of which tab is active.
    assert 'pill pill-metric' in body
    assert 'Eval:' in body


def test_competition_page_embeds_canonical_sample(client: TestClient) -> None:
    """Submit modal must carry the canonical sample so 'Use sample' works without a network round-trip."""
    body = client.get("/competitions/hallucination_hunter").text
    assert 'id="canonical-sample"' in body
    assert '"track_id": "hallucination_hunter"' in body
    assert '"predictions"' in body


def test_competition_page_unknown_track_returns_404(client: TestClient) -> None:
    response = client.get("/competitions/this-does-not-exist")
    assert response.status_code == 404
    assert response.json()["detail"]["error"] == "unknown_track_id"


# ---------- Per-track Rules content ----------

def test_rules_tab_shows_rate_limit(client: TestClient) -> None:
    body = client.get("/competitions/hallucination_hunter").text
    # The fixture's settings set rate_limit_per_day=5 and that's what TrackMeta
    # surfaces by default. We just check the number is present in the Rules section.
    assert "5 submissions / day" in body


def test_rules_tab_shows_track_specific_judge_budget(client: TestClient) -> None:
    """Track 1 has no judge calls; the Rules tab must say so explicitly."""
    body_t1 = client.get("/competitions/hallucination_hunter").text
    assert "does <strong>not</strong> call the judge model" in body_t1

    body_t3 = client.get("/competitions/rag_treasure_hunt").text
    assert "50,000 judge tokens / day" in body_t3


def test_rules_tab_mentions_hidden_test_set_path(client: TestClient) -> None:
    """Anti-cheat language has to be specific enough to be reassuring."""
    body = client.get("/competitions/rag_treasure_hunt").text
    assert "corpora/gold/rag_treasure_hunt.json" in body
    assert "temperature=0" in body


# ---------- Data tab content ----------

def test_data_tab_lists_public_and_hidden_files(client: TestClient) -> None:
    body = client.get("/competitions/rag_treasure_hunt").text
    # Public corpus + questions linked + hidden gold called out.
    assert "index.json" in body
    assert "questions.json" in body
    assert "Hidden" in body or 'badge hidden' in body


# ---------- Leaderboard tab + auto-refresh contract ----------

def test_leaderboard_tab_shows_empty_state_initially(client: TestClient) -> None:
    body = client.get("/competitions/prompt_golf").text
    assert "No submissions yet for this track" in body


def test_leaderboard_tab_renders_real_submission_in_html(client: TestClient) -> None:
    sample = client.get("/samples/hallucination_hunter").json()
    sample["student_id"] = "bob"
    sample["submission_id"] = "sub_lb_bob"
    submit = client.post("/submit", json=sample)
    assert submit.status_code == 200, submit.text

    body = client.get("/competitions/hallucination_hunter").text
    # Server-rendered leaderboard row should be in the initial HTML, not just the JS refresh.
    assert "bob" in body
    assert "sub_lb_bob" in body
    # Top-1 styling on rank #1.
    assert "top-1" in body


def test_leaderboard_json_endpoint_remains_unchanged(client: TestClient) -> None:
    """The auto-refresh fetches /leaderboard/{track_id} JSON — that contract must hold."""
    response = client.get("/leaderboard/hallucination_hunter")
    assert response.status_code == 200
    body = response.json()
    assert body["track_id"] == "hallucination_hunter"
    assert isinstance(body["entries"], list)


# ---------- Per-student filter + sortable columns ----------

def test_leaderboard_renders_show_my_submissions_toggle(client: TestClient) -> None:
    """Each track page must carry the filter toggle so logged-in students can scope the view."""
    body = client.get("/competitions/hallucination_hunter").text
    assert 'id="filter-mine"' in body
    assert "Show only my submissions" in body
    # The disabled-until-set-up-id pattern: the toggle must start disabled in
    # the server-rendered HTML so a fresh visitor doesn't toggle a no-op.
    assert "disabled" in body and "filter-mine" in body


def test_leaderboard_renders_sortable_headers(client: TestClient) -> None:
    body = client.get("/competitions/prompt_golf").text
    # Three columns must be marked sortable in the server-rendered table.
    for key in ("rank", "student_id", "final_score", "scored_at"):
        assert f'data-sort="{key}"' in body, f"missing sortable column: {key}"
    # The default sort is final_score desc — only that header should start
    # active and carry the down-arrow indicator.
    assert 'class="sortable active" data-sort="final_score"' in body
    assert "&#9660;" in body or "▼" in body


def test_leaderboard_renders_set_id_button(client: TestClient) -> None:
    """Students can click 'Set ID' even before submitting, so they can pre-set
    their student_id before the first submission lands on the leaderboard."""
    body = client.get("/competitions/meta_judge").text
    assert 'id="set-id-btn"' in body
    assert "Set ID" in body


# ---------- Mobile responsiveness ----------

def test_leaderboard_table_wrapped_for_horizontal_scroll(client: TestClient) -> None:
    """On narrow viewports the leaderboard must scroll horizontally instead of
    clipping the Submission column. The wrapper div is the load-bearing piece."""
    body = client.get("/competitions/hallucination_hunter").text
    assert 'class="lb-scroll"' in body


def test_competition_page_has_mobile_breakpoint(client: TestClient) -> None:
    """Phones (<=600px) must get the tightened padding / font sizes."""
    body = client.get("/competitions/prompt_golf").text
    assert "@media (max-width: 600px)" in body


# ---------- Reference solution callout ----------

def test_track3_code_tab_links_reference_notebook(client: TestClient) -> None:
    """Track 3 has a published reference baseline; the Code tab must surface it."""
    body = client.get("/competitions/rag_treasure_hunt").text
    assert "track3_reference_solution.ipynb" in body
    assert "Reference solution" in body


def test_other_tracks_have_no_reference_callout(client: TestClient) -> None:
    """Tracks without a reference notebook must not show an empty callout —
    if we add one for Track 1/2/4 later, set TrackMeta.reference_notebook."""
    for track_id in ("hallucination_hunter", "prompt_golf", "meta_judge"):
        body = client.get(f"/competitions/{track_id}").text
        assert "Reference solution" not in body, f"unexpected callout on {track_id}"
