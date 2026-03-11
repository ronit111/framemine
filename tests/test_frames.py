"""Tests for framemine.frames module."""

import subprocess
from pathlib import Path
from unittest.mock import patch, call

import pytest

from framemine.frames import (
    FrameExtractionConfig,
    check_ffmpeg,
    extract_frames_interval,
    extract_keyframes,
    get_frames,
)


# ── check_ffmpeg ──────────────────────────────────────


class TestCheckFfmpeg:
    def test_check_ffmpeg_available(self):
        with patch("framemine.frames.shutil.which", return_value="/usr/bin/ffmpeg"):
            assert check_ffmpeg() is True

    def test_check_ffmpeg_missing(self):
        with patch("framemine.frames.shutil.which", return_value=None):
            assert check_ffmpeg() is False


# ── FrameExtractionConfig ────────────────────────────


class TestFrameExtractionConfig:
    def test_frame_extraction_config_defaults(self):
        config = FrameExtractionConfig()
        assert config.scene_threshold == 0.3
        assert config.lower_threshold == 0.15
        assert config.max_keyframes == 15
        assert config.fallback_interval == 3


# ── extract_keyframes ────────────────────────────────


class TestExtractKeyframes:
    def test_extract_keyframes_builds_correct_command(self, tmp_path):
        video = tmp_path / "clip.mp4"
        video.write_bytes(b"\x00")
        out = tmp_path / "out"

        with patch("framemine.frames.subprocess.run") as mock_run:
            extract_keyframes(video, out, threshold=0.3, max_keyframes=15)

        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]

        assert cmd[0] == "ffmpeg"
        assert cmd[cmd.index("-i") + 1] == str(video)
        assert cmd[cmd.index("-vf") + 1] == "select=gt(scene\\,0.3)"
        assert cmd[cmd.index("-fps_mode") + 1] == "vfr"
        assert cmd[cmd.index("-frames:v") + 1] == "15"
        assert "-pix_fmt" in cmd
        assert cmd[cmd.index("-pix_fmt") + 1] == "yuvj420p"
        assert "-strict" in cmd
        assert cmd[cmd.index("-strict") + 1] == "unofficial"
        assert "-y" in cmd

        # Output pattern uses stem
        pattern_arg = cmd[-2]  # pattern is second-to-last (before -y)
        assert "clip_%03d.jpg" in pattern_arg

        # Called with check=True and suppressed output
        assert mock_run.call_args[1]["check"] is True
        assert mock_run.call_args[1]["stdout"] == subprocess.DEVNULL
        assert mock_run.call_args[1]["stderr"] == subprocess.DEVNULL


# ── extract_frames_interval ──────────────────────────


class TestExtractFramesInterval:
    def test_extract_frames_interval_builds_correct_command(self, tmp_path):
        video = tmp_path / "clip.mp4"
        video.write_bytes(b"\x00")
        out = tmp_path / "out"

        with patch("framemine.frames.subprocess.run") as mock_run:
            extract_frames_interval(video, out, interval=5, max_keyframes=10)

        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]

        assert cmd[0] == "ffmpeg"
        assert cmd[cmd.index("-vf") + 1] == "fps=1/5"
        assert cmd[cmd.index("-frames:v") + 1] == "10"
        assert "-fps_mode" not in cmd  # interval mode doesn't use -fps_mode
        assert "-pix_fmt" in cmd
        assert cmd[cmd.index("-pix_fmt") + 1] == "yuvj420p"
        assert "-strict" in cmd
        assert cmd[cmd.index("-strict") + 1] == "unofficial"
        assert "-y" in cmd

        pattern_arg = cmd[-2]
        assert "clip_%03d.jpg" in pattern_arg

        assert mock_run.call_args[1]["check"] is True
        assert mock_run.call_args[1]["stdout"] == subprocess.DEVNULL
        assert mock_run.call_args[1]["stderr"] == subprocess.DEVNULL


# ── get_frames ────────────────────────────────────────


def _create_dummy_frames(directory: Path, stem: str, count: int) -> list[Path]:
    """Helper: create dummy jpg files simulating ffmpeg output."""
    directory.mkdir(parents=True, exist_ok=True)
    paths = []
    for i in range(1, count + 1):
        p = directory / f"{stem}_{i:03d}.jpg"
        p.write_bytes(b"\xff\xd8\xff")  # minimal JPEG header
        paths.append(p)
    return sorted(paths)


class TestGetFrames:
    def test_get_frames_raises_on_missing_video(self, tmp_path):
        fake_video = tmp_path / "nonexistent.mp4"
        with pytest.raises(FileNotFoundError, match="Video not found"):
            get_frames(fake_video, tmp_path / "out")

    def test_get_frames_raises_on_missing_ffmpeg(self, tmp_path):
        video = tmp_path / "clip.mp4"
        video.write_bytes(b"\x00")

        with patch("framemine.frames.check_ffmpeg", return_value=False):
            with pytest.raises(RuntimeError, match="ffmpeg is not installed"):
                get_frames(video, tmp_path / "out")

    def test_get_frames_scene_detection_success(self, tmp_path):
        """First scene-detection call succeeds and returns frames."""
        video = tmp_path / "clip.mp4"
        video.write_bytes(b"\x00")
        out = tmp_path / "out"
        frames_dir = out / "clip"

        dummy_frames = _create_dummy_frames(frames_dir, "clip", 3)

        with (
            patch("framemine.frames.check_ffmpeg", return_value=True),
            patch("framemine.frames.subprocess.run") as mock_run,
        ):
            result = get_frames(video, out)

        assert result == dummy_frames
        # Only the first extract_keyframes call was needed
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert "select=gt(scene\\,0.3)" in cmd[cmd.index("-vf") + 1]

    def test_get_frames_falls_back_to_lower_threshold(self, tmp_path):
        """First scene detection raises CalledProcessError, second succeeds."""
        video = tmp_path / "clip.mp4"
        video.write_bytes(b"\x00")
        out = tmp_path / "out"
        frames_dir = out / "clip"

        def side_effect(*args, **kwargs):
            cmd = args[0]
            vf_idx = cmd.index("-vf") + 1
            vf_arg = cmd[vf_idx]
            if "0.3" in vf_arg:
                raise subprocess.CalledProcessError(1, "ffmpeg")
            # Lower threshold call succeeds; create frames to simulate output
            _create_dummy_frames(frames_dir, "clip", 2)

        with (
            patch("framemine.frames.check_ffmpeg", return_value=True),
            patch("framemine.frames.subprocess.run", side_effect=side_effect),
        ):
            result = get_frames(video, out)

        assert len(result) == 2
        assert all(p.name.startswith("clip_") for p in result)

    def test_get_frames_falls_back_to_interval(self, tmp_path):
        """Both scene detections produce no frames, interval fallback works."""
        video = tmp_path / "clip.mp4"
        video.write_bytes(b"\x00")
        out = tmp_path / "out"
        frames_dir = out / "clip"

        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            cmd = args[0]
            vf_idx = cmd.index("-vf") + 1
            vf_arg = cmd[vf_idx]
            # Scene detection calls succeed but produce no files
            if "select=" in vf_arg:
                return  # no frames created
            # Interval call creates frames
            if "fps=" in vf_arg:
                _create_dummy_frames(frames_dir, "clip", 4)

        with (
            patch("framemine.frames.check_ffmpeg", return_value=True),
            patch("framemine.frames.subprocess.run", side_effect=side_effect),
        ):
            result = get_frames(video, out)

        assert len(result) == 4
        # Three calls total: two scene thresholds + one interval
        assert call_count == 3

    def test_get_frames_returns_empty_on_total_failure(self, tmp_path):
        """All three extraction methods produce nothing."""
        video = tmp_path / "clip.mp4"
        video.write_bytes(b"\x00")
        out = tmp_path / "out"

        with (
            patch("framemine.frames.check_ffmpeg", return_value=True),
            patch("framemine.frames.subprocess.run"),  # succeeds but no files created
        ):
            result = get_frames(video, out)

        assert result == []

    def test_get_frames_with_custom_config(self, tmp_path):
        """Custom config values are used in the ffmpeg commands."""
        video = tmp_path / "clip.mp4"
        video.write_bytes(b"\x00")
        out = tmp_path / "out"
        frames_dir = out / "clip"

        custom_config = FrameExtractionConfig(
            scene_threshold=0.5,
            lower_threshold=0.25,
            max_keyframes=8,
            fallback_interval=5,
        )

        # Make first call succeed with frames
        _create_dummy_frames(frames_dir, "clip", 2)

        with (
            patch("framemine.frames.check_ffmpeg", return_value=True),
            patch("framemine.frames.subprocess.run") as mock_run,
        ):
            result = get_frames(video, out, config=custom_config)

        assert len(result) == 2
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        # Verify custom threshold was used
        assert "select=gt(scene\\,0.5)" in cmd[cmd.index("-vf") + 1]
        # Verify custom max_keyframes
        assert cmd[cmd.index("-frames:v") + 1] == "8"
