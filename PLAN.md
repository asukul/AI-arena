# AI Arena — Build Plan

> Claude Code project anchor. Read this file at the start of every session.
> Update it as decisions are made. The TODO at the bottom is the source of truth for "what's next."

---

## Project context (read me first)

**What this is:** A Kaggle-style competition platform for the D4 Summer 2026 bootcamp's new LLM, GenAI, and RAG modules. Kaggle InClass cannot evaluate generative-AI student work (its scoring engine compares CSV against fixed labels), so we are building a focused custom platform that uses LLM-as-judge plus RAG-specific metrics.

**Owner:** Adisak Sukul (Iowa State University, Department of Computer Science)
**Target launch:** D4 Summer Bootcamp 2026
**Build window:** ~7 working days (Day 1 is highest-risk; subsequent days extend a working pipeline)

**Existing infrastructure to reuse:**
- Canvas LMS (already running auto-graders for DS 2010 quizzes via n8n — that stays separate; the Arena is a new clean Python codebase)
- GCP project with Cloud Run, Cloud Storage, Firestore, Cloud Tasks, Cloud Scheduler available
- Anthropic API access (Claude Haiku 4.5 for primary judge, Opus 4.7 for re-grade)
- Gemini API access (Flash for cross-family bias check, free tier covers most usage)

**Why pure Python (not n8n):** With Claude Code as the daily author/maintainer, the historical case for n8n's visual workflows has collapsed. A single Python repo is more testable, refactorable, and pedagogically valuable — the codebase itself is a Phase 2 teaching artifact.

---

## Architecture

```
Student in Canvas Assignment
        │
        │  submits JSON file or notebook URL
        ▼
  Canvas webhook ─────────► FastAPI on Cloud Run
                                   │
                                   │  enqueue
                                   ▼
                           Cloud Tasks queue
                                   │
                                   ▼
                       Evaluator (Cloud Run job)
                       ├── tracks/hallucination.py
                       ├── tracks/prompt_golf.py
                       ├── tracks/rag.py          (uses RAGAS)
                       └── tracks/meta_judge.py
                                   │
                                   ▼
                          judge.py (Claude API)
                                   │
                                   ▼
                       Firestore (results + leaderboard data)
                                   │
                          ┌────────┴────────┐
                          ▼                 ▼
                 Canvas grade passback   Firebase Hosting
                                         (static HTML +
                                          Firestore JS SDK)
```

**Key principles:**
- Single repo, single mental model
- Every scoring function has unit tests
- Judge prompts live in version-controlled `.txt` files, not embedded in code
- Hidden test set never leaves the server — students see only their score
- All four tracks share the same submission JSON envelope

---

## Repository layout

```
d4-arena/
├── api/
│   ├── main.py                 # FastAPI app: webhook + admin endpoints
│   ├── canvas.py               # Canvas API client (fetch submission, post grade)
│   ├── auth.py                 # Webhook signature verification
│   └── rate_limit.py           # 5 submissions/student/day enforcement
├── evaluator/
│   ├── tracks/
│   │   ├── hallucination.py    # Track 1: F1 on classification CSV
│   │   ├── prompt_golf.py      # Track 2: judge accuracy ÷ token cost
│   │   ├── rag.py              # Track 3: RAGAS + judge + citation match
│   │   └── meta_judge.py       # Track 4: Cohen's kappa vs. instructor gold
│   ├── judge.py                # Claude API wrapper, retries, T=0
│   ├── regrade.py              # Cross-family Gemini Flash re-grade pass
│   └── scoring.py              # Rubric weighting, dimension aggregation
├── prompts/
│   ├── judge_correctness.txt
│   ├── judge_faithfulness.txt
│   └── ...                     # one file per judge prompt, version-controlled
├── leaderboard/
│   ├── firestore_client.py     # server-side writes
│   ├── web/                    # static HTML + JS (deployed via Firebase Hosting)
│   │   ├── index.html
│   │   ├── leaderboard.js      # Firestore real-time listener
│   │   └── style.css
│   └── firebase.json           # Firebase Hosting config
├── tests/
│   ├── test_hallucination.py
│   ├── test_prompt_golf.py
│   ├── test_rag.py
│   ├── test_judge.py           # mocked Claude responses
│   └── test_scoring.py
├── corpora/
│   └── isu_course_catalog/     # Track 3 starter corpus
├── docs/
│   ├── student_starter.ipynb   # Colab notebook for participants
│   └── judge_rubrics.md        # public-facing rubric documentation
├── Dockerfile
├── requirements.txt
├── pyproject.toml
└── PLAN.md                     # this file
```

---

## Submission JSON schema (LOCK BEFORE DAY 1)

Every track uses this envelope. The `track_payload` differs per track but the wrapper is universal — this is what makes the FastAPI handler trivially reusable.

```json
{
  "submission_id": "sub_d4_001_v3",
  "student_id": "asukul",
  "track_id": "rag_treasure_hunt",
  "submission_timestamp": "2026-06-15T14:32:00Z",
  "model_used": "claude-haiku-4-5",
  "prompt_version": "v3",
  "self_reported_strategy": "Hybrid BM25 + dense, top-5 chunks",
  "track_payload": {
    "answers": [
      {
        "question_id": "Q001",
        "answer": "Generated answer text here",
        "citations": ["doc3_chunk12", "doc8_chunk2"],
        "retrieved_contexts": ["doc3_chunk12", "doc1_chunk4"],
        "estimated_cost_usd": 0.0042,
        "latency_seconds": 3.8
      }
    ]
  }
}
```

---

## Tracks

### Track 1 — Hallucination Hunter (build first)
- **Submission:** CSV of `(claim_id, label)` predictions
- **Metric:** F1 score against hidden ground truth
- **Why first:** Classification-shaped; validates Canvas → FastAPI → Cloud Tasks → Firestore → leaderboard plumbing without judge complexity.

### Track 2 — Prompt Golf
- **Submission:** Single prompt template + sample outputs
- **Metric:** `judge_accuracy / total_tokens` (higher is better)
- **Why second:** Exercises the judge layer with simple, reproducible scoring.

### Track 3 — RAG Treasure Hunt
- **Submission:** JSON of answers, citations, retrieved contexts
- **Metric:** Weighted rubric (correctness 30%, faithfulness 25%, retrieval 15%, citations 15%, cost 10%, safety 5%)
- **Corpus:** ISU course catalog for v1 (clean, ownable, pedagogically tame)

### Track 4 — Build-Your-Own AI Judge
- **Submission:** Their own evaluator function + rubric
- **Metric:** Cohen's kappa agreement with instructor gold ratings
- **Why last:** Pedagogical capstone — students learn evaluation by doing it.

---

## Anti-cheat & fairness controls

| Control | Implementation |
|---|---|
| Hidden test set | Test data never returned in API responses, only scores |
| Rate limit (5/student/day) | `api/rate_limit.py`, Firestore counter |
| Judge `temperature=0` | Set in every Claude API call |
| Cross-family re-grade | Top 10% re-scored by Gemini Flash; Δ > 10% triggers manual review |

---

## Conventions

**Python:** 3.12+, `uv` for package management if available, otherwise pip. Type hints everywhere. `ruff` for linting, `pytest` for tests, `pydantic` for schema validation.

**Commits:** Conventional commits (`feat:`, `fix:`, `test:`, `docs:`). Keep commits small and reversible.

**Secrets:** never committed. GCP Secret Manager for API keys; `.env.example` in repo, `.env` in `.gitignore`.

**Judge prompts:** plain text files in `prompts/`. Each file starts with a one-line header comment describing what the prompt grades and what scale it returns.

**Tests before code:** for every new scoring function, write the test first. Cover at least: happy path, empty input, malformed input, edge case at scoring boundary.

**LLM calls:** always go through `evaluator/judge.py`. Never call the Anthropic SDK directly from a track file. The wrapper enforces `temperature=0`, retries with exponential backoff, and logs token counts to Firestore.

**No premature optimization:** ship the simplest working version of each track, then refactor. The 7-day timeline is the constraint.

---

## Day-by-day plan

### Day 1 — Foundation + Track 1 end-to-end
**Goal:** A real submission to Hallucination Hunter receives a real grade and appears on the leaderboard.

- [x] Initialize repo: `pyproject.toml`, `requirements.txt`, `.gitignore`, `Dockerfile`
- [x] FastAPI skeleton (`api/main.py`) with `/health` and `/submit` endpoints (note: `/healthz` is intercepted by Cloud Run edge, see troubleshooting in README)
- [x] Canvas webhook signature verification (`api/auth.py`)
- [x] Cloud Tasks integration: `/submit` enqueues, evaluator pulls
- [x] Firestore client setup (`leaderboard/firestore_client.py`)
- [x] Track 1 evaluator (`evaluator/tracks/hallucination.py`): F1 on classification CSV
- [x] Pytest tests for Track 1 scoring (happy path, empty, malformed, edge case)
- [x] Canvas grade passback (`api/canvas.py`)
- [x] Deploy to Cloud Run, smoke-test with one fake submission end-to-end

### Day 2 — Polish + student-facing materials
- [x] Rate-limiting (`api/rate_limit.py`): 5 submissions/student/day via Firestore counter
- [x] Error handling: friendly messages for malformed submissions
- [x] Logging: structured JSON logs to Cloud Logging
- [x] Student starter Colab notebook for Track 1 (`docs/student_starter.ipynb`)
- [x] Public rubric doc (`docs/judge_rubrics.md`) with Track 1 scoring explained

### Day 3 — Track 2 (Prompt Golf) with judge layer
- [x] `evaluator/judge.py`: Claude API wrapper, T=0, retries, token logging
- [x] First judge prompt: `prompts/judge_correctness.txt`
- [x] Track 2 evaluator (`evaluator/tracks/prompt_golf.py`): runs prompt, judges output, divides by token count
- [x] Tests for Track 2 with mocked judge responses
- [x] Add Track 2 to leaderboard

### Day 4 — Track 3 (RAG) with RAGAS
- [x] ~~`pip install ragas` and integrate~~ — Deferred to Phase 2; v1 computes the metrics in-tree (no RAGAS dep). Migration is a drop-in because the wire shape matches.
- [x] Track 3 evaluator (`evaluator/tracks/rag.py`): faithfulness, retrieval recall + judge correctness + citation F1 + cost + safety
- [x] Weighted scoring (`evaluator/scoring.py`): 30/25/15/15/10/5
- [x] Build `corpora/isu_course_catalog/` chunked corpus with gold citations
- [x] Tests for Track 3 with small mock corpus
- [x] Cross-family re-grade pass (`evaluator/regrade.py`) for top 10%

### Day 5 — Leaderboard surfaces (in-app + Firebase)
- [x] In-app HTML leaderboard tab on each per-track competition page (auto-refreshes every 10s by polling `/leaderboard/{track_id}` JSON). Keeps the platform usable without Firebase Hosting deploy.
- [x] `leaderboard/web/index.html` + `leaderboard.js` — Firestore JS SDK with real-time listener (kept as Phase-2 path; needs `firebase init` + web-app registration to fill in `apiKey` / `appId`).
- [x] Style: clean table, sortable columns, per-track view
- [x] `firebase.json` config
- [ ] `firebase deploy --only hosting` — interactive auth required; deferred until v1 launch.

### Day 6 — Documentation + Track 4 (meta-judge)
- [x] Track 4 evaluator (`evaluator/tracks/meta_judge.py`): Cohen's kappa
- [x] Instructor gold-rating fixture for kappa computation (`corpora/gold/meta_judge.json`)
- [x] Update student starter notebook with all four tracks (single notebook, anchored sections per track, pulls canonical samples from `/samples/{track_id}`)
- [x] FAQ doc (`docs/faq.md`): "why did I get this score?" common cases
- [x] README with one-paragraph summary + run instructions

### Day 7 — Dry run + buffer
- [ ] Recruit 2–3 DS Club students to submit fake entries to each track
- [ ] Fix whatever they break
- [ ] Add monitoring dashboard in Cloud Logging
- [x] Set GCP budget alert at $200 to catch runaway usage early (`scripts/budget_alert.ps1`)
- [x] Cost guardrail: per-student daily token budget enforced in `evaluator/token_budget.py` (`BudgetedJudge` wraps the configured judge per submission; default 50,000 tokens/day; configurable via `DAILY_TOKEN_BUDGET`).

### Day 8 — Kaggle-style UX redesign (added 2026-05-04)
**Goal:** Make the public surface feel familiar to anyone who has used Kaggle, so D4 students don't have to learn a new mental model.

- [x] Per-track competition shell (`api/competition.py`) at `GET /competitions/{track_id}` with horizontal tabs (Overview / Data / Code / Leaderboard / Rules), persistent submit button top-right, evaluation metric pinned in the header.
- [x] Card-grid landing (`api/landing.py`) replacing the flat table at `GET /` — one card per competition with live submission/student counts and "top student" headline.
- [x] In-browser submit modal: paste JSON, drag-drop `.json`, or "Use sample as starting point". Posts via `fetch('/submit')` and shows the response inline. Students never leave the page.
- [x] Server-rendered leaderboard tab + 10s JS auto-refresh against the existing `/leaderboard/{track_id}` JSON.
- [x] Single source of truth for per-track metadata (`api/competition_data.py`) shared by the landing, the competition shell, and (eventually) the Get Started page.
- [x] 29 new tests in `tests/test_competition_page.py` (175 total).

---

## Open decisions to resolve before Day 1

- [ ] **First RAG corpus:** ISU course catalog (recommended), DSpace, or Wikipedia subset?
- [ ] **API key model:** shared D4 key (easier, costs more), BYO student keys (cheaper, less equitable), or hybrid (basic tracks shared, advanced BYO)?
- [ ] **Leaderboard visibility:** class-only via Canvas, fully public, or pseudonymous-public + identified-in-Canvas (recommended)?
- [ ] **Pseudonym scheme** if going public: numeric IDs, animal names, or student-chosen handles?

---

## Costs and guardrails

**Comfortable budget:** ~$1,030 (see funding doc).
**Lean budget:** ~$500 with BYO student keys and Max 20x billed elsewhere.

**Guardrails to implement:**
- GCP budget alert at $200 (warns Adisak)
- GCP budget hard cap at $400 (auto-disables billing as last resort)
- Per-student daily token budget in `judge.py` (default: 50k tokens/day per student)
- Anthropic API workspace spend limit set in console

---

## Testing strategy

- Every scoring function has unit tests covering: correct input, empty input, malformed input, edge case at scoring boundary
- Judge calls are mocked in unit tests (use saved JSON fixtures) — no real API calls in tests
- One end-to-end integration test per track, hitting a local FastAPI instance with a fake Canvas webhook payload
- Manual smoke test before each Day's commit: post a real submission, verify grade reaches Canvas and leaderboard

---

## Out of scope for v1 (Phase 2 candidates)

- Agent task track (needs sandboxed execution environment)
- Fine-tuning track (needs GPU compute)
- Red-team track (needs adversarial test design)
- LTI 1.3 grade passback (REST API is sufficient for v1)
- Multi-instructor self-serve UI (one instructor for v1)
- Cross-course leaderboards (D4-only for v1)

---

## Useful commands (placeholder — fill in as repo grows)

```bash
# Local dev
uv venv && source .venv/bin/activate
uv pip install -r requirements.txt
uvicorn api.main:app --reload

# Tests
pytest -xvs tests/

# Deploy FastAPI to Cloud Run
gcloud run deploy d4-arena-api --source . --region us-central1

# Deploy leaderboard to Firebase Hosting
cd leaderboard && firebase deploy --only hosting

# Tail logs
gcloud logging tail "resource.type=cloud_run_revision"
```

---

## Notes for Claude Code

- This file (`PLAN.md`) is the project anchor. Read it at the start of every session.
- Before writing any new code, check the day-by-day TODO above and the "Out of scope for v1" list.
- When in doubt about a tradeoff, prefer: simple over clever, tested over untested, working over perfect.
- The user (Adisak) prefers structured tables, alternative comparisons, and ready-to-run deliverables. Match that style.
- The codebase will eventually be open-sourced as a teaching artifact — write it as if a curious student will read every line.
