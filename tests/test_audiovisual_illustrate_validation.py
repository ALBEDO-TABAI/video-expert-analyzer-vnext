from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from audiovisual.reporting.builder import _validate_illustrated_markdown


def _catalog(*rel_paths: str) -> list[dict]:
    return [{"scene_number": idx + 1, "rel_path": rel} for idx, rel in enumerate(rel_paths)]


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
