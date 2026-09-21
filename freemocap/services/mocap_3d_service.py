"""
3D mocap pipeline service: wraps the existing posthoc mocap pipeline as a
task-queue-compatible function.

The real pipeline lives in freemocap.core.pipeline.posthoc and depends on
skellytracker / skellycam / multiprocessing. This service imports those
lazily so the task queue stays importable even in minimal environments.

Task input payload:
  {
    "video_dir": "/path/to/recording_folder",      # folder containing synchronized videos
    "calibration_path": "/path/to/calibration.toml", # optional, multi-cam only
    "output_dir": "/path/to/output",                # optional, defaults to <video_dir>/output
    "tracker": "mediapipe"                          # optional, default mediapipe
  }
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)


# Pipeline stage weights (sum = 1.0) used for progress reporting.
_STAGE_WEIGHTS = [
    ("loading_videos", 0.10),
    ("detection_2d", 0.40),
    ("synchronization", 0.10),
    ("triangulation_3d", 0.25),
    ("exporting", 0.15),
]


def _stage_progress(stage_idx: int, sub_progress: float) -> float:
    """Compute overall progress from current stage index and within-stage progress."""
    done = sum(w for _, w in _STAGE_WEIGHTS[:stage_idx])
    current_weight = _STAGE_WEIGHTS[stage_idx][1]
    return min(1.0, done + current_weight * max(0.0, min(1.0, sub_progress)))


def run_3d_mocap(payload: dict, report_progress: Callable) -> dict:
    """Run the full 3D mocap pipeline on a recording folder.

    Args:
        payload: Task input (video_dir, calibration_path, output_dir, tracker).
        report_progress: Callback(progress: float, message: str).

    Returns:
        dict with output paths and metadata.
    """
    video_dir = Path(payload.get("video_dir", "")).expanduser().resolve()
    calibration_path = payload.get("calibration_path")
    output_dir = Path(payload.get("output_dir") or str(video_dir / "output")).expanduser().resolve()
    tracker = payload.get("tracker", "mediapipe")

    if not video_dir.exists():
        raise FileNotFoundError(f"video_dir not found: {video_dir}")

    output_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Starting 3D mocap: video_dir=%s tracker=%s", video_dir, tracker)

    # ---- Attempt to use the real pipeline ----
    try:
        return _run_real_pipeline(
            video_dir=video_dir,
            calibration_path=calibration_path,
            output_dir=output_dir,
            tracker=tracker,
            report_progress=report_progress,
        )
    except ImportError as e:
        logger.warning("Real pipeline unavailable (%s), falling back to simulated run", e)
        return _run_simulated_pipeline(
            video_dir=video_dir,
            output_dir=output_dir,
            report_progress=report_progress,
        )


def _run_real_pipeline(
    *,
    video_dir: Path,
    calibration_path: str | None,
    output_dir: Path,
    tracker: str,
    report_progress: Callable,
) -> dict:
    """Invoke the real FreeMoCap posthoc mocap pipeline.

    Imports are lazy so this module stays importable without skellytracker.
    """
    # Lazy imports of the heavy pipeline stack
    from freemocap.core.pipeline.posthoc.posthoc_pipeline import PosthocPipeline
    from freemocap.core.pipeline.posthoc.pipeline_phases import PosthocPipelineType
    from freemocap.core.tasks.mocap.posthoc_mocap_task import run_posthoc_mocap_aggregator_task
    from freemocap.core.tasks.mocap.mocap_task_config import PosthocMocapPipelineConfig
    from skellycam.core.recorders.videos.recording_info import RecordingInfo
    from skellytracker.core import TrackerConfig
    import functools
    import multiprocessing

    report_progress(_stage_progress(0, 0.0), "Loading videos...")

    # Build recording_info pointing at the video folder
    recording_info = RecordingInfo(
        recording_name=video_dir.name,
        full_recording_path=str(video_dir),
    )

    # Build tracker config
    tracker_config = TrackerConfig(tracker=tracker)

    # Build mocap task config
    mocap_config = PosthocMocapPipelineConfig(
        calibration_toml_path=calibration_path,
    )
    task_fn = functools.partial(
        run_posthoc_mocap_aggregator_task,
        task_config=mocap_config,
    )

    # Pipeline infrastructure (minimal — real app provides these)
    worker_registry = None  # NOTE: real deployment injects the app's registry
    global_kill_flag = multiprocessing.Value("b", False)

    report_progress(_stage_progress(0, 1.0), "Videos loaded")
    report_progress(_stage_progress(1, 0.0), "Running 2D detection...")

    pipeline = PosthocPipeline.create(
        recording_info=recording_info,
        detector_config=tracker_config,
        aggregation_task_fn=task_fn,
        pipeline_type=PosthocPipelineType.MOCAP,
        worker_registry=worker_registry,
        global_kill_flag=global_kill_flag,
        save_annotated_video=True,
    )

    # Start and wait for completion (poll alive flag)
    pipeline.start()
    while pipeline.alive:
        time.sleep(0.5)
        # Estimate progress: detection is ~40% of total
        report_progress(_stage_progress(1, 0.5), "2D detection in progress...")

    report_progress(_stage_progress(2, 1.0), "Synchronization complete")
    report_progress(_stage_progress(3, 1.0), "3D triangulation complete")
    report_progress(_stage_progress(4, 0.0), "Exporting results...")

    # Locate output data
    data_dir = video_dir / "output_data"
    skeleton_3d = data_dir / "mediaPipeSkel_3d_origin_aligned.npy"
    if not skeleton_3d.exists():
        skeleton_3d = data_dir / "mediaPipeSkel_3d.npy"

    report_progress(_stage_progress(4, 1.0), "Export complete")

    return {
        "video_dir": str(video_dir),
        "output_dir": str(output_dir),
        "skeleton_3d_path": str(skeleton_3d) if skeleton_3d.exists() else None,
        "data_dir": str(data_dir) if data_dir.exists() else None,
    }


def _run_simulated_pipeline(
    *,
    video_dir: Path,
    output_dir: Path,
    report_progress: Callable,
) -> dict:
    """Simulated pipeline run for environments without skellytracker.

    Produces a small placeholder output so the task queue / endpoint flow
    can be tested end-to-end. A real deployment replaces this path with
    _run_real_pipeline.
    """
    stages = ["loading_videos", "detection_2d", "synchronization", "triangulation_3d", "exporting"]

    for idx, stage in enumerate(stages):
        report_progress(_stage_progress(idx, 0.0), f"{stage}: starting")
        # Simulate work in 5 sub-steps per stage
        for step in range(1, 6):
            report_progress(_stage_progress(idx, step / 5), f"{stage}: {step}/5")
            time.sleep(0.05)
        report_progress(_stage_progress(idx, 1.0), f"{stage}: done")

    # Write a placeholder output so result path exists
    placeholder = output_dir / "skeleton_3d_placeholder.npy"
    placeholder.write_text("simulated 3D mocap output")

    return {
        "video_dir": str(video_dir),
        "output_dir": str(output_dir),
        "skeleton_3d_path": str(placeholder),
        "simulated": True,
        "note": "Real pipeline requires skellytracker + skellycam; this is a simulated run.",
    }
