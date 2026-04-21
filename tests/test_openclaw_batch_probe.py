from pathlib import Path
import json
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import openclaw_batch_probe


def _write_batch_input(path: Path, batch_id: str, scene_numbers: list[int]) -> None:
    payload = {
        "batch_id": batch_id,
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
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_collect_probe_scenes_spans_multiple_batches(tmp_path: Path) -> None:
    host_batches = tmp_path / "video" / "host_batches"
    host_batches.mkdir(parents=True)
    (host_batches / "index.json").write_text(
        json.dumps(
            {
                "batches": [
                    {"batch_id": "batch-001", "input": "batch-001-input.json"},
                    {"batch_id": "batch-002", "input": "batch-002-input.json"},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    _write_batch_input(host_batches / "batch-001-input.json", "batch-001", [1, 2])
    _write_batch_input(host_batches / "batch-002-input.json", "batch-002", [3, 4])

    scenes = openclaw_batch_probe.collect_probe_scenes(host_batches, target_count=3)

    assert [scene["scene_number"] for scene in scenes] == [1, 2, 3]
    assert [scene["batch_id"] for scene in scenes] == ["batch-001", "batch-001", "batch-002"]
    assert scenes[0]["frames"]["primary"] == str((host_batches.parent / "frames/scene-001.jpg").resolve())


def test_find_models_json_candidates_prefers_main_agent_then_other_agents(tmp_path: Path) -> None:
    openclaw_root = tmp_path / ".openclaw" / "agents"
    second = openclaw_root / "second" / "agent"
    main = openclaw_root / "main" / "agent"
    alpha = openclaw_root / "alpha" / "agent"
    for directory in (second, main, alpha):
        directory.mkdir(parents=True)
        (directory / "models.json").write_text("{}", encoding="utf-8")

    candidates = openclaw_batch_probe.find_models_json_candidates(openclaw_root.parent)

    assert candidates[0] == main / "models.json"
    assert candidates[1:] == [alpha / "models.json", second / "models.json"]


def test_build_attempt_order_keeps_preferred_then_fallbacks() -> None:
    providers = {
        "kcode": {
            "models": [{"id": "K2.6-code-preview", "input": ["text"]}],
        },
        "zai": {
            "models": [{"id": "GLM-5V-Turbo", "input": ["text", "image"]}],
        },
    }

    attempts = openclaw_batch_probe.build_attempt_order(
        providers,
        preferred_model="kcode/K2.6-code-preview",
        fallback_models=["zai/GLM-5V-Turbo", "zai/GLM-5V-Turbo"],
    )

    assert [attempt["model_ref"] for attempt in attempts] == [
        "kcode/K2.6-code-preview",
        "zai/GLM-5V-Turbo",
    ]
    assert attempts[0]["declared_image_support"] is False
    assert attempts[1]["declared_image_support"] is True


def test_build_batch_like_output_uses_probe_receipt() -> None:
    scene_result = {
        "scene_number": 1,
        "type_classification": "TYPE-A Hook",
        "description": "测试画面",
        "visual_summary": "测试摘要",
        "storyboard": {
            "shot_size": "中景",
            "lighting": "硬光",
            "camera_movement": "推进",
            "visual_style": "MV",
            "technique": "快速切换",
        },
        "scores": {
            "aesthetic_beauty": 8,
            "credibility": 7,
            "impact": 9,
            "memorability": 8,
            "fun_interest": 7,
        },
        "selection_reasoning": "强冲击开场",
        "edit_suggestion": "保留作前奏钩子",
    }

    payload = openclaw_batch_probe.build_batch_like_output(
        batch_id="probe-n1",
        scene_results=[scene_result],
        model_ref="zai/GLM-5V-Turbo",
    )

    assert payload["batch_id"] == "probe-n1"
    assert payload["receipt"]["status"] == "completed"
    assert payload["receipt"]["has_todo"] is False
    assert "zai/GLM-5V-Turbo" in payload["receipt"]["worker_summary"]
    assert payload["scenes"][0]["scene_number"] == 1


def test_load_data_url_uses_base64_payload(tmp_path: Path) -> None:
    image_path = tmp_path / "sample.jpg"
    image_path.write_bytes(b"abc")

    data_url = openclaw_batch_probe._load_data_url(image_path)

    assert data_url.startswith("data:image/jpeg;base64,")
    assert data_url.endswith("YWJj")


def test_normalize_base_url_strips_duplicate_v1_for_anthropic_style() -> None:
    normalized = openclaw_batch_probe._normalize_base_url(
        "anthropic-messages",
        "https://api.kimi.com/coding/v1",
    )

    assert normalized == "https://api.kimi.com/coding"


def test_analyze_scenes_preserves_input_order_under_parallel_execution() -> None:
    scenes = [
        {"scene_number": 1, "batch_id": "batch-001"},
        {"scene_number": 2, "batch_id": "batch-001"},
        {"scene_number": 3, "batch_id": "batch-001"},
    ]

    def fake_analyzer(scene: dict, attempts: list, total_scenes: int) -> dict:
        time.sleep({1: 0.03, 2: 0.01, 3: 0.02}[scene["scene_number"]])
        number = scene["scene_number"]
        return {
            "scene_result": {
                "scene_number": number,
                "type_classification": "TYPE-B Narrative",
                "description": f"scene-{number}",
                "visual_summary": f"summary-{number}",
                "storyboard": {
                    "shot_size": "中景",
                    "lighting": "硬光",
                    "camera_movement": "静止镜头",
                    "visual_style": "MV",
                    "technique": "测试",
                },
                "scores": {
                    "aesthetic_beauty": 7,
                    "credibility": 7,
                    "impact": 7,
                    "memorability": 7,
                    "fun_interest": 7,
                },
                "selection_reasoning": "ok",
                "edit_suggestion": "ok",
            },
            "used_model": "kcode/K2.6-code-preview",
            "attempts": [{"model_ref": "kcode/K2.6-code-preview", "ok": True, "elapsed_s": 0.01, "error": ""}],
            "elapsed_s": 0.01,
        }

    run_items, successful_results, failed_results = openclaw_batch_probe.analyze_scenes(
        scenes,
        attempts=[],
        max_workers=3,
        analyzer_fn=fake_analyzer,
    )

    assert [item["scene_number"] for item in run_items] == [1, 2, 3]
    assert [scene["scene_number"] for scene in successful_results] == [1, 2, 3]
    assert failed_results == []


def test_analyze_scenes_notifies_each_completed_payload() -> None:
    scenes = [
        {"scene_number": 1, "batch_id": "batch-001"},
        {"scene_number": 2, "batch_id": "batch-001"},
        {"scene_number": 3, "batch_id": "batch-001"},
    ]
    callback_order: list[int] = []

    def fake_analyzer(scene: dict, attempts: list, total_scenes: int) -> dict:
        time.sleep({1: 0.03, 2: 0.01, 3: 0.02}[scene["scene_number"]])
        number = scene["scene_number"]
        return {
            "scene_result": {
                "scene_number": number,
                "type_classification": "TYPE-B Narrative",
                "description": f"scene-{number}",
                "visual_summary": f"summary-{number}",
                "storyboard": {
                    "shot_size": "中景",
                    "lighting": "硬光",
                    "camera_movement": "静止镜头",
                    "visual_style": "MV",
                    "technique": "测试",
                },
                "scores": {
                    "aesthetic_beauty": 7,
                    "credibility": 7,
                    "impact": 7,
                    "memorability": 7,
                    "fun_interest": 7,
                },
                "selection_reasoning": "ok",
                "edit_suggestion": "ok",
            },
            "used_model": "kcode/K2.6-code-preview",
            "attempts": [{"model_ref": "kcode/K2.6-code-preview", "ok": True, "elapsed_s": 0.01, "error": ""}],
            "elapsed_s": 0.01,
        }

    def on_result(payload: dict) -> None:
        callback_order.append(payload["run_item"]["scene_number"])

    run_items, successful_results, failed_results = openclaw_batch_probe.analyze_scenes(
        scenes,
        attempts=[],
        max_workers=3,
        analyzer_fn=fake_analyzer,
        on_result=on_result,
    )

    assert callback_order == [2, 3, 1]
    assert [item["scene_number"] for item in run_items] == [1, 2, 3]
    assert [scene["scene_number"] for scene in successful_results] == [1, 2, 3]
    assert failed_results == []


def test_build_validation_report_compares_against_reference_output() -> None:
    generated = [
        {
            "scene_number": 1,
            "type_classification": "TYPE-A Hook",
            "description": "generated-1",
            "visual_summary": "summary-1",
            "storyboard": {
                "shot_size": "特写",
                "lighting": "硬光",
                "camera_movement": "推进",
                "visual_style": "MV",
                "technique": "强调表情",
            },
            "scores": {
                "aesthetic_beauty": 8,
                "credibility": 7,
                "impact": 9,
                "memorability": 8,
                "fun_interest": 7,
            },
            "selection_reasoning": "reason-1",
            "edit_suggestion": "edit-1",
        },
        {
            "scene_number": 2,
            "type_classification": "TYPE-B Narrative",
            "description": "generated-2",
            "visual_summary": "summary-2",
            "storyboard": {
                "shot_size": "中景",
                "lighting": "柔光",
                "camera_movement": "静止镜头",
                "visual_style": "MV",
                "technique": "强调动作",
            },
            "scores": {
                "aesthetic_beauty": 7,
                "credibility": 8,
                "impact": 6,
                "memorability": 7,
                "fun_interest": 6,
            },
            "selection_reasoning": "reason-2",
            "edit_suggestion": "edit-2",
        },
    ]
    reference = [
        {
            "scene_number": 1,
            "type_classification": "TYPE-A Hook",
            "description": "reference-1",
            "visual_summary": "reference-summary-1",
            "storyboard": {
                "shot_size": "特写",
                "lighting": "硬光",
                "camera_movement": "推进",
                "visual_style": "MV",
                "technique": "强调表情",
            },
            "scores": {
                "aesthetic_beauty": 8,
                "credibility": 7,
                "impact": 8,
                "memorability": 8,
                "fun_interest": 7,
            },
            "selection_reasoning": "reference-reason-1",
            "edit_suggestion": "reference-edit-1",
        },
        {
            "scene_number": 2,
            "type_classification": "TYPE-C Aesthetic",
            "description": "reference-2",
            "visual_summary": "reference-summary-2",
            "storyboard": {
                "shot_size": "中景",
                "lighting": "柔光",
                "camera_movement": "静止镜头",
                "visual_style": "MV",
                "technique": "强调动作",
            },
            "scores": {
                "aesthetic_beauty": 7,
                "credibility": 8,
                "impact": 6,
                "memorability": 7,
                "fun_interest": 6,
            },
            "selection_reasoning": "reference-reason-2",
            "edit_suggestion": "reference-edit-2",
        },
    ]

    report = openclaw_batch_probe.build_validation_report(
        generated_scenes=generated,
        reference_scenes=reference,
        sample_size=2,
    )

    assert report["order_matches_reference"] is True
    assert report["overlap_scene_count"] == 2
    assert report["type_match_rate"] == 0.5
    assert report["sample_scene_numbers"] == [1, 2]
    assert report["samples"][0]["score_deltas"]["impact"] == 1
    assert report["samples"][1]["type_matches"] is False


def test_analyze_scenes_continues_after_single_scene_failure() -> None:
    scenes = [
        {"scene_number": 1, "batch_id": "batch-001"},
        {"scene_number": 2, "batch_id": "batch-001"},
        {"scene_number": 3, "batch_id": "batch-001"},
    ]

    def flaky_analyzer(scene: dict, attempts: list, total_scenes: int) -> dict:
        number = scene["scene_number"]
        if number == 2:
            raise openclaw_batch_probe.ProbeFailure(
                "scene 2 failed",
                [{"model_ref": "x/y", "ok": False, "elapsed_s": 0.01, "error": "500"}],
            )
        return {
            "scene_result": {
                "scene_number": number,
                "type_classification": "TYPE-B Narrative",
                "description": f"scene-{number}",
                "visual_summary": f"summary-{number}",
                "storyboard": {
                    "shot_size": "中景",
                    "lighting": "硬光",
                    "camera_movement": "静止镜头",
                    "visual_style": "MV",
                    "technique": "测试",
                },
                "scores": {
                    "aesthetic_beauty": 7,
                    "credibility": 7,
                    "impact": 7,
                    "memorability": 7,
                    "fun_interest": 7,
                },
                "selection_reasoning": "ok",
                "edit_suggestion": "ok",
            },
            "used_model": "kcode/K2.6-code-preview",
            "attempts": [{"model_ref": "kcode/K2.6-code-preview", "ok": True, "elapsed_s": 0.01, "error": ""}],
            "elapsed_s": 0.01,
        }

    run_items, successful_results, failed_results = openclaw_batch_probe.analyze_scenes(
        scenes,
        attempts=[],
        max_workers=1,
        analyzer_fn=flaky_analyzer,
    )

    assert [item["scene_number"] for item in run_items] == [1, 2, 3]
    assert [item.get("ok") for item in run_items] == [True, False, True]
    assert [scene["scene_number"] for scene in successful_results] == [1, 3]
    assert len(failed_results) == 1
    assert failed_results[0]["scene_number"] == 2
    assert "scene 2 failed" in failed_results[0]["error"]
    assert failed_results[0]["attempts"][0]["model_ref"] == "x/y"
