"""Tests for ai_analyzer: score validation, weighted scoring, recomputation."""

import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import ai_analyzer
import host_batching
import openclaw_batch_probe
from ai_analyzer import (
    _parse_scene_response,
    _validate_scene_json,
    compute_weighted_score,
    recompute_scene_scores,
    SCENE_REQUIRED_SCORE_FIELDS,
)


# ── helpers ──────────────────────────────────────────────────────────

def _valid_scene(**score_overrides) -> dict:
    """Return a minimally valid scene-analysis dict."""
    scores = {
        "aesthetic_beauty": 7,
        "credibility": 7,
        "impact": 7,
        "memorability": 7,
        "fun_interest": 7,
    }
    scores.update(score_overrides)
    return {
        "type_classification": "TYPE-A Hook",
        "description": "A test scene.",
        "visual_summary": "Test visual.",
        "storyboard": {
            "shot_size": "中景",
            "lighting": "自然光",
            "camera_movement": "固定",
            "visual_style": "写实",
            "technique": "手持",
        },
        "scores": scores,
        "selection_reasoning": "test reasoning",
        "edit_suggestion": "keep",
    }


def _completed_scene(scene_number: int = 1) -> dict:
    return {
        "scene_number": scene_number,
        "timestamp_range": f"00:00:0{scene_number},000 --> 00:00:0{scene_number},900",
        "duration_seconds": 0.9,
        "frame_path": "",
        "frame_samples": {
            "primary": "",
            "start": "",
            "mid": "",
            "end": "",
        },
        "storyboard": {
            "voiceover": "",
            "onscreen_text": "",
            "camera_movement_hint": "静止镜头",
            "camera_movement_rationale": "",
            "camera_movement": "固定",
            "lighting": "自然光",
            "shot_size": "中景",
            "technique": "手持",
            "visual_style": "写实",
            "visual_description": "A test scene.",
            "timestamp": f"00:00:0{scene_number},000 --> 00:00:0{scene_number},900",
            "screenshot_path": "",
        },
        **_valid_scene(),
        "notes": "",
        "weighted_score": 8.1,
        "selection": "[USABLE]",
    }


def _write_batch_output(
    host_dir: Path,
    *,
    receipt: dict,
    scene_number: int = 1,
) -> None:
    (host_dir / "index.json").write_text(
        json.dumps(
            {
                "total_scenes": 1,
                "completed_scenes": 1,
                "coverage_ratio": 1.0,
                "batches": [
                    {
                        "batch_id": "batch-001",
                        "scene_numbers": [scene_number],
                        "input": "batch-001-input.json",
                        "output": "batch-001-output.json",
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (host_dir / "batch-001-output.json").write_text(
        json.dumps(
            {
                "batch_id": "batch-001",
                "receipt": receipt,
                "scenes": [
                    {
                        "scene_number": scene_number,
                        **_valid_scene(),
                        "notes": "",
                        "weighted_score": 8.1,
                        "selection": "[USABLE]",
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


# ── _validate_scene_json: score range clamping ───────────────────────

def test_valid_scores_pass_validation():
    result = _validate_scene_json(_valid_scene(), 1)
    assert result is not None
    for field in SCENE_REQUIRED_SCORE_FIELDS:
        assert 1 <= result["scores"][field] <= 10


def test_score_above_10_is_clamped():
    scene = _valid_scene(impact=15)
    result = _validate_scene_json(scene, 2)
    assert result is not None
    assert result["scores"]["impact"] == 10


def test_score_below_1_is_clamped():
    scene = _valid_scene(memorability=-3)
    result = _validate_scene_json(scene, 3)
    assert result is not None
    assert result["scores"]["memorability"] == 1


def test_score_zero_is_clamped():
    scene = _valid_scene(aesthetic_beauty=0)
    result = _validate_scene_json(scene, 4)
    assert result is not None
    assert result["scores"]["aesthetic_beauty"] == 1


def test_non_numeric_score_replaced_with_5():
    scene = _valid_scene()
    scene["scores"]["credibility"] = "great"
    result = _validate_scene_json(scene, 5)
    assert result is not None
    assert result["scores"]["credibility"] == 5


def test_float_score_within_range_passes():
    scene = _valid_scene(impact=8.5)
    result = _validate_scene_json(scene, 6)
    assert result is not None
    # floats within [1,10] are kept as-is (not forced to int)
    assert result["scores"]["impact"] == 8.5


def test_missing_score_field_returns_none():
    scene = _valid_scene()
    del scene["scores"]["impact"]
    assert _validate_scene_json(scene, 7) is None


def test_missing_scores_dict_returns_none():
    scene = _valid_scene()
    scene["scores"] = "not a dict"
    assert _validate_scene_json(scene, 8) is None


def test_parse_scene_response_extracts_json_from_markdown_block():
    content = """这里是分析结果：

```json
{
  "type_classification": "TYPE-A Hook",
  "description": "A test scene.",
  "visual_summary": "Test visual.",
  "storyboard": {
    "shot_size": "中景",
    "lighting": "自然光",
    "camera_movement": "固定",
    "visual_style": "写实",
    "technique": "手持"
  },
  "scores": {
    "aesthetic_beauty": 7,
    "credibility": 7,
    "impact": 7,
    "memorability": 7,
    "fun_interest": 7
  },
  "selection_reasoning": "test reasoning",
  "edit_suggestion": "keep"
}
```"""

    result = _parse_scene_response(content, 1)

    assert result is not None
    assert result["type_classification"] == "TYPE-A Hook"


# ── compute_weighted_score ───────────────────────────────────────────

def test_type_a_weighted_score():
    analysis = {
        "scores": {"impact": 10, "memorability": 8, "aesthetic_beauty": 6, "fun_interest": 4},
        "type_classification": "TYPE-A Hook",
    }
    result = compute_weighted_score(analysis)
    expected = 10 * 0.40 + 8 * 0.30 + 6 * 0.20 + 4 * 0.10
    assert abs(result["weighted_score"] - round(expected, 2)) < 0.01
    assert result["selection"] == "[MUST KEEP]"  # impact=10 triggers MUST KEEP


def test_type_b_weighted_score():
    analysis = {
        "scores": {"credibility": 9, "memorability": 8, "aesthetic_beauty": 7, "fun_interest": 6, "impact": 5},
        "type_classification": "TYPE-B Narrative",
    }
    result = compute_weighted_score(analysis)
    expected = 9 * 0.40 + 8 * 0.30 + 7 * 0.20 + 6 * 0.10
    assert abs(result["weighted_score"] - round(expected, 2)) < 0.01


def test_type_c_weighted_score():
    analysis = {
        "scores": {"aesthetic_beauty": 9, "impact": 7, "memorability": 8, "credibility": 6, "fun_interest": 5},
        "type_classification": "TYPE-C Aesthetic",
    }
    result = compute_weighted_score(analysis)
    expected = 9 * 0.50 + 7 * 0.20 + 8 * 0.20 + 6 * 0.10
    assert abs(result["weighted_score"] - round(expected, 2)) < 0.01


def test_type_d_weighted_score():
    analysis = {
        "scores": {"credibility": 8, "memorability": 7, "aesthetic_beauty": 6, "impact": 5, "fun_interest": 4},
        "type_classification": "TYPE-D Commercial",
    }
    result = compute_weighted_score(analysis)
    expected = 8 * 0.40 + 7 * 0.40 + 6 * 0.20
    assert abs(result["weighted_score"] - round(expected, 2)) < 0.01


def test_must_keep_threshold():
    analysis = {
        "scores": {"impact": 7, "memorability": 7, "aesthetic_beauty": 7, "fun_interest": 7, "credibility": 7},
        "type_classification": "TYPE-A Hook",
    }
    result = compute_weighted_score(analysis)
    # weighted = 7.0 exactly -> USABLE, not MUST KEEP
    assert result["selection"] == "[USABLE]"


def test_usable_threshold():
    analysis = {
        "scores": {"impact": 7, "memorability": 7, "aesthetic_beauty": 7, "fun_interest": 7, "credibility": 7},
        "type_classification": "TYPE-A Hook",
    }
    result = compute_weighted_score(analysis)
    # weighted = 7.0 exactly -> USABLE
    assert result["selection"] == "[USABLE]"


def test_discard_below_threshold():
    analysis = {
        "scores": {"impact": 3, "memorability": 3, "aesthetic_beauty": 3, "fun_interest": 3, "credibility": 3},
        "type_classification": "TYPE-A Hook",
    }
    result = compute_weighted_score(analysis)
    assert result["selection"] == "[DISCARD]"


def test_any_score_10_triggers_must_keep():
    analysis = {
        "scores": {"impact": 3, "memorability": 3, "aesthetic_beauty": 10, "fun_interest": 3, "credibility": 3},
        "type_classification": "TYPE-A Hook",
    }
    result = compute_weighted_score(analysis)
    assert result["selection"] == "[MUST KEEP]"


# ── recompute_scene_scores ───────────────────────────────────────────

def test_recompute_updates_all_scenes():
    data = {
        "scenes": [
            {"scores": {"aesthetic_beauty": 8, "credibility": 7, "impact": 6, "memorability": 5, "fun_interest": 4},
             "type_classification": "TYPE-A Hook", "description": "scene 1"},
            {"scores": {"aesthetic_beauty": 9, "credibility": 8, "impact": 7, "memorability": 6, "fun_interest": 5},
             "type_classification": "TYPE-B Narrative", "description": "scene 2"},
        ]
    }
    result = recompute_scene_scores(data)
    assert "weighted_score" in result["scenes"][0]
    assert "weighted_score" in result["scenes"][1]
    assert "visual_description" in result["scenes"][0]["storyboard"]


def test_recompute_skips_scene_with_zero_score():
    data = {
        "scenes": [
            {"scores": {"aesthetic_beauty": 0, "credibility": 7, "impact": 6, "memorability": 5, "fun_interest": 4},
             "type_classification": "TYPE-A Hook"},
        ]
    }
    result = recompute_scene_scores(data)
    assert "weighted_score" not in result["scenes"][0]


def test_recompute_skips_scene_with_missing_score():
    data = {
        "scenes": [
            {"scores": {"credibility": 7, "impact": 6},
             "type_classification": "TYPE-A Hook"},
        ]
    }
    result = recompute_scene_scores(data)
    assert "weighted_score" not in result["scenes"][0]


def test_main_reuses_auto_score_result_without_extra_refresh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    scores_path = tmp_path / "scene_scores.json"
    scores_path.write_text("{}", encoding="utf-8")
    sentinel = {"scenes": []}

    monkeypatch.setattr(
        ai_analyzer,
        "resolve_stage",
        lambda mode, path: "score_batches" if mode == "score_batches" else mode,
    )
    monkeypatch.setattr(ai_analyzer, "auto_score_scenes", lambda *args, **kwargs: sentinel)
    monkeypatch.setattr(
        ai_analyzer,
        "refresh_analysis_data",
        lambda *args, **kwargs: pytest.fail("main() should reuse auto_score_scenes() data for staged modes"),
    )
    monkeypatch.setattr(ai_analyzer, "load_run_state", lambda path: {"status": "waiting_for_batches"})
    monkeypatch.setattr(ai_analyzer, "write_delivery_report", lambda *args, **kwargs: None)

    assert ai_analyzer.main([str(scores_path), "--mode", "score_batches"]) == 0


def test_main_finalize_runs_delivery_pipeline_with_verified_outputs(
    tmp_path: Path,
    finalize_pipeline_stubs: dict,
) -> None:
    scores_path = tmp_path / "scene_scores.json"
    scores_path.write_text("{}", encoding="utf-8")

    assert ai_analyzer.main([str(scores_path), "--mode", "finalize", "--storyboard-formats", "md"]) == 0

    assert finalize_pipeline_stubs["completed_calls"], (
        "finalize flow should mark the run as completed after verification passes"
    )
    assert finalize_pipeline_stubs["storyboard_calls"] == [{"formats": ("md",), "skip_enrich": True}]
    assert finalize_pipeline_stubs["classification_summary_calls"] == [
        {"video_id": "demo", "video_dir": tmp_path, "kwargs": {}}
    ]
    assert finalize_pipeline_stubs["classification_result_calls"] == [
        {
            "video_id": "demo",
            "video_dir": tmp_path,
            "runtime_config": finalize_pipeline_stubs["routing_config"],
            "kwargs": {},
        }
    ]
    assert (
        finalize_pipeline_stubs["audiovisual_inputs"][0]["classification_result"]["applied_route"]["framework"]
        == "narrative_trailer"
    )
    assert finalize_pipeline_stubs["save_calls"] == []


def test_auto_score_scenes_uses_parallel_batch_scoring_with_default_4_workers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scores_path = tmp_path / "scene_scores.json"
    scores_path.write_text('{"scenes": []}', encoding="utf-8")
    captured: dict[str, object] = {}

    monkeypatch.setattr(ai_analyzer, "merge_host_batch_outputs", lambda *args, **kwargs: {"scenes": []})
    monkeypatch.setattr(ai_analyzer, "refresh_analysis_data", lambda *args, **kwargs: {"video_id": "demo", "scenes": []})
    monkeypatch.setattr(ai_analyzer, "prepare_host_batches", lambda *args, **kwargs: {"completed_scenes": 0, "coverage_ratio": 0.0})
    monkeypatch.setattr(
        ai_analyzer,
        "get_next_pending_batch",
        lambda *args, **kwargs: {
            "batch_id": "batch-001",
            "scene_numbers": [1, 6],
            "input": "batch-001-input.json",
            "output": "batch-001-output.json",
        },
    )
    monkeypatch.setattr(ai_analyzer, "validate_scene_resource_readiness", lambda data: ([], []))
    monkeypatch.setattr(ai_analyzer, "validate_next_batch_packet", lambda *args, **kwargs: [])
    monkeypatch.setattr(ai_analyzer, "build_verification_payload", lambda *args, **kwargs: {"passed": True})
    monkeypatch.setattr(ai_analyzer, "mark_stage", lambda *args, **kwargs: None)

    def fake_auto_fill(*args, **kwargs):
        captured.update(kwargs)
        return {"completed_batches": [], "failed_batches": [], "config_source": "openclaw"}

    monkeypatch.setattr(ai_analyzer, "auto_fill_pending_batches", fake_auto_fill, raising=False)
    monkeypatch.setattr(
        ai_analyzer,
        "resolve_auto_scoring_config",
        lambda *args, **kwargs: {"models_json_path": "/tmp/models.json", "preferred_model": "kcode/K2.6-code-preview"},
        raising=False,
    )

    ai_analyzer.auto_score_scenes(scores_path, tmp_path, mode="score_batches")

    assert captured["max_workers"] == 4


def test_score_batches_refreshes_resources_for_all_pending_scenes_before_auto_parallel_scoring(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scores_path = tmp_path / "scene_scores.json"
    scores_path.write_text('{"scenes": []}', encoding="utf-8")
    total_scenes = 7

    def make_scene(scene_number: int) -> dict:
        return {
            "scene_number": scene_number,
            "filename": f"scene-{scene_number:03d}.mp4",
            "timestamp_range": f"00:00:{scene_number:02d},000 --> 00:00:{scene_number:02d},900",
            "duration_seconds": 0.9,
            "frame_path": "",
            "frame_samples": {},
            "storyboard": {
                "voiceover": "",
                "onscreen_text": "",
                "camera_movement_hint": "静止镜头",
                "camera_movement_rationale": "",
                "screenshot_path": "",
            },
            "type_classification": "",
            "description": "",
            "visual_summary": "",
            "scores": {},
            "selection_reasoning": "",
            "edit_suggestion": "",
            "notes": "",
        }

    base_scenes = [make_scene(scene_number) for scene_number in range(1, total_scenes + 1)]
    auto_fill_calls: list[int] = []

    monkeypatch.setattr(ai_analyzer, "merge_host_batch_outputs", lambda *args, **kwargs: {"scenes": base_scenes})

    def fake_refresh_analysis_data(*args, scene_numbers=None, **kwargs):
        target_numbers = set(scene_numbers or range(1, total_scenes + 1))
        frames_dir = tmp_path / "frames"
        frames_dir.mkdir(parents=True, exist_ok=True)
        refreshed_scenes = []
        for source_scene in base_scenes:
            scene = json.loads(json.dumps(source_scene))
            scene_number = int(scene["scene_number"])
            if scene_number in target_numbers:
                primary = frames_dir / f"scene-{scene_number:03d}.jpg"
                start = frames_dir / f"scene-{scene_number:03d}__start.jpg"
                mid = frames_dir / f"scene-{scene_number:03d}__mid.jpg"
                end = frames_dir / f"scene-{scene_number:03d}__end.jpg"
                for path in (primary, start, mid, end):
                    path.write_bytes(b"frame")
                scene["frame_path"] = str(primary)
                scene["frame_samples"] = {
                    "primary": str(primary),
                    "start": str(start),
                    "mid": str(mid),
                    "end": str(end),
                }
                scene["storyboard"]["screenshot_path"] = str(primary)
            refreshed_scenes.append(scene)
        return {"video_id": "demo", "scenes": refreshed_scenes}

    monkeypatch.setattr(ai_analyzer, "refresh_analysis_data", fake_refresh_analysis_data)
    monkeypatch.setattr(host_batching, "_ensure_contact_sheet", lambda *args, **kwargs: None)
    monkeypatch.setattr(ai_analyzer, "validate_next_batch_packet", lambda *args, **kwargs: [])
    monkeypatch.setattr(ai_analyzer, "build_verification_payload", lambda *args, **kwargs: {"passed": True})
    monkeypatch.setattr(ai_analyzer, "mark_stage", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        ai_analyzer,
        "resolve_auto_scoring_config",
        lambda *args, **kwargs: {
            "config_source": "env",
            "providers": {"demo": {"models": [{"id": "model", "input": ["text", "image"]}]}},
            "preferred_model": "demo/model",
            "fallback_models": [],
            "max_workers": 1,
        },
    )

    def fake_auto_fill(*args, **kwargs):
        auto_fill_calls.append(int(kwargs["max_workers"]))
        return {
            "scored_scenes": 0,
            "failed_scenes": 0,
            "completed_batches": [],
            "failed_batches": [],
            "max_workers": kwargs["max_workers"],
            "scored_scene_numbers": [],
            "failed_scene_numbers": [],
        }

    monkeypatch.setattr(ai_analyzer, "auto_fill_pending_batches", fake_auto_fill, raising=False)

    ai_analyzer.auto_score_scenes(scores_path, tmp_path, mode="score_batches")

    assert auto_fill_calls == [1]


def test_auto_fill_pending_batches_writes_completed_scene_before_whole_batch_finishes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_batch_fixture,
) -> None:
    write_batch_fixture(tmp_path, [1, 2])
    observed_first_flush: list[str] = []

    monkeypatch.setattr(openclaw_batch_probe, "build_attempt_order", lambda *args, **kwargs: [{"model_ref": "demo/model"}])

    def fake_analyze_scenes(scenes, attempts, max_workers=1, analyzer_fn=None, on_result=None):
        first_scene = {
            "scene_number": 1,
            **_valid_scene(),
        }
        second_scene = {
            "scene_number": 2,
            **_valid_scene(impact=8),
        }
        first_payload = {
            "index": 0,
            "run_item": {"scene_number": 1, "batch_id": "batch-001", "ok": True, "used_model": "demo/model", "elapsed_s": 0.1, "attempts": []},
            "scene_result": first_scene,
            "failed": None,
        }
        second_payload = {
            "index": 1,
            "run_item": {"scene_number": 2, "batch_id": "batch-001", "ok": True, "used_model": "demo/model", "elapsed_s": 0.1, "attempts": []},
            "scene_result": second_scene,
            "failed": None,
        }
        on_result(first_payload)
        output_payload = json.loads((tmp_path / "host_batches" / "batch-001-output.json").read_text(encoding="utf-8"))
        observed_first_flush.append(output_payload["scenes"][0]["description"])
        on_result(second_payload)
        return (
            [first_payload["run_item"], second_payload["run_item"]],
            [first_scene, second_scene],
            [],
        )

    monkeypatch.setattr(openclaw_batch_probe, "analyze_scenes", fake_analyze_scenes)

    summary = ai_analyzer.auto_fill_pending_batches(
        tmp_path / "scene_scores.json",
        tmp_path,
        {
            "config_source": "env",
            "providers": {"demo": {"models": [{"id": "model", "input": ["text", "image"]}]}},
            "preferred_model": "demo/model",
            "fallback_models": [],
        },
        max_workers=2,
    )

    assert observed_first_flush == ["A test scene."]
    assert summary["scored_scenes"] == 2


def test_prepare_host_batches_preserves_completed_receipt_for_finished_scenes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host_dir = tmp_path / "host_batches"
    host_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(host_batching, "_ensure_contact_sheet", lambda *args, **kwargs: None)

    completed_scene = {
        "scene_number": 1,
        "timestamp_range": "00:00:00,000 --> 00:00:00,900",
        "duration_seconds": 0.9,
        "frame_path": "",
        "frame_samples": {
            "primary": "",
            "start": "",
            "mid": "",
            "end": "",
        },
        "storyboard": {
            "voiceover": "",
            "onscreen_text": "",
            "camera_movement_hint": "静止镜头",
            "camera_movement_rationale": "",
            **_valid_scene()["storyboard"],
        },
        **_valid_scene(),
        "notes": "",
        "weighted_score": 8.1,
        "selection": "[USABLE]",
    }

    (host_dir / "batch-001-output.json").write_text(
        json.dumps(
            {
                "batch_id": "batch-001",
                "receipt": {
                    "batch_id": "batch-001",
                    "scene_numbers": [1],
                    "output_path": "batch-001-output.json",
                    "status": "pending",
                    "has_todo": True,
                    "needs_review": [],
                    "worker_summary": "stale",
                    "started_at": "",
                    "updated_at": "",
                    "completed_at": "",
                },
                "scenes": [
                    {
                        "scene_number": 1,
                        **_valid_scene(),
                        "notes": "",
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    result = host_batching.prepare_host_batches(
        {"video_id": "demo", "scenes": [completed_scene]},
        tmp_path,
        batch_size=1,
    )
    output_payload = json.loads((host_dir / "batch-001-output.json").read_text(encoding="utf-8"))

    assert result["batches"][0]["status"] == "completed"
    assert output_payload["receipt"]["status"] == "completed"
    assert output_payload["receipt"]["has_todo"] is False


def test_prepare_host_batches_backfills_missing_sample_frames_for_later_batches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frames_dir = tmp_path / "frames"
    scenes_dir = tmp_path / "scenes"
    frames_dir.mkdir(parents=True, exist_ok=True)
    scenes_dir.mkdir(parents=True, exist_ok=True)

    def make_scene(scene_number: int, *, missing_samples: bool) -> dict:
        scene_file = scenes_dir / f"scene-{scene_number:03d}.mp4"
        scene_file.write_bytes(b"scene")
        primary = frames_dir / f"scene-{scene_number:03d}.jpg"
        primary.write_bytes(b"primary")
        sample_paths = {
            "primary": str(primary),
            "start": str(frames_dir / f"scene-{scene_number:03d}__start.jpg"),
            "mid": str(frames_dir / f"scene-{scene_number:03d}__mid.jpg"),
            "end": str(frames_dir / f"scene-{scene_number:03d}__end.jpg"),
        }
        if not missing_samples:
            for key in ("start", "mid", "end"):
                Path(sample_paths[key]).write_bytes(key.encode("utf-8"))
        return {
            "scene_number": scene_number,
            "filename": scene_file.name,
            "file_path": str(scene_file),
            "timestamp_range": f"00:00:{scene_number:02d},000 --> 00:00:{scene_number:02d},900",
            "duration_seconds": 0.9,
            "frame_path": str(primary),
            "frame_samples": sample_paths,
            "storyboard": {
                "voiceover": "",
                "onscreen_text": "",
                "camera_movement_hint": "静止镜头",
            },
            "type_classification": "TODO: 选择 TYPE-A/B/C/D",
            "description": "TODO: 一句话描述画面内容",
            "scores": {},
        }

    scenes = [make_scene(scene_number, missing_samples=(scene_number == 7)) for scene_number in range(1, 8)]
    extracted_scene_numbers: list[int] = []

    def fake_extract(scene_path: Path, frames_dir_arg: Path, scene_stem: str) -> dict:
        extracted_scene_numbers.append(int(scene_stem.rsplit("-", 1)[-1]))
        sample_paths = {
            "primary": frames_dir_arg / f"{scene_stem}.jpg",
            "start": frames_dir_arg / f"{scene_stem}__start.jpg",
            "mid": frames_dir_arg / f"{scene_stem}__mid.jpg",
            "end": frames_dir_arg / f"{scene_stem}__end.jpg",
        }
        for key, path in sample_paths.items():
            path.write_bytes(key.encode("utf-8"))
        return {
            "duration_seconds": 0.9,
            "sample_paths": {key: str(path) for key, path in sample_paths.items()},
        }

    monkeypatch.setattr(host_batching, "_ensure_contact_sheet", lambda *args, **kwargs: None)
    monkeypatch.setattr(host_batching, "extract_scene_sample_frames", fake_extract, raising=False)

    host_batching.prepare_host_batches(
        {"video_id": "demo", "scenes": scenes},
        tmp_path,
        batch_size=6,
    )

    batch_two_payload = json.loads((tmp_path / "host_batches" / "batch-002-input.json").read_text(encoding="utf-8"))

    assert extracted_scene_numbers == [7]
    assert batch_two_payload["scenes"][0]["frames"]["start"] == "frames/scene-007__start.jpg"
    assert batch_two_payload["scenes"][0]["frames"]["mid"] == "frames/scene-007__mid.jpg"
    assert batch_two_payload["scenes"][0]["frames"]["end"] == "frames/scene-007__end.jpg"


def test_prepare_host_batches_blocks_receipt_with_disallowed_local_fallback_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host_dir = tmp_path / "host_batches"
    host_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(host_batching, "_ensure_contact_sheet", lambda *args, **kwargs: None)

    completed_scene = _completed_scene()

    (host_dir / "batch-001-output.json").write_text(
        json.dumps(
            {
                "batch_id": "batch-001",
                "receipt": {
                    "batch_id": "batch-001",
                    "scene_numbers": [1],
                    "output_path": "batch-001-output.json",
                    "status": "completed",
                    "has_todo": False,
                    "needs_review": [],
                    "worker_summary": "completed with PIL-based frame feature analysis; scenes=1",
                    "started_at": "",
                    "updated_at": "",
                    "completed_at": "",
                },
                "scenes": [
                    {
                        "scene_number": 1,
                        **_valid_scene(),
                        "notes": "",
                        "weighted_score": 8.1,
                        "selection": "[USABLE]",
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    result = host_batching.prepare_host_batches(
        {"video_id": "demo", "scenes": [completed_scene]},
        tmp_path,
        batch_size=1,
    )
    output_payload = json.loads((host_dir / "batch-001-output.json").read_text(encoding="utf-8"))

    assert result["batches"][0]["status"] == "blocked"
    assert output_payload["receipt"]["status"] == "blocked"
    assert output_payload["receipt"]["has_todo"] is True


def test_validate_finalize_readiness_blocks_when_batch_receipt_needs_review(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host_dir = tmp_path / "host_batches"
    host_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(ai_analyzer, "validate_scene_resource_readiness", lambda data: ([], []))

    _write_batch_output(
        host_dir,
        receipt={
            "batch_id": "batch-001",
            "scene_numbers": [1],
            "output_path": "batch-001-output.json",
            "status": "completed",
            "has_todo": False,
            "needs_review": [{"scene_number": 1, "error": "403 Forbidden"}],
            "worker_summary": "auto parallel scoring via openclaw; success=0 failed=1 models={}",
            "started_at": "",
            "updated_at": "",
            "completed_at": "",
        },
    )

    problems = ai_analyzer.validate_finalize_readiness(
        tmp_path,
        {"video_id": "demo", "scenes": [_completed_scene()]},
    )

    assert any("batch-001" in item for item in problems)
    assert any("待复核" in item for item in problems)


def test_build_verification_payload_fails_when_batch_receipt_is_blocked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host_dir = tmp_path / "host_batches"
    host_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(ai_analyzer, "collect_scene_resource_issues", lambda data: [])

    _write_batch_output(
        host_dir,
        receipt={
            "batch_id": "batch-001",
            "scene_numbers": [1],
            "output_path": "batch-001-output.json",
            "status": "completed",
            "has_todo": False,
            "needs_review": [],
            "worker_summary": "Analyzed 1 scenes using PIL image analysis (brightness, color, contrast features)",
            "started_at": "",
            "updated_at": "",
            "completed_at": "",
        },
    )

    report = ai_analyzer.build_verification_payload(
        tmp_path,
        {"video_id": "demo", "scenes": [_completed_scene()]},
        (),
        include_output_checks=False,
    )

    assert report["passed"] is False
    assert report["blocked_batches"] == ["batch-001"]


def test_run_auto_scoring_validation_reports_sample_mismatches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_batch_fixture,
) -> None:
    scores_path = tmp_path / "scene_scores.json"
    scores_path.write_text(
        json.dumps(
            {
                "video_id": "demo",
                "scenes": [
                    {"scene_number": 1, **_valid_scene()},
                    {"scene_number": 2, **_valid_scene()},
                    {"scene_number": 3, **_valid_scene()},
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    write_batch_fixture(tmp_path, [1, 2, 3])

    monkeypatch.setattr(openclaw_batch_probe, "load_provider_catalog", lambda *args, **kwargs: {"demo": {"models": [{"id": "model", "input": ["text", "image"]}]}})
    monkeypatch.setattr(openclaw_batch_probe, "build_attempt_order", lambda *args, **kwargs: [{"model_ref": "demo/model"}])
    monkeypatch.setattr(openclaw_batch_probe, "sample_scene_numbers", lambda scene_numbers, sample_size: [1, 3])
    monkeypatch.setattr(
        openclaw_batch_probe,
        "analyze_scenes",
        lambda *args, **kwargs: (
            [
                {"scene_number": 1, "batch_id": "batch-001", "ok": True, "used_model": "demo/model", "elapsed_s": 0.1, "attempts": []},
                {"scene_number": 3, "batch_id": "batch-001", "ok": True, "used_model": "demo/model", "elapsed_s": 0.1, "attempts": []},
            ],
            [
                {"scene_number": 1, **_valid_scene()},
                {"scene_number": 3, **({**_valid_scene(impact=2), "type_classification": "TYPE-C Aesthetic"})},
            ],
            [],
        ),
    )

    report = ai_analyzer.run_auto_scoring_validation(
        scores_path,
        tmp_path,
        {
            "config_source": "openclaw",
            "models_json_path": str(tmp_path / "models.json"),
            "preferred_model": "demo/model",
            "fallback_models": [],
        },
        scored_scene_numbers=[1, 2, 3],
        sample_size=2,
    )

    assert report["report_path"]
    assert Path(report["report_path"]).exists()
    assert report["needs_review_scene_numbers"] == [3]


def test_score_batches_runs_auto_parallel_scoring_not_manual_instructions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys,
) -> None:
    scores_path = tmp_path / "scene_scores.json"
    scores_path.write_text("{}", encoding="utf-8")
    payload = {"video_id": "demo", "scenes": [_valid_scene()]}

    monkeypatch.setattr(
        ai_analyzer,
        "resolve_stage",
        lambda mode, path: "score_batches" if mode == "score_batches" else mode,
    )
    monkeypatch.setattr(ai_analyzer, "auto_score_scenes", lambda *args, **kwargs: payload)
    monkeypatch.setattr(ai_analyzer, "load_run_state", lambda path: {"status": "running"})
    monkeypatch.setattr(ai_analyzer, "write_delivery_report", lambda *args, **kwargs: None)

    assert ai_analyzer.main([str(scores_path), "--mode", "score_batches"]) == 0

    output = capsys.readouterr().out
    assert "自动并行评分" in output
    assert "逐个 scene 查看 primary / start / mid / end 四帧" not in output
    assert "立即开始分析当前批次" not in output


def test_score_batches_blocked_on_missing_auto_scoring_config_prints_setup_hint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys,
) -> None:
    scores_path = tmp_path / "scene_scores.json"
    scores_path.write_text("{}", encoding="utf-8")
    payload = {"video_id": "demo", "scenes": [_valid_scene()]}

    monkeypatch.setattr(
        ai_analyzer,
        "resolve_stage",
        lambda mode, path: "score_batches" if mode == "score_batches" else mode,
    )
    monkeypatch.setattr(ai_analyzer, "auto_score_scenes", lambda *args, **kwargs: payload)
    monkeypatch.setattr(
        ai_analyzer,
        "load_run_state",
        lambda path: {"status": "blocked", "last_error": "缺少自动评分配置"},
    )
    monkeypatch.setattr(ai_analyzer, "write_delivery_report", lambda *args, **kwargs: None)

    assert ai_analyzer.main([str(scores_path), "--mode", "score_batches"]) == 2

    output = capsys.readouterr().out
    assert "缺少自动评分配置" in output
    assert "OpenClaw" in output
    assert "models.json" in output
    assert "API Key" in output


def test_main_non_openclaw_ready_to_finalize_runs_finalize_immediately(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scores_path = tmp_path / "scene_scores.json"
    scores_path.write_text("{}", encoding="utf-8")
    payload = {"video_id": "demo", "scenes": [_valid_scene()], "audiovisual_route": {"framework": "narrative_trailer"}}
    completed_calls: list[dict] = []
    state_calls = {"count": 0}

    monkeypatch.setattr(
        ai_analyzer,
        "resolve_stage",
        lambda mode, path: "score_batches" if mode == "score_batches" else mode,
    )
    monkeypatch.setattr(ai_analyzer, "auto_score_scenes", lambda *args, **kwargs: payload)

    def fake_load_run_state(path: Path) -> dict:
        state_calls["count"] += 1
        if state_calls["count"] == 1:
            return {"status": "ready_to_finalize", "can_finalize": True}
        return {"status": "completed", "current_stage": "completed"}

    monkeypatch.setattr(ai_analyzer, "load_run_state", fake_load_run_state)
    monkeypatch.setattr(ai_analyzer, "write_delivery_report", lambda *args, **kwargs: None)
    monkeypatch.setattr(ai_analyzer, "validate_finalize_readiness", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        ai_analyzer,
        "generate_detailed_analysis_outputs",
        lambda *args, **kwargs: {"detailed_report_path": tmp_path / "demo_detailed.md"},
    )
    monkeypatch.setattr(ai_analyzer, "select_and_copy_best_shots", lambda *args, **kwargs: None)
    monkeypatch.setattr(ai_analyzer, "generate_complete_report", lambda *args, **kwargs: tmp_path / "demo_complete.md")
    monkeypatch.setattr(
        ai_analyzer,
        "generate_storyboard_outputs",
        lambda *args, **kwargs: {
            "md": tmp_path / "storyboard.md",
            "context_md": tmp_path / "storyboard_context.md",
            "context_json": tmp_path / "storyboard_context.json",
        },
    )
    monkeypatch.setattr(ai_analyzer, "enrich_storyboard_data", lambda data, *args, **kwargs: data)
    monkeypatch.setattr(ai_analyzer, "_normalize_scene_resource_paths", lambda data, *args, **kwargs: data)
    monkeypatch.setattr(ai_analyzer, "recompute_scene_scores", lambda data: data)
    monkeypatch.setattr(ai_analyzer, "save_scores_data", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        ai_analyzer,
        "generate_audiovisual_report_outputs",
        lambda data, *args, **kwargs: {"data": data, "md": tmp_path / "audiovisual.md"},
    )
    monkeypatch.setattr(
        ai_analyzer,
        "write_classification_summary_outputs",
        lambda *args, **kwargs: {
            "md": tmp_path / "classification_summary.md",
            "json": tmp_path / "classification_summary.json",
        },
    )
    monkeypatch.setattr(
        ai_analyzer,
        "generate_classification_result",
        lambda *args, **kwargs: {"applied_route": {"framework": "narrative_trailer"}},
    )
    monkeypatch.setattr(
        ai_analyzer,
        "build_verification_payload",
        lambda *args, **kwargs: {
            "requested_formats": ["md"],
            "required_outputs": {},
            "missing_outputs": [],
            "missing_screenshot_scenes": [],
            "missing_sample_scenes": [],
            "checked_at": "",
            "passed": True,
        },
    )
    monkeypatch.setattr(
        ai_analyzer,
        "mark_completed_state",
        lambda *args, **kwargs: completed_calls.append({"args": args, "kwargs": kwargs}),
    )

    assert ai_analyzer.main([str(scores_path), "--mode", "score_batches", "--storyboard-formats", "md"]) == 0
    assert completed_calls, "default mode should enter finalize instead of stopping once ready_to_finalize"
