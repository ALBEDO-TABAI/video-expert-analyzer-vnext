from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import openclaw_batch_probe


def _write_models_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def test_load_provider_catalog_accepts_valid_schema(tmp_path: Path) -> None:
    models_json = tmp_path / "models.json"
    _write_models_json(
        models_json,
        {
            "providers": {
                "acme": {
                    "baseUrl": "https://api.example.com",
                    "models": [{"id": "alpha"}],
                }
            }
        },
    )
    providers = openclaw_batch_probe.load_provider_catalog(models_json)
    assert "acme" in providers


def test_load_provider_catalog_rejects_missing_base_url(tmp_path: Path) -> None:
    models_json = tmp_path / "models.json"
    _write_models_json(
        models_json,
        {"providers": {"acme": {"models": [{"id": "alpha"}]}}},
    )
    with pytest.raises(ValueError, match="baseUrl"):
        openclaw_batch_probe.load_provider_catalog(models_json)


def test_load_provider_catalog_rejects_empty_models(tmp_path: Path) -> None:
    models_json = tmp_path / "models.json"
    _write_models_json(
        models_json,
        {
            "providers": {
                "acme": {"baseUrl": "https://x", "models": []},
            }
        },
    )
    with pytest.raises(ValueError, match="models"):
        openclaw_batch_probe.load_provider_catalog(models_json)


def test_openclaw_root_env_var_overrides_default(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OPENCLAW_ROOT", str(tmp_path))
    assert openclaw_batch_probe._default_openclaw_root() == tmp_path


def test_openclaw_models_json_env_var_overrides_default(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    custom = tmp_path / "custom-models.json"
    monkeypatch.setenv("OPENCLAW_MODELS_JSON", str(custom))
    assert openclaw_batch_probe._default_models_json() == custom
