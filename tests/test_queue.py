"""Tests for the in-memory queue. (Cloud Tasks variant is exercised in deploy.)"""

from __future__ import annotations

from api.queue import InMemoryQueue


def test_in_memory_queue_invokes_handler_synchronously() -> None:
    seen: list[dict] = []
    queue = InMemoryQueue(handler=seen.append)
    task_id = queue.enqueue({"submission_id": "s1", "x": 1})
    assert task_id == "local-task-0001"
    assert seen == [{"submission_id": "s1", "x": 1}]


def test_in_memory_queue_records_each_enqueue() -> None:
    seen: list[dict] = []
    queue = InMemoryQueue(handler=seen.append)
    queue.enqueue({"a": 1})
    queue.enqueue({"a": 2})
    queue.enqueue({"a": 3})
    assert [s["a"] for s in queue.enqueued] == [1, 2, 3]
    assert len(seen) == 3
