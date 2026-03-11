"""Comprehensive tests for the framemine CLI (Click app)."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest
import yaml
from click.testing import CliRunner

from framemine import __version__
from framemine.cli import cli, _load_config
from framemine.download import MediaFile
from framemine.schema import Schema


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_image(path: Path) -> Path:
    """Create a minimal valid JPEG-ish file at path (for frame lists)."""
    from PIL import Image

    img = Image.new("RGB", (10, 10), color="blue")
    img.save(path)
    return path


def _make_schema(**overrides) -> Schema:
    """Create a Schema with sane defaults, applying any overrides."""
    defaults = dict(
        name="books",
        display_name="Books & Reading",
        description="Extract book recommendations",
        prompt="Extract books.",
        output_columns=["title", "author", "type", "genre", "source"],
        dedup_key=["title"],
        enrichment="books",
        item_type_field="type",
    )
    defaults.update(overrides)
    return Schema(**defaults)


CANNED_BOOKS = [
    {"title": "The Great Gatsby", "author": "F. Scott Fitzgerald", "type": "book"},
    {"title": "Sapiens", "author": "Yuval Noah Harari", "type": "book"},
]

CANNED_RECIPES = [
    {"name": "Pasta Carbonara", "cuisine": "Italian", "difficulty": "medium"},
]


# ---------------------------------------------------------------------------
# 1. Version
# ---------------------------------------------------------------------------

class TestVersion:
    def test_version_flag(self):
        result = CliRunner().invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert __version__ in result.output
        assert "framemine" in result.output

    def test_version_string_format(self):
        result = CliRunner().invoke(cli, ["--version"])
        # Expect "framemine, version X.Y.Z"
        assert f"version {__version__}" in result.output


# ---------------------------------------------------------------------------
# 2. schemas command
# ---------------------------------------------------------------------------

class TestSchemasCommand:
    @patch("framemine.cli.get_schema_info")
    def test_lists_schemas(self, mock_info):
        mock_info.return_value = [
            {"name": "books", "display_name": "Books & Reading", "description": "Extract books"},
            {"name": "recipes", "display_name": "Recipes & Cooking", "description": "Extract recipes"},
            {"name": "products", "display_name": "Products", "description": "Extract products"},
        ]
        result = CliRunner().invoke(cli, ["schemas"])
        assert result.exit_code == 0
        assert "books" in result.output
        assert "recipes" in result.output
        assert "products" in result.output
        assert "Books & Reading" in result.output

    @patch("framemine.cli.get_schema_info")
    def test_no_schemas(self, mock_info):
        mock_info.return_value = []
        result = CliRunner().invoke(cli, ["schemas"])
        assert result.exit_code == 0
        assert "No schemas found" in result.output


# ---------------------------------------------------------------------------
# 3. check command
# ---------------------------------------------------------------------------

class TestCheckCommand:
    @patch("framemine.cli.check_ytdlp", return_value=True)
    @patch("framemine.cli.check_ffmpeg", return_value=True)
    def test_all_ok(self, mock_ff, mock_yt):
        result = CliRunner().invoke(cli, ["check"])
        assert result.exit_code == 0
        assert "ffmpeg" in result.output
        assert "OK" in result.output
        assert "All required dependencies OK" in result.output

    @patch("framemine.cli.check_ytdlp", return_value=False)
    @patch("framemine.cli.check_ffmpeg", return_value=False)
    def test_ffmpeg_missing(self, mock_ff, mock_yt):
        result = CliRunner().invoke(cli, ["check"])
        assert result.exit_code != 0
        assert "MISSING" in result.output
        assert "Some dependencies missing" in result.output

    @patch("framemine.cli.check_ytdlp", return_value=False)
    @patch("framemine.cli.check_ffmpeg", return_value=True)
    def test_ytdlp_missing_nonfatal(self, mock_ff, mock_yt):
        # yt-dlp missing is not fatal by itself (only ffmpeg + python pkgs matter)
        result = CliRunner().invoke(cli, ["check"])
        assert "yt-dlp" in result.output
        assert "MISSING" in result.output


# ---------------------------------------------------------------------------
# 4. extract command — full pipeline with mocks
# ---------------------------------------------------------------------------

class TestExtractCommand:
    """Tests for `framemine extract` with all external calls mocked."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        """Create reusable temp images and output dir for each test."""
        self.runner = CliRunner()
        self.tmp_path = tmp_path
        self.output_dir = tmp_path / "output"
        self.output_dir.mkdir()

        # Create fake image files that can stand in as frames
        self.frame1 = _make_image(tmp_path / "frame_001.jpg")
        self.frame2 = _make_image(tmp_path / "frame_002.jpg")

    def _invoke_extract(self, source, schema="books", extra_args=None):
        """Convenience: invoke `extract` with common args."""
        args = ["extract", source, "-s", schema, "--output-dir", str(self.output_dir)]
        if extra_args:
            args.extend(extra_args)
        return self.runner.invoke(cli, args, catch_exceptions=False)

    # -- Video source, full pipeline --

    @patch("framemine.cli.enrich_items")
    @patch("framemine.cli.deduplicate", side_effect=lambda items, **kw: items)
    @patch("framemine.cli.write_outputs")
    @patch("framemine.cli.create_backend")
    @patch("framemine.cli.get_frames")
    @patch("framemine.cli.check_ffmpeg", return_value=True)
    @patch("framemine.cli.resolve_input")
    @patch("framemine.cli.load_schema")
    def test_video_full_pipeline(
        self, mock_schema, mock_resolve, mock_ffcheck, mock_frames,
        mock_backend_factory, mock_write, mock_dedup, mock_enrich,
    ):
        mock_schema.return_value = _make_schema()
        mock_resolve.return_value = [
            MediaFile(path=Path("/fake/video.mp4"), media_type="video", source_url="https://example.com/v1"),
        ]
        mock_frames.return_value = [self.frame1, self.frame2]

        backend = MagicMock()
        backend.extract.return_value = list(CANNED_BOOKS)
        mock_backend_factory.return_value = backend

        mock_write.return_value = {
            "json": self.output_dir / "books.json",
            "excel": self.output_dir / "books.xlsx",
        }

        result = self._invoke_extract("/fake/video.mp4")

        assert result.exit_code == 0
        assert "Schema: Books & Reading" in result.output
        assert "Found 1 media file(s)" in result.output
        assert "2 item(s)" in result.output

        # Backend was called with frames + prompt
        backend.extract.assert_called_once_with([self.frame1, self.frame2], "Extract books.")
        # write_outputs was called
        mock_write.assert_called_once()
        # enrichment was called (books schema has enrichment)
        mock_enrich.assert_called_once()

    # -- Image source --

    @patch("framemine.cli.enrich_items")
    @patch("framemine.cli.deduplicate", side_effect=lambda items, **kw: items)
    @patch("framemine.cli.write_outputs")
    @patch("framemine.cli.create_backend")
    @patch("framemine.cli.resolve_input")
    @patch("framemine.cli.load_schema")
    def test_image_source_skips_ffmpeg(
        self, mock_schema, mock_resolve, mock_backend_factory,
        mock_write, mock_dedup, mock_enrich,
    ):
        """For image media_type, frames == [media.path]; ffmpeg is not called."""
        mock_schema.return_value = _make_schema()
        mock_resolve.return_value = [
            MediaFile(path=self.frame1, media_type="image"),
        ]

        backend = MagicMock()
        backend.extract.return_value = list(CANNED_BOOKS)
        mock_backend_factory.return_value = backend

        mock_write.return_value = {"json": self.output_dir / "books.json"}

        result = self._invoke_extract(str(self.frame1))

        assert result.exit_code == 0
        # Image path is passed directly (no get_frames call needed)
        backend.extract.assert_called_once_with([self.frame1], "Extract books.")

    # -- Multiple media files --

    @patch("framemine.cli.enrich_items")
    @patch("framemine.cli.deduplicate", side_effect=lambda items, **kw: items)
    @patch("framemine.cli.write_outputs")
    @patch("framemine.cli.create_backend")
    @patch("framemine.cli.get_frames")
    @patch("framemine.cli.check_ffmpeg", return_value=True)
    @patch("framemine.cli.resolve_input")
    @patch("framemine.cli.load_schema")
    def test_multiple_media_files(
        self, mock_schema, mock_resolve, mock_ffcheck, mock_frames,
        mock_backend_factory, mock_write, mock_dedup, mock_enrich,
    ):
        mock_schema.return_value = _make_schema()
        mock_resolve.return_value = [
            MediaFile(path=Path("/fake/vid1.mp4"), media_type="video"),
            MediaFile(path=self.frame1, media_type="image"),
        ]
        mock_frames.return_value = [self.frame2]

        backend = MagicMock()
        backend.extract.side_effect = [
            [CANNED_BOOKS[0]],  # from video
            [CANNED_BOOKS[1]],  # from image
        ]
        mock_backend_factory.return_value = backend

        mock_write.return_value = {"json": self.output_dir / "books.json"}

        result = self._invoke_extract("/fake/dir")

        assert result.exit_code == 0
        assert "Found 2 media file(s)" in result.output
        assert backend.extract.call_count == 2

    # -- --json-only flag --

    @patch("framemine.cli.enrich_items")
    @patch("framemine.cli.deduplicate", side_effect=lambda items, **kw: items)
    @patch("framemine.cli.write_outputs")
    @patch("framemine.cli.create_backend")
    @patch("framemine.cli.resolve_input")
    @patch("framemine.cli.load_schema")
    def test_json_only_flag(
        self, mock_schema, mock_resolve, mock_backend_factory,
        mock_write, mock_dedup, mock_enrich,
    ):
        mock_schema.return_value = _make_schema()
        mock_resolve.return_value = [
            MediaFile(path=self.frame1, media_type="image"),
        ]

        backend = MagicMock()
        backend.extract.return_value = list(CANNED_BOOKS)
        mock_backend_factory.return_value = backend

        mock_write.return_value = {"json": self.output_dir / "books.json"}

        result = self._invoke_extract(str(self.frame1), extra_args=["--json-only"])

        assert result.exit_code == 0
        # Verify excel_output=False was passed
        _, kwargs = mock_write.call_args
        assert kwargs.get("excel_output") is False or (
            # positional check: write_outputs(items, path, columns=..., sheet_name=..., json_output=True, excel_output=False)
            mock_write.call_args
        )
        # More robust: inspect the actual keyword
        call_kwargs = mock_write.call_args
        # write_outputs is called with json_output=True, excel_output=not json_only
        assert call_kwargs.kwargs.get("excel_output") is False or call_kwargs[1].get("excel_output") is False

    # -- --no-enrich flag --

    @patch("framemine.cli.enrich_items")
    @patch("framemine.cli.deduplicate", side_effect=lambda items, **kw: items)
    @patch("framemine.cli.write_outputs")
    @patch("framemine.cli.create_backend")
    @patch("framemine.cli.resolve_input")
    @patch("framemine.cli.load_schema")
    def test_no_enrich_flag(
        self, mock_schema, mock_resolve, mock_backend_factory,
        mock_write, mock_dedup, mock_enrich,
    ):
        mock_schema.return_value = _make_schema(enrichment="books")
        mock_resolve.return_value = [
            MediaFile(path=self.frame1, media_type="image"),
        ]

        backend = MagicMock()
        backend.extract.return_value = list(CANNED_BOOKS)
        mock_backend_factory.return_value = backend

        mock_write.return_value = {"json": self.output_dir / "books.json"}

        result = self._invoke_extract(str(self.frame1), extra_args=["--no-enrich"])

        assert result.exit_code == 0
        mock_enrich.assert_not_called()

    # -- Enrichment called when schema has it --

    @patch("framemine.cli.enrich_items")
    @patch("framemine.cli.deduplicate", side_effect=lambda items, **kw: items)
    @patch("framemine.cli.write_outputs")
    @patch("framemine.cli.create_backend")
    @patch("framemine.cli.resolve_input")
    @patch("framemine.cli.load_schema")
    def test_enrichment_called_for_books_schema(
        self, mock_schema, mock_resolve, mock_backend_factory,
        mock_write, mock_dedup, mock_enrich,
    ):
        mock_schema.return_value = _make_schema(enrichment="books")
        mock_resolve.return_value = [
            MediaFile(path=self.frame1, media_type="image"),
        ]

        backend = MagicMock()
        backend.extract.return_value = list(CANNED_BOOKS)
        mock_backend_factory.return_value = backend

        mock_write.return_value = {"json": self.output_dir / "books.json"}

        result = self._invoke_extract(str(self.frame1))

        assert result.exit_code == 0
        mock_enrich.assert_called_once()
        # Verify the enrichment type matches schema
        enrich_args, enrich_kwargs = mock_enrich.call_args
        assert enrich_args[1] == "books"  # schema.enrichment passed as second positional arg

    # -- Enrichment NOT called when schema has no enrichment --

    @patch("framemine.cli.enrich_items")
    @patch("framemine.cli.deduplicate", side_effect=lambda items, **kw: items)
    @patch("framemine.cli.write_outputs")
    @patch("framemine.cli.create_backend")
    @patch("framemine.cli.resolve_input")
    @patch("framemine.cli.load_schema")
    def test_no_enrichment_for_recipes_schema(
        self, mock_schema, mock_resolve, mock_backend_factory,
        mock_write, mock_dedup, mock_enrich,
    ):
        mock_schema.return_value = _make_schema(
            name="recipes",
            display_name="Recipes & Cooking",
            enrichment=None,
            dedup_key=["name"],
            output_columns=["name", "cuisine", "difficulty"],
        )
        mock_resolve.return_value = [
            MediaFile(path=self.frame1, media_type="image"),
        ]

        backend = MagicMock()
        backend.extract.return_value = list(CANNED_RECIPES)
        mock_backend_factory.return_value = backend

        mock_write.return_value = {"json": self.output_dir / "recipes.json"}

        result = self._invoke_extract(str(self.frame1), schema="recipes")

        assert result.exit_code == 0
        mock_enrich.assert_not_called()

    # -- Source URL tagging --

    @patch("framemine.cli.enrich_items")
    @patch("framemine.cli.deduplicate", side_effect=lambda items, **kw: items)
    @patch("framemine.cli.write_outputs")
    @patch("framemine.cli.create_backend")
    @patch("framemine.cli.resolve_input")
    @patch("framemine.cli.load_schema")
    def test_source_url_tagging(
        self, mock_schema, mock_resolve, mock_backend_factory,
        mock_write, mock_dedup, mock_enrich,
    ):
        mock_schema.return_value = _make_schema()
        mock_resolve.return_value = [
            MediaFile(path=self.frame1, media_type="image", source_url="https://example.com/reel/123"),
        ]

        items = [{"title": "Test Book", "author": "Author"}]
        backend = MagicMock()
        backend.extract.return_value = items
        mock_backend_factory.return_value = backend

        mock_write.return_value = {"json": self.output_dir / "books.json"}

        result = self._invoke_extract(str(self.frame1))

        assert result.exit_code == 0
        # The items passed to write_outputs should have source set
        written_items = mock_write.call_args[0][0]
        assert written_items[0]["source"] == "https://example.com/reel/123"

    # -- Output file creation (integration-ish: use real write_outputs) --

    @patch("framemine.cli.enrich_items")
    @patch("framemine.cli.deduplicate", side_effect=lambda items, **kw: items)
    @patch("framemine.cli.create_backend")
    @patch("framemine.cli.resolve_input")
    @patch("framemine.cli.load_schema")
    def test_output_files_created(
        self, mock_schema, mock_resolve, mock_backend_factory,
        mock_dedup, mock_enrich,
    ):
        """With real write_outputs, verify JSON and Excel files appear on disk."""
        mock_schema.return_value = _make_schema()
        mock_resolve.return_value = [
            MediaFile(path=self.frame1, media_type="image"),
        ]

        backend = MagicMock()
        backend.extract.return_value = list(CANNED_BOOKS)
        mock_backend_factory.return_value = backend

        result = self._invoke_extract(str(self.frame1))

        assert result.exit_code == 0
        json_file = self.output_dir / "books.json"
        xlsx_file = self.output_dir / "books.xlsx"
        assert json_file.exists()
        assert xlsx_file.exists()

        # Validate JSON content
        data = json.loads(json_file.read_text())
        assert len(data) == 2
        assert data[0]["title"] == "The Great Gatsby"

    @patch("framemine.cli.enrich_items")
    @patch("framemine.cli.deduplicate", side_effect=lambda items, **kw: items)
    @patch("framemine.cli.create_backend")
    @patch("framemine.cli.resolve_input")
    @patch("framemine.cli.load_schema")
    def test_json_only_no_excel_file(
        self, mock_schema, mock_resolve, mock_backend_factory,
        mock_dedup, mock_enrich,
    ):
        """With --json-only and real write_outputs, only JSON is created."""
        mock_schema.return_value = _make_schema()
        mock_resolve.return_value = [
            MediaFile(path=self.frame1, media_type="image"),
        ]

        backend = MagicMock()
        backend.extract.return_value = list(CANNED_BOOKS)
        mock_backend_factory.return_value = backend

        result = self._invoke_extract(str(self.frame1), extra_args=["--json-only"])

        assert result.exit_code == 0
        assert (self.output_dir / "books.json").exists()
        assert not (self.output_dir / "books.xlsx").exists()

    # -- Custom output name --

    @patch("framemine.cli.enrich_items")
    @patch("framemine.cli.deduplicate", side_effect=lambda items, **kw: items)
    @patch("framemine.cli.create_backend")
    @patch("framemine.cli.resolve_input")
    @patch("framemine.cli.load_schema")
    def test_custom_output_name(
        self, mock_schema, mock_resolve, mock_backend_factory,
        mock_dedup, mock_enrich,
    ):
        mock_schema.return_value = _make_schema()
        mock_resolve.return_value = [
            MediaFile(path=self.frame1, media_type="image"),
        ]

        backend = MagicMock()
        backend.extract.return_value = list(CANNED_BOOKS)
        mock_backend_factory.return_value = backend

        result = self._invoke_extract(
            str(self.frame1),
            extra_args=["-o", "my_output", "--json-only"],
        )

        assert result.exit_code == 0
        assert (self.output_dir / "my_output.json").exists()
        assert not (self.output_dir / "books.json").exists()


# ---------------------------------------------------------------------------
# 4b. extract command — error cases
# ---------------------------------------------------------------------------

class TestExtractErrors:
    def setup_method(self):
        self.runner = CliRunner()

    @patch("framemine.cli.load_schema", side_effect=FileNotFoundError("Schema 'bogus' not found"))
    def test_missing_schema(self, mock_schema):
        result = self.runner.invoke(cli, ["extract", "/some/source", "-s", "bogus"])
        assert result.exit_code != 0
        assert "Schema 'bogus' not found" in result.output

    @patch("framemine.cli.load_schema", side_effect=ValueError("Malformed YAML"))
    def test_invalid_schema(self, mock_schema):
        result = self.runner.invoke(cli, ["extract", "/some/source", "-s", "bad"])
        assert result.exit_code != 0
        assert "Malformed YAML" in result.output

    @patch("framemine.cli.resolve_input", return_value=[])
    @patch("framemine.cli.load_schema")
    def test_no_media_files_found(self, mock_schema, mock_resolve):
        mock_schema.return_value = _make_schema()
        result = self.runner.invoke(cli, ["extract", "/empty/dir", "-s", "books"])
        assert result.exit_code != 0
        assert "No media files found" in result.output

    @patch("framemine.cli.resolve_input", side_effect=FileNotFoundError("Source path does not exist: /nope"))
    @patch("framemine.cli.load_schema")
    def test_source_not_found(self, mock_schema, mock_resolve):
        mock_schema.return_value = _make_schema()
        result = self.runner.invoke(cli, ["extract", "/nope", "-s", "books"])
        assert result.exit_code != 0
        assert "Source path does not exist" in result.output

    @patch("framemine.cli.resolve_input", side_effect=RuntimeError("yt-dlp is required"))
    @patch("framemine.cli.load_schema")
    def test_ytdlp_not_available(self, mock_schema, mock_resolve):
        mock_schema.return_value = _make_schema()
        result = self.runner.invoke(cli, ["extract", "https://example.com", "-s", "books"])
        assert result.exit_code != 0
        assert "yt-dlp is required" in result.output

    @patch("framemine.cli.create_backend", side_effect=RuntimeError("No API key configured"))
    @patch("framemine.cli.resolve_input")
    @patch("framemine.cli.load_schema")
    def test_ai_backend_creation_fails(self, mock_schema, mock_resolve, mock_backend):
        mock_schema.return_value = _make_schema()
        mock_resolve.return_value = [
            MediaFile(path=Path("/fake/img.jpg"), media_type="image"),
        ]
        result = self.runner.invoke(cli, ["extract", "/fake/img.jpg", "-s", "books"])
        assert result.exit_code != 0
        assert "No API key configured" in result.output

    def test_bad_config_path(self, tmp_path):
        result = self.runner.invoke(cli, [
            "extract", "/some/source", "-s", "books",
            "-c", str(tmp_path / "nonexistent.yaml"),
        ])
        assert result.exit_code != 0
        assert "Config file not found" in result.output

    def test_missing_required_schema_option(self):
        result = self.runner.invoke(cli, ["extract", "/some/source"])
        assert result.exit_code != 0
        assert "Missing option" in result.output or "required" in result.output.lower()

    # -- Video with ffmpeg missing --

    @patch("framemine.cli.enrich_items")
    @patch("framemine.cli.deduplicate", side_effect=lambda items, **kw: items)
    @patch("framemine.cli.write_outputs")
    @patch("framemine.cli.create_backend")
    @patch("framemine.cli.check_ffmpeg", return_value=False)
    @patch("framemine.cli.resolve_input")
    @patch("framemine.cli.load_schema")
    def test_video_skipped_when_ffmpeg_missing(
        self, mock_schema, mock_resolve, mock_ffcheck,
        mock_backend_factory, mock_write, mock_dedup, mock_enrich,
    ):
        """When ffmpeg is missing and all files are video, extraction yields no items."""
        mock_schema.return_value = _make_schema()
        mock_resolve.return_value = [
            MediaFile(path=Path("/fake/video.mp4"), media_type="video"),
        ]

        backend = MagicMock()
        mock_backend_factory.return_value = backend

        result = self.runner.invoke(cli, [
            "extract", "/fake/dir", "-s", "books",
        ])

        # No items => exit 1 with "No items extracted"
        assert result.exit_code != 0
        assert "skipped" in result.output or "No items extracted" in result.output
        backend.extract.assert_not_called()

    # -- Backend returns empty list --

    @patch("framemine.cli.create_backend")
    @patch("framemine.cli.resolve_input")
    @patch("framemine.cli.load_schema")
    def test_no_items_extracted(self, mock_schema, mock_resolve, mock_backend_factory):
        mock_schema.return_value = _make_schema()
        mock_resolve.return_value = [
            MediaFile(path=Path("/fake/img.jpg"), media_type="image"),
        ]

        backend = MagicMock()
        backend.extract.return_value = []
        mock_backend_factory.return_value = backend

        result = self.runner.invoke(cli, ["extract", "/fake/img.jpg", "-s", "books"])

        assert result.exit_code != 0
        assert "No items extracted" in result.output


# ---------------------------------------------------------------------------
# 5. Config loading
# ---------------------------------------------------------------------------

class TestLoadConfig:
    def test_explicit_config_path(self, tmp_path):
        cfg_file = tmp_path / "my_config.yaml"
        cfg_file.write_text(yaml.dump({"ai": {"backend": "openai"}}))

        config = _load_config(str(cfg_file))
        assert config["ai"]["backend"] == "openai"

    def test_explicit_path_not_found(self, tmp_path):
        with pytest.raises(Exception) as exc_info:
            _load_config(str(tmp_path / "nope.yaml"))
        assert "Config file not found" in str(exc_info.value)

    def test_empty_yaml_returns_empty_dict(self, tmp_path):
        cfg_file = tmp_path / "empty.yaml"
        cfg_file.write_text("")
        config = _load_config(str(cfg_file))
        assert config == {}

    def test_no_config_files_returns_empty_dict(self, tmp_path, monkeypatch):
        """When no config file exists anywhere, returns {}."""
        # Patch CONFIG_SEARCH_PATHS to non-existent locations
        monkeypatch.setattr(
            "framemine.cli.CONFIG_SEARCH_PATHS",
            [tmp_path / "a.yaml", tmp_path / "b.yaml"],
        )
        config = _load_config()
        assert config == {}

    def test_fallback_to_cwd_config(self, tmp_path, monkeypatch):
        """Finds framemine.yaml in current directory via CONFIG_SEARCH_PATHS."""
        cwd_config = tmp_path / "framemine.yaml"
        cwd_config.write_text(yaml.dump({"ai": {"backend": "gemini"}}))

        monkeypatch.setattr(
            "framemine.cli.CONFIG_SEARCH_PATHS",
            [cwd_config, tmp_path / "nope.yaml"],
        )
        config = _load_config()
        assert config["ai"]["backend"] == "gemini"

    def test_first_search_path_wins(self, tmp_path, monkeypatch):
        """If multiple config files exist, the first match wins."""
        first = tmp_path / "first.yaml"
        second = tmp_path / "second.yaml"
        first.write_text(yaml.dump({"ai": {"backend": "first"}}))
        second.write_text(yaml.dump({"ai": {"backend": "second"}}))

        monkeypatch.setattr(
            "framemine.cli.CONFIG_SEARCH_PATHS",
            [first, second],
        )
        config = _load_config()
        assert config["ai"]["backend"] == "first"

    def test_config_with_nested_keys(self, tmp_path):
        cfg = {
            "ai": {"backend": "gemini", "gemini": {"api_key": "test-key"}},
            "download": {"max_resolution": 480},
            "extraction": {"scene_threshold": 0.5, "max_keyframes": 10},
        }
        cfg_file = tmp_path / "full.yaml"
        cfg_file.write_text(yaml.dump(cfg))

        config = _load_config(str(cfg_file))
        assert config["ai"]["gemini"]["api_key"] == "test-key"
        assert config["download"]["max_resolution"] == 480
        assert config["extraction"]["scene_threshold"] == 0.5


# ---------------------------------------------------------------------------
# 6. extract with config file
# ---------------------------------------------------------------------------

class TestExtractWithConfig:
    @patch("framemine.cli.enrich_items")
    @patch("framemine.cli.deduplicate", side_effect=lambda items, **kw: items)
    @patch("framemine.cli.write_outputs")
    @patch("framemine.cli.create_backend")
    @patch("framemine.cli.resolve_input")
    @patch("framemine.cli.load_schema")
    def test_config_passed_to_backend(
        self, mock_schema, mock_resolve, mock_backend_factory,
        mock_write, mock_dedup, mock_enrich, tmp_path,
    ):
        """Verify ai config section is passed to create_backend."""
        cfg_file = tmp_path / "test_config.yaml"
        cfg_file.write_text(yaml.dump({
            "ai": {"backend": "openai", "openai": {"api_key": "sk-test"}},
        }))

        mock_schema.return_value = _make_schema()

        frame = _make_image(tmp_path / "img.jpg")
        mock_resolve.return_value = [
            MediaFile(path=frame, media_type="image"),
        ]

        backend = MagicMock()
        backend.extract.return_value = list(CANNED_BOOKS)
        mock_backend_factory.return_value = backend

        mock_write.return_value = {"json": tmp_path / "books.json"}

        output_dir = tmp_path / "out"
        output_dir.mkdir()

        runner = CliRunner()
        result = runner.invoke(cli, [
            "extract", str(frame), "-s", "books",
            "-c", str(cfg_file),
            "--output-dir", str(output_dir),
        ], catch_exceptions=False)

        assert result.exit_code == 0
        # create_backend receives the ai section of config
        mock_backend_factory.assert_called_once_with(
            {"backend": "openai", "openai": {"api_key": "sk-test"}}
        )


# ---------------------------------------------------------------------------
# 7. Verbose flag
# ---------------------------------------------------------------------------

class TestVerboseFlag:
    @patch("framemine.cli.get_schema_info", return_value=[])
    def test_verbose_flag_accepted(self, mock_info):
        result = CliRunner().invoke(cli, ["-v", "schemas"])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# 8. Deduplication integration
# ---------------------------------------------------------------------------

class TestExtractDedup:
    @patch("framemine.cli.enrich_items")
    @patch("framemine.cli.write_outputs")
    @patch("framemine.cli.create_backend")
    @patch("framemine.cli.resolve_input")
    @patch("framemine.cli.load_schema")
    def test_dedup_removes_duplicates(
        self, mock_schema, mock_resolve, mock_backend_factory,
        mock_write, mock_enrich, tmp_path,
    ):
        """With real deduplicate, duplicate items are collapsed."""
        mock_schema.return_value = _make_schema()

        frame = _make_image(tmp_path / "img.jpg")
        mock_resolve.return_value = [
            MediaFile(path=frame, media_type="image"),
        ]

        # Return duplicates from AI
        duped = [
            {"title": "The Great Gatsby", "author": "Fitzgerald", "type": "book"},
            {"title": "The Great Gatsby", "author": "F. Scott Fitzgerald", "type": "book"},
            {"title": "Sapiens", "author": "Harari", "type": "book"},
        ]
        backend = MagicMock()
        backend.extract.return_value = duped
        mock_backend_factory.return_value = backend

        mock_write.return_value = {"json": tmp_path / "books.json"}

        output_dir = tmp_path / "out"
        output_dir.mkdir()

        result = CliRunner().invoke(cli, [
            "extract", str(frame), "-s", "books",
            "--output-dir", str(output_dir),
            "--json-only",
        ], catch_exceptions=False)

        assert result.exit_code == 0
        # After dedup on title, should be 2 unique items
        assert "After dedup: 2" in result.output


# ---------------------------------------------------------------------------
# 9. Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_no_arguments(self):
        result = CliRunner().invoke(cli, [])
        # Click groups return exit code 0 or 2 for bare invocation (shows help/usage)
        assert result.exit_code in (0, 2)
        assert "Extract structured data" in result.output or "Usage" in result.output

    def test_unknown_command(self):
        result = CliRunner().invoke(cli, ["nonexistent"])
        assert result.exit_code != 0
        assert "No such command" in result.output

    @patch("framemine.cli.enrich_items")
    @patch("framemine.cli.deduplicate", side_effect=lambda items, **kw: items)
    @patch("framemine.cli.write_outputs")
    @patch("framemine.cli.create_backend")
    @patch("framemine.cli.get_frames", return_value=[])
    @patch("framemine.cli.check_ffmpeg", return_value=True)
    @patch("framemine.cli.resolve_input")
    @patch("framemine.cli.load_schema")
    def test_video_with_no_frames_extracted(
        self, mock_schema, mock_resolve, mock_ffcheck, mock_frames,
        mock_backend_factory, mock_write, mock_dedup, mock_enrich,
    ):
        """If get_frames returns [], the video is skipped gracefully."""
        mock_schema.return_value = _make_schema()
        mock_resolve.return_value = [
            MediaFile(path=Path("/fake/video.mp4"), media_type="video"),
        ]

        backend = MagicMock()
        mock_backend_factory.return_value = backend

        result = CliRunner().invoke(cli, [
            "extract", "/fake/dir", "-s", "books",
        ])

        assert result.exit_code != 0
        assert "no frames extracted" in result.output or "No items extracted" in result.output
        backend.extract.assert_not_called()
