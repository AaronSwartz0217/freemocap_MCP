"""
Task queue service: Celery + Redis backed async task execution,
with an in-process (threading) fallback for development/testing
when Redis is unavailable.

Environment variables:
  FMC_TASK_QUEUE_BACKEND  - "celery" (default if Redis available) or "inprocess"
  FMC_REDIS_URL           - Redis URL, e.g. redis://localhost:6379/0
  FMC_CELERY_BROKER       - Celery broker URL (defaults to FMC_REDIS_URL)
  FMC_CELERY_BACKEND      - Celery result backend URL (defaults to FMC_REDIS_URL)
"""
from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Task state / status
# ---------------------------------------------------------------------------
class TaskState(str, Enum):
    PENDING = "PENDING"        # queued, not started
    STARTED = "STARTED"        # worker picked it up
    PROGRESS = "PROGRESS"      # running, progress reported
    SUCCESS = "SUCCESS"        # completed successfully
    FAILURE = "FAILURE"        # failed with exception
    REVOKED = "REVOKED"        # cancelled


@dataclass
class TaskStatus:
    task_id: str
    state: str
    progress: float = 0.0
    message: str = ""
    result: Any | None = None
    error: str | None = None
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = {
            "task_id": self.task_id,
            "state": self.state,
            "progress": self.progress,
            "message": self.message,
        }
        if self.state == TaskState.SUCCESS and self.result is not None:
            d["result"] = self.result
        if self.state == TaskState.FAILURE and self.error is not None:
            d["error"] = self.error
        if self.metadata:
            d["metadata"] = self.metadata
        return d


# ---------------------------------------------------------------------------
# Task registry: maps task_type -> callable(payload, report_progress)
# ---------------------------------------------------------------------------
TaskFunc = Callable[[dict, Callable], Any]
_TASK_REGISTRY: dict[str, TaskFunc] = {}


def register_task(task_type: str):
    """Decorator to register a task function."""
    def decorator(func: TaskFunc) -> TaskFunc:
        _TASK_REGISTRY[task_type] = func
        logger.debug("Registered task type: %s", task_type)
        return func
    return decorator


def get_registered_task_types() -> list[str]:
    return sorted(_TASK_REGISTRY.keys())


# ---------------------------------------------------------------------------
# Demo / built-in tasks (for testing the queue)
# ---------------------------------------------------------------------------
@register_task("demo.echo")
def _demo_echo(payload: dict, report_progress: Callable) -> dict:
    """Simply echo back the payload."""
    report_progress(1.0, "echo done")
    return {"echo": payload}


@register_task("demo.long_task")
def _demo_long_task(payload: dict, report_progress: Callable) -> dict:
    """Simulate a long-running task with periodic progress updates."""
    steps = int(payload.get("steps", 5))
    delay = float(payload.get("delay", 0.2))
    for i in range(1, steps + 1):
        progress = i / steps
        report_progress(progress, f"step {i}/{steps}")
        time.sleep(delay)
    return {"steps": steps, "done": True}


# ---------------------------------------------------------------------------
# Abstract queue backend
# ---------------------------------------------------------------------------
class TaskQueueBackend:
    def submit_task(self, task_type: str, payload: dict) -> str:
        raise NotImplementedError

    def get_status(self, task_id: str) -> TaskStatus | None:
        raise NotImplementedError

    def get_result(self, task_id: str) -> Any | None:
        raise NotImplementedError

    def cancel_task(self, task_id: str) -> bool:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# In-process backend (threading) — fallback when Redis is unavailable
# ---------------------------------------------------------------------------
class InProcessTaskQueue(TaskQueueBackend):
    """Simple in-process task queue using threads.

    Suitable for development and single-instance testing. NOT for production
    (no persistence, no cross-process distribution).
    """

    def __init__(self):
        self._tasks: dict[str, TaskStatus] = {}
        self._lock = threading.Lock()
        self._cancel_flags: dict[str, threading.Event] = {}

    def submit_task(self, task_type: str, payload: dict) -> str:
        task_id = str(uuid.uuid4())
        cancel_event = threading.Event()
        with self._lock:
            self._tasks[task_id] = TaskStatus(
                task_id=task_id, state=TaskState.PENDING, progress=0.0,
                message="queued",
            )
            self._cancel_flags[task_id] = cancel_event

        func = _TASK_REGISTRY.get(task_type)
        if func is None:
            with self._lock:
                self._tasks[task_id].state = TaskState.FAILURE
                self._tasks[task_id].error = f"Unknown task type: {task_type}"
            return task_id

        def report_progress(progress: float, message: str = ""):
            if cancel_event.is_set():
                raise RuntimeError("task cancelled")
            with self._lock:
                if task_id in self._tasks:
                    self._tasks[task_id].state = TaskState.PROGRESS
                    self._tasks[task_id].progress = float(progress)
                    self._tasks[task_id].message = message

        def runner():
            try:
                with self._lock:
                    self._tasks[task_id].state = TaskState.STARTED
                    self._tasks[task_id].message = "started"
                result = func(payload, report_progress)
                with self._lock:
                    self._tasks[task_id].state = TaskState.SUCCESS
                    self._tasks[task_id].progress = 1.0
                    self._tasks[task_id].message = "completed"
                    self._tasks[task_id].result = result
            except RuntimeError as e:
                if "cancelled" in str(e).lower():
                    with self._lock:
                        self._tasks[task_id].state = TaskState.REVOKED
                        self._tasks[task_id].message = "cancelled"
                else:
                    with self._lock:
                        self._tasks[task_id].state = TaskState.FAILURE
                        self._tasks[task_id].error = str(e)
            except Exception as e:
                logger.exception("Task %s failed", task_id)
                with self._lock:
                    self._tasks[task_id].state = TaskState.FAILURE
                    self._tasks[task_id].error = f"{type(e).__name__}: {e}"

        thread = threading.Thread(target=runner, daemon=True, name=f"task-{task_id[:8]}")
        thread.start()
        return task_id

    def get_status(self, task_id: str) -> TaskStatus | None:
        with self._lock:
            status = self._tasks.get(task_id)
            return TaskStatus(**status.__dict__) if status else None

    def get_result(self, task_id: str) -> Any | None:
        with self._lock:
            status = self._tasks.get(task_id)
            if status is None:
                return None
            if status.state == TaskState.SUCCESS:
                return status.result
            if status.state == TaskState.FAILURE:
                return {"error": status.error}
            return None

    def cancel_task(self, task_id: str) -> bool:
        with self._lock:
            status = self._tasks.get(task_id)
            event = self._cancel_flags.get(task_id)
        if status is None:
            return False
        if status.state in (TaskState.SUCCESS, TaskState.FAILURE, TaskState.REVOKED):
            return False
        if event:
            event.set()
        with self._lock:
            status.state = TaskState.REVOKED
            status.message = "cancellation requested"
        return True


# ---------------------------------------------------------------------------
# Celery backend (Redis broker + result backend)
# ---------------------------------------------------------------------------
class CeleryTaskQueue(TaskQueueBackend):
    """Celery-backed task queue with Redis broker and result backend."""

    def __init__(self, broker_url: str, backend_url: str):
        from celery import Celery

        self._celery = Celery(
            "freemocap_tasks",
            broker=broker_url,
            backend=backend_url,
        )
        self._celery.conf.update(
            task_serializer="json",
            result_serializer="json",
            accept_content=["json"],
            timezone="UTC",
            enable_utc=True,
            task_track_started=True,
            result_expires=3600,
        )

        @self._celery.task(bind=True, name="freemocap.run_task")
        def run_task(self, task_type: str, payload: dict):
            func = _TASK_REGISTRY.get(task_type)
            if func is None:
                raise ValueError(f"Unknown task type: {task_type}")

            def report_progress(progress: float, message: str = ""):
                self.update_state(
                    state=TaskState.PROGRESS,
                    meta={"progress": float(progress), "message": message},
                )

            return func(payload, report_progress)

        self._run_task = run_task

    def submit_task(self, task_type: str, payload: dict) -> str:
        result = self._run_task.delay(task_type, payload)
        return result.id

    def get_status(self, task_id: str) -> TaskStatus | None:
        result = self._celery.AsyncResult(task_id)
        state = result.state
        info = result.info or {}
        progress = 0.0
        message = ""
        error = None
        task_result = None

        if state == TaskState.PROGRESS and isinstance(info, dict):
            progress = info.get("progress", 0.0)
            message = info.get("message", "")
        elif state == TaskState.SUCCESS:
            progress = 1.0
            message = "completed"
            task_result = result.result
        elif state == TaskState.FAILURE:
            error = str(result.result) if result.result else "unknown error"

        return TaskStatus(
            task_id=task_id,
            state=state,
            progress=progress,
            message=message,
            result=task_result,
            error=error,
        )

    def get_result(self, task_id: str) -> Any | None:
        result = self._celery.AsyncResult(task_id)
        if result.state == TaskState.SUCCESS:
            return result.result
        if result.state == TaskState.FAILURE:
            return {"error": str(result.result)}
        return None

    def cancel_task(self, task_id: str) -> bool:
        result = self._celery.AsyncResult(task_id)
        if result.state in (TaskState.SUCCESS, TaskState.FAILURE, TaskState.REVOKED):
            return False
        result.revoke(terminate=True)
        return True


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------
def get_task_queue() -> TaskQueueBackend:
    """Return the configured task queue backend.

    Falls back to InProcessTaskQueue if Celery/Redis is unavailable.
    """
    backend = os.environ.get("FMC_TASK_QUEUE_BACKEND", "").lower()
    redis_url = os.environ.get("FMC_REDIS_URL", "redis://localhost:6379/0")
    broker_url = os.environ.get("FMC_CELERY_BROKER", redis_url)
    backend_url = os.environ.get("FMC_CELERY_BACKEND", redis_url)

    if backend == "inprocess":
        logger.info("Using in-process task queue (explicit)")
        return InProcessTaskQueue()

    # Try Celery; fall back to in-process if Redis is unreachable
    try:
        import redis as redis_lib
        client = redis_lib.Redis.from_url(redis_url, socket_connect_timeout=2)
        client.ping()
        client.close()
        logger.info("Using Celery task queue with Redis at %s", redis_url)
        return CeleryTaskQueue(broker_url, backend_url)
    except Exception as e:
        logger.warning("Redis unavailable (%s), falling back to in-process task queue", e)
        return InProcessTaskQueue()


# Module-level singleton (lazy)
_queue: TaskQueueBackend | None = None


def get_queue() -> TaskQueueBackend:
    global _queue
    if _queue is None:
        _queue = get_task_queue()
    return _queue
