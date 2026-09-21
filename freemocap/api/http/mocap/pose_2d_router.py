"""2D pose estimation endpoints.

Minimal 2D pipeline: upload an image, receive either:
  * ``POST /pose-2d/image`` — an OpenPose-style skeleton overlay image
    (black background, colored bone connections, joint circles)
  * ``POST /pose-2d/json``  — the 33 MediaPipe body landmarks as JSON

This is the P3 "2D pipeline minimal implementation" from the project plan. It
runs MediaPipe Pose directly on a single still image, independent of the
full multi-stage FreeMoCap recording pipeline.
"""

import io
import logging
from typing import Any

import numpy as np
from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import Response

logger = logging.getLogger(__name__)

pose_2d_router = APIRouter(prefix="/pose-2d", tags=["Pose2D"])

# ---------------------------------------------------------------------------
# MediaPipe lazy import — keeps the module importable even when the heavy
# FreeMoCap dependency stack is not installed (e.g. during lightweight tests).
# ---------------------------------------------------------------------------
try:
    import cv2
    import mediapipe as mp

    _POSE = mp.solutions.pose.Pose(
        static_image_mode=True,
        model_complexity=1,
        enable_segmentation=False,
        min_detection_confidence=0.5,
    )
    _POSE_CONNECTIONS = mp.solutions.pose.POSE_CONNECTIONS
    _MEDIAPIPE_AVAILABLE = True
except Exception:  # pragma: no cover - import guard
    cv2 = None  # type: ignore[assignment]
    mp = None  # type: ignore[assignment]
    _POSE = None
    _POSE_CONNECTIONS = set()
    _MEDIAPIPE_AVAILABLE = False


# OpenPose-style color palette (BGR, since OpenCV uses BGR).
# Group connections by body region so left/right sides are distinguishable.
_COLORS = {
    "torso": (255, 0, 0),       # blue
    "right_arm": (0, 0, 255),   # red
    "left_arm": (0, 255, 0),    # green
    "right_leg": (0, 165, 255), # orange
    "left_leg": (255, 255, 0),  # cyan
}


def _connection_color(a: int, b: int) -> tuple[int, int, int]:
    """Return a region-based color for a MediaPipe pose connection.

    MediaPipe Pose landmark indices (0..32):
      0       nose
      1..10   face / upper-head
      11..14  shoulders + elbows (11/12 shoulders, 13/14 elbows)
      15..16  wrists
      17..22  hands (thumb/index/pinky)
      23..24  hips
      25..26  knees
      27..28  ankles
      29..32  feet
    """
    upper = {0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 23, 24}
    right = {12, 14, 16, 18, 20, 22, 24, 26, 28, 30, 32}
    left = {11, 13, 15, 17, 19, 21, 23, 25, 27, 29, 31}
    arm = {11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22}
    leg = {23, 24, 25, 26, 27, 28, 29, 30, 31, 32}

    if a in arm and b in arm:
        if a in right or b in right:
            return _COLORS["right_arm"]
        return _COLORS["left_arm"]
    if a in leg and b in leg:
        if a in right or b in right:
            return _COLORS["right_leg"]
        return _COLORS["left_leg"]
    return _COLORS["torso"]


def _draw_openpose_skeleton(
    image: np.ndarray,
    landmarks: list[Any],
) -> np.ndarray:
    """Render an OpenPose-style skeleton on a pure-black canvas.

    Args:
        image: original BGR image (only its dimensions are used).
        landmarks: MediaPipe Pose landmark list (33 normalized landmarks).

    Returns:
        uint8 BGR image of the same size as ``image`` with a black background.
    """
    h, w = image.shape[:2]
    canvas = np.zeros((h, w, 3), dtype=np.uint8)

    points: list[tuple[int, int] | None] = []
    for lm in landmarks:
        x, y = int(lm.x * w), int(lm.y * h)
        # MediaPipe may return landmarks outside the image; clip them.
        if 0 <= x < w and 0 <= y < h:
            points.append((x, y))
        else:
            points.append(None)

    # Bone connections
    for a, b in _POSE_CONNECTIONS:
        pa, pb = points[a], points[b]
        if pa is None or pb is None:
            continue
        color = _connection_color(a, b)
        cv2.line(canvas, pa, pb, color, thickness=3, lineType=cv2.LINE_AA)

    # Joint circles
    for pt in points:
        if pt is None:
            continue
        cv2.circle(canvas, pt, radius=4, color=(255, 255, 255), thickness=-1, lineType=cv2.LINE_AA)

    return canvas


def _detect_pose(image_bgr: np.ndarray) -> list[Any] | None:
    """Run MediaPipe Pose on a BGR image and return the landmark list."""
    if not _MEDIAPIPE_AVAILABLE:
        raise HTTPException(
            status_code=503,
            detail="MediaPipe is not available in this environment.",
        )
    rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
    result = _POSE.process(rgb)
    if result.pose_landmarks is None:
        return None
    return result.pose_landmarks.landmark


@pose_2d_router.post("/image", summary="Upload an image, get an OpenPose-style skeleton image")
async def pose_2d_image(file: UploadFile = File(...)) -> Response:
    """Detect a single person's pose and return the skeleton as a PNG image.

    The output is rendered in OpenPose style: a black background with colored
    bone connections and white joint circles — suitable for ControlNet input.
    """
    if not _MEDIAPIPE_AVAILABLE:
        raise HTTPException(status_code=503, detail="MediaPipe is not available.")

    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty file uploaded.")

    arr = np.frombuffer(raw, dtype=np.uint8)
    image = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if image is None:
        raise HTTPException(status_code=400, detail="Could not decode the uploaded image.")

    landmarks = _detect_pose(image)
    if landmarks is None:
        raise HTTPException(status_code=422, detail="No human pose detected in the image.")

    skeleton = _draw_openpose_skeleton(image, landmarks)
    ok, buf = cv2.imencode(".png", skeleton)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to encode skeleton image.")

    return Response(content=buf.tobytes(), media_type="image/png")


@pose_2d_router.post("/json", summary="Upload an image, get MediaPipe landmarks as JSON")
async def pose_2d_json(file: UploadFile = File(...)) -> dict:
    """Detect a single person's pose and return the 33 landmarks as JSON.

    Each landmark has ``x`` and ``y`` (normalized 0..1) plus ``visibility``.
    """
    if not _MEDIAPIPE_AVAILABLE:
        raise HTTPException(status_code=503, detail="MediaPipe is not available.")

    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty file uploaded.")

    arr = np.frombuffer(raw, dtype=np.uint8)
    image = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if image is None:
        raise HTTPException(status_code=400, detail="Could not decode the uploaded image.")

    landmarks = _detect_pose(image)
    if landmarks is None:
        raise HTTPException(status_code=422, detail="No human pose detected in the image.")

    points = [
        {"index": i, "x": lm.x, "y": lm.y, "visibility": getattr(lm, "visibility", 0.0)}
        for i, lm in enumerate(landmarks)
    ]
    return {
        "success": True,
        "detector": "mediapipe_pose",
        "landmark_count": len(points),
        "landmarks": points,
    }
