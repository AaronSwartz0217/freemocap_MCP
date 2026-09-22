"""HTTP router for 3D mocap pipeline submission.

Convenience layer on top of the generic task queue: accepts a recording
folder path and submits a `mocap.run_3d` task. Status/result polling
reuses the generic /tasks/{task_id} endpoints.
"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from freemocap.services.task_queue import get_queue

logger = logging.getLogger(__name__)

mocap_3d_router = APIRouter(prefix="/mocap-3d", tags=["Mocap3D"])

# Trackers supported by the 3D pipeline.
# NOTE: Only `mediapipe` produces real 3D data (has depth). `rtmpose` outputs
# 2D-only keypoints with zero Z-axis, so the resulting skeleton is flat.
# We still allow rtmpose for users who want 2D tracking through this endpoint,
# but we warn them clearly.
_VALID_TRACKERS = {"mediapipe", "rtmpose"}

_RTMPOSE_WARNING = (
    "WARNING: tracker='rtmpose' produces 2D-only keypoints (Z-axis = 0). "
    "The output skeleton will be flat with no depth. "
    "Use tracker='mediapipe' for true 3D reconstruction."
)


class Run3DMocapRequest(BaseModel):
    video_dir: str = Field(..., description="Path to the recording folder containing synchronized videos")
    calibration_path: str | None = Field(default=None, description="Path to calibration TOML (required for multi-camera)")
    output_dir: str | None = Field(default=None, description="Output directory (defaults to <video_dir>/output)")
    tracker: str = Field(
        default="mediapipe",
        description="Tracker to use. 'mediapipe' (recommended, true 3D with depth) or 'rtmpose' (2D-only, flat skeleton).",
    )


class Run3DMocapResponse(BaseModel):
    task_id: str
    task_type: str
    state: str
    message: str


@mocap_3d_router.post("/run", response_model=Run3DMocapResponse, summary="Submit a 3D mocap pipeline task")
async def run_3d_mocap(req: Run3DMocapRequest):
    """Submit a 3D motion capture pipeline task.

    The task runs asynchronously. Poll GET /tasks/{task_id} for progress
    and GET /tasks/{task_id}/result for the output paths.
    """
    # Validate tracker choice
    if req.tracker not in _VALID_TRACKERS:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid tracker '{req.tracker}'. Must be one of: {sorted(_VALID_TRACKERS)}",
        )

    video_dir = Path(req.video_dir).expanduser()
    if not video_dir.exists():
        raise HTTPException(status_code=400, detail=f"video_dir not found: {video_dir}")

    # Warn loudly if user chose rtmpose for a 3D pipeline
    message = "3D mocap task submitted"
    if req.tracker == "rtmpose":
        logger.warning("3D mocap task submitted with tracker='rtmpose' — output will be flat (no Z-axis depth)")
        message = f"{message}. {_RTMPOSE_WARNING}"

    payload = {
        "video_dir": str(video_dir),
        "tracker": req.tracker,
    }
    if req.calibration_path:
        payload["calibration_path"] = req.calibration_path
    if req.output_dir:
        payload["output_dir"] = req.output_dir

    task_id = get_queue().submit_task("mocap.run_3d", payload)
    logger.info("Submitted 3D mocap task %s for video_dir=%s tracker=%s", task_id, video_dir, req.tracker)
    return Run3DMocapResponse(
        task_id=task_id,
        task_type="mocap.run_3d",
        state="PENDING",
        message=message,
    )
