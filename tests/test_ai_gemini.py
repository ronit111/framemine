"""Tests for Gemini AI backend and ModelRotator."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from framemine.ai.base import AIBackend
from framemine.ai.gemini import DEFAULT_MODELS, GeminiBackend, ModelRotator


# --- ModelRotator tests ---


def test_model_rotator_initial_state():
    models = ["model-a", "model-b", "model-c"]
    rotator = ModelRotator(models)
    assert rotator.current == "model-a"
    assert rotator.exhausted == set()
    assert rotator.models == models


def test_model_rotator_rotate_cycles():
    models = ["model-a", "model-b", "model-c"]
    rotator = ModelRotator(models)

    assert rotator.current == "model-a"
    assert rotator.rotate() is True
    assert rotator.current == "model-b"
    assert rotator.rotate() is True
    assert rotator.current == "model-c"


def test_model_rotator_exhausted_all():
    models = ["model-a", "model-b"]
    rotator = ModelRotator(models)

    assert rotator.rotate() is True  # exhausts a, moves to b
    assert rotator.rotate() is False  # exhausts b, none left


def test_model_rotator_reset():
    models = ["model-a", "model-b"]
    rotator = ModelRotator(models)

    rotator.rotate()  # exhausts a
    rotator.rotate()  # exhausts b
    assert rotator.exhausted == {"model-a", "model-b"}

    rotator.reset()
    assert rotator.exhausted == set()
    # After reset, can rotate again
    assert rotator.rotate() is True


# --- API key resolution ---


def test_gemini_resolve_api_key_from_env():
    with patch.dict("os.environ", {"GEMINI_API_KEY": "test-key-123"}):
        key = GeminiBackend._resolve_api_key()
        assert key == "test-key-123"


def test_gemini_resolve_api_key_missing():
    with patch.dict("os.environ", {}, clear=True):
        with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
            GeminiBackend._resolve_api_key()


# --- GeminiBackend.extract ---


def test_gemini_extract_success(sample_frames):
    """Mock genai.Client, verify correct model and content sent."""
    expected = [{"title": "Test Book", "author": "Author"}]

    mock_response = MagicMock()
    mock_response.text = json.dumps(expected)

    mock_client_instance = MagicMock()
    mock_client_instance.models.generate_content.return_value = mock_response

    with patch("google.genai.Client", return_value=mock_client_instance) as mock_client_cls:
        backend = GeminiBackend(api_key="fake-key", models=["gemini-2.0-flash"])
        result = backend.extract(sample_frames, "Extract books")

    assert result == expected
    mock_client_cls.assert_called_once_with(api_key="fake-key")

    call_kwargs = mock_client_instance.models.generate_content.call_args
    assert call_kwargs.kwargs["model"] == "gemini-2.0-flash"
    # contents should be [prompt] + images
    contents = call_kwargs.kwargs["contents"]
    assert contents[0] == "Extract books"
    assert len(contents) == 1 + len(sample_frames)


def test_gemini_extract_rate_limit_rotates(sample_frames):
    """Mock 429 error, verify rotation happens."""
    expected = [{"title": "Book"}]
    mock_response = MagicMock()
    mock_response.text = json.dumps(expected)

    rate_limit_error = Exception("429 Resource has been exhausted")

    mock_client_instance = MagicMock()
    mock_client_instance.models.generate_content.side_effect = [
        rate_limit_error,
        mock_response,
    ]

    with patch("google.genai.Client", return_value=mock_client_instance), patch(
        "framemine.ai.gemini.time.sleep"
    ):
        backend = GeminiBackend(
            api_key="fake-key",
            models=["model-a", "model-b"],
            max_retries_per_model=3,
        )
        result = backend.extract(sample_frames, "Extract")

    assert result == expected
    # Should have been called twice (first fails, second succeeds)
    assert mock_client_instance.models.generate_content.call_count == 2

    # Second call should use the rotated model
    second_call = mock_client_instance.models.generate_content.call_args_list[1]
    assert second_call.kwargs["model"] == "model-b"


def test_gemini_extract_all_models_exhausted_waits_and_resets(sample_frames):
    """Verify backoff + reset behavior when all models exhausted."""
    expected = [{"title": "Book"}]
    mock_response = MagicMock()
    mock_response.text = json.dumps(expected)

    rate_limit_error = Exception("RESOURCE_EXHAUSTED")

    # Two models, both fail with 429, then after reset the first succeeds
    mock_client_instance = MagicMock()
    mock_client_instance.models.generate_content.side_effect = [
        rate_limit_error,  # model-a fails
        rate_limit_error,  # model-b fails (all exhausted -> wait + reset)
        mock_response,  # model-b succeeds after reset
    ]

    with patch("google.genai.Client", return_value=mock_client_instance), patch(
        "framemine.ai.gemini.time.sleep"
    ) as mock_sleep:
        backend = GeminiBackend(
            api_key="fake-key",
            models=["model-a", "model-b"],
            delay_seconds=4.0,
            max_retries_per_model=3,
        )
        result = backend.extract(sample_frames, "Extract")

    assert result == expected
    # Verify sleep was called for backoff (at least once for the exhaustion wait)
    assert mock_sleep.call_count >= 1


# --- parse_response tests ---


def test_parse_response_clean_json():
    data = [{"title": "Book A"}, {"title": "Book B"}]
    assert AIBackend.parse_response(json.dumps(data)) == data


def test_parse_response_fenced_json():
    data = [{"title": "Book A"}]
    text = f"```json\n{json.dumps(data)}\n```"
    assert AIBackend.parse_response(text) == data


def test_parse_response_malformed():
    assert AIBackend.parse_response("this is not json at all {broken") == []


def test_parse_response_empty():
    assert AIBackend.parse_response("") == []
    assert AIBackend.parse_response("   ") == []
