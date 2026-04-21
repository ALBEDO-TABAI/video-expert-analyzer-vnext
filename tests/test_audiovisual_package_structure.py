from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


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


def test_new_audiovisual_package_entrypoints_smoke(monkeypatch) -> None:
    from audiovisual.reporting.builder import build_audiovisual_report_markdown
    import audiovisual.reporting.template_engine as template_engine
    from audiovisual.rendering.pdf import build_audiovisual_report_pdf_blocks
    from audiovisual.routing.infer import infer_audiovisual_route

    monkeypatch.setattr(
        template_engine,
        "synthesize_audiovisual_report",
        lambda *args, **kwargs: "# 视听剖析报告\n\n## 路由判断\n\n剧情化 MV\n",
    )

    payload = _music_video_payload()

    route = infer_audiovisual_route(payload)
    markdown = build_audiovisual_report_markdown(payload)
    blocks = build_audiovisual_report_pdf_blocks(payload)

    assert route["framework"] == "narrative_performance"
    assert route["route_subtype"] == "剧情化 MV"
    assert "## 路由判断" in markdown
    assert "剧情化 MV" in markdown
    assert any(block.get("type") == "heading" for block in blocks)
    assert any(block.get("type") == "paragraph" for block in blocks)


def test_old_top_level_audiovisual_modules_are_removed() -> None:
    old_modules = [
        ROOT / "scripts" / "audiovisual_report_builder.py",
        ROOT / "scripts" / "audiovisual_route_engine.py",
        ROOT / "scripts" / "audiovisual_report_sections.py",
        ROOT / "scripts" / "audiovisual_pdf_renderer.py",
        ROOT / "scripts" / "audiovisual_template_engine.py",
    ]
    assert all(not path.exists() for path in old_modules)


def test_new_package_has_no_dynamic_symbol_injection() -> None:
    package_root = ROOT / "scripts" / "audiovisual"
    python_files = sorted(package_root.rglob("*.py"))
    combined = "\n".join(path.read_text(encoding="utf-8") for path in python_files)

    assert "globals().update" not in combined
    assert "_ensure_builder_symbols" not in combined
