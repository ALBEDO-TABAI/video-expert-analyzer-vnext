"""Shared fixtures for the test suite.

Why these live here:

- `write_batch_fixture` and `valid_scene` are used across multiple ai_analyzer
  tests; centralising them keeps fixture drift in one place.
- `finalize_pipeline_stubs` bundles the dozen-plus monkeypatches that
  `main(--mode finalize)` requires. Tests that exercise finalize behavior only
  need to override the *one* stub they care about and can read the capture
  lists for assertions, instead of re-stubbing every collaborator inline.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


# ── data factories ──────────────────────────────────────────────────────


def _build_valid_scene(**score_overrides: Any) -> Dict[str, Any]:
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


@pytest.fixture
def valid_scene() -> Callable[..., Dict[str, Any]]:
    """Factory returning a minimally valid scene-analysis dict."""
    return _build_valid_scene


# ── batch fixture writer ────────────────────────────────────────────────


def _write_batch_fixture_impl(base_dir: Path, scene_numbers: List[int]) -> None:
    host_dir = base_dir / "host_batches"
    host_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "batch_id": "batch-001",
        "scenes": [
            {
                "scene_number": scene_number,
                "time_range": f"00:00:0{scene_number},000 --> 00:00:0{scene_number},900",
                "duration_s": 0.9,
                "frames": {
                    "primary": f"frames/scene-{scene_number:03d}.jpg",
                    "start": f"frames/scene-{scene_number:03d}__start.jpg",
                    "mid": f"frames/scene-{scene_number:03d}__mid.jpg",
                    "end": f"frames/scene-{scene_number:03d}__end.jpg",
                },
                "hints": {
                    "voiceover": "",
                    "onscreen_text": "",
                    "camera_movement_hint": "静止镜头",
                },
                "existing": {
                    "type_classification": "",
                    "description": "",
                    "scores": {},
                },
            }
            for scene_number in scene_numbers
        ],
    }
    (host_dir / "index.json").write_text(
        json.dumps(
            {
                "batches": [
                    {
                        "batch_id": "batch-001",
                        "scene_numbers": scene_numbers,
                        "input": "batch-001-input.json",
                        "output": "batch-001-output.json",
                    }
                ]
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (host_dir / "batch-001-input.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (host_dir / "batch-001-output.json").write_text(
        json.dumps(
            {
                "batch_id": "batch-001",
                "receipt": {
                    "batch_id": "batch-001",
                    "scene_numbers": scene_numbers,
                    "output_path": "batch-001-output.json",
                    "status": "pending",
                    "has_todo": True,
                    "needs_review": [],
                    "worker_summary": "",
                    "started_at": "",
                    "updated_at": "",
                    "completed_at": "",
                },
                "scenes": [
                    {
                        "scene_number": scene_number,
                        "type_classification": "",
                        "description": "",
                        "visual_summary": "",
                        "storyboard": {
                            "shot_size": "",
                            "lighting": "",
                            "camera_movement": "",
                            "visual_style": "",
                            "technique": "",
                        },
                        "scores": {},
                        "selection_reasoning": "",
                        "edit_suggestion": "",
                        "notes": "",
                    }
                    for scene_number in scene_numbers
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


@pytest.fixture
def write_batch_fixture() -> Callable[[Path, List[int]], None]:
    """Factory writing the host_batches/ scaffolding for a single batch."""
    return _write_batch_fixture_impl


# ── finalize-pipeline stubs ─────────────────────────────────────────────


@pytest.fixture
def finalize_pipeline_stubs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Dict[str, Any]:
    """Install the boilerplate monkeypatches that ``main(--mode finalize)`` needs.

    Returns a dict with capture lists keyed by call site so tests can assert
    on what flowed through each stub. Tests can also override individual
    entries via ``monkeypatch.setattr(ai_analyzer, ...)`` after this fixture
    runs — pytest applies overrides in order.
    """
    import ai_analyzer

    captures: Dict[str, Any] = {
        "completed_calls": [],
        "storyboard_calls": [],
        "classification_summary_calls": [],
        "classification_result_calls": [],
        "audiovisual_inputs": [],
        "save_calls": [],
        "routing_config": {"config_source": "test-router"},
        "final_data": {
            "video_id": "demo",
            "scenes": [_build_valid_scene()],
            "audiovisual_route": {"framework": "narrative_trailer"},
        },
    }

    final_data = captures["final_data"]
    routing_config = captures["routing_config"]

    monkeypatch.setattr(ai_analyzer, "resolve_stage", lambda mode, path: "finalize")
    monkeypatch.setattr(ai_analyzer, "auto_score_scenes", lambda *a, **kw: final_data)
    monkeypatch.setattr(ai_analyzer, "resolve_auto_scoring_config", lambda: routing_config)
    monkeypatch.setattr(ai_analyzer, "validate_finalize_readiness", lambda *a, **kw: [])
    monkeypatch.setattr(
        ai_analyzer,
        "generate_detailed_analysis_outputs",
        lambda *a, **kw: {"detailed_report_path": tmp_path / "demo_detailed.md"},
    )
    monkeypatch.setattr(ai_analyzer, "select_and_copy_best_shots", lambda *a, **kw: None)
    monkeypatch.setattr(
        ai_analyzer, "generate_complete_report", lambda *a, **kw: tmp_path / "demo_complete.md"
    )
    monkeypatch.setattr(
        ai_analyzer,
        "generate_storyboard_outputs",
        lambda *a, **kw: captures["storyboard_calls"].append(kw)
        or {
            "md": tmp_path / "storyboard.md",
            "context_md": tmp_path / "storyboard_context.md",
            "context_json": tmp_path / "storyboard_context.json",
        },
    )
    monkeypatch.setattr(ai_analyzer, "enrich_storyboard_data", lambda data, *a, **kw: data)
    monkeypatch.setattr(
        ai_analyzer, "_normalize_scene_resource_paths", lambda data, *a, **kw: data
    )
    monkeypatch.setattr(ai_analyzer, "recompute_scene_scores", lambda data: data)
    monkeypatch.setattr(
        ai_analyzer,
        "save_scores_data",
        lambda *args, **kwargs: captures["save_calls"].append(args),
    )
    monkeypatch.setattr(
        ai_analyzer,
        "write_classification_summary_outputs",
        lambda data, video_dir, **kw: captures["classification_summary_calls"].append(
            {"video_id": data.get("video_id"), "video_dir": video_dir, "kwargs": kw}
        )
        or {
            "md": tmp_path / "classification_summary.md",
            "json": tmp_path / "classification_summary.json",
        },
    )
    monkeypatch.setattr(
        ai_analyzer,
        "generate_classification_result",
        lambda data, video_dir, runtime_config=None, **kw: captures[
            "classification_result_calls"
        ].append(
            {
                "video_id": data.get("video_id"),
                "video_dir": video_dir,
                "runtime_config": runtime_config,
                "kwargs": kw,
            }
        )
        or {
            "classification": {
                "type": "narrative_trailer",
                "type_cn": "预告 / 先导片",
                "confidence": "high",
            },
            "facets": {"visual_source": "P", "audio_dominance": "LM"},
            "reasoning_summary": "片名和结构都符合预告逻辑。",
            "applied_route": {
                "framework": "narrative_trailer",
                "route_label": "剧情预告 / 叙事预告",
                "route_subtype": "预告 / 先导片",
                "reference": "剧情预告 / 叙事预告",
                "visual_axis": "P",
                "visual_label": "原创演绎拍摄",
                "audio_axis": "LM",
                "audio_label": "语言 + 音乐并重",
                "visual_rationale": "测试",
                "visual_confidence": 0.95,
                "audio_rationale": "测试",
                "voiceover_ratio": 0.8,
                "dual_layer": {"enabled": False, "primary": "", "secondary": "", "reason": ""},
                "content_profile": {"key": "narrative_trailer", "label": "剧情预告", "reason": "测试"},
                "fallback": False,
            },
        },
    )
    monkeypatch.setattr(
        ai_analyzer,
        "generate_audiovisual_report_outputs",
        lambda data, *a, **kw: captures["audiovisual_inputs"].append(data)
        or {"data": data, "md": tmp_path / "audiovisual.md"},
    )
    monkeypatch.setattr(
        ai_analyzer,
        "build_verification_payload",
        lambda *a, **kw: {
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
        lambda *args, **kwargs: captures["completed_calls"].append(
            {"args": args, "kwargs": kwargs}
        ),
    )

    return captures
