"""Download videos/images from URLs and discover local media files."""

import logging
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

SUPPORTED_VIDEO_EXTENSIONS = {".mp4", ".mkv", ".webm", ".mov", ".avi", ".flv"}
SUPPORTED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


@dataclass
class MediaFile:
    """A discovered or downloaded media file."""

    path: Path
    source_url: str | None = None
    media_type: str = "video"  # "video" or "image"


def check_ytdlp() -> bool:
    """Return True if yt-dlp is available on PATH."""
    return shutil.which("yt-dlp") is not None


def _classify_media_type(path: Path) -> str | None:
    """Return 'video', 'image', or None based on file extension."""
    ext = path.suffix.lower()
    if ext in SUPPORTED_VIDEO_EXTENSIONS:
        return "video"
    if ext in SUPPORTED_IMAGE_EXTENSIONS:
        return "image"
    return None


def discover_local_media(directory: Path) -> list[MediaFile]:
    """
    Scan a directory for video and image files (non-recursive, top-level only).

    Returns list of MediaFile sorted by filename.
    Classifies based on file extension.
    """
    media_files: list[MediaFile] = []
    for entry in directory.iterdir():
        if not entry.is_file():
            continue
        media_type = _classify_media_type(entry)
        if media_type is not None:
            media_files.append(MediaFile(path=entry, media_type=media_type))
    media_files.sort(key=lambda m: m.path.name)
    return media_files


def download_url(
    url: str,
    output_dir: Path,
    cookies_from_browser: str | None = None,
    max_resolution: int = 720,
    retries: int = 3,
) -> MediaFile | None:
    """
    Download a single URL using yt-dlp.

    Returns MediaFile on success, None on failure.
    Logs errors but never raises.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Snapshot existing files before download so we can find new ones after.
    existing_files = set(output_dir.iterdir())

    cmd = [
        "yt-dlp",
        "-o",
        str(output_dir / "%(id)s.%(ext)s"),
        "--format",
        f"bestvideo[height<={max_resolution}]+bestaudio/best[height<={max_resolution}]/best",
        "--retries",
        str(retries),
    ]
    if cookies_from_browser:
        cmd.extend(["--cookies-from-browser", cookies_from_browser])
    cmd.append(url)

    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            logger.error("yt-dlp failed for %s: %s", url, result.stderr)
            return None
    except Exception:
        logger.exception("Failed to run yt-dlp for %s", url)
        return None

    # Find newly created file(s).
    new_files = set(output_dir.iterdir()) - existing_files
    if not new_files:
        logger.error("yt-dlp reported success but no new file found for %s", url)
        return None

    # Pick the first new file (by name for determinism).
    downloaded = sorted(new_files, key=lambda p: p.name)[0]
    media_type = _classify_media_type(downloaded) or "video"

    return MediaFile(path=downloaded, source_url=url, media_type=media_type)


def download_url_list(
    url_file: Path,
    output_dir: Path,
    cookies_from_browser: str | None = None,
    max_resolution: int = 720,
    retries: int = 3,
    progress_callback: callable | None = None,
) -> list[MediaFile]:
    """
    Download all URLs from a text file (one per line, # comments and blank lines skipped).

    Calls progress_callback(current, total, url, success) after each.
    Returns list of successfully downloaded MediaFiles.
    """
    lines = url_file.read_text().splitlines()
    urls = [
        line.strip()
        for line in lines
        if line.strip() and not line.strip().startswith("#")
    ]
    total = len(urls)
    results: list[MediaFile] = []

    for i, url in enumerate(urls, start=1):
        media = download_url(
            url,
            output_dir,
            cookies_from_browser=cookies_from_browser,
            max_resolution=max_resolution,
            retries=retries,
        )
        success = media is not None
        if success:
            results.append(media)
        if progress_callback is not None:
            progress_callback(i, total, url, success)

    return results


def resolve_input(
    source: str,
    output_dir: Path,
    cookies_from_browser: str | None = None,
    max_resolution: int = 720,
    max_posts: int | None = None,
) -> list[MediaFile]:
    """
    High-level entry point. Routes based on source type:

    1. Platform saved content (instagram:user, tiktok:user, youtube:url)
    2. Directory path -> discover_local_media()
    3. .txt file path -> download_url_list()
    4. URL (starts with http) -> download_url() single
    5. Single file path -> wrap as MediaFile

    Raises FileNotFoundError if local path doesn't exist.
    Raises ValueError for unrecognized source format.
    Raises RuntimeError if required download tool is not available.
    """
    # Platform saved content (e.g. instagram:username)
    from .saved import is_saved_source, parse_saved_source, download_saved
    if is_saved_source(source):
        platform, target = parse_saved_source(source)
        return download_saved(
            platform, target, output_dir,
            cookies_from_browser=cookies_from_browser,
            max_resolution=max_resolution,
            max_posts=max_posts,
        )

    # URL input
    if source.startswith("http://") or source.startswith("https://"):
        if not check_ytdlp():
            raise RuntimeError(
                "yt-dlp is required for downloading URLs but was not found on PATH."
            )
        result = download_url(
            source,
            output_dir,
            cookies_from_browser=cookies_from_browser,
            max_resolution=max_resolution,
        )
        return [result] if result else []

    path = Path(source)

    # Local path must exist.
    if not path.exists():
        raise FileNotFoundError(f"Source path does not exist: {source}")

    # Directory
    if path.is_dir():
        return discover_local_media(path)

    # URL list file
    if path.suffix == ".txt":
        if not check_ytdlp():
            raise RuntimeError(
                "yt-dlp is required for downloading URLs but was not found on PATH."
            )
        return download_url_list(
            path,
            output_dir,
            cookies_from_browser=cookies_from_browser,
            max_resolution=max_resolution,
        )

    # Single file
    media_type = _classify_media_type(path)
    if media_type is not None:
        return [MediaFile(path=path, media_type=media_type)]

    raise ValueError(f"Unrecognized source format: {source}")
