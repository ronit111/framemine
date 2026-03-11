"""Tests for OpenAI-compatible AI backend and factory."""

import base64
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from framemine.ai import create_backend
from framemine.ai.gemini import GeminiBackend
from framemine.ai.openai_compat import OpenAICompatBackend


# --- API key resolution ---


def test_openai_resolve_api_key_from_env():
    with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test-key"}):
        key = OpenAICompatBackend._resolve_api_key()
        assert key == "sk-test-key"


def test_openai_resolve_api_key_missing():
    with patch.dict("os.environ", {}, clear=True):
        with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
            OpenAICompatBackend._resolve_api_key()


# --- Image encoding ---


def test_openai_encode_image(tmp_path):
    content = b"fake image bytes for testing"
    img_path = tmp_path / "test.jpg"
    img_path.write_bytes(content)

    encoded = OpenAICompatBackend._encode_image(img_path)
    assert encoded == base64.b64encode(content).decode("utf-8")
    # Verify round-trip
    assert base64.b64decode(encoded) == content


# --- Message building ---


def test_openai_build_messages(sample_frames):
    backend = OpenAICompatBackend(api_key="sk-test", model="gpt-4o-mini")
    messages = backend._build_messages(sample_frames, "Describe these images")

    assert len(messages) == 1
    msg = messages[0]
    assert msg["role"] == "user"

    content = msg["content"]
    # First part is text prompt
    assert content[0]["type"] == "text"
    assert content[0]["text"] == "Describe these images"

    # Remaining parts are image_url entries
    assert len(content) == 1 + len(sample_frames)
    for i, part in enumerate(content[1:]):
        assert part["type"] == "image_url"
        assert part["image_url"]["url"].startswith("data:image/")
        assert ";base64," in part["image_url"]["url"]


# --- Extract ---


def test_openai_extract_success(sample_frames):
    expected = [{"title": "Test Book", "author": "Author"}]

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": json.dumps(expected)}}]
    }

    with patch("framemine.ai.openai_compat.requests.post", return_value=mock_resp) as mock_post:
        backend = OpenAICompatBackend(api_key="sk-test", model="gpt-4o-mini")
        result = backend.extract(sample_frames, "Extract books")

    assert result == expected
    mock_post.assert_called_once()

    call_kwargs = mock_post.call_args
    assert "chat/completions" in call_kwargs.args[0]
    assert call_kwargs.kwargs["headers"]["Authorization"] == "Bearer sk-test"
    body = call_kwargs.kwargs["json"]
    assert body["model"] == "gpt-4o-mini"


def test_openai_extract_retry_on_failure(sample_frames):
    expected = [{"title": "Book"}]

    mock_fail_resp = MagicMock()
    mock_fail_resp.raise_for_status.side_effect = Exception("500 Server Error")

    mock_ok_resp = MagicMock()
    mock_ok_resp.raise_for_status.return_value = None
    mock_ok_resp.json.return_value = {
        "choices": [{"message": {"content": json.dumps(expected)}}]
    }

    with patch(
        "framemine.ai.openai_compat.requests.post",
        side_effect=[mock_fail_resp, mock_ok_resp],
    ), patch("framemine.ai.openai_compat.time.sleep"):
        backend = OpenAICompatBackend(
            api_key="sk-test", model="gpt-4o-mini", max_retries=3
        )
        result = backend.extract(sample_frames, "Extract")

    assert result == expected


# --- Factory tests ---


def test_create_backend_gemini():
    with patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}):
        backend = create_backend({"backend": "gemini"})
        assert isinstance(backend, GeminiBackend)


def test_create_backend_openai():
    with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}):
        backend = create_backend({"backend": "openai"})
        assert isinstance(backend, OpenAICompatBackend)


def test_create_backend_unknown():
    with pytest.raises(ValueError, match="Unknown AI backend"):
        create_backend({"backend": "anthropic"})
