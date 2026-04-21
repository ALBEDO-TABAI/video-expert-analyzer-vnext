"""Tests for lightweight classification-summary generation."""

from collections import Counter
from pathlib import Path
import json
import sys


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import ai_analyzer
import classification_summary


def _scene(scene_number: int) -> dict:
    return {
        "scene_number": scene_number,
        "timestamp_range": f"00:00:{scene_number:02d},000 --> 00:00:{scene_number:02d},900",
        "description": f"画面描述 {scene_number}",
        "type_classification": "TYPE-B Narrative" if scene_number % 2 else "TYPE-C Aesthetic",
        "storyboard": {
            "visual_description": f"画面描述 {scene_number}",
            "voiceover": f"旁白 {scene_number}" if scene_number % 3 else "",
            "onscreen_text": f"画面文字 {scene_number}" if scene_number % 5 == 0 else "",
            "shot_size": "中景",
            "lighting": "自然光",
            "camera_movement": "固定",
            "visual_style": "写实",
            "technique": "观察",
        },
    }


def test_build_classification_summary_payload_balances_three_phases() -> None:
    payload = classification_summary.build_classification_summary_payload(
        {
            "video_id": "demo",
            "title": "测试视频",
            "video_title": "测试视频",
            "scenes": [_scene(index) for index in range(1, 64)],
        },
        target_groups=21,
    )

    assert payload["video_title"] == "测试视频"
    assert payload["group_count"] == 21
    assert payload["groups"][0]["scene_start"] == 1
    assert payload["groups"][-1]["scene_end"] == 63
    assert Counter(group["phase"] for group in payload["groups"]) == {
        "opening": 7,
        "middle": 7,
        "closing": 7,
    }


def test_write_classification_summary_outputs_writes_markdown_and_json(tmp_path: Path) -> None:
    outputs = classification_summary.write_classification_summary_outputs(
        {
            "video_id": "demo",
            "title": "测试视频",
            "video_title": "测试视频",
            "scenes": [_scene(index) for index in range(1, 8)],
        },
        tmp_path,
        target_groups=7,
    )

    markdown_text = outputs["md"].read_text(encoding="utf-8")
    json_payload = json.loads(outputs["json"].read_text(encoding="utf-8"))

    assert outputs["md"].exists()
    assert outputs["json"].exists()
    assert "测试视频" in markdown_text
    assert "## 分类分组" in markdown_text
    assert json_payload["group_count"] == 7


def test_expected_output_paths_include_classification_summary_files() -> None:
    outputs = ai_analyzer._expected_output_paths(Path("/tmp/demo"), "video-001", ("md",))

    assert outputs["classification_summary_md"].name == "video-001_classification_summary.md"
    assert outputs["classification_summary_json"].name == "video-001_classification_summary.json"
    assert outputs["classification_result_json"].name == "classification_result.json"
