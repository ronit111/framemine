"""Frame extraction from video files using ffmpeg."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from subprocess import DEVNULL


@dataclass
class FrameExtractionConfig:
    """Configuration for frame extraction behavior."""

    scene_threshold: float = 0.3
    lower_threshold: float = 0.15
    max_keyframes: int = 15
    fallback_interval: int = 3  # seconds


def check_ffmpeg() -> bool:
    """Return True if ffmpeg is available on PATH."""
    return shutil.which("ffmpeg") is not None


def extract_keyframes(
    video_path: Path,
    output_dir: Path,
    threshold: float,
    max_keyframes: int = 15,
) -> list[Path]:
    """Extract scene-change keyframes using ffmpeg select filter.

    Returns sorted list of frame paths.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(video_path).stem
    pattern = str(output_dir / f"{stem}_%03d.jpg")

    subprocess.run(
        [
            "ffmpeg",
            "-i",
            str(video_path),
            "-vf",
            f"select=gt(scene\\,{threshold})",
            "-fps_mode",
            "vfr",
            "-frames:v",
            str(max_keyframes),
            "-pix_fmt",
            "yuvj420p",
            "-q:v",
            "2",
            "-strict",
            "unofficial",
            pattern,
            "-y",
        ],
        check=True,
        stdout=DEVNULL,
        stderr=DEVNULL,
    )
    return sorted(output_dir.glob(f"{stem}_*.jpg"))


def extract_frames_interval(
    video_path: Path,
    output_dir: Path,
    interval: int = 3,
    max_keyframes: int = 15,
) -> list[Path]:
    """Fallback: extract one frame every N seconds."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(video_path).stem
    pattern = str(output_dir / f"{stem}_%03d.jpg")

    subprocess.run(
        [
            "ffmpeg",
            "-i",
            str(video_path),
            "-vf",
            f"fps=1/{interval}",
            "-frames:v",
            str(max_keyframes),
            "-pix_fmt",
            "yuvj420p",
            "-q:v",
            "2",
            "-strict",
            "unofficial",
            pattern,
            "-y",
        ],
        check=True,
        stdout=DEVNULL,
        stderr=DEVNULL,
    )
    return sorted(output_dir.glob(f"{stem}_*.jpg"))


def get_frames(
    video_path: Path,
    output_dir: Path,
    config: FrameExtractionConfig | None = None,
) -> list[Path]:
    """Main entry point for frame extraction.

    Tries scene detection at config.scene_threshold, then lower_threshold,
    then interval fallback. Returns list of extracted frame paths (JPEGs).

    Raises:
        FileNotFoundError: If video_path doesn't exist.
        RuntimeError: If ffmpeg is not available.
    """
    video_path = Path(video_path)
    output_dir = Path(output_dir)

    if not video_path.exists():
        raise FileNotFoundError(f"Video not found: {video_path}")

    if not check_ffmpeg():
        raise RuntimeError(
            "ffmpeg is not installed or not found on PATH. "
            "Install it from https://ffmpeg.org/"
        )

    if config is None:
        config = FrameExtractionConfig()

    frames_dir = output_dir / video_path.stem

    # Try scene detection at primary threshold, then lower threshold
    for threshold in [config.scene_threshold, config.lower_threshold]:
        try:
            frames = extract_keyframes(
                video_path, frames_dir, threshold, config.max_keyframes
            )
            if frames:
                return frames
        except subprocess.CalledProcessError:
            pass

    # Fall back to fixed-interval extraction
    try:
        return extract_frames_interval(
            video_path, frames_dir, config.fallback_interval, config.max_keyframes
        )
    except subprocess.CalledProcessError:
        return []
