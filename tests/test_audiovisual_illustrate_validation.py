from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from audiovisual.reporting import template_engine
from audiovisual.reporting.builder import (
    _annotate_image_captions,
    _validate_illustrated_markdown,
)


def _catalog(*rel_paths: str) -> list[dict]:
    return [{"scene_number": idx + 1, "rel_path": rel} for idx, rel in enumerate(rel_paths)]


def _catalog_full(*entries: tuple[int, str, str, str]) -> list[dict]:
    return [
        {"scene_number": num, "rel_path": rel, "timestamp": ts, "visual": visual}
        for num, rel, ts, visual in entries
    ]


def test_validate_illustrate_passes_when_paths_in_catalog() -> None:
    original = "## 主题\n\n段落 A 提到 Scene 1。\n"
    illustrated = (
        "## 主题\n\n段落 A 提到 Scene 1。\n\n![Scene 001](<scenes/001.png>)\n"
    )
    _validate_illustrated_markdown(illustrated, original, _catalog("scenes/001.png"))


def test_validate_illustrate_rejects_fabricated_paths() -> None:
    original = "## 主题\n\n段落 A 提到 Scene 1。\n"
    illustrated = (
        "## 主题\n\n段落 A 提到 Scene 1。\n\n![Scene 001](<scenes/fake.png>)\n"
    )
    with pytest.raises(ValueError, match="目录外"):
        _validate_illustrated_markdown(illustrated, original, _catalog("scenes/001.png"))


def test_validate_illustrate_rejects_dedupe_within_window() -> None:
    original = "## 主题\n\n第一段。\n\n第二段。\n\n第三段。\n"
    illustrated = (
        "## 主题\n\n"
        "第一段。\n\n![a](<scenes/001.png>)\n\n"
        "第二段。\n\n![b](<scenes/001.png>)\n"
    )
    with pytest.raises(ValueError, match="重复"):
        _validate_illustrated_markdown(illustrated, original, _catalog("scenes/001.png"))


def test_validate_illustrate_allows_preexisting_images() -> None:
    original = "## 主题\n\n![original](<pre/existing.png>)\n\n段落 A。\n"
    illustrated = (
        "## 主题\n\n![original](<pre/existing.png>)\n\n段落 A。\n\n![Scene 1](<scenes/001.png>)\n"
    )
    _validate_illustrated_markdown(illustrated, original, _catalog("scenes/001.png"))


def test_annotate_image_captions_adds_scene_caption_below_new_image() -> None:
    catalog = _catalog_full((3, "scenes/003.png", "00:12-00:18", "少年在窗边远眺，光偏暖"))
    original = "## 主题\n\n段落 A 提到 Scene 3。\n"
    illustrated = "## 主题\n\n段落 A 提到 Scene 3。\n\n![Scene 003](<scenes/003.png>)\n"
    annotated = _annotate_image_captions(illustrated, original, catalog)
    assert "*Scene 003 · 00:12-00:18 · 画面：少年在窗边远眺，光偏暖*" in annotated
    # caption sits on the line right after the image (after a blank line)
    assert "![Scene 003](<scenes/003.png>)\n\n*Scene 003" in annotated


def test_annotate_image_captions_skips_preexisting_images() -> None:
    catalog = _catalog_full((1, "pre/existing.png", "00:00-00:05", "原有图片"))
    original = "## 主题\n\n![pre](<pre/existing.png>)\n"
    annotated = _annotate_image_captions(original, original, catalog)
    assert "*Scene" not in annotated


def test_annotate_image_captions_idempotent_when_caption_already_present() -> None:
    catalog = _catalog_full((1, "scenes/001.png", "00:01-00:03", "开场全景"))
    original = "段落\n"
    illustrated = (
        "段落\n\n![Scene 001](<scenes/001.png>)\n\n*Scene 001 · 00:01-00:03 · 画面：开场全景*\n"
    )
    annotated = _annotate_image_captions(illustrated, original, catalog)
    # caption should not be duplicated
    assert annotated.count("*Scene 001 · 00:01-00:03 · 画面：开场全景*") == 1


def test_inject_figure_blocks_no_longer_appends_trailing_gallery(monkeypatch) -> None:
    """Body without FIGURE markers must not get a tail-of-report figure dump."""
    monkeypatch.setattr(
        template_engine,
        "_highlight_specs_for_route",
        lambda data, route: [
            ("opening", {"scene_number": 1, "screenshot": "scenes/001.png"}, "note"),
        ],
    )
    body = "## 模块 A\n\n正文。\n"
    result = template_engine._inject_figure_blocks(body, {}, {}, None)
    assert result == body


def test_extract_dimension_evaluations_strips_section_and_parses_lines() -> None:
    body = (
        "## 模块 A\n\n正文 A。\n\n"
        "## 维度速评\n\n"
        "- 冲击力：开场快切到 Scene 003 的高对比镜头，瞬间抓住注意力。\n"
        "- 美学：色彩统一在偏暖的工业色调，但 Scene 014 出现噪点拉低质感。\n"
        "- 记忆度：母题反复出现于 Scene 002 与 Scene 011，记忆点清晰。\n"
        "- 趣味性：节奏前段紧凑，但中段 Scene 020-024 重复同类镜头略显疲态。\n"
        "- 可信度：旁白与画面在 Scene 008 出现错位，可信度受影响。\n"
        "- 信息效率：每段落都有明确推进，单位时间信息密度足够高。\n"
    )
    stripped, parsed = template_engine._extract_dimension_evaluations(body)
    assert "## 维度速评" not in stripped
    assert "## 模块 A" in stripped
    assert parsed["impact"].startswith("开场快切")
    assert parsed["info_efficiency"].startswith("每段落都有明确推进")
    assert set(parsed.keys()) == {
        "impact",
        "aesthetic",
        "memorability",
        "fun",
        "credibility",
        "info_efficiency",
    }


def test_extract_dimension_evaluations_returns_unchanged_when_section_missing() -> None:
    body = "## 模块 A\n\n正文。\n"
    stripped, parsed = template_engine._extract_dimension_evaluations(body)
    assert stripped == body
    assert parsed == {}


def test_dimension_eval_context_falls_back_when_partial() -> None:
    ctx = template_engine._dimension_eval_context({"impact": "本片冲击力很强"})
    assert ctx["eval_impact"] == "本片冲击力很强"
    # missing dims fall back to fixed descriptions, never raise
    assert ctx["eval_aesthetic"]
    assert ctx["eval_info_efficiency"]
