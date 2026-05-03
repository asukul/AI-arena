"""
Submission-queue abstraction.

Two implementations:

  CloudTasksQueue   — production. Creates an HTTP task that POSTs the
                      submission JSON to the evaluator endpoint with OIDC
                      auth, so Cloud Run knows the request really came from
                      our queue and not from a random caller.

  InMemoryQueue     — local dev / tests. Synchronously invokes the handler
                      inline. Lets us run the whole pipeline on a laptop with
                      zero GCP credentials, and lets pytest assert what got
                      enqueued without spinning up the gRPC client.

Production caller is `api.main` (the /submit handler).  Production target is
`/internal/evaluate` on the same Cloud Run service.

Lazy-import the google-cloud-tasks SDK so importing this module never
requires the gRPC stack to be installed.  Tests can stub freely.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, Protocol


class SubmissionQueue(Protocol):
    """Anything that can enqueue a submission for evaluation."""

    def enqueue(self, submission_json: dict[str, Any]) -> str:
        """Schedule the submission. Returns an opaque task identifier."""
        ...


class InMemoryQueue:
    """Synchronous in-process queue. The handler runs inline at enqueue time."""

    def __init__(self, handler: Callable[[dict[str, Any]], None]) -> None:
        self._handler = handler
        self.enqueued: list[dict[str, Any]] = []

    def enqueue(self, submission_json: dict[str, Any]) -> str:
        self.enqueued.append(submission_json)
        self._handler(submission_json)
        return f"local-task-{len(self.enqueued):04d}"


class CloudTasksQueue:
    """Production queue backed by Google Cloud Tasks."""

    def __init__(
        self,
        project_id: str,
        region: str,
        queue_id: str,
        target_url: str,
        invoker_sa: str,
    ) -> None:
        if not target_url:
            raise ValueError("CloudTasksQueue requires EVALUATOR_TARGET_URL to be set")
        if not invoker_sa:
            raise ValueError("CloudTasksQueue requires TASKS_INVOKER_SA to be set")
        self.project_id = project_id
        self.region = region
        self.queue_id = queue_id
        self.target_url = target_url
        self.invoker_sa = invoker_sa
        self._client: Any | None = None

    def _get_client(self) -> Any:
        if self._client is None:
            from google.cloud import tasks_v2  # lazy: keep import out of test paths
            self._client = tasks_v2.CloudTasksClient()
        return self._client

    def enqueue(self, submission_json: dict[str, Any]) -> str:
        from google.cloud import tasks_v2

        client = self._get_client()
        parent = client.queue_path(self.project_id, self.region, self.queue_id)
        task: dict[str, Any] = {
            "http_request": {
                "http_method": tasks_v2.HttpMethod.POST,
                "url": self.target_url,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps(submission_json).encode("utf-8"),
                "oidc_token": {"service_account_email": self.invoker_sa},
            }
        }
        created = client.create_task(parent=parent, task=task)
        return str(created.name)
