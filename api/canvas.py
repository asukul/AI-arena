"""
Canvas REST API client.

We need exactly two operations from Canvas for v1:

  1. Fetch a submission's metadata (course id, assignment id, user id, file
     URL) when the webhook arrives.  The webhook payload itself often
     includes most of this, but we GET to confirm the file URL and posted
     state.

  2. Post the score back to the originating assignment so it lands in the
     student's gradebook.

Auth is a personal-access token in the `Authorization: Bearer …` header.
The token is loaded from Secret Manager into env (`CANVAS_API_TOKEN`).

`dry_run=True` lets local dev exercise the call shape without touching the
real LMS.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

log = logging.getLogger(__name__)


class CanvasClient:
    def __init__(
        self,
        base_url: str,
        api_token: str,
        *,
        dry_run: bool = False,
        timeout: float = 15.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_token = api_token
        self.dry_run = dry_run
        self._timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_token}",
            "Accept": "application/json",
        }

    def post_grade(
        self,
        *,
        course_id: int,
        assignment_id: int,
        user_id: int,
        score: float,
        comment: str | None = None,
    ) -> dict[str, Any]:
        """PUT a score (and optional comment) to a single submission.

        See: https://canvas.instructure.com/doc/api/submissions.html
             #method.submissions_api.update
        """
        if self.dry_run:
            log.info(
                "canvas.post_grade dry_run course=%s assn=%s user=%s score=%.4f",
                course_id, assignment_id, user_id, score,
            )
            return {"dry_run": True, "score": score}

        url = (
            f"{self.base_url}/api/v1/courses/{course_id}"
            f"/assignments/{assignment_id}/submissions/{user_id}"
        )
        body: dict[str, Any] = {"submission": {"posted_grade": str(score)}}
        if comment:
            body["comment"] = {"text_comment": comment}

        with httpx.Client(timeout=self._timeout) as client:
            response = client.put(url, headers=self._headers(), json=body)
            response.raise_for_status()
            return dict(response.json())

    def fetch_submission_file(self, file_url: str) -> bytes:
        """GET the bytes of a student's uploaded submission file.

        Canvas file URLs are pre-authenticated via a `verifier` query param
        in the webhook payload, so we don't strictly need the bearer token —
        but sending it is harmless and works for un-verified URLs too.
        """
        if self.dry_run:
            log.info("canvas.fetch_submission_file dry_run url=%s", file_url)
            return b""

        with httpx.Client(timeout=self._timeout) as client:
            response = client.get(file_url, headers=self._headers())
            response.raise_for_status()
            return response.content
