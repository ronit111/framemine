"""Shared test fixtures for framemine."""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

SAMPLES_DIR = Path(__file__).parent.parent / "samples"
PROJECT_ROOT = Path(__file__).parent.parent


@pytest.fixture
def sample_video():
    """Path to sample video file for integration tests."""
    path = SAMPLES_DIR / "book_reel_sample.mp4"
    if not path.exists():
        pytest.skip("Sample video not available")
    return path


@pytest.fixture
def sample_frames(tmp_path):
    """Create dummy frame images for unit tests."""
    from PIL import Image

    frames = []
    for i in range(3):
        frame = tmp_path / f"frame_{i:03d}.jpg"
        img = Image.new("RGB", (100, 100), color=(i * 80, i * 80, i * 80))
        img.save(frame)
        frames.append(frame)
    return frames


@pytest.fixture
def sample_media_dir(tmp_path):
    """Create a directory with mixed media files for testing."""
    from PIL import Image

    # Videos (empty files, just for path detection)
    (tmp_path / "video1.mp4").write_bytes(b"\x00" * 100)
    (tmp_path / "video2.mkv").write_bytes(b"\x00" * 100)

    # Images
    for name in ["img1.jpg", "img2.png"]:
        img = Image.new("RGB", (50, 50), color="red")
        img.save(tmp_path / name)

    # Non-media files (should be ignored)
    (tmp_path / "notes.txt").write_text("not media")
    (tmp_path / "data.json").write_text("{}")

    return tmp_path


@pytest.fixture
def mock_ai_response_books():
    """Canned AI response for books schema."""
    return [
        {"title": "The Great Gatsby", "author": "F. Scott Fitzgerald", "type": "book"},
        {"title": "To Kill a Mockingbird", "author": "Harper Lee", "type": "book"},
        {"title": "Sapiens", "author": "Yuval Noah Harari", "type": "book"},
    ]


@pytest.fixture
def mock_ai_response_recipes():
    """Canned AI response for recipes schema."""
    return [
        {"name": "Pasta Carbonara", "cuisine": "Italian", "difficulty": "medium"},
        {"name": "Pad Thai", "cuisine": "Thai", "difficulty": "medium"},
    ]


@pytest.fixture
def mock_ai_backend(mock_ai_response_books):
    """A mock AI backend that returns canned book responses."""
    backend = MagicMock()
    backend.extract.return_value = mock_ai_response_books
    return backend


@pytest.fixture
def config_example():
    """Load the example config file as a dict."""
    import yaml

    config_path = PROJECT_ROOT / "config.example.yaml"
    with open(config_path) as f:
        return yaml.safe_load(f)
