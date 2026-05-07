"""
Admin page — manage the active judge provider, API key, and model.

  GET  /admin                — token-gated HTML console
  GET  /admin/current        — JSON of the active config (no key in response)
  POST /admin/test           — body: {provider, api_key} → returns {ok, models[], error?}
  POST /admin/save           — body: {provider, model, api_key} → persist + invalidate cache

Auth:
  All non-static endpoints require an `X-Admin-Token` header (or the same
  value as `?token=...` query param on /admin). The expected value is read
  from `ADMIN_TOKEN` env var (mounted from Secret Manager). If unset or
  empty, admin endpoints return 503 — there's no anonymous-admin mode.

Security note: the API key is never logged and never returned in any
response after save. The /admin/current endpoint omits it. The admin
page UI clears its key field on successful save.
"""

from __future__ import annotations

import json
import os
import secrets
from html import escape
from typing import Any

from fastapi import HTTPException, Request

from api.admin_config import AdminStore, invalidate_cache
from evaluator.providers import PROVIDER_NAMES, get_provider


# ---------- Auth helpers ----------

def _expected_token() -> str:
    """Pulled at request time so a Cloud Run secret refresh takes effect
    without restarting the process."""
    return (os.environ.get("ADMIN_TOKEN") or "").strip()


def require_admin(request: Request) -> None:
    """Constant-time compare against ADMIN_TOKEN. Raises 401/503."""
    expected = _expected_token()
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="Admin disabled: ADMIN_TOKEN secret is not configured on this service.",
        )
    candidate = (
        request.headers.get("x-admin-token")
        or request.query_params.get("token")
        or ""
    )
    if not candidate or not secrets.compare_digest(candidate, expected):
        raise HTTPException(
            status_code=401,
            detail="invalid admin token",
        )


# ---------- HTML page ----------

_ADMIN_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>AI Arena — Admin</title>
  <style>
    :root { color-scheme: dark; }
    * { box-sizing: border-box; }
    body {
      margin: 0; padding: 0; min-height: 100vh;
      font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
      background: #0c1017; color: #f5f5f7; line-height: 1.5;
    }
    .topbar {
      background: #0a0d14; border-bottom: 1px solid #1d2434;
      padding: 0 24px; height: 48px;
      display: flex; align-items: center; gap: 24px;
    }
    .topbar .logo { font-weight: 700; }
    .topbar .logo .accent { color: #ffc107; }
    .topbar .topbar-nav { display: flex; gap: 18px; margin-left: auto; }
    .topbar .topbar-nav a { color: #a8b1bf; font-size: 14px; text-decoration: none; }
    .topbar .topbar-nav a:hover { color: #f5f5f7; }
    main { max-width: 720px; margin: 0 auto; padding: 32px 24px 64px; }
    h1 { font-size: 28px; margin: 0 0 6px 0; letter-spacing: -0.4px; }
    h1 .accent { color: #ffc107; }
    .tagline { color: #a8b1bf; margin: 0 0 24px 0; font-size: 14px; }
    .card {
      background: #151c28; border: 1px solid #232c3d; border-radius: 12px;
      padding: 22px 26px; margin: 0 0 18px 0;
    }
    .card h2 {
      margin: 0 0 12px 0; font-size: 14px; color: #ffd460;
      text-transform: uppercase; letter-spacing: 0.6px;
    }
    label { display: block; margin: 14px 0 6px; font-size: 13px; color: #c9d1de; }
    select, input[type=text], input[type=password] {
      width: 100%; padding: 10px 12px; background: #0a0d14;
      color: #f5f5f7; border: 1px solid #232c3d; border-radius: 8px;
      font-family: inherit; font-size: 14px;
    }
    select:focus, input:focus { outline: none; border-color: #2c80ff; }
    .row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
    .row > * { flex: 1 1 auto; }
    button.btn {
      padding: 10px 18px; border-radius: 8px; border: 1px solid transparent;
      font-size: 14px; font-weight: 600; cursor: pointer; white-space: nowrap;
    }
    button.btn-primary { background: #2c80ff; color: white; flex: 0 0 auto; }
    button.btn-primary:hover { background: #4592ff; }
    button.btn-primary:disabled { background: #2a3447; cursor: not-allowed; }
    button.btn-secondary { background: transparent; color: #a8b1bf; border-color: #2a3447; flex: 0 0 auto; }
    button.btn-secondary:hover { color: #f5f5f7; border-color: #4a5568; }
    .status { padding: 10px 14px; border-radius: 8px; margin-top: 12px;
              font-size: 13px; white-space: pre-wrap; word-break: break-word; }
    .status.ok  { background: #102d1b; color: #a6e8b6; border: 1px solid #1d4d2b; }
    .status.err { background: #2d1010; color: #f5b8b8; border: 1px solid #4d1d1d; }
    .status.info { background: #102030; color: #a4d6ff; border: 1px solid #1c3654; }
    .pill {
      display: inline-block; padding: 3px 10px; border-radius: 999px;
      font-size: 12px; font-weight: 600; background: #1d4d2b; color: #a6e8b6;
    }
    .muted { color: #6d7787; font-size: 12px; margin-top: 6px; }
    code { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
           font-size: 12px; background: #1d2434; padding: 2px 6px; border-radius: 4px; }
    .hidden { display: none; }
  </style>
</head>
<body>
  <div class="topbar">
    <div class="logo">AI <span class="accent">Arena</span></div>
    <nav class="topbar-nav">
      <a href="/">Competitions</a>
      <a href="/get-started">Docs</a>
    </nav>
  </div>
  <main>
    <h1>Admin <span class="accent">Console</span></h1>
    <p class="tagline">
      Configure the LLM judge used by Track 2 (Prompt Golf) and Track 3
      (RAG Treasure Hunt). Keys live in Secret Manager; metadata lives in
      Firestore. Only this page writes to either.
    </p>

    <div class="card" id="auth-card">
      <h2>Authenticate</h2>
      <p class="muted">
        Enter the admin token (the value of the <code>admin-token</code> Secret Manager secret).
        It's saved to this browser's localStorage so you don't have to re-enter on refresh.
      </p>
      <label for="token-input">Admin token</label>
      <input type="password" id="token-input" autocomplete="off" placeholder="••••••••••••••••" />
      <div class="row" style="margin-top:12px;">
        <button class="btn btn-primary" id="auth-btn" type="button">Sign in</button>
        <button class="btn btn-secondary" id="forget-btn" type="button">Forget token</button>
      </div>
      <div id="auth-status" class="status info hidden"></div>
    </div>

    <div class="card hidden" id="current-card">
      <h2>Active configuration</h2>
      <div id="current-status" class="status info">Loading…</div>
    </div>

    <div class="card hidden" id="config-card">
      <h2>Set or rotate judge</h2>

      <label for="provider">Provider</label>
      <select id="provider">
        <option value="">— pick a provider —</option>
        <option value="anthropic">Anthropic (Claude — paid)</option>
        <option value="gemini">Google Gemini (free tier on Flash)</option>
        <option value="openai">OpenAI</option>
        <option value="openrouter">OpenRouter (multi-provider proxy)</option>
      </select>

      <label for="api-key">API key</label>
      <input type="password" id="api-key" autocomplete="off" placeholder="sk-… / AIza… / your provider's key" />
      <div class="muted">
        The key is sent over HTTPS to this service, written to Secret
        Manager, and never returned in any response. It's not logged.
      </div>

      <div class="row" style="margin-top:14px;">
        <button class="btn btn-primary" id="test-btn" type="button">Test connection &rarr;</button>
        <button class="btn btn-secondary" id="clear-btn" type="button">Clear</button>
      </div>

      <div id="test-status" class="status hidden"></div>

      <div id="model-row" class="hidden" style="margin-top: 16px;">
        <label for="model">Pick a model</label>
        <select id="model">
          <option value="">—</option>
        </select>
        <div class="row" style="margin-top:14px;">
          <button class="btn btn-primary" id="save-btn" type="button" disabled>Save as active judge</button>
        </div>
        <div id="save-status" class="status hidden"></div>
      </div>
    </div>
  </main>

<script>
(function () {
  const TOKEN_KEY = 'arena_admin_token';

  const $ = (id) => document.getElementById(id);
  const tokenInput = $('token-input');
  const authBtn    = $('auth-btn');
  const forgetBtn  = $('forget-btn');
  const authStatus = $('auth-status');
  const currentCard = $('current-card');
  const currentStatus = $('current-status');
  const configCard = $('config-card');
  const providerSel = $('provider');
  const keyInput = $('api-key');
  const testBtn = $('test-btn');
  const clearBtn = $('clear-btn');
  const testStatus = $('test-status');
  const modelRow = $('model-row');
  const modelSel = $('model');
  const saveBtn = $('save-btn');
  const saveStatus = $('save-status');

  function getToken()  { try { return localStorage.getItem(TOKEN_KEY) || ''; } catch { return ''; } }
  function setToken(t) { try { localStorage.setItem(TOKEN_KEY, t); } catch {} }
  function delToken()  { try { localStorage.removeItem(TOKEN_KEY); } catch {} }

  function show(el)    { el.classList.remove('hidden'); }
  function hide(el)    { el.classList.add('hidden'); }
  function setStatus(el, kind, text) {
    el.className = 'status ' + kind;
    el.textContent = text;
    el.classList.remove('hidden');
  }

  async function api(path, method, body) {
    const headers = { 'X-Admin-Token': getToken() };
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    const r = await fetch(path, {
      method,
      headers,
      body: body ? JSON.stringify(body) : null,
    });
    let data = null;
    try { data = await r.json(); } catch {}
    return { ok: r.ok, status: r.status, data };
  }

  // ---------- Auth flow ----------
  async function refreshAfterAuth() {
    show(currentCard);
    show(configCard);
    const r = await api('/admin/current', 'GET');
    if (r.ok && r.data) {
      const d = r.data;
      const updated = d.updated_at ? ` (updated ${new Date(d.updated_at).toLocaleString()})` : '';
      const by = d.updated_by ? ` by ${d.updated_by}` : '';
      const text = d.provider
        ? `Active: ${d.provider} / ${d.model}${updated}${by}`
        : 'No active judge config — set one below.';
      setStatus(currentStatus, d.provider ? 'ok' : 'info', text);
    } else if (r.status === 401) {
      setStatus(authStatus, 'err', 'Invalid token. Re-enter and try again.');
      hide(currentCard); hide(configCard);
      delToken();
      tokenInput.value = '';
      tokenInput.focus();
    } else {
      setStatus(currentStatus, 'err',
        'Could not load current config: ' + (r.data ? JSON.stringify(r.data) : `HTTP ${r.status}`));
    }
  }

  authBtn.addEventListener('click', () => {
    const v = tokenInput.value.trim();
    if (!v) { setStatus(authStatus, 'err', 'Token is empty.'); return; }
    setToken(v);
    hide(authStatus);
    refreshAfterAuth();
  });

  forgetBtn.addEventListener('click', () => {
    delToken();
    tokenInput.value = '';
    hide(currentCard); hide(configCard); hide(authStatus);
  });

  if (getToken()) {
    tokenInput.value = '••••••••••••••••';
    refreshAfterAuth();
  }

  // ---------- Test connection ----------
  testBtn.addEventListener('click', async () => {
    const provider = providerSel.value;
    const api_key  = keyInput.value.trim();
    if (!provider) { setStatus(testStatus, 'err', 'Pick a provider first.'); return; }
    if (!api_key)  { setStatus(testStatus, 'err', 'Paste an API key first.'); return; }

    testBtn.disabled = true;
    setStatus(testStatus, 'info', 'Testing…');
    hide(modelRow);
    saveBtn.disabled = true;

    const r = await api('/admin/test', 'POST', { provider, api_key });
    testBtn.disabled = false;

    if (r.ok && r.data && r.data.ok) {
      const models = r.data.models || [];
      modelSel.innerHTML = '<option value="">— pick a model —</option>'
        + models.map(m =>
            `<option value="${m.id}">${m.name || m.id}${m.description ? ' — ' + m.description : ''}</option>`
          ).join('');
      setStatus(testStatus, 'ok',
        `Connected. ${models.length} model${models.length === 1 ? '' : 's'} available.`);
      show(modelRow);
    } else {
      const detail = r.data && r.data.error ? r.data.error : (r.data ? JSON.stringify(r.data) : `HTTP ${r.status}`);
      setStatus(testStatus, 'err', 'Test failed: ' + detail);
    }
  });

  modelSel.addEventListener('change', () => {
    saveBtn.disabled = !modelSel.value;
  });

  // ---------- Save ----------
  saveBtn.addEventListener('click', async () => {
    const provider = providerSel.value;
    const api_key  = keyInput.value.trim();
    const model    = modelSel.value;
    if (!provider || !api_key || !model) { return; }

    saveBtn.disabled = true;
    setStatus(saveStatus, 'info', 'Saving to Secret Manager + Firestore…');
    const r = await api('/admin/save', 'POST', { provider, model, api_key });

    if (r.ok && r.data && r.data.ok) {
      setStatus(saveStatus, 'ok',
        `Saved. ${provider} / ${model} is now the active judge. New submissions to Tracks 2 & 3 will use it.`);
      keyInput.value = '';
      refreshAfterAuth();
    } else {
      const detail = r.data && r.data.error ? r.data.error : (r.data ? JSON.stringify(r.data) : `HTTP ${r.status}`);
      setStatus(saveStatus, 'err', 'Save failed: ' + detail);
      saveBtn.disabled = false;
    }
  });

  clearBtn.addEventListener('click', () => {
    providerSel.value = '';
    keyInput.value = '';
    modelSel.innerHTML = '<option value="">—</option>';
    hide(testStatus); hide(modelRow); hide(saveStatus);
    saveBtn.disabled = true;
  });
})();
</script>
</body>
</html>
"""


def render_admin_html() -> str:
    """The admin page renders the same HTML for everyone — auth happens
    client-side against /admin/current. No server-side templating needed."""
    return _ADMIN_HTML


# ---------- Endpoint helpers (called from api/main.py) ----------

def serialize_current(store: AdminStore) -> dict[str, Any]:
    """Read the active config and return a JSON-safe dict.

    The api_key is omitted from the response — by design. The admin can
    rotate by entering a new key in the UI; they shouldn't need to read
    the old one back from the platform.
    """
    cfg = store.read()
    if cfg is None:
        return {"provider": None, "model": None, "updated_at": None, "updated_by": None}
    return {
        "provider": cfg.provider,
        "model": cfg.model,
        "updated_at": cfg.updated_at.isoformat() if cfg.updated_at else None,
        "updated_by": cfg.updated_by,
    }


def test_connection(*, provider: str, api_key: str) -> dict[str, Any]:
    """Used by POST /admin/test. Returns {ok, models, error?}."""
    if provider not in PROVIDER_NAMES:
        return {"ok": False, "error": f"unknown provider: {provider!r}"}
    try:
        models = get_provider(provider).list_models(api_key)
    except Exception as exc:
        return {"ok": False, "error": _human_error(exc)}
    return {
        "ok": True,
        "models": [
            {"id": m.id, "name": m.name, "description": m.description}
            for m in models
        ],
    }


def save_config(
    store: AdminStore, *, provider: str, model: str, api_key: str, updated_by: str,
) -> dict[str, Any]:
    """Used by POST /admin/save. Persists then invalidates the runner's cache."""
    if provider not in PROVIDER_NAMES:
        return {"ok": False, "error": f"unknown provider: {provider!r}"}
    if not model:
        return {"ok": False, "error": "model is required"}
    if not api_key:
        return {"ok": False, "error": "api_key is required"}
    try:
        store.write(provider=provider, model=model, api_key=api_key, updated_by=updated_by)
    except Exception as exc:
        return {"ok": False, "error": _human_error(exc)}
    invalidate_cache()
    return {"ok": True}


def _human_error(exc: Exception) -> str:
    """Trim provider stack traces to one human-readable line for the UI."""
    msg = str(exc) or exc.__class__.__name__
    # httpx errors include the request URL — strip it so we don't leak
    # the API key (which Gemini puts in the URL as a query param).
    if "?key=" in msg:
        msg = msg.split("?key=", 1)[0] + "?key=<redacted>"
    return msg[:300]
