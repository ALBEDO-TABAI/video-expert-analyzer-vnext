"""Tests for pipeline_enhanced helper functions."""

import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import ai_analyzer
import pipeline_enhanced
from pipeline_enhanced import VideoAnalysisPipeline, sanitize_filename, generate_folder_name


# ── sanitize_filename ────────────────────────────────────────────────

def test_removes_illegal_characters():
    assert sanitize_filename('video: "best*of/all?') == "video bestofall"


def test_collapses_whitespace():
    assert sanitize_filename("  hello   world  ") == "hello world"


def test_truncates_long_name():
    long_name = "a" * 100
    assert len(sanitize_filename(long_name)) == 50


def test_custom_max_length():
    assert len(sanitize_filename("abcdefghij", max_length=5)) == 5


def test_empty_string_passes():
    assert sanitize_filename("") == ""


def test_unicode_preserved():
    assert sanitize_filename("视频分析-第1集") == "视频分析-第1集"


def test_backslash_removed():
    assert sanitize_filename("path\\to\\file") == "pathtofile"


def test_normalize_config_backfills_auto_scoring_defaults() -> None:
    config, updated = pipeline_enhanced._normalize_config(
        {
            "output_base_dir": "/tmp/demo",
            "first_run": False,
            "default_scene_threshold": 27.0,
        }
    )

    assert config["auto_scoring"]["max_workers"] == 4
    assert config["auto_scoring"]["preferred_model"] == "kcode/K2.6-code-preview"
    assert updated is True


def test_normalize_config_migrates_legacy_default_max_workers_to_lower_default() -> None:
    config, updated = pipeline_enhanced._normalize_config(
        {
            "output_base_dir": "/tmp/demo",
            "first_run": False,
            "default_scene_threshold": 27.0,
            "auto_scoring": {
                "models_json_path": "",
                "preferred_model": "kcode/K2.6-code-preview",
                "fallback_models": [
                    "zai/GLM-5V-Turbo",
                    "novacode-openai/gpt-5.4",
                ],
                "max_workers": 10,
            },
        }
    )

    assert config["auto_scoring"]["max_workers"] == 4
    assert updated is True


# ── generate_folder_name ────────────────────────────────────────────

def test_folder_name_with_uploader_and_title():
    info = {"title": "Test Video", "uploader": "TestChannel"}
    name = generate_folder_name(info, "vid123")
    assert "TestChannel" in name
    assert "Test Video" in name


def test_folder_name_title_only():
    info = {"title": "Solo Title"}
    name = generate_folder_name(info, "vid456")
    assert "Solo Title" in name


def test_folder_name_truncates_long():
    info = {"title": "A" * 200}
    name = generate_folder_name(info, "vid789")
    assert len(name) <= 60


def test_prepare_next_batch_uses_pipeline_openclaw_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipeline = VideoAnalysisPipeline.__new__(VideoAnalysisPipeline)
    pipeline.scores_path = tmp_path / "scene_scores.json"
    pipeline.scores_path.write_text("{}", encoding="utf-8")
    pipeline.video_output_dir = tmp_path
    pipeline.run_state_path = tmp_path / "run_state.json"
    pipeline.run_state_path.write_text(
        json.dumps({"next_batch": {"batch_id": "batch-001"}}, ensure_ascii=False),
        encoding="utf-8",
    )
    pipeline.results = {"steps_completed": []}
    pipeline.openclaw_mode = True
    pipeline._mark_step_complete = lambda *args, **kwargs: None

    captured: dict[str, object] = {}

    def fake_auto_score_scenes(*args, **kwargs):
        captured.update(kwargs)
        return {}

    monkeypatch.setattr(sys.modules["ai_analyzer"], "auto_score_scenes", fake_auto_score_scenes)

    next_batch = pipeline._step_prepare_next_batch({"scene_count": 0})

    assert next_batch == {"batch_id": "batch-001"}
    assert captured["openclaw_mode"] is True
