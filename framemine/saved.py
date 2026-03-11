"""Download saved/favorited content from social media platforms."""

import logging
import shutil
import subprocess
from pathlib import Path

from .download import MediaFile, discover_local_media, check_ytdlp

logger = logging.getLogger(__name__)

SUPPORTED_PLATFORMS = {"instagram", "tiktok", "youtube"}


def check_instaloader() -> bool:
    """Return True if instaloader is available on PATH."""
    return shutil.which("instaloader") is not None


def is_saved_source(source: str) -> bool:
    """Check if source string is a platform:target format (e.g. instagram:username)."""
    if ":" not in source:
        return False
    # Don't match URLs or absolute paths
    if source.startswith(("http://", "https://", "/", ".")):
        return False
    # Windows drive letters like C:
    if len(source.split(":", 1)[0]) == 1:
        return False
    platform = source.split(":", 1)[0].lower()
    return platform in SUPPORTED_PLATFORMS


def parse_saved_source(source: str) -> tuple[str, str]:
    """Parse 'platform:target' into (platform, target). Strips leading @ from target."""
    platform, target = source.split(":", 1)
    return platform.lower(), target.strip().lstrip("@")


def download_instagram_saved(
    username: str,
    output_dir: Path,
    max_posts: int | None = None,
) -> list[MediaFile]:
    """
    Download saved posts from Instagram using instaloader.

    instaloader handles auth interactively on first use (prompts for password),
    then caches the session at ~/.config/instaloader/session-USERNAME for
    subsequent runs.

    Raises RuntimeError if instaloader is not installed.
    """
    if not check_instaloader():
        raise RuntimeError(
            "instaloader is required for Instagram downloads. "
            "Install it: pip install instaloader"
        )

    output_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        "instaloader",
        "--login", username,
        ":saved",
        "--dirname-pattern", str(output_dir),
        "--filename-pattern", "{shortcode}",
        "--no-metadata-json",
        "--no-captions",
        "--no-profile-pic",
        "--no-compress-json",
    ]

    if max_posts is not None:
        cmd.extend(["--count", str(max_posts)])

    logger.info("Downloading Instagram saved posts for @%s...", username)
    logger.debug("Running: %s", " ".join(cmd))

    # Don't capture output — instaloader needs terminal access for auth prompts
    try:
        result = subprocess.run(cmd)
        if result.returncode != 0:
            logger.error("instaloader exited with code %d", result.returncode)
            return []
    except Exception:
        logger.exception("Failed to run instaloader")
        return []

    return discover_local_media(output_dir)


def download_ytdlp_collection(
    url: str,
    output_dir: Path,
    cookies_from_browser: str | None = None,
    max_resolution: int = 720,
    max_posts: int | None = None,
) -> list[MediaFile]:
    """
    Download a collection (playlist, user page, favorites) using yt-dlp.

    Raises RuntimeError if yt-dlp is not installed.
    """
    if not check_ytdlp():
        raise RuntimeError(
            "yt-dlp is required for URL downloads but was not found on PATH."
        )

    output_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        "yt-dlp",
        "-o", str(output_dir / "%(id)s.%(ext)s"),
        "--format",
        f"bestvideo[height<={max_resolution}]+bestaudio/best[height<={max_resolution}]/best",
    ]

    if cookies_from_browser:
        cmd.extend(["--cookies-from-browser", cookies_from_browser])

    if max_posts is not None:
        cmd.extend(["--playlist-end", str(max_posts)])

    cmd.append(url)

    logger.info("Downloading collection from %s...", url)
    logger.debug("Running: %s", " ".join(cmd))

    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            logger.error("yt-dlp failed: %s", result.stderr[:200] if result.stderr else "unknown error")
            return []
    except Exception:
        logger.exception("Failed to run yt-dlp")
        return []

    return discover_local_media(output_dir)


def download_saved(
    platform: str,
    target: str,
    output_dir: Path,
    cookies_from_browser: str | None = None,
    max_resolution: int = 720,
    max_posts: int | None = None,
) -> list[MediaFile]:
    """
    Route to platform-specific saved content downloader.

    Platform routing:
      instagram:USERNAME  → instaloader (saved posts, handles auth interactively)
      tiktok:USERNAME     → yt-dlp (user's videos, cookies recommended)
      youtube:URL         → yt-dlp (playlist or channel)

    Raises ValueError for unknown platforms.
    Raises RuntimeError if required tool is not installed.
    """
    if platform == "instagram":
        return download_instagram_saved(
            target, output_dir, max_posts=max_posts,
        )

    elif platform == "tiktok":
        url = f"https://www.tiktok.com/@{target}"
        if not cookies_from_browser:
            logger.warning(
                "TikTok downloads usually require browser cookies for full access. "
                "Try adding --cookies chrome if downloads fail."
            )
        return download_ytdlp_collection(
            url, output_dir,
            cookies_from_browser=cookies_from_browser,
            max_resolution=max_resolution,
            max_posts=max_posts,
        )

    elif platform == "youtube":
        # target is a playlist/channel URL, or a channel name
        if target.startswith("http"):
            url = target
        else:
            url = f"https://www.youtube.com/@{target}"
        return download_ytdlp_collection(
            url, output_dir,
            cookies_from_browser=cookies_from_browser,
            max_resolution=max_resolution,
            max_posts=max_posts,
        )

    else:
        raise ValueError(
            f"Unknown platform: {platform}. "
            f"Supported: {', '.join(sorted(SUPPORTED_PLATFORMS))}"
        )
