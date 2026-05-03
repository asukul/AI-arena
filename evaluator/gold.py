"""
Gold-data loader.

Hidden test data (gold labels, gold answers, gold citations) lives on the
server only — never in API responses. This module is the only place that
reads it from disk; downstream scorers receive in-memory mappings.

For v1 we keep gold data as plain JSON files alongside the corpus, indexed
by track_id. A future iteration may move it to a Firestore collection or a
private Cloud Storage bucket so it can be rotated without redeploying.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class GoldProvider:
    """Resolves a track_id to its gold dataset (shape varies by track)."""

    def __init__(self, gold_dir: Path) -> None:
        self.gold_dir = gold_dir

    def for_track(self, track_id: str) -> Any:
        path = self.gold_dir / f"{track_id}.json"
        if not path.exists():
            raise FileNotFoundError(
                f"No gold data for track_id={track_id!r} at {path}. "
                f"Drop a JSON file there to register it."
            )
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
