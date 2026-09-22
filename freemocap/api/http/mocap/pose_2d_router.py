"""2D pose estimation endpoints.

Minimal 2D pipeline: upload an image, receive either:
  * ``POST /pose-2d/image`` — an OpenPose-style skeleton overlay image
    (black background, colored bone connections, joint circles)
  * ``POST /pose-2d/json``  — the 33 MediaPipe body landmarks as JSON
  * ``POST /pose-2d/coco``  — COCO-format (17 keypoints) skeleton image +
    keypoints, accepts base64 image (MCP-friendly)

This is the P3 "2D pipeline minimal implementation" from the project plan. It
runs MediaPipe Pose directly on a single still image, independent of the
full multi-stage FreeMoCap recording pipeline.
"""

import base64
import io
import logging
from typing import Any

import numpy as np
from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

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
    # Convert MediaPipe's RepeatedCompositeContainer to a plain Python list
    # so beartype's type-checking (list[Any] | None) is satisfied.
    return list(result.pose_landmarks.landmark)


# ---------------------------------------------------------------------------
# COCO 17-keypoint format support
# ---------------------------------------------------------------------------

# COCO keypoint names (17 keypoints, standard COCO dataset format)
COCO_KEYPOINT_NAMES = [
    "nose", "left_eye", "right_eye", "left_ear", "right_ear",
    "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
    "left_wrist", "right_wrist", "left_hip", "right_hip",
    "left_knee", "right_knee", "left_ankle", "right_ankle",
]

# MediaPipe (33) -> COCO (17) index mapping
# MediaPipe indices: 0=nose, 2=left_eye, 5=right_eye, 7=left_ear, 8=right_ear,
# 11=left_shoulder, 12=right_shoulder, 13=left_elbow, 14=right_elbow,
# 15=left_wrist, 16=right_wrist, 23=left_hip, 24=right_hip,
# 25=left_knee, 26=right_knee, 27=left_ankle, 28=right_ankle
MEDIAPIPE_TO_COCO = {
    0: 0,   # nose
    2: 1,   # left_eye
    5: 2,   # right_eye
    7: 3,   # left_ear
    8: 4,   # right_ear
    11: 5,  # left_shoulder
    12: 6,  # right_shoulder
    13: 7,  # left_elbow
    14: 8,  # right_elbow
    15: 9,  # left_wrist
    16: 10, # right_wrist
    23: 11, # left_hip
    24: 12, # right_hip
    25: 13, # left_knee
    26: 14, # right_knee
    27: 15, # left_ankle
    28: 16, # right_ankle
}

# Pre-built reverse mapping: COCO index -> MediaPipe index (avoids O(n^2) lookup
# inside the per-frame conversion loop).
_COCO_TO_MEDIAPIPE = [
    next(mp_i for mp_i, coco_i in MEDIAPIPE_TO_COCO.items() if coco_i == coco_idx)
    for coco_idx in range(len(COCO_KEYPOINT_NAMES))
]

# COCO skeleton connections (1-indexed in COCO spec, converted to 0-indexed here)
COCO_SKELETON = [
    (15, 13), (13, 11), (16, 14), (14, 12), (11, 12),
    (5, 11), (6, 12), (5, 6), (5, 7), (6, 8),
    (7, 9), (8, 10), (1, 2), (0, 1), (0, 2),
    (1, 3), (2, 4), (3, 5), (4, 6),
]

# COCO-style colors (BGR) — matches the standard COCO visualization palette
COCO_COLORS = [
    (255, 0, 0), (255, 85, 0), (255, 170, 0), (255, 255, 0),
    (170, 255, 0), (85, 255, 0), (0, 255, 0), (0, 255, 85),
    (0, 255, 170), (0, 255, 255), (0, 170, 255), (0, 85, 255),
    (0, 0, 255), (85, 0, 255), (170, 0, 255), (255, 0, 255),
    (255, 0, 170), (255, 0, 85),
]


def _mediapipe_to_coco_keypoints(landmarks: list[Any], width: int, height: int) -> list[dict]:
    """Convert MediaPipe 33 landmarks to COCO 17 keypoint format.

    Returns a list of 17 dicts, each with 'x', 'y' (pixel coords),
    'visibility', and 'name'. Keypoints not detected get visibility=0.
    """
    coco_keypoints = []
    for coco_idx, mp_idx in enumerate(_COCO_TO_MEDIAPIPE):
        name = COCO_KEYPOINT_NAMES[coco_idx]
        if mp_idx >= len(landmarks):
            coco_keypoints.append({"name": name, "x": 0, "y": 0, "visibility": 0.0})
            continue

        lm = landmarks[mp_idx]
        x = int(lm.x * width)
        y = int(lm.y * height)
        visibility = float(getattr(lm, "visibility", 0.0))
        in_bounds = 0 <= x < width and 0 <= y < height
        coco_keypoints.append({
            "name": name,
            "x": x if in_bounds else 0,
            "y": y if in_bounds else 0,
            "visibility": visibility if in_bounds else 0.0,
        })
    return coco_keypoints


def _draw_coco_skeleton(
    image: np.ndarray,
    coco_keypoints: list[dict],
) -> np.ndarray:
    """Render a COCO-style skeleton on a pure-black canvas.

    Args:
        image: original BGR image (only its dimensions are used).
        coco_keypoints: list of 17 COCO keypoint dicts with pixel x/y.

    Returns:
        uint8 BGR image of the same size as ``image`` with a black background.
    """
    h, w = image.shape[:2]
    canvas = np.zeros((h, w, 3), dtype=np.uint8)

    points = []
    for kp in coco_keypoints:
        if kp["visibility"] > 0 and (kp["x"] > 0 or kp["y"] > 0):
            points.append((kp["x"], kp["y"]))
        else:
            points.append(None)

    # Draw skeleton connections
    for i, (a, b) in enumerate(COCO_SKELETON):
        pa, pb = points[a], points[b]
        if pa is None or pb is None:
            continue
        color = COCO_COLORS[i % len(COCO_COLORS)]
        cv2.line(canvas, pa, pb, color, thickness=3, lineType=cv2.LINE_AA)

    # Draw keypoint circles
    for i, pt in enumerate(points):
        if pt is None:
            continue
        color = COCO_COLORS[i % len(COCO_COLORS)]
        cv2.circle(canvas, pt, radius=4, color=color, thickness=-1, lineType=cv2.LINE_AA)

    return canvas


class CocoPoseRequest(BaseModel):
    """Request body for the COCO pose endpoint (MCP-friendly).

    Accepts a base64-encoded image so the endpoint can be called as an MCP
    tool with a plain JSON argument (no multipart file upload required).
    """
    image_base64: str


@pose_2d_router.post("/coco", summary="Generate COCO-format skeleton from base64 image (MCP-friendly)")
async def pose_2d_coco(request: CocoPoseRequest) -> dict:
    """Detect pose and return a COCO-format (17 keypoints) skeleton.

    Accepts a base64-encoded image and returns:
      * ``skeleton_image_base64`` — COCO-style skeleton PNG (black background)
      * ``keypoints`` — 17 COCO keypoints with pixel coordinates and visibility
      * ``coco_annotations`` — COCO-compatible annotation dict

    This endpoint is designed for MCP tool invocation (JSON in / JSON out).
    """
    if not _MEDIAPIPE_AVAILABLE:
        raise HTTPException(status_code=503, detail="MediaPipe is not available.")

    # Decode base64 image
    try:
        # Strip data URL prefix if present (e.g. "data:image/png;base64,...")
        img_str = request.image_base64
        if "," in img_str and img_str.startswith("data:"):
            img_str = img_str.split(",", 1)[1]
        img_bytes = base64.b64decode(img_str)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid base64 image data.")

    arr = np.frombuffer(img_bytes, dtype=np.uint8)
    image = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if image is None:
        raise HTTPException(status_code=400, detail="Could not decode the image.")

    h, w = image.shape[:2]
    landmarks = _detect_pose(image)
    if landmarks is None:
        raise HTTPException(status_code=422, detail="No human pose detected in the image.")

    # Convert to COCO format
    coco_keypoints = _mediapipe_to_coco_keypoints(landmarks, w, h)

    # Draw COCO skeleton
    skeleton = _draw_coco_skeleton(image, coco_keypoints)
    ok, buf = cv2.imencode(".png", skeleton)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to encode skeleton image.")

    skeleton_b64 = base64.b64encode(buf.tobytes()).decode("utf-8")

    # COCO-compatible flat keypoint array: [x, y, visibility, x, y, visibility, ...]
    coco_kp_flat = []
    num_keypoints = 0
    for kp in coco_keypoints:
        v = 2 if kp["visibility"] > 0.5 else (1 if kp["visibility"] > 0 else 0)
        coco_kp_flat.extend([kp["x"], kp["y"], v])
        if v > 0:
            num_keypoints += 1

    return {
        "success": True,
        "detector": "mediapipe_pose",
        "format": "coco_17_keypoints",
        "image_size": {"width": w, "height": h},
        "skeleton_image_base64": skeleton_b64,
        "keypoints": coco_keypoints,
        "coco_annotations": {
            "keypoints": coco_kp_flat,
            "num_keypoints": num_keypoints,
            "category_id": 1,
        },
    }


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
