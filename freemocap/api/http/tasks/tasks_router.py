"""HTTP router for async task queue operations."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from freemocap.services.task_queue import (
    TaskState,
    get_queue,
    get_registered_task_types,
)

logger = logging.getLogger(__name__)

tasks_router = APIRouter(prefix="/tasks", tags=["Tasks"])


class SubmitTaskRequest(BaseModel):
    task_type: str = Field(..., description="Registered task type, e.g. 'demo.long_task'")
    payload: dict = Field(default_factory=dict, description="Task-specific input payload")


class SubmitTaskResponse(BaseModel):
    task_id: str
    state: str
    message: str


class TaskStatusResponse(BaseModel):
    task_id: str
    state: str
    progress: float
    message: str
    result: Any | None = None
    error: str | None = None


@tasks_router.post("/submit", response_model=SubmitTaskResponse, summary="Submit an async task")
async def submit_task(req: SubmitTaskRequest):
    """Submit a task to the queue. Returns immediately with a task_id."""
    if req.task_type not in get_registered_task_types():
        raise HTTPException(
            status_code=400,
            detail=f"Unknown task_type '{req.task_type}'. Available: {get_registered_task_types()}",
        )
    task_id = get_queue().submit_task(req.task_type, req.payload)
    return SubmitTaskResponse(task_id=task_id, state=TaskState.PENDING, message="submitted")


@tasks_router.get("/types", summary="List registered task types")
async def list_task_types():
    return {"task_types": get_registered_task_types()}


@tasks_router.get("/{task_id}", response_model=TaskStatusResponse, summary="Get task status/progress")
async def get_task_status(task_id: str):
    status = get_queue().get_status(task_id)
    if status is None:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    return status.to_dict()


@tasks_router.get("/{task_id}/result", summary="Get task result")
async def get_task_result(task_id: str):
    result = get_queue().get_result(task_id)
    if result is None:
        status = get_queue().get_status(task_id)
        if status is None:
            raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
        return {"task_id": task_id, "state": status.state, "result": None, "message": "task not completed"}
    return {"task_id": task_id, "result": result}


@tasks_router.delete("/{task_id}", summary="Cancel a task")
async def cancel_task(task_id: str):
    ok = get_queue().cancel_task(task_id)
    if not ok:
        status = get_queue().get_status(task_id)
        if status is None:
            raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
        return {"task_id": task_id, "cancelled": False, "state": status.state, "message": "task already in terminal state"}
    return {"task_id": task_id, "cancelled": True, "message": "cancellation requested"}
