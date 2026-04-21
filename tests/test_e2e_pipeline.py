"""End-to-end coverage for the prepare → score → merge → finalize chain.

Why this exists:

The unit tests in test_ai_analyzer.py exercise each pipeline stage in
isolation, but no single test confirms that *real* code from one stage flows
into the next. That's exactly the seam where regressions hide — a change to
the receipt schema, scene-resource shape, or run_state transitions can pass
every unit test and still break the integration.

This test drives the four stages directly (rather than through ``main``) so
each phase exercises real production code, with only the LLM call and the
PIL-based contact sheet stubbed out. After each stage we re-read the
on-disk artefacts and assert the expected state transition occurred.
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
import host_batching
import openclaw_batch_probe


def _scene(scene_number: int) -> Dict[str, Any]:
    return {
        "scene_number": scene_number,
        "filename": f"scene-{scene_number:03d}.mp4",
        "timestamp_range": f"00:00:0{scene_number},000 --> 00:00:0{scene_number},900",
        "duration_seconds": 0.9,
        "frame_path": f"frames/scene-{scene_number:03d}.jpg",
        "frame_samples": {
            "primary": f"frames/scene-{scene_number:03d}.jpg",
            "start": f"frames/scene-{scene_number:03d}__start.jpg",
            "mid": f"frames/scene-{scene_number:03d}__mid.jpg",
            "end": f"frames/scene-{scene_number:03d}__end.jpg",
        },
        "storyboard": {
            "voiceover": "",
            "onscreen_text": "",
            "camera_movement_hint": "静止镜头",
            "screenshot_path": f"frames/scene-{scene_number:03d}.jpg",
        },
        "type_classification": "TODO",
        "description": "TODO",
        "visual_summary": "",
        "scores": {},
        "selection_reasoning": "",
        "edit_suggestion": "",
        "notes": "",
    }


def _llm_result(scene_number: int) -> Dict[str, Any]:
    """Canned LLM output: a fully-scored scene that should pass merge."""
    return {
        "scene_number": scene_number,
        "type_classification": "TYPE-A Hook",
        "description": f"Scene {scene_number} description.",
        "visual_summary": f"Scene {scene_number} visual summary.",
        "storyboard": {
            "shot_size": "中景",
            "lighting": "自然光",
            "camera_movement": "固定",
            "visual_style": "写实",
            "technique": "手持",
        },
        "scores": {
            "aesthetic_beauty": 8,
            "credibility": 7,
            "impact": 9,
            "memorability": 8,
            "fun_interest": 6,
        },
        "selection_reasoning": f"Reasoning for scene {scene_number}.",
        "edit_suggestion": "keep",
        "notes": "",
    }


def test_prepare_score_merge_finalize_drives_state_to_completed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # ── stage 0: seed video_dir + scores_path with two pending scenes ──
    video_dir = tmp_path
    frames_dir = video_dir / "frames"
    frames_dir.mkdir(parents=True)
    for scene_number in (1, 2):
        for suffix in ("", "__start", "__mid", "__end"):
            (frames_dir / f"scene-{scene_number:03d}{suffix}.jpg").write_bytes(b"frame")

    scores_path = video_dir / "scene_scores.json"
    initial_data = {"video_id": "demo", "scenes": [_scene(1), _scene(2)]}
    scores_path.write_text(json.dumps(initial_data, ensure_ascii=False), encoding="utf-8")

    # No PIL contact-sheet rendering in this test environment.
    monkeypatch.setattr(host_batching, "_ensure_contact_sheet", lambda *a, **kw: None)

    # ── stage 1: prepare ──────────────────────────────────────────────
    index = host_batching.prepare_host_batches(initial_data, video_dir, batch_size=2)
    assert index["total_batches"] == 1
    assert index["coverage_ratio"] == 0.0

    host_dir = video_dir / "host_batches"
    assert (host_dir / "index.json").exists()
    assert (host_dir / "batch-001-input.json").exists()
    assert (host_dir / "batch-001-output.json").exists()

    output_after_prepare = json.loads(
        (host_dir / "batch-001-output.json").read_text(encoding="utf-8")
    )
    assert output_after_prepare["receipt"]["status"] == "pending"
    assert output_after_prepare["receipt"]["has_todo"] is True

    # ── stage 2: score (auto_fill_pending_batches with stubbed LLM) ──
    monkeypatch.setattr(
        openclaw_batch_probe,
        "build_attempt_order",
        lambda *a, **kw: [{"model_ref": "demo/model"}],
    )

    def fake_analyze_scenes(scenes, attempts, max_workers=1, analyzer_fn=None, on_result=None):
        run_items: List[Dict[str, Any]] = []
        successful: List[Dict[str, Any]] = []
        for index_, packet in enumerate(scenes):
            scene_number = int(packet.get("scene_number", 0) or 0)
            scene_result = _llm_result(scene_number)
            run_item = {
                "scene_number": scene_number,
                "batch_id": packet.get("batch_id", "batch-001"),
                "ok": True,
                "used_model": "demo/model",
                "elapsed_s": 0.1,
                "attempts": [],
            }
            payload = {
                "index": index_,
                "run_item": run_item,
                "scene_result": scene_result,
                "failed": None,
            }
            if on_result is not None:
                on_result(payload)
            run_items.append(run_item)
            successful.append(scene_result)
        return run_items, successful, []

    monkeypatch.setattr(openclaw_batch_probe, "analyze_scenes", fake_analyze_scenes)

    score_summary = ai_analyzer.auto_fill_pending_batches(
        scores_path,
        video_dir,
        {
            "config_source": "env",
            "providers": {"demo": {"models": [{"id": "model", "input": ["text", "image"]}]}},
            "preferred_model": "demo/model",
            "fallback_models": [],
        },
        max_workers=1,
    )
    assert score_summary["scored_scenes"] == 2
    assert score_summary["failed_scenes"] == 0
    assert "batch-001" in score_summary["completed_batches"]

    output_after_score = json.loads(
        (host_dir / "batch-001-output.json").read_text(encoding="utf-8")
    )
    assert output_after_score["receipt"]["status"] == "completed"
    assert output_after_score["receipt"]["has_todo"] is False
    # Both scenes should now carry the LLM-supplied descriptions.
    descriptions = [scene["description"] for scene in output_after_score["scenes"]]
    assert descriptions == ["Scene 1 description.", "Scene 2 description."]

    # ── stage 3: merge ────────────────────────────────────────────────
    merged = host_batching.merge_host_batch_outputs(scores_path, video_dir)
    assert len(merged["scenes"]) == 2
    for scene in merged["scenes"]:
        # weighted_score and selection only get computed once the scene
        # has both a description and full scores — proves both the LLM
        # write-back and the score-recompute hooked together.
        assert scene["weighted_score"] > 0
        assert scene["selection"] in ("[MUST KEEP]", "[USABLE]")

    persisted = json.loads(scores_path.read_text(encoding="utf-8"))
    assert [s["scene_number"] for s in persisted["scenes"]] == [1, 2]
    assert persisted["scenes"][0]["scores"]["impact"] == 9

    # The index.json coverage_ratio must now reflect both scenes done.
    refreshed_index = json.loads((host_dir / "index.json").read_text(encoding="utf-8"))
    assert refreshed_index["completed_scenes"] == 2
    assert refreshed_index["coverage_ratio"] == 1.0

    # ── stage 4: finalize (mark_completed_state) ─────────────────────
    # Stub the two delivery hooks that touch the filesystem in ways
    # unrelated to the prepare/score/merge contract under test.
    write_delivery_calls: List[tuple] = []
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
        "write_delivery_report",
        lambda *args, **kwargs: write_delivery_calls.append(args) or {"path": ""},
    )

    state_path = ai_analyzer.run_state_path_for(scores_path)
    final_state = ai_analyzer.mark_completed_state(
        state_path,
        scores_path,
        video_dir,
        merged,
        ("md",),
    )

    assert final_state["status"] == "completed"
    assert final_state["current_stage"] == "completed"
    assert final_state["can_finalize"] is True
    assert final_state["coverage_ratio"] == 1.0
    assert final_state["completed_scenes"] == 2

    # The on-disk run_state.json must agree with the in-memory state we got back.
    persisted_state = json.loads(state_path.read_text(encoding="utf-8"))
    assert persisted_state["status"] == "completed"
    assert persisted_state["completed_scenes"] == 2

    # Delivery report must have been written exactly once during finalize.
    assert len(write_delivery_calls) == 1
