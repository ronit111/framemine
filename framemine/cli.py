"""Click-based CLI for framemine."""

import logging
import sys
import tempfile
from pathlib import Path

import click
import yaml

from . import __version__
from .ai import create_backend
from .dedup import deduplicate
from .download import resolve_input, check_ytdlp
from .enrichment import enrich_items
from .frames import FrameExtractionConfig, check_ffmpeg, get_frames
from .output import write_outputs
from .schema import get_schema_info, load_schema

logger = logging.getLogger(__name__)

CONFIG_SEARCH_PATHS = [
    Path("framemine.yaml"),
    Path.home() / ".config" / "framemine" / "config.yaml",
]


def _load_config(config_path: str | None = None) -> dict:
    """Load config from explicit path, ./framemine.yaml, or ~/.config/framemine/config.yaml."""
    if config_path:
        p = Path(config_path)
        if not p.exists():
            raise click.BadParameter(f"Config file not found: {config_path}")
        with open(p) as f:
            return yaml.safe_load(f) or {}

    for p in CONFIG_SEARCH_PATHS:
        if p.exists():
            with open(p) as f:
                return yaml.safe_load(f) or {}

    return {}


@click.group()
@click.version_option(version=__version__, prog_name="framemine")
@click.option("-v", "--verbose", is_flag=True, help="Enable debug logging.")
def cli(verbose: bool) -> None:
    """Extract structured data from visual social media content."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(message)s",
        handlers=[logging.StreamHandler()],
    )


@cli.command()
@click.argument("source")
@click.option("-s", "--schema", "schema_name", required=True, help="Extraction schema (e.g. books, recipes, products).")
@click.option("-o", "--output", "output_name", default=None, help="Output filename stem (default: schema name).")
@click.option("-c", "--config", "config_path", default=None, help="Path to config YAML.")
@click.option("--cookies", default=None, help="Browser name for yt-dlp cookies (e.g. chrome, firefox).")
@click.option("--no-enrich", is_flag=True, help="Skip metadata enrichment.")
@click.option("--json-only", is_flag=True, help="Output JSON only, no Excel.")
@click.option("--output-dir", default=".", help="Directory for output files.")
def extract(
    source: str,
    schema_name: str,
    output_name: str | None,
    config_path: str | None,
    cookies: str | None,
    no_enrich: bool,
    json_only: bool,
    output_dir: str,
) -> None:
    """Run the full extraction pipeline.

    SOURCE can be a local directory, a .txt file of URLs, a single URL, or a media file.
    """
    config = _load_config(config_path)
    ai_config = config.get("ai", {})
    dl_config = config.get("download", {})
    ext_config = config.get("extraction", {})

    # Load schema
    try:
        schema = load_schema(schema_name)
    except (FileNotFoundError, ValueError) as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    click.echo(f"Schema: {schema.display_name}")
    click.echo(f"Source: {source}")

    # Resolve input (download if needed)
    with tempfile.TemporaryDirectory(prefix="framemine_") as tmp:
        tmp_path = Path(tmp)
        download_dir = tmp_path / "downloads"

        try:
            media_files = resolve_input(
                source,
                download_dir,
                cookies_from_browser=cookies,
                max_resolution=dl_config.get("max_resolution", 720),
            )
        except (FileNotFoundError, ValueError, RuntimeError) as e:
            click.echo(f"Error: {e}", err=True)
            sys.exit(1)

        if not media_files:
            click.echo("No media files found.", err=True)
            sys.exit(1)

        click.echo(f"Found {len(media_files)} media file(s)")

        # Create AI backend
        try:
            backend = create_backend(ai_config)
        except (RuntimeError, ValueError) as e:
            click.echo(f"Error: {e}", err=True)
            sys.exit(1)

        # Frame extraction config
        frame_config = FrameExtractionConfig(
            scene_threshold=ext_config.get("scene_threshold", 0.3),
            max_keyframes=ext_config.get("max_keyframes", 15),
            fallback_interval=ext_config.get("fallback_interval", 3),
        )

        # Process each media file
        all_items: list[dict] = []
        frames_dir = tmp_path / "frames"

        for i, media in enumerate(media_files, 1):
            click.echo(f"  [{i}/{len(media_files)}] {media.path.name}", nl=False)

            if media.media_type == "video":
                if not check_ffmpeg():
                    click.echo(" — skipped (ffmpeg not found)", err=True)
                    continue
                frames = get_frames(media.path, frames_dir, frame_config)
            else:
                frames = [media.path]

            if not frames:
                click.echo(" — no frames extracted")
                continue

            items = backend.extract(frames, schema.prompt)

            # Tag items with source URL if available
            if media.source_url:
                for item in items:
                    item.setdefault("source", media.source_url)

            all_items.extend(items)
            click.echo(f" — {len(items)} item(s)")

    if not all_items:
        click.echo("No items extracted.", err=True)
        sys.exit(1)

    click.echo(f"\nTotal raw items: {len(all_items)}")

    # Deduplicate
    all_items = deduplicate(all_items, key_fields=schema.dedup_key)
    click.echo(f"After dedup: {len(all_items)}")

    # Enrich
    if not no_enrich and schema.enrichment:
        click.echo(f"Enriching with {schema.enrichment} metadata...")
        enrich_items(
            all_items,
            schema.enrichment,
            progress_callback=lambda cur, total: click.echo(
                f"  Enriched {cur}/{total}", nl=(cur == total)
            ) if cur % 10 == 0 or cur == total else None,
        )

    # Write outputs
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = output_name or schema_name
    out_path = out_dir / stem

    results = write_outputs(
        all_items,
        out_path,
        columns=schema.output_columns,
        sheet_name=schema.display_name,
        json_output=True,
        excel_output=not json_only,
    )

    click.echo(f"\nOutput:")
    for fmt, path in results.items():
        click.echo(f"  {fmt}: {path}")
    click.echo(f"  {len(all_items)} items total")


@cli.command()
def schemas() -> None:
    """List available extraction schemas."""
    info = get_schema_info()
    if not info:
        click.echo("No schemas found.")
        return
    for s in info:
        click.echo(f"  {s['name']:12s} {s['display_name']} — {s['description']}")


@cli.command()
def check() -> None:
    """Check that required dependencies are installed."""
    all_ok = True

    # ffmpeg
    if check_ffmpeg():
        click.echo("  ffmpeg        OK")
    else:
        click.echo("  ffmpeg        MISSING — install from https://ffmpeg.org/")
        all_ok = False

    # yt-dlp (optional)
    if check_ytdlp():
        click.echo("  yt-dlp        OK")
    else:
        click.echo("  yt-dlp        MISSING (optional, needed for URL downloads)")

    # Python packages
    packages = ["click", "google.genai", "PIL", "openpyxl", "requests", "yaml"]
    for pkg in packages:
        try:
            __import__(pkg)
            click.echo(f"  {pkg:14s} OK")
        except ImportError:
            click.echo(f"  {pkg:14s} MISSING")
            all_ok = False

    if all_ok:
        click.echo("\nAll required dependencies OK.")
    else:
        click.echo("\nSome dependencies missing. Run: pip install framemine")
        sys.exit(1)
