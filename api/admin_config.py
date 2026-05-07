"""
Admin-managed judge configuration.

Stores the active judge {provider, model} in Firestore at
`admin_config/judge_active`, and the API key in Secret Manager as
`judge-api-key`. Separating them keeps the (cheap, frequently-read)
metadata in Firestore and the (sensitive) credential in Secret Manager.

The runner reads this configuration at submission time via
`get_active_judge_config()` (which is cached for `_CACHE_TTL_S`
seconds so we don't hammer Firestore on every judge call).

Two implementations:

  FirestoreAdminStore   — production. Lazy-imports google-cloud-firestore
                          and google-cloud-secret-manager.
  InMemoryAdminStore    — local dev / tests. Plain dict.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol


_CACHE_TTL_S = 300  # 5 minutes — short enough that an admin key rotation
                    # is felt promptly, long enough that we don't read
                    # Firestore on every single judge call.


@dataclass(frozen=True)
class JudgeConfig:
    """The active judge configuration. Returned by AdminStore.read()."""
    provider: str               # "anthropic" | "gemini" | "openai" | "openrouter"
    model: str                  # the model id passed to the provider
    api_key: str                # the actual key — NEVER logged
    updated_at: datetime | None = None
    updated_by: str | None = None


class AdminStore(Protocol):
    """Read/write the active judge config. Two implementations below."""
    def read(self) -> JudgeConfig | None: ...
    def write(self, *, provider: str, model: str, api_key: str, updated_by: str) -> None: ...


# ---------- In-memory implementation (dev / tests) ----------

class InMemoryAdminStore:
    """A single in-process slot for the active config. Tests use this."""

    def __init__(self) -> None:
        self._config: JudgeConfig | None = None

    def read(self) -> JudgeConfig | None:
        return self._config

    def write(self, *, provider: str, model: str, api_key: str, updated_by: str) -> None:
        self._config = JudgeConfig(
            provider=provider,
            model=model,
            api_key=api_key,
            updated_at=datetime.now(UTC),
            updated_by=updated_by,
        )


# ---------- Production: Firestore + Secret Manager ----------

_FIRESTORE_DOC = ("admin_config", "judge_active")  # collection, document
_SECRET_NAME = "judge-api-key"


class FirestoreAdminStore:
    """Production AdminStore.

    Metadata (provider, model, updated_at, updated_by) lives in Firestore.
    The API key lives in Secret Manager — versioned, with audit trail,
    and easily rotated via `gcloud secrets versions add`.
    """

    def __init__(self, project_id: str) -> None:
        self.project_id = project_id
        self._fs: Any | None = None
        self._sm: Any | None = None

    def _firestore(self) -> Any:
        if self._fs is None:
            from google.cloud import firestore  # lazy
            self._fs = firestore.Client(project=self.project_id)
        return self._fs

    def _secret_client(self) -> Any:
        if self._sm is None:
            from google.cloud import secretmanager  # lazy
            self._sm = secretmanager.SecretManagerServiceClient()
        return self._sm

    def read(self) -> JudgeConfig | None:
        coll, doc = _FIRESTORE_DOC
        snap = self._firestore().collection(coll).document(doc).get()
        if not snap.exists:
            return None
        data = snap.to_dict() or {}
        provider = data.get("provider")
        model = data.get("model")
        if not provider or not model:
            return None
        api_key = self._read_secret()
        if not api_key:
            return None
        return JudgeConfig(
            provider=str(provider),
            model=str(model),
            api_key=api_key,
            updated_at=data.get("updated_at"),
            updated_by=data.get("updated_by"),
        )

    def write(
        self, *, provider: str, model: str, api_key: str, updated_by: str
    ) -> None:
        # 1. Append a new version to the Secret Manager secret. Auto-create
        #    the secret on first save (a fresh project won't have it yet).
        self._write_secret(api_key)

        # 2. Write metadata to Firestore. Field names are lowercase-snake
        #    so the same document can be inspected from `gcloud firestore`.
        coll, doc = _FIRESTORE_DOC
        self._firestore().collection(coll).document(doc).set({
            "provider": provider,
            "model": model,
            "updated_at": datetime.now(UTC),
            "updated_by": updated_by,
        })

    def _read_secret(self) -> str:
        client = self._secret_client()
        name = f"projects/{self.project_id}/secrets/{_SECRET_NAME}/versions/latest"
        try:
            response = client.access_secret_version(request={"name": name})
            return response.payload.data.decode("utf-8").strip()
        except Exception:
            return ""

    def _write_secret(self, api_key: str) -> None:
        from google.api_core import exceptions as gax_exceptions
        client = self._secret_client()
        parent = f"projects/{self.project_id}"
        secret_path = f"{parent}/secrets/{_SECRET_NAME}"

        # Auto-create the secret if it doesn't exist yet. This makes the
        # admin page work cleanly on a fresh project — no manual setup.
        try:
            client.get_secret(request={"name": secret_path})
        except gax_exceptions.NotFound:
            client.create_secret(
                request={
                    "parent": parent,
                    "secret_id": _SECRET_NAME,
                    "secret": {"replication": {"automatic": {}}},
                }
            )

        client.add_secret_version(
            request={
                "parent": secret_path,
                "payload": {"data": api_key.encode("utf-8")},
            }
        )


# ---------- Cached read for hot paths ----------

_cache_value: JudgeConfig | None = None
_cache_expires_at: float = 0.0


def get_active_judge_config(store: AdminStore) -> JudgeConfig | None:
    """Cached accessor used by the runner on every submission.

    Cache is process-local (Cloud Run scales horizontally, so each instance
    will see its own first-read latency, but each subsequent read is free).
    Admin saves bump the cache via `invalidate_cache()` so a new key takes
    effect on the *next* judge call within the same instance.
    """
    global _cache_value, _cache_expires_at
    now = time.monotonic()
    if _cache_value is not None and now < _cache_expires_at:
        return _cache_value
    cfg = store.read()
    _cache_value = cfg
    _cache_expires_at = now + _CACHE_TTL_S
    return cfg


def invalidate_cache() -> None:
    """Force the next read to bypass the cache."""
    global _cache_value, _cache_expires_at
    _cache_value = None
    _cache_expires_at = 0.0
