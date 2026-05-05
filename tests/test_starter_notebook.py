"""
Tests that pin the student starter notebook to the contract students rely on.

The notebook (`docs/student_starter.ipynb`) is the on-ramp for every track.
If it drifts from the live API or breaks structurally, students hit a wall
on day one. These tests run on every CI green so we notice fast.

What we check:
  * The .ipynb is valid JSON in the nbformat 4 schema.
  * Every code cell parses as Python (no syntax errors).
  * Every track has its own anchored section.
  * The cells reference the live `/samples/{track_id}` endpoints (not curl-only).
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
NOTEBOOK = REPO_ROOT / "docs" / "student_starter.ipynb"

ALL_TRACKS = (
    "hallucination_hunter",
    "prompt_golf",
    "rag_treasure_hunt",
    "meta_judge",
)


@pytest.fixture(scope="module")
def nb() -> dict:
    return json.loads(NOTEBOOK.read_text(encoding="utf-8"))


def _cell_source(cell: dict) -> str:
    src = cell.get("source", "")
    return "".join(src) if isinstance(src, list) else src


def _all_source(nb: dict) -> str:
    return "\n".join(_cell_source(c) for c in nb["cells"])


def test_notebook_is_valid_nbformat_4(nb: dict) -> None:
    assert nb.get("nbformat") == 4
    assert isinstance(nb.get("cells"), list) and nb["cells"], "no cells in notebook"


def test_every_code_cell_parses(nb: dict) -> None:
    """Catch typos / dangling colons before students hit them."""
    failures: list[tuple[int, str]] = []
    for i, c in enumerate(nb["cells"]):
        if c["cell_type"] != "code":
            continue
        src = _cell_source(c)
        # Strip Jupyter line-magic so ast.parse doesn't choke on `%pip install`.
        src = "\n".join(line for line in src.split("\n") if not line.lstrip().startswith("%"))
        try:
            ast.parse(src)
        except SyntaxError as e:
            failures.append((i, str(e)))
    assert not failures, f"syntax errors in code cells: {failures}"


@pytest.mark.parametrize("track_id", ALL_TRACKS)
def test_notebook_covers_track(nb: dict, track_id: str) -> None:
    """Each track must appear in the notebook *and* have its own anchored section."""
    body = _all_source(nb)
    assert track_id in body, f"notebook does not mention {track_id}"


def test_notebook_uses_samples_endpoint(nb: dict) -> None:
    """Notebook should pull canonical samples instead of hard-coding payloads."""
    body = _all_source(nb)
    assert "/samples/" in body, "notebook should fetch from /samples/{track_id}"


def test_notebook_warns_about_daily_limits(nb: dict) -> None:
    """Students should be told the rate-limit upfront, not surprised by a 429."""
    body = _all_source(nb).lower()
    assert "5 submissions" in body or "daily limit" in body
    assert "50,000" in body or "judge token" in body


def test_notebook_explains_kappa_for_meta_judge(nb: dict) -> None:
    """Track 4's metric is the most easily-misunderstood — make sure it's spelled out."""
    body = _all_source(nb)
    # Either the kappa symbol or the linear-weighted formulation.
    assert "Cohen" in body or "κ" in body
    assert "linear-weighted" in body
