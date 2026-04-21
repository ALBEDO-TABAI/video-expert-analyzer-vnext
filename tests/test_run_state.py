"""Tests for run_state: load, save, mark_stage, validation."""

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from run_state import default_run_state, load_run_state, save_run_state, mark_stage


def test_default_run_state_structure():
    state = default_run_state()
    assert state["version"] == "vnext"
    assert state["status"] == "running"
    assert state["current_stage"] == "prepare"
    assert isinstance(state["completed_stages"], list)
    assert state["total_scenes"] == 0
    assert state["coverage_ratio"] == 0.0
    assert state["can_finalize"] is False
    assert "verification" in state


def _assert_state_matches_default(got: dict, expected: dict) -> None:
    """Compare states ignoring updated_at (timestamps always differ)."""
    got_copy = {k: v for k, v in got.items() if k != "updated_at"}
    exp_copy = {k: v for k, v in expected.items() if k != "updated_at"}
    assert got_copy == exp_copy


def test_load_missing_file_returns_default(tmp_path: Path):
    state = load_run_state(tmp_path / "nonexistent.json")
    _assert_state_matches_default(state, default_run_state())


def test_load_corrupt_json_returns_default(tmp_path: Path):
    bad_file = tmp_path / "bad_state.json"
    bad_file.write_text("not valid json{{{", encoding="utf-8")
    state = load_run_state(bad_file)
    _assert_state_matches_default(state, default_run_state())


def test_load_non_dict_returns_default(tmp_path: Path):
    arr_file = tmp_path / "arr_state.json"
    arr_file.write_text("[1, 2, 3]", encoding="utf-8")
    state = load_run_state(arr_file)
    _assert_state_matches_default(state, default_run_state())


def test_save_and_load_roundtrip(tmp_path: Path):
    path = tmp_path / "state.json"
    original = default_run_state()
    original["status"] = "paused"
    original["total_scenes"] = 42
    save_run_state(path, original)

    loaded = load_run_state(path)
    assert loaded["status"] == "paused"
    assert loaded["total_scenes"] == 42


def test_save_fills_missing_keys(tmp_path: Path):
    path = tmp_path / "partial.json"
    save_run_state(path, {"status": "ok", "version": "vnext"})

    loaded = load_run_state(path)
    # defaults should be filled in
    assert "total_scenes" in loaded
    assert "verification" in loaded


def test_mark_stage_updates_current(tmp_path: Path):
    path = tmp_path / "state.json"
    state = mark_stage(path, stage="score_batches", status="running")
    assert state["current_stage"] == "score_batches"
    assert state["status"] == "running"


def test_mark_stage_appends_completed(tmp_path: Path):
    path = tmp_path / "state.json"
    mark_stage(path, stage="prepare", completed=True)
    mark_stage(path, stage="score_batches", completed=True)
    state = load_run_state(path)
    assert state["completed_stages"] == ["prepare", "score_batches"]


def test_mark_stage_no_duplicate_completed(tmp_path: Path):
    path = tmp_path / "state.json"
    mark_stage(path, stage="prepare", completed=True)
    mark_stage(path, stage="prepare", completed=True)
    state = load_run_state(path)
    assert state["completed_stages"].count("prepare") == 1


def test_mark_stage_clears_next_batch_on_finalize(tmp_path: Path):
    path = tmp_path / "state.json"
    mark_stage(path, stage="finalize", next_batch={"batch_id": "b1"})
    state = load_run_state(path)
    assert state["next_batch"] == {"batch_id": "b1"}

    mark_stage(path, stage="completed", can_finalize=True)
    state = load_run_state(path)
    assert state["next_batch"] is None


def test_mark_stage_updates_coverage(tmp_path: Path):
    path = tmp_path / "state.json"
    state = mark_stage(path, stage="score_batches", total_scenes=20, completed_scenes=15, coverage_ratio=0.75)
    assert state["total_scenes"] == 20
    assert state["completed_scenes"] == 15
    assert state["coverage_ratio"] == 0.75


def test_mark_stage_records_error(tmp_path: Path):
    path = tmp_path / "state.json"
    state = mark_stage(path, stage="prepare", last_error="download failed")
    assert state["last_error"] == "download failed"


def test_coverage_ratio_rounded(tmp_path: Path):
    path = tmp_path / "state.json"
    state = mark_stage(path, stage="score_batches", coverage_ratio=0.333333)
    assert state["coverage_ratio"] == 0.3333


def test_verification_merged(tmp_path: Path):
    path = tmp_path / "state.json"
    mark_stage(path, stage="prepare", verification={"passed": True, "missing_outputs": ["a.md"]})
    state = load_run_state(path)
    assert state["verification"]["passed"] is True
    assert state["verification"]["missing_outputs"] == ["a.md"]
    # default keys should still be present
    assert "checked_at" in state["verification"]


def test_scores_path_normalized(tmp_path: Path):
    path = tmp_path / "state.json"
    state = mark_stage(path, stage="score_batches", scores_path="/tmp/../tmp/scores.json")
    assert ".." not in state["scores_path"]


def test_scores_path_stored_relative_to_video_dir(tmp_path: Path):
    path = tmp_path / "state.json"
    video_dir = tmp_path / "video-job"
    state = mark_stage(
        path,
        stage="score_batches",
        scores_path=str(video_dir / "scene_scores.json"),
        video_dir=str(video_dir),
    )
    assert state["scores_path"] == "scene_scores.json"
    assert state["video_dir"] == str(video_dir)


def test_scores_path_outside_video_dir_falls_back_to_absolute(tmp_path: Path):
    path = tmp_path / "state.json"
    state = mark_stage(
        path,
        stage="score_batches",
        scores_path=str(tmp_path / "elsewhere" / "scene_scores.json"),
        video_dir=str(tmp_path / "video-job"),
    )
    assert state["scores_path"].endswith("scene_scores.json")
