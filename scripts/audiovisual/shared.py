#!/usr/bin/env python3
from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import re
from typing import Dict, List, Sequence
from urllib.parse import unquote

_MARKDOWN_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\((?:<([^>]+)>|([^)]+))\)")

def _safe_text(value: object, fallback: str = "") -> str:
    text = str(value or "").strip()
    return fallback if not text or text.upper().startswith("TODO") else text


def _avg(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _top_text(values: Sequence[str], limit: int = 3) -> str:
    items = Counter(value for value in values if value).most_common(limit)
    return "、".join(item for item, _ in items) if items else "未形成稳定偏好"


def _voiceover(scene: Dict) -> str:
    storyboard = scene.get("storyboard", {})
    return _safe_text(storyboard.get("voiceover") or scene.get("voiceover"))


def _onscreen_text(scene: Dict) -> str:
    storyboard = scene.get("storyboard", {})
    return _safe_text(storyboard.get("onscreen_text") or scene.get("onscreen_text"))


def _scene_desc(scene: Dict) -> str:
    return _safe_text(scene.get("description") or scene.get("visual_description"))


def _scene_screenshot(scene: Dict) -> str:
    storyboard = scene.get("storyboard", {})
    return _safe_text(
        storyboard.get("screenshot_path")
        or scene.get("screenshot_path")
        or scene.get("frame_path")
    )


def _relative_media_path(path_text: str, report_dir: Path | None) -> str:
    if not path_text or report_dir is None:
        return ""
    path = Path(path_text)
    if not path.is_absolute():
        return path.as_posix()
    try:
        relative = path.relative_to(report_dir)
    except ValueError:
        try:
            relative = Path(path).resolve().relative_to(report_dir.resolve())
        except (ValueError, OSError):
            relative = path
    return relative.as_posix()


def _markdown_media_path(path_text: str, report_dir: Path | None) -> str:
    """Return a raw (unencoded) relative path suitable for wrapping in an
    angle-bracket markdown image link: ``![alt](<path>)``.

    We intentionally do not URL-encode: Obsidian does not reliably resolve
    percent-encoded paths for vault-internal images, and angle brackets let
    the raw path (including spaces and unicode) pass through cleanly.
    """
    rel_path = _relative_media_path(path_text, report_dir)
    if not rel_path:
        return ""
    return rel_path


def _decode_markdown_media_path(path_text: str) -> str:
    return unquote(str(path_text or "").strip())


def _normalize_markdown_image_links(markdown_text: str, report_dir: Path | None) -> str:
    if not markdown_text:
        return ""

    def _replace(match: re.Match[str]) -> str:
        alt_text = match.group(1)
        raw_path = _decode_markdown_media_path(match.group(2) or match.group(3) or "")
        if not raw_path or raw_path.startswith(("http://", "https://", "data:")):
            return match.group(0)
        normalized = _markdown_media_path(raw_path, report_dir) or raw_path
        return f"![{alt_text}](<{normalized}>)"

    return _MARKDOWN_IMAGE_RE.sub(_replace, markdown_text)


def _title_text(data: Dict) -> str:
    return _safe_text(data.get("title") or data.get("video_title") or data.get("video_id"))


def _scene_haystack(scene: Dict) -> str:
    return " ".join(
        [
            _scene_desc(scene),
            _voiceover(scene),
            _onscreen_text(scene),
            _safe_text(scene.get("storyboard", {}).get("shot_size")),
            _safe_text(scene.get("storyboard", {}).get("visual_style")),
            _safe_text(scene.get("storyboard", {}).get("technique")),
        ]
    )


def _scene_slice(
    scenes: Sequence[Dict],
    start_ratio: float,
    end_ratio: float = 1.0,
    *,
    min_items: int = 1,
) -> List[Dict]:
    if not scenes:
        return []
    total = len(scenes)
    start_index = max(0, min(total - 1, int(total * start_ratio)))
    end_index = max(start_index + min_items, int(total * end_ratio) or total)
    return list(scenes[start_index:min(total, end_index)])


def _group_scenes_by_count(scenes: Sequence[Dict]) -> Dict[str, List[Dict]]:
    ordered = list(scenes)
    total = len(ordered)
    if not ordered:
        return {"opening": [], "middle": [], "closing": []}
    if total == 1:
        return {"opening": ordered[:1], "middle": ordered[:1], "closing": ordered[:1], "_mode": "single"}
    if total == 2:
        return {"opening": ordered[:1], "middle": ordered[1:], "closing": ordered[1:], "_mode": "paired"}
    if total == 3:
        return {"opening": ordered[:1], "middle": ordered[1:2], "closing": ordered[2:], "_mode": "minimal"}
    return {"_mode": "full"}


def _merge_context_row(base_scene: Dict, context_row: Dict) -> Dict:
    merged = dict(base_scene or {})
    storyboard = dict(merged.get("storyboard", {}))

    for field in ("voiceover", "onscreen_text", "shot_size", "lighting", "camera_movement", "visual_style", "technique"):
        value = _safe_text(context_row.get(field))
        if value:
            storyboard[field] = value

    screenshot_path = _safe_text(context_row.get("screenshot_path"))
    if screenshot_path:
        storyboard["screenshot_path"] = screenshot_path
        merged["frame_path"] = merged.get("frame_path") or screenshot_path

    timestamp = _safe_text(context_row.get("timestamp"))
    if timestamp:
        storyboard["timestamp"] = timestamp
        merged["timestamp_range"] = merged.get("timestamp_range") or timestamp

    visual_description = _safe_text(context_row.get("visual_description"))
    if visual_description:
        merged["description"] = merged.get("description") or visual_description
        merged["visual_description"] = merged.get("visual_description") or visual_description

    for field in ("visual_summary", "story_role", "story_function"):
        value = _safe_text(context_row.get(field))
        if value:
            merged[field] = value

    if storyboard:
        merged["storyboard"] = storyboard
    return merged


def _analysis_rows(data: Dict) -> List[Dict]:
    scenes = data.get("scenes", [])
    scenes_by_number = {
        int(scene.get("scene_number", 0)): dict(scene)
        for scene in scenes
        if int(scene.get("scene_number", 0)) > 0
    }
    context_rows = data.get("storyboard_context_rows") or []
    if not context_rows:
        return sorted([dict(scene) for scene in scenes], key=lambda scene: int(scene.get("scene_number", 0)))

    merged_rows: List[Dict] = []
    seen_numbers = set()
    for row in sorted(context_rows, key=lambda scene: int(scene.get("scene_number", 0))):
        scene_number = int(row.get("scene_number", 0))
        merged_rows.append(_merge_context_row(scenes_by_number.get(scene_number, {}), row))
        seen_numbers.add(scene_number)

    for scene in sorted([dict(scene) for scene in scenes], key=lambda item: int(item.get("scene_number", 0))):
        scene_number = int(scene.get("scene_number", 0))
        if scene_number not in seen_numbers:
            merged_rows.append(scene)

    return sorted(merged_rows, key=lambda scene: int(scene.get("scene_number", 0)))


__all__ = [name for name in globals() if name.startswith("_")]
