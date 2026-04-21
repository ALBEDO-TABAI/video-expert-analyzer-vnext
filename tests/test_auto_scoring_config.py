"""Failure-path coverage for auto-scoring config + models.json discovery.

Why: the happy path is exercised end-to-end via auto_score_scenes integration
tests, but the resolution layer (find_models_json_candidates +
resolve_auto_scoring_config) had no direct tests for missing/empty/corrupt
inputs — exactly where regressions are easiest to introduce.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import ai_analyzer
import openclaw_batch_probe


_AUTO_SCORING_ENV_VARS = (
    "VIDEO_ANALYZER_API_KEY",
    "VIDEO_ANALYZER_MODEL",
    "VIDEO_ANALYZER_PROVIDER",
    "VIDEO_ANALYZER_API_STYLE",
    "VIDEO_ANALYZER_BASE_URL",
    "OPENAI_API_KEY",
    "OPENAI_MODEL",
    "OPENAI_BASE_URL",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_MODEL",
    "ANTHROPIC_BASE_URL",
)


@pytest.fixture(autouse=True)
def _clean_auto_scoring_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip every env var that could mask the failure paths under test."""
    for name in _AUTO_SCORING_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def _stub_settings(
    monkeypatch: pytest.MonkeyPatch,
    *,
    models_json_path: str = "",
    preferred_model: str = "kcode/K2.6-code-preview",
    fallback_models: List[str] | None = None,
    max_workers: int = 4,
) -> List[Dict[str, Any]]:
    """Replace _load_auto_scoring_settings with a controllable fake.

    Returns a list that captures save_config calls so tests can assert
    that discovery results get persisted back to the user config.
    """
    save_calls: List[Dict[str, Any]] = []
    auto_scoring = {
        "models_json_path": models_json_path,
        "preferred_model": preferred_model,
        "fallback_models": list(fallback_models or []),
        "max_workers": max_workers,
    }
    config = {"auto_scoring": dict(auto_scoring)}

    def fake_save(payload: Dict[str, Any]) -> None:
        save_calls.append(payload)

    def fake_load_settings():
        # Return fresh copies so the function under test can mutate without
        # bleeding state between calls.
        return dict(config), dict(auto_scoring), fake_save

    monkeypatch.setattr(ai_analyzer, "_load_auto_scoring_settings", fake_load_settings)
    return save_calls


# ── find_models_json_candidates ─────────────────────────────────────────


def test_find_models_json_candidates_returns_empty_when_root_missing(tmp_path: Path) -> None:
    nonexistent = tmp_path / "does-not-exist"
    assert openclaw_batch_probe.find_models_json_candidates(nonexistent) == []


def test_find_models_json_candidates_returns_empty_when_agents_dir_has_no_models(tmp_path: Path) -> None:
    agents = tmp_path / "agents" / "main" / "agent"
    agents.mkdir(parents=True)
    # Agent dir exists but no models.json — discovery should yield nothing
    # rather than blowing up.
    assert openclaw_batch_probe.find_models_json_candidates(tmp_path) == []


# ── resolve_auto_scoring_config: failure dict ───────────────────────────


def test_resolve_auto_scoring_config_returns_error_dict_when_nothing_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_settings(monkeypatch)
    monkeypatch.setattr(
        "openclaw_batch_probe.find_models_json_candidates",
        lambda *_args, **_kwargs: [],
    )

    result = ai_analyzer.resolve_auto_scoring_config()

    assert ai_analyzer.AUTO_SCORING_MISSING_MESSAGE in result["error"]
    assert ai_analyzer.is_missing_auto_scoring_config_error(result["error"]) is True
    # Error path should still surface a usable max_workers so callers can size
    # their pool consistently.
    assert result["max_workers"] == 4


def test_resolve_auto_scoring_config_falls_back_to_discovery_when_configured_path_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A stale models_json_path in user config must not block fresh discovery."""
    discovered = tmp_path / "discovered" / "models.json"
    discovered.parent.mkdir(parents=True)
    discovered.write_text(json.dumps({"providers": {}}), encoding="utf-8")

    save_calls = _stub_settings(monkeypatch, models_json_path=str(tmp_path / "missing.json"))
    monkeypatch.setattr(
        "openclaw_batch_probe.find_models_json_candidates",
        lambda *_args, **_kwargs: [discovered],
    )

    result = ai_analyzer.resolve_auto_scoring_config()

    assert result["config_source"] == "openclaw"
    assert result["models_json_path"] == str(discovered.resolve())
    # Discovered path should be persisted back so future runs skip discovery.
    assert save_calls and save_calls[0]["auto_scoring"]["models_json_path"] == str(discovered.resolve())


def test_resolve_auto_scoring_config_uses_configured_path_when_it_exists(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    configured = tmp_path / "configured" / "models.json"
    configured.parent.mkdir(parents=True)
    configured.write_text(json.dumps({"providers": {}}), encoding="utf-8")

    _stub_settings(monkeypatch, models_json_path=str(configured))
    # Discovery must NOT be invoked when the configured path is valid;
    # raise to force the test to fail loudly if it ever is.
    def _should_not_be_called(*_args, **_kwargs):  # pragma: no cover
        raise AssertionError("discovery must not run when configured path exists")

    monkeypatch.setattr(
        "openclaw_batch_probe.find_models_json_candidates", _should_not_be_called
    )

    result = ai_analyzer.resolve_auto_scoring_config()

    assert result["config_source"] == "openclaw"
    assert result["models_json_path"] == str(configured.resolve())


def test_resolve_auto_scoring_config_falls_back_to_env_when_no_openclaw(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_settings(monkeypatch)
    monkeypatch.setattr(
        "openclaw_batch_probe.find_models_json_candidates",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setenv("VIDEO_ANALYZER_API_KEY", "test-key")
    monkeypatch.setenv("VIDEO_ANALYZER_MODEL", "test-model")
    monkeypatch.setenv("VIDEO_ANALYZER_PROVIDER", "myprovider")

    result = ai_analyzer.resolve_auto_scoring_config()

    assert result["config_source"] == "env"
    assert result["preferred_model"] == "myprovider/test-model"
    assert "myprovider" in result["providers"]
    assert "error" not in result


# ── _resolve_env_auto_scoring_config ────────────────────────────────────


def test_resolve_env_returns_none_when_no_credentials_set() -> None:
    assert ai_analyzer._resolve_env_auto_scoring_config({"max_workers": 4}) is None


def test_resolve_env_prefers_video_analyzer_vars_over_openai(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When both VIDEO_ANALYZER_* and OPENAI_* are set, the explicit
    VIDEO_ANALYZER_* override must win (it's the documented escape hatch)."""
    monkeypatch.setenv("VIDEO_ANALYZER_API_KEY", "video-key")
    monkeypatch.setenv("VIDEO_ANALYZER_MODEL", "video-model")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.setenv("OPENAI_MODEL", "openai-model")

    result = ai_analyzer._resolve_env_auto_scoring_config({"max_workers": 2})

    assert result is not None
    assert result["preferred_model"] == "env/video-model"


def test_resolve_env_uses_openai_when_only_openai_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4o")

    result = ai_analyzer._resolve_env_auto_scoring_config({"max_workers": 2})

    assert result is not None
    assert result["preferred_model"] == "openai/gpt-4o"
    assert result["providers"]["openai"]["apiKey"] == "openai-key"


def test_resolve_env_uses_anthropic_when_only_anthropic_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ant-key")
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-x")

    result = ai_analyzer._resolve_env_auto_scoring_config({"max_workers": 2})

    assert result is not None
    assert result["preferred_model"] == "anthropic/claude-x"
    assert result["providers"]["anthropic"]["api"] == "anthropic-messages"


# ── load_provider_catalog: corrupt JSON ─────────────────────────────────


def test_load_provider_catalog_raises_on_corrupt_json(tmp_path: Path) -> None:
    bad = tmp_path / "models.json"
    bad.write_text("not valid json{{{", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        openclaw_batch_probe.load_provider_catalog(bad)


def test_load_provider_catalog_raises_when_providers_missing(tmp_path: Path) -> None:
    no_providers = tmp_path / "models.json"
    no_providers.write_text(json.dumps({"unrelated": {}}), encoding="utf-8")
    with pytest.raises(ValueError, match="providers"):
        openclaw_batch_probe.load_provider_catalog(no_providers)
