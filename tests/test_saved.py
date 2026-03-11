"""Tests for framemine.saved — social media saved content downloading."""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from framemine.download import MediaFile
from framemine.saved import (
    SUPPORTED_PLATFORMS,
    check_instaloader,
    download_instagram_saved,
    download_saved,
    download_ytdlp_collection,
    is_saved_source,
    parse_saved_source,
)


# ---------------------------------------------------------------------------
# check_instaloader
# ---------------------------------------------------------------------------


class TestCheckInstaloader:
    @patch("framemine.saved.shutil.which", return_value="/usr/bin/instaloader")
    def test_available(self, mock_which):
        assert check_instaloader() is True
        mock_which.assert_called_once_with("instaloader")

    @patch("framemine.saved.shutil.which", return_value=None)
    def test_missing(self, mock_which):
        assert check_instaloader() is False
        mock_which.assert_called_once_with("instaloader")


# ---------------------------------------------------------------------------
# is_saved_source
# ---------------------------------------------------------------------------


class TestIsSavedSource:
    @pytest.mark.parametrize(
        "source",
        [
            "instagram:username",
            "Instagram:Username",
            "INSTAGRAM:user",
            "tiktok:username",
            "TikTok:user",
            "youtube:https://youtube.com/playlist?list=abc",
            "youtube:channelname",
        ],
    )
    def test_valid_saved_sources(self, source):
        assert is_saved_source(source) is True

    @pytest.mark.parametrize(
        "source",
        [
            "https://example.com",
            "http://example.com",
            "https://instagram.com/p/abc",
            "./folder",
            "./relative/path",
            "/abs/path",
            "/absolute/file.mp4",
            "video.mp4",
            "somefile.txt",
            "unknown:something",
            "twitter:user",
            "C:/Windows/path",  # Windows drive letter
            "D:file",
        ],
    )
    def test_invalid_saved_sources(self, source):
        assert is_saved_source(source) is False

    def test_no_colon_at_all(self):
        assert is_saved_source("justtext") is False

    def test_empty_string(self):
        assert is_saved_source("") is False


# ---------------------------------------------------------------------------
# parse_saved_source
# ---------------------------------------------------------------------------


class TestParseSavedSource:
    def test_basic_parse(self):
        platform, target = parse_saved_source("instagram:someuser")
        assert platform == "instagram"
        assert target == "someuser"

    def test_strips_at_sign(self):
        platform, target = parse_saved_source("tiktok:@cooluser")
        assert platform == "tiktok"
        assert target == "cooluser"

    def test_strips_multiple_at_signs(self):
        # lstrip("@") removes all leading @s
        _, target = parse_saved_source("instagram:@@user")
        assert target == "user"

    def test_lowercases_platform(self):
        platform, _ = parse_saved_source("YouTube:https://youtube.com/playlist")
        assert platform == "youtube"

    def test_preserves_target_case(self):
        _, target = parse_saved_source("instagram:CaseSensitiveUser")
        assert target == "CaseSensitiveUser"

    def test_strips_whitespace_from_target(self):
        _, target = parse_saved_source("instagram:  someuser  ")
        assert target == "someuser"
        # strip() removes leading/trailing, but lstrip("@") only strips @
        # Actually: target.strip().lstrip("@") strips spaces then @
        # Re-reading the code: target = source.split(":", 1)[1] then .strip().lstrip("@")
        # "  someuser  ".strip() -> "someuser" then lstrip("@") -> "someuser"

    def test_strips_whitespace_then_at(self):
        _, target = parse_saved_source("instagram:  @padded  ")
        assert target == "padded"

    def test_url_target_preserved(self):
        platform, target = parse_saved_source(
            "youtube:https://www.youtube.com/playlist?list=PLabc"
        )
        assert platform == "youtube"
        assert target == "https://www.youtube.com/playlist?list=PLabc"


# ---------------------------------------------------------------------------
# download_instagram_saved
# ---------------------------------------------------------------------------


class TestDownloadInstagramSaved:
    @patch("framemine.saved.discover_local_media")
    @patch("framemine.saved.subprocess.run")
    @patch("framemine.saved.check_instaloader", return_value=True)
    def test_basic_command(self, mock_check, mock_run, mock_discover, tmp_path):
        mock_run.return_value = MagicMock(returncode=0)
        expected_files = [MediaFile(path=tmp_path / "abc.mp4", media_type="video")]
        mock_discover.return_value = expected_files

        result = download_instagram_saved("testuser", tmp_path)

        assert result == expected_files
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]

        assert cmd[0] == "instaloader"
        assert "--login" in cmd
        assert cmd[cmd.index("--login") + 1] == "testuser"
        assert ":saved" in cmd
        assert "--dirname-pattern" in cmd
        assert cmd[cmd.index("--dirname-pattern") + 1] == str(tmp_path)
        assert "--filename-pattern" in cmd
        assert cmd[cmd.index("--filename-pattern") + 1] == "{shortcode}"
        assert "--no-metadata-json" in cmd
        assert "--no-captions" in cmd
        assert "--no-profile-pic" in cmd
        assert "--no-compress-json" in cmd
        # No --count by default
        assert "--count" not in cmd

        mock_discover.assert_called_once_with(tmp_path)

    @patch("framemine.saved.discover_local_media")
    @patch("framemine.saved.subprocess.run")
    @patch("framemine.saved.check_instaloader", return_value=True)
    def test_with_max_posts(self, mock_check, mock_run, mock_discover, tmp_path):
        mock_run.return_value = MagicMock(returncode=0)
        mock_discover.return_value = []

        download_instagram_saved("testuser", tmp_path, max_posts=50)

        cmd = mock_run.call_args[0][0]
        assert "--count" in cmd
        assert cmd[cmd.index("--count") + 1] == "50"

    @patch("framemine.saved.check_instaloader", return_value=False)
    def test_raises_when_instaloader_missing(self, mock_check, tmp_path):
        with pytest.raises(RuntimeError, match="instaloader is required"):
            download_instagram_saved("testuser", tmp_path)

    @patch("framemine.saved.discover_local_media")
    @patch("framemine.saved.subprocess.run")
    @patch("framemine.saved.check_instaloader", return_value=True)
    def test_returns_empty_on_subprocess_failure(
        self, mock_check, mock_run, mock_discover, tmp_path
    ):
        mock_run.return_value = MagicMock(returncode=1)

        result = download_instagram_saved("testuser", tmp_path)

        assert result == []
        mock_discover.assert_not_called()

    @patch("framemine.saved.discover_local_media")
    @patch("framemine.saved.subprocess.run", side_effect=OSError("command not found"))
    @patch("framemine.saved.check_instaloader", return_value=True)
    def test_returns_empty_on_exception(
        self, mock_check, mock_run, mock_discover, tmp_path
    ):
        result = download_instagram_saved("testuser", tmp_path)

        assert result == []
        mock_discover.assert_not_called()

    @patch("framemine.saved.discover_local_media")
    @patch("framemine.saved.subprocess.run")
    @patch("framemine.saved.check_instaloader", return_value=True)
    def test_creates_output_dir(self, mock_check, mock_run, mock_discover, tmp_path):
        mock_run.return_value = MagicMock(returncode=0)
        mock_discover.return_value = []
        nested = tmp_path / "sub" / "dir"

        download_instagram_saved("testuser", nested)

        assert nested.exists()


# ---------------------------------------------------------------------------
# download_ytdlp_collection
# ---------------------------------------------------------------------------


class TestDownloadYtdlpCollection:
    @patch("framemine.saved.discover_local_media")
    @patch("framemine.saved.subprocess.run")
    @patch("framemine.saved.check_ytdlp", return_value=True)
    def test_basic_command(self, mock_check, mock_run, mock_discover, tmp_path):
        mock_run.return_value = MagicMock(returncode=0)
        expected_files = [MediaFile(path=tmp_path / "vid.mp4", media_type="video")]
        mock_discover.return_value = expected_files

        url = "https://www.tiktok.com/@user"
        result = download_ytdlp_collection(url, tmp_path)

        assert result == expected_files
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]

        assert cmd[0] == "yt-dlp"
        assert "-o" in cmd
        assert url in cmd  # URL should be the last argument
        assert cmd[-1] == url
        assert "--playlist-end" not in cmd
        assert "--cookies-from-browser" not in cmd

        mock_discover.assert_called_once_with(tmp_path)

    @patch("framemine.saved.discover_local_media")
    @patch("framemine.saved.subprocess.run")
    @patch("framemine.saved.check_ytdlp", return_value=True)
    def test_with_max_posts(self, mock_check, mock_run, mock_discover, tmp_path):
        mock_run.return_value = MagicMock(returncode=0)
        mock_discover.return_value = []

        download_ytdlp_collection("https://example.com", tmp_path, max_posts=10)

        cmd = mock_run.call_args[0][0]
        assert "--playlist-end" in cmd
        assert cmd[cmd.index("--playlist-end") + 1] == "10"

    @patch("framemine.saved.discover_local_media")
    @patch("framemine.saved.subprocess.run")
    @patch("framemine.saved.check_ytdlp", return_value=True)
    def test_with_cookies(self, mock_check, mock_run, mock_discover, tmp_path):
        mock_run.return_value = MagicMock(returncode=0)
        mock_discover.return_value = []

        download_ytdlp_collection(
            "https://example.com", tmp_path, cookies_from_browser="chrome"
        )

        cmd = mock_run.call_args[0][0]
        assert "--cookies-from-browser" in cmd
        assert cmd[cmd.index("--cookies-from-browser") + 1] == "chrome"

    @patch("framemine.saved.discover_local_media")
    @patch("framemine.saved.subprocess.run")
    @patch("framemine.saved.check_ytdlp", return_value=True)
    def test_without_cookies(self, mock_check, mock_run, mock_discover, tmp_path):
        mock_run.return_value = MagicMock(returncode=0)
        mock_discover.return_value = []

        download_ytdlp_collection("https://example.com", tmp_path)

        cmd = mock_run.call_args[0][0]
        assert "--cookies-from-browser" not in cmd

    @patch("framemine.saved.check_ytdlp", return_value=False)
    def test_raises_when_ytdlp_missing(self, mock_check, tmp_path):
        with pytest.raises(RuntimeError, match="yt-dlp is required"):
            download_ytdlp_collection("https://example.com", tmp_path)

    @patch("framemine.saved.discover_local_media")
    @patch("framemine.saved.subprocess.run")
    @patch("framemine.saved.check_ytdlp", return_value=True)
    def test_returns_empty_on_failure(
        self, mock_check, mock_run, mock_discover, tmp_path
    ):
        mock_run.return_value = MagicMock(
            returncode=1, stderr="Error downloading"
        )

        result = download_ytdlp_collection("https://example.com", tmp_path)

        assert result == []
        mock_discover.assert_not_called()

    @patch("framemine.saved.discover_local_media")
    @patch("framemine.saved.subprocess.run", side_effect=OSError("not found"))
    @patch("framemine.saved.check_ytdlp", return_value=True)
    def test_returns_empty_on_exception(
        self, mock_check, mock_run, mock_discover, tmp_path
    ):
        result = download_ytdlp_collection("https://example.com", tmp_path)

        assert result == []
        mock_discover.assert_not_called()

    @patch("framemine.saved.discover_local_media")
    @patch("framemine.saved.subprocess.run")
    @patch("framemine.saved.check_ytdlp", return_value=True)
    def test_max_resolution_in_format(
        self, mock_check, mock_run, mock_discover, tmp_path
    ):
        mock_run.return_value = MagicMock(returncode=0)
        mock_discover.return_value = []

        download_ytdlp_collection(
            "https://example.com", tmp_path, max_resolution=1080
        )

        cmd = mock_run.call_args[0][0]
        format_idx = cmd.index("--format") + 1
        assert "1080" in cmd[format_idx]

    @patch("framemine.saved.discover_local_media")
    @patch("framemine.saved.subprocess.run")
    @patch("framemine.saved.check_ytdlp", return_value=True)
    def test_creates_output_dir(self, mock_check, mock_run, mock_discover, tmp_path):
        mock_run.return_value = MagicMock(returncode=0)
        mock_discover.return_value = []
        nested = tmp_path / "deep" / "nested"

        download_ytdlp_collection("https://example.com", nested)

        assert nested.exists()


# ---------------------------------------------------------------------------
# download_saved (routing)
# ---------------------------------------------------------------------------


class TestDownloadSaved:
    @patch("framemine.saved.download_instagram_saved")
    def test_instagram_routing(self, mock_ig, tmp_path):
        expected = [MediaFile(path=tmp_path / "a.mp4")]
        mock_ig.return_value = expected

        result = download_saved("instagram", "someuser", tmp_path, max_posts=5)

        assert result == expected
        mock_ig.assert_called_once_with("someuser", tmp_path, max_posts=5)

    @patch("framemine.saved.download_ytdlp_collection")
    def test_tiktok_routing_builds_url(self, mock_ytdlp, tmp_path):
        mock_ytdlp.return_value = []

        download_saved(
            "tiktok", "cooluser", tmp_path,
            cookies_from_browser="chrome",
            max_resolution=480,
            max_posts=20,
        )

        mock_ytdlp.assert_called_once_with(
            "https://www.tiktok.com/@cooluser",
            tmp_path,
            cookies_from_browser="chrome",
            max_resolution=480,
            max_posts=20,
        )

    @patch("framemine.saved.download_ytdlp_collection")
    def test_youtube_with_url_passthrough(self, mock_ytdlp, tmp_path):
        mock_ytdlp.return_value = []
        yt_url = "https://www.youtube.com/playlist?list=PLabc123"

        download_saved("youtube", yt_url, tmp_path)

        mock_ytdlp.assert_called_once()
        assert mock_ytdlp.call_args[0][0] == yt_url

    @patch("framemine.saved.download_ytdlp_collection")
    def test_youtube_with_channel_name(self, mock_ytdlp, tmp_path):
        mock_ytdlp.return_value = []

        download_saved("youtube", "channelname", tmp_path)

        mock_ytdlp.assert_called_once()
        assert mock_ytdlp.call_args[0][0] == "https://www.youtube.com/@channelname"

    def test_unknown_platform_raises(self, tmp_path):
        with pytest.raises(ValueError, match="Unknown platform: twitter"):
            download_saved("twitter", "user", tmp_path)

    def test_unknown_platform_error_lists_supported(self, tmp_path):
        with pytest.raises(ValueError, match="Supported:"):
            download_saved("myspace", "user", tmp_path)

    @patch("framemine.saved.download_ytdlp_collection")
    def test_tiktok_without_cookies_still_works(self, mock_ytdlp, tmp_path):
        """TikTok without cookies logs a warning but doesn't fail."""
        mock_ytdlp.return_value = []

        download_saved("tiktok", "user", tmp_path, cookies_from_browser=None)

        mock_ytdlp.assert_called_once()
        assert mock_ytdlp.call_args[1]["cookies_from_browser"] is None


# ---------------------------------------------------------------------------
# resolve_input integration (in download.py)
# ---------------------------------------------------------------------------


class TestResolveInputSavedIntegration:
    @patch("framemine.saved.download_instagram_saved")
    @patch("framemine.saved.check_instaloader", return_value=True)
    def test_instagram_source_routes_to_saved(self, mock_check, mock_ig, tmp_path):
        from framemine.download import resolve_input

        expected = [MediaFile(path=tmp_path / "post.mp4")]
        mock_ig.return_value = expected

        result = resolve_input("instagram:myuser", tmp_path)

        assert result == expected
        mock_ig.assert_called_once_with("myuser", tmp_path, max_posts=None)

    @patch("framemine.saved.download_instagram_saved")
    @patch("framemine.saved.check_instaloader", return_value=True)
    def test_max_posts_passed_through(self, mock_check, mock_ig, tmp_path):
        from framemine.download import resolve_input

        mock_ig.return_value = []

        resolve_input("instagram:user", tmp_path, max_posts=25)

        mock_ig.assert_called_once_with("user", tmp_path, max_posts=25)

    @patch("framemine.saved.download_ytdlp_collection")
    @patch("framemine.saved.check_ytdlp", return_value=True)
    def test_tiktok_source_routes_to_saved(self, mock_check, mock_ytdlp, tmp_path):
        from framemine.download import resolve_input

        mock_ytdlp.return_value = []

        resolve_input("tiktok:@someuser", tmp_path, cookies_from_browser="firefox")

        mock_ytdlp.assert_called_once()
        call_url = mock_ytdlp.call_args[0][0]
        assert call_url == "https://www.tiktok.com/@someuser"

    @patch("framemine.saved.download_ytdlp_collection")
    @patch("framemine.saved.check_ytdlp", return_value=True)
    def test_youtube_source_routes_to_saved(self, mock_check, mock_ytdlp, tmp_path):
        from framemine.download import resolve_input

        mock_ytdlp.return_value = []
        yt_url = "https://www.youtube.com/playlist?list=PLxyz"

        resolve_input(f"youtube:{yt_url}", tmp_path)

        mock_ytdlp.assert_called_once()
        assert mock_ytdlp.call_args[0][0] == yt_url

    def test_url_does_not_route_to_saved(self, tmp_path):
        """A plain URL should NOT be treated as a saved source."""
        from framemine.download import resolve_input

        # Plain https URL should try download_url, not saved
        with patch("framemine.download.check_ytdlp", return_value=True), \
             patch("framemine.download.download_url", return_value=None) as mock_dl:
            result = resolve_input("https://example.com/video.mp4", tmp_path)
            mock_dl.assert_called_once()
            assert result == []

    def test_local_path_does_not_route_to_saved(self, tmp_path):
        """A local directory should NOT be treated as a saved source."""
        from framemine.download import resolve_input

        result = resolve_input(str(tmp_path), tmp_path)
        # Should return discover_local_media results (empty dir = empty list)
        assert result == []
