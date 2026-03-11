"""Tests for framemine.download module."""

from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from framemine.download import (
    MediaFile,
    check_ytdlp,
    discover_local_media,
    download_url,
    download_url_list,
    resolve_input,
)


# ---------------------------------------------------------------------------
# check_ytdlp
# ---------------------------------------------------------------------------


def test_check_ytdlp_available():
    with patch("framemine.download.shutil.which", return_value="/usr/local/bin/yt-dlp"):
        assert check_ytdlp() is True


def test_check_ytdlp_missing():
    with patch("framemine.download.shutil.which", return_value=None):
        assert check_ytdlp() is False


# ---------------------------------------------------------------------------
# discover_local_media
# ---------------------------------------------------------------------------


def test_discover_local_media_finds_videos_and_images(sample_media_dir):
    results = discover_local_media(sample_media_dir)
    names = [m.path.name for m in results]
    assert "video1.mp4" in names
    assert "video2.mkv" in names
    assert "img1.jpg" in names
    assert "img2.png" in names
    assert len(results) == 4


def test_discover_local_media_ignores_non_media(sample_media_dir):
    results = discover_local_media(sample_media_dir)
    names = [m.path.name for m in results]
    assert "notes.txt" not in names
    assert "data.json" not in names


def test_discover_local_media_empty_dir(tmp_path):
    results = discover_local_media(tmp_path)
    assert results == []


def test_discover_local_media_classifies_correctly(sample_media_dir):
    results = discover_local_media(sample_media_dir)
    by_name = {m.path.name: m for m in results}
    assert by_name["video1.mp4"].media_type == "video"
    assert by_name["video2.mkv"].media_type == "video"
    assert by_name["img1.jpg"].media_type == "image"
    assert by_name["img2.png"].media_type == "image"


def test_discover_local_media_sorted_by_filename(sample_media_dir):
    results = discover_local_media(sample_media_dir)
    names = [m.path.name for m in results]
    assert names == sorted(names)


# ---------------------------------------------------------------------------
# download_url
# ---------------------------------------------------------------------------


def test_download_url_builds_correct_command(tmp_path):
    """Verify the yt-dlp command is assembled with the right arguments."""
    # Create a fake downloaded file so post-download scan finds something.
    fake_file = tmp_path / "abc123.mp4"

    def fake_run(cmd, **kwargs):
        fake_file.write_bytes(b"\x00" * 10)
        return MagicMock(returncode=0)

    with patch("framemine.download.subprocess.run", side_effect=fake_run) as mock_run:
        result = download_url("https://example.com/video", tmp_path)

    assert result is not None
    assert result.source_url == "https://example.com/video"

    cmd = mock_run.call_args[0][0]
    assert cmd[0] == "yt-dlp"
    assert "-o" in cmd
    assert "--format" in cmd
    fmt_idx = cmd.index("--format") + 1
    assert "720" in cmd[fmt_idx]
    assert "--retries" in cmd
    assert "3" in cmd
    assert cmd[-1] == "https://example.com/video"
    # --cookies-from-browser should NOT be present.
    assert "--cookies-from-browser" not in cmd


def test_download_url_with_cookies(tmp_path):
    fake_file = tmp_path / "abc123.mp4"

    def fake_run(cmd, **kwargs):
        fake_file.write_bytes(b"\x00" * 10)
        return MagicMock(returncode=0)

    with patch("framemine.download.subprocess.run", side_effect=fake_run) as mock_run:
        download_url(
            "https://example.com/video",
            tmp_path,
            cookies_from_browser="chrome",
        )

    cmd = mock_run.call_args[0][0]
    assert "--cookies-from-browser" in cmd
    cb_idx = cmd.index("--cookies-from-browser") + 1
    assert cmd[cb_idx] == "chrome"


def test_download_url_returns_none_on_failure(tmp_path):
    with patch(
        "framemine.download.subprocess.run",
        return_value=MagicMock(returncode=1, stderr="error"),
    ):
        result = download_url("https://example.com/fail", tmp_path)

    assert result is None


def test_download_url_returns_none_on_exception(tmp_path):
    with patch(
        "framemine.download.subprocess.run",
        side_effect=OSError("not found"),
    ):
        result = download_url("https://example.com/fail", tmp_path)

    assert result is None


def test_download_url_custom_resolution(tmp_path):
    fake_file = tmp_path / "abc123.mp4"

    def fake_run(cmd, **kwargs):
        fake_file.write_bytes(b"\x00" * 10)
        return MagicMock(returncode=0)

    with patch("framemine.download.subprocess.run", side_effect=fake_run) as mock_run:
        download_url("https://example.com/video", tmp_path, max_resolution=1080)

    cmd = mock_run.call_args[0][0]
    fmt_idx = cmd.index("--format") + 1
    assert "1080" in cmd[fmt_idx]


# ---------------------------------------------------------------------------
# download_url_list
# ---------------------------------------------------------------------------


def test_download_url_list_skips_comments_and_blanks(tmp_path):
    url_file = tmp_path / "urls.txt"
    url_file.write_text(
        "# This is a comment\n"
        "\n"
        "https://example.com/vid1\n"
        "  # Another comment\n"
        "https://example.com/vid2\n"
        "\n"
    )

    call_count = 0

    def fake_download(url, output_dir, **kwargs):
        nonlocal call_count
        call_count += 1
        fake = tmp_path / f"dl_{call_count}.mp4"
        fake.write_bytes(b"\x00")
        return MediaFile(path=fake, source_url=url, media_type="video")

    with patch("framemine.download.download_url", side_effect=fake_download):
        results = download_url_list(url_file, tmp_path)

    assert len(results) == 2
    assert call_count == 2


def test_download_url_list_calls_progress_callback(tmp_path):
    url_file = tmp_path / "urls.txt"
    url_file.write_text("https://example.com/a\nhttps://example.com/b\n")

    callback = MagicMock()

    call_count = 0

    def fake_download(url, output_dir, **kwargs):
        nonlocal call_count
        call_count += 1
        fake = tmp_path / f"dl_{call_count}.mp4"
        fake.write_bytes(b"\x00")
        return MediaFile(path=fake, source_url=url, media_type="video")

    with patch("framemine.download.download_url", side_effect=fake_download):
        download_url_list(url_file, tmp_path, progress_callback=callback)

    assert callback.call_count == 2
    # First call: current=1, total=2, url, success=True
    callback.assert_any_call(1, 2, "https://example.com/a", True)
    callback.assert_any_call(2, 2, "https://example.com/b", True)


def test_download_url_list_reports_failures_in_callback(tmp_path):
    url_file = tmp_path / "urls.txt"
    url_file.write_text("https://example.com/good\nhttps://example.com/bad\n")

    callback = MagicMock()

    def fake_download(url, output_dir, **kwargs):
        if "bad" in url:
            return None
        fake = tmp_path / "good.mp4"
        fake.write_bytes(b"\x00")
        return MediaFile(path=fake, source_url=url, media_type="video")

    with patch("framemine.download.download_url", side_effect=fake_download):
        results = download_url_list(url_file, tmp_path, progress_callback=callback)

    assert len(results) == 1
    callback.assert_any_call(1, 2, "https://example.com/good", True)
    callback.assert_any_call(2, 2, "https://example.com/bad", False)


# ---------------------------------------------------------------------------
# resolve_input
# ---------------------------------------------------------------------------


def test_resolve_input_routes_to_local_dir(sample_media_dir, tmp_path):
    results = resolve_input(str(sample_media_dir), tmp_path)
    assert len(results) == 4
    names = {m.path.name for m in results}
    assert "video1.mp4" in names
    assert "img1.jpg" in names


def test_resolve_input_routes_to_url_list(tmp_path):
    url_file = tmp_path / "urls.txt"
    url_file.write_text("https://example.com/vid1\nhttps://example.com/vid2\n")

    output_dir = tmp_path / "output"

    call_count = 0

    def fake_download(url, out, **kwargs):
        nonlocal call_count
        call_count += 1
        out.mkdir(parents=True, exist_ok=True)
        fake = out / f"dl_{call_count}.mp4"
        fake.write_bytes(b"\x00")
        return MediaFile(path=fake, source_url=url, media_type="video")

    with (
        patch("framemine.download.check_ytdlp", return_value=True),
        patch("framemine.download.download_url", side_effect=fake_download),
    ):
        results = resolve_input(str(url_file), output_dir)

    assert len(results) == 2


def test_resolve_input_routes_to_single_url(tmp_path):
    fake = tmp_path / "abc.mp4"

    def fake_download(url, out, **kwargs):
        fake.write_bytes(b"\x00")
        return MediaFile(path=fake, source_url=url, media_type="video")

    with (
        patch("framemine.download.check_ytdlp", return_value=True),
        patch("framemine.download.download_url", side_effect=fake_download),
    ):
        results = resolve_input("https://example.com/video", tmp_path)

    assert len(results) == 1
    assert results[0].source_url == "https://example.com/video"


def test_resolve_input_routes_to_single_file(tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"\x00" * 50)

    results = resolve_input(str(video), tmp_path)
    assert len(results) == 1
    assert results[0].path == video
    assert results[0].media_type == "video"


def test_resolve_input_routes_to_single_image(tmp_path):
    image = tmp_path / "photo.jpg"
    image.write_bytes(b"\x00" * 50)

    results = resolve_input(str(image), tmp_path)
    assert len(results) == 1
    assert results[0].media_type == "image"


def test_resolve_input_raises_on_missing_path(tmp_path):
    with pytest.raises(FileNotFoundError):
        resolve_input("/nonexistent/path/video.mp4", tmp_path)


def test_resolve_input_raises_on_urls_without_ytdlp(tmp_path):
    with patch("framemine.download.check_ytdlp", return_value=False):
        with pytest.raises(RuntimeError, match="yt-dlp"):
            resolve_input("https://example.com/video", tmp_path)


def test_resolve_input_raises_on_url_list_without_ytdlp(tmp_path):
    url_file = tmp_path / "urls.txt"
    url_file.write_text("https://example.com/vid1\n")

    with patch("framemine.download.check_ytdlp", return_value=False):
        with pytest.raises(RuntimeError, match="yt-dlp"):
            resolve_input(str(url_file), tmp_path)


def test_resolve_input_raises_on_unrecognized_format(tmp_path):
    weird = tmp_path / "data.csv"
    weird.write_text("a,b,c")

    with pytest.raises(ValueError, match="Unrecognized"):
        resolve_input(str(weird), tmp_path)
