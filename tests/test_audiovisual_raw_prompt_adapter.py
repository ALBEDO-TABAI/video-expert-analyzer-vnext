from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import audiovisual.reporting.raw_prompt_adapter as raw_prompt_adapter


RAW_PROMPT_CASES = [
    ("concept_mv", "concept_mv", "concept-mv-storyboard-analysis-prompt.md"),
    ("performance_mv", "narrative_performance", "performance-mv-storyboard-analysis-prompt.md"),
    ("live_session", "narrative_performance", "live-session-storyboard-analysis-prompt.md"),
    ("narrative_short", "narrative_performance", "narrative-short-storyboard-analysis-prompt.md"),
    ("talking_head", "lecture_performance", "talking-head-storyboard-analysis-prompt.md"),
    ("commentary_remix", "commentary_mix", "video-essay-storyboard-analysis-prompt.md"),
    ("documentary_essay", "documentary_generic", "documentary-storyboard-analysis-prompt.md"),
    ("brand_film", "journey_brand_film", "ad-brand-campaign-storyboard-analysis-prompt.md"),
    ("event_promo", "event_brand_ad", "event-promo-storyboard-analysis-prompt.md"),
    ("explainer", "technical_explainer", "explainer-storyboard-analysis-prompt.md"),
    ("infographic_motion", "infographic_animation", "infographic-motion-storyboard-analysis-prompt.md"),
    ("narrative_trailer", "narrative_trailer", "trailer-analysis-prompt.md"),
    ("rhythm_remix", "mix_music", "rhythm-remix-storyboard-analysis-prompt.md"),
    ("mood_montage", "cinematic_life", "mood-montage-storyboard-analysis-prompt.md"),
    ("cinematic_vlog", "cinematic_life", "cinematic-vlog-storyboard-analysis-prompt.md"),
    ("reality_record", "documentary_generic", "reality-record-storyboard-analysis-prompt.md"),
    ("meme_viral", "meme", "meme-viral-storyboard-analysis-prompt.md"),
    ("motion_graphics", "pure_motion_graphics", "motion-graphics-storyboard-analysis-prompt.md"),
    ("experimental", "experimental", "experimental-storyboard-analysis-prompt.md"),
]


def _payload(type_key: str, framework: str) -> dict:
    route = {
        "framework": framework,
        "route_label": framework,
        "route_subtype": "",
        "child_type": type_key,
        "child_type_cn": type_key,
        "reference": "测试",
        "visual_axis": "S",
        "visual_label": "测试",
        "audio_axis": "L",
        "audio_label": "测试",
        "visual_rationale": "测试",
        "audio_rationale": "测试",
        "voiceover_ratio": 0.3,
        "dual_layer": {"enabled": False},
        "content_profile": {"key": framework},
    }
    return {
        "video_id": f"raw-{type_key}",
        "title": f"Raw {type_key}",
        "video_title": f"Raw {type_key}",
        "audiovisual_route": route,
        "classification_result": {
            "classification": {
                "type": type_key,
                "type_cn": type_key,
                "confidence": "high",
            },
            "applied_route": route,
        },
    }


def _storyboard_payload(scene_count: int = 18) -> dict:
    rows = []
    for i in range(1, scene_count + 1):
        rows.append(
            {
                "scene_number": i,
                "timestamp": f"00:{i:02d}",
                "visual_summary": f"画面摘要 {i}",
                "story_role": f"角色 {i}",
                "story_function": f"功能 {i}",
                "visual_description": f"画面描述 {i}",
                "voiceover": f"旁白 {i}",
                "onscreen_text": f"文字 {i}",
                "shot_size": "中景",
                "lighting": "自然光",
                "camera_movement": "推进",
                "visual_style": "测试风格",
                "technique": "测试手法",
            }
        )
    return {
        "video_id": "raw-scenes",
        "title": "Raw scenes",
        "video_title": "Raw scenes",
        "storyboard_context_rows": rows,
        "scenes": [{"scene_number": i} for i in range(1, scene_count + 1)],
    }


@pytest.mark.parametrize(("type_key", "framework", "expected_name"), RAW_PROMPT_CASES)
def test_raw_prompt_path_resolution_for_stable_types(type_key: str, framework: str, expected_name: str) -> None:
    payload = _payload(type_key, framework)

    prompt_path = raw_prompt_adapter.resolve_raw_prompt_path_for_data(payload, payload["audiovisual_route"])

    assert prompt_path is not None
    assert prompt_path.name == expected_name


def test_raw_prompt_resolution_returns_none_for_unmapped_type() -> None:
    payload = _payload("unknown_type", "narrative_performance")

    prompt_path = raw_prompt_adapter.resolve_raw_prompt_path_for_data(payload, payload["audiovisual_route"])

    assert prompt_path is None


@pytest.mark.parametrize("framework", ["cinematic_life", "mix_music", "pure_motion_graphics"])
def test_mood_montage_uses_same_raw_prompt_across_framework_variants(framework: str) -> None:
    payload = _payload("mood_montage", framework)

    prompt_path = raw_prompt_adapter.resolve_raw_prompt_path_for_data(payload, payload["audiovisual_route"])

    assert prompt_path is not None
    assert prompt_path.name == "mood-montage-storyboard-analysis-prompt.md"


def test_sanitized_prompt_removes_low_value_sections() -> None:
    payload = _payload("commentary_remix", "commentary_mix")

    prompt_text = raw_prompt_adapter.load_sanitized_raw_prompt_for_data(payload, payload["audiovisual_route"])

    assert "## SYSTEM ROLE" in prompt_text
    assert "## ANALYSIS PIPELINE" in prompt_text
    assert "## THEORETICAL ANCHORS" not in prompt_text
    assert "## INPUT FORMAT" not in prompt_text
    assert "## REFERENCES" not in prompt_text


def test_extract_required_sections_from_raw_prompt() -> None:
    payload = _payload("commentary_remix", "commentary_mix")
    prompt_text = raw_prompt_adapter.load_sanitized_raw_prompt_for_data(payload, payload["audiovisual_route"])

    headings = raw_prompt_adapter.extract_required_sections_from_raw_prompt(prompt_text)

    assert headings == [
        "论证架构拆解",
        "旁白—画面权力关系",
        "解说者主体性分析",
        "修辞诉求配比与节奏",
        "引用生态系统",
        "视听论证节奏",
        "开场与收束策略",
    ]


def test_dynamic_discovery_picks_up_new_prompt_files(tmp_path: Path) -> None:
    (tmp_path / "brand-new-storyboard-analysis-prompt.md").write_text(
        "## SYSTEM ROLE\nstub\n", encoding="utf-8"
    )

    types = raw_prompt_adapter.available_raw_prompt_types(prompts_dir=tmp_path)
    assert "brand_new" in types

    payload = _payload("brand_new", "experimental")
    prompt_path = raw_prompt_adapter.resolve_raw_prompt_path_for_data(
        payload, payload["audiovisual_route"], prompts_dir=tmp_path
    )
    assert prompt_path is not None
    assert prompt_path.name == "brand-new-storyboard-analysis-prompt.md"


def test_unmapped_type_raises_with_available_type_list(tmp_path: Path) -> None:
    (tmp_path / "alpha-storyboard-analysis-prompt.md").write_text("## SYSTEM ROLE\nstub\n", encoding="utf-8")
    payload = _payload("missing_type", "experimental")

    with pytest.raises(FileNotFoundError) as excinfo:
        raw_prompt_adapter.load_sanitized_raw_prompt_for_data(
            payload, payload["audiovisual_route"], prompts_dir=tmp_path
        )

    msg = str(excinfo.value)
    assert "missing_type" in msg
    assert "alpha" in msg
    assert "Available types" in msg


def test_raw_prompt_scene_packet_prefers_full_scene_coverage() -> None:
    payload = _storyboard_payload(scene_count=18)

    packet = raw_prompt_adapter.build_raw_prompt_scene_packet(payload)

    assert "Scene 001" in packet
    assert "Scene 018" in packet
    assert packet.count("Scene ") >= 18
