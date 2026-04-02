"""Tests for LLM picker functions."""

from contextlib import contextmanager
from unittest.mock import patch

import pytest

from intentkit.models.llm_picker import (
    pick_default_model,
    pick_long_context_model,
    pick_summarize_model,
)


@contextmanager
def mock_llm_config(**keys):
    """Mock the config object in both llm and llm_picker modules.

    All API keys default to None unless explicitly provided.
    """
    defaults = dict(
        anthropic_api_key=None,
        google_api_key=None,
        openai_api_key=None,
        openrouter_api_key=None,
        xai_api_key=None,
        deepseek_api_key=None,
        minimax_api_key=None,
        openai_compatible_api_key=None,
        openai_compatible_base_url=None,
        openai_compatible_model=None,
        openai_compatible_model_lite=None,
    )
    defaults.update(keys)
    with (
        patch("intentkit.models.llm.config") as m1,
        patch("intentkit.models.llm_picker.config") as m2,
    ):
        for k, v in defaults.items():
            setattr(m1, k, v)
            setattr(m2, k, v)
        yield


# ── pick_summarize_model ─────────────────────────────────────────────


def test_pick_summarize_model_raises_when_none():
    with mock_llm_config():
        with pytest.raises(RuntimeError):
            pick_summarize_model()


def test_pick_summarize_model_prefers_anthropic_when_available():
    with mock_llm_config(
        anthropic_api_key="anthropic-key",
        google_api_key="google-key",
        openai_api_key="openai-key",
    ):
        assert pick_summarize_model() == "claude-sonnet-4-6"


def test_pick_summarize_model_openai_when_only_openai_is_available():
    with mock_llm_config(openai_api_key="openai-key"):
        assert pick_summarize_model() == "gpt-5.4-mini"


def test_pick_summarize_model_xai_when_higher_priority_providers_are_absent():
    with mock_llm_config(xai_api_key="xai-key", deepseek_api_key="deepseek-key"):
        assert pick_summarize_model() == "grok-4-1-fast-non-reasoning"


# ── pick_default_model ───────────────────────────────────────────────


def test_pick_default_model_prefers_anthropic_when_available():
    with mock_llm_config(
        anthropic_api_key="anthropic-key",
        google_api_key="google-key",
        openai_api_key="openai-key",
    ):
        assert pick_default_model() == "claude-sonnet-4-6"


def test_pick_default_model_uses_openrouter_variant_when_openrouter_is_only_option():
    with mock_llm_config(openrouter_api_key="openrouter-key"):
        assert pick_default_model() == "minimax/minimax-m2.7"


def test_pick_default_model_uses_google_before_openai():
    with mock_llm_config(google_api_key="google-key", openai_api_key="openai-key"):
        assert pick_default_model() == "google/gemini-3-flash-preview"


def test_pick_default_model_falls_to_deepseek_when_needed():
    with mock_llm_config(deepseek_api_key="deepseek-key"):
        assert pick_default_model() == "deepseek-chat"


def test_pick_default_model_fallback_when_none():
    with mock_llm_config():
        assert pick_default_model() == "gpt-5.4-mini"


# ── pick_long_context_model ──────────────────────────────────────────


def test_pick_long_context_model_returns_expected_google_model():
    with mock_llm_config(google_api_key="google-key"):
        assert pick_long_context_model() == "gemini-3.1-flash-lite-preview"


def test_pick_long_context_model_raises_when_none():
    with mock_llm_config():
        with pytest.raises(RuntimeError):
            pick_long_context_model()
