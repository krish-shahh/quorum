"""Shared pytest fixtures that prevent CI hangs when API keys are absent."""

import os

# Pin the test session to the default risk profile BEFORE any test module
# imports quorum.default_config. Otherwise the user's active ~/.quorum/profile.yaml
# (e.g. "scalp") would leak into DEFAULT_CONFIG and break tests that assert the
# conservative baseline (regime thresholds, correlation flag, etc.). Tests that
# specifically exercise a profile set QUORUM_PROFILE themselves.
os.environ["QUORUM_PROFILE"] = "default"

from unittest.mock import MagicMock, patch

import pytest


def pytest_configure(config):
    for marker in ("unit", "integration", "smoke"):
        config.addinivalue_line("markers", f"{marker}: {marker}-level tests")


_API_KEY_ENV_VARS = (
    "OPENAI_API_KEY",
    "GOOGLE_API_KEY",
    "ANTHROPIC_API_KEY",
    "XAI_API_KEY",
    "DEEPSEEK_API_KEY",
    "DASHSCOPE_API_KEY",
    "DASHSCOPE_CN_API_KEY",
    "ZHIPU_API_KEY",
    "ZHIPU_CN_API_KEY",
    "MINIMAX_API_KEY",
    "MINIMAX_CN_API_KEY",
    "OPENROUTER_API_KEY",
    "AZURE_OPENAI_API_KEY",
    "ALPHA_VANTAGE_API_KEY",
)


@pytest.fixture(autouse=True)
def _dummy_api_keys(monkeypatch):
    for env_var in _API_KEY_ENV_VARS:
        monkeypatch.setenv(env_var, os.environ.get(env_var, "placeholder"))


@pytest.fixture()
def mock_llm_client():
    client = MagicMock()
    client.get_llm.return_value = MagicMock()
    with patch(
        "quorum.llm_clients.factory.create_llm_client",
        return_value=client,
    ):
        yield client
