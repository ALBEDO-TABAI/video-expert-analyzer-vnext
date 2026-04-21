from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from audiovisual.routing.infer import infer_audiovisual_route, infer_content_profile
from audiovisual.reporting.builder import build_audiovisual_report_markdown
from host_batching import _write_batch_brief
from openclaw_dispatch import _worker_prompt


def _music_video_payload() -> dict:
    scenes = []
    descriptions = [
        "黑白复古舞台表演近景，成员直视镜头，整体像无声电影画面。",
        "红色剧院群舞中景，镜头快速推进，属于剧情化 MV 的开场表演。",
        "展示柜中的成员全身远景，周围观众围看，是主题片段里的核心意象。",
        "舞台后场化妆间特写，歌词继续推进角色状态和情绪。",
    ]
    voiceovers = [
        "Why you think that 'bout nude",
        "Think outside the box",
        "Hello my name is 예삐 예삐요",
        "Self-made woman",
    ]
    for index, (description, voiceover) in enumerate(zip(descriptions, voiceovers), start=1):
        scenes.append(
            {
                "scene_number": index,
                "description": description,
                "type_classification": "TYPE-B Narrative",
                "weighted_score": 7.8,
                "scores": {
                    "aesthetic_beauty": 8,
                    "credibility": 6,
                    "impact": 8,
                    "memorability": 7,
                    "fun_interest": 6,
                },
                "storyboard": {
                    "voiceover": voiceover,
                    "onscreen_text": "",
                    "shot_size": "中近景",
                    "visual_style": "复古舞台 / 黑白高对比",
                    "technique": "表演拍摄",
                    "camera_movement": "稳定前推",
                },
            }
        )
    return {
        "video_id": "nxde-test",
        "title": "(여자)아이들((G)I-DLE) - 'Nxde' Official Music Video",
        "video_title": "(여자)아이들((G)I-DLE) - 'Nxde' Official Music Video",
        "scenes": scenes,
    }


def test_music_video_route_is_not_misclassified_as_commentary() -> None:
    data = _music_video_payload()

    profile = infer_content_profile(data)
    route = infer_audiovisual_route(data)

    assert profile["key"] == "music_video"
    assert route["audio_axis"] == "LM"
    assert route["framework"] == "narrative_performance"
    assert route["route_subtype"] == "剧情化 MV"


def test_routing_trace_records_per_branch_threshold_hits() -> None:
    data = _music_video_payload()

    route = infer_audiovisual_route(data)

    trace = route["routing_trace"]
    assert trace["selected"] == "music_video"
    branch_keys = [b["key"] for b in trace["branches"]]
    assert "commentary_analysis" in branch_keys
    assert "music_video" in branch_keys

    # signals snapshot should include voiceover_ratio + music_intent flag
    assert "voiceover_ratio" in trace["signals"]
    assert trace["signals"]["music_intent"] is True

    # each condition must record value, threshold, and hit
    music_branch = next(b for b in trace["branches"] if b["key"] == "music_video")
    assert music_branch["hit"] is True
    cond = music_branch["conditions"][0]
    assert cond["name"] == "music_intent"
    assert cond["hit"] is True

    # commentary branch should record the actual voiceover_ratio + 0.5 threshold
    commentary_branch = next(b for b in trace["branches"] if b["key"] == "commentary_analysis")
    voiceover_cond = next(c for c in commentary_branch["conditions"] if c["name"] == "voiceover_ratio")
    assert voiceover_cond["threshold"] == 0.5
    assert voiceover_cond["op"] == ">="
    assert voiceover_cond["value"] == trace["signals"]["voiceover_ratio"]


def test_music_video_report_does_not_inject_detective_template_language(monkeypatch) -> None:
    import audiovisual.reporting.template_engine as template_engine

    monkeypatch.setattr(
        template_engine,
        "synthesize_audiovisual_report",
        lambda *args, **kwargs: "# 视听剖析报告\n\n## 路由判断\n\n剧情化 MV\n",
    )

    markdown = build_audiovisual_report_markdown(_music_video_payload())

    assert "剧情化 MV" in markdown
    for phrase in ("案件", "调查任务", "侦探", "谁偷了黄金", "真相揭晓"):
        assert phrase not in markdown


def test_worker_prompt_requires_start_mid_end_frames() -> None:
    prompt = _worker_prompt(
        Path("/skill-root"),
        Path("/tmp/scene_scores.json"),
        {
            "batch_id": "batch-001",
            "brief": "/tmp/batch-001-brief.md",
            "contact_sheet": "/tmp/batch-001-contact-sheet.png",
            "input": "/tmp/batch-001-input.json",
            "output": "/tmp/batch-001-output.json",
        },
    )

    assert "start, mid, and end frames" in prompt
    assert "Do not rely on the contact sheet alone" in prompt


def test_batch_brief_requires_three_frame_review(tmp_path: Path) -> None:
    brief_path = _write_batch_brief(
        "batch-001",
        [
            {
                "scene_number": 1,
                "timestamp_range": "00:00:00,000 --> 00:00:01,000",
                "storyboard": {"voiceover": "Why you think that 'bout nude"},
            }
        ],
        tmp_path,
        tmp_path / "batch-001-contact-sheet.png",
        tmp_path / "batch-001-input.json",
        tmp_path / "batch-001-output.json",
    )

    text = brief_path.read_text(encoding="utf-8")

    assert "必须逐个 scene 查看 start / mid / end 三帧" in text
    assert "contact sheet 只用于总览" in text
