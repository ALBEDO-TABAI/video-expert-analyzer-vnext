#!/usr/bin/env python3
"""
Storyboard export helpers for Video Expert Analyzer.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


STORYBOARD_TEXT_FIELDS = (
    "shot_size",
    "lighting",
    "camera_movement",
    "visual_style",
    "technique",
)

ANALYSIS_FIELD_LABELS = {
    "scores.aesthetic_beauty": "美感评分",
    "scores.credibility": "可信度评分",
    "scores.impact": "冲击力评分",
    "scores.memorability": "记忆度评分",
    "scores.fun_interest": "趣味度评分",
    "type_classification": "类型分类",
    "description": "画面描述",
    "weighted_score": "加权总分",
    "selection": "筛选建议",
    "selection_reasoning": "筛选理由",
    "edit_suggestion": "剪辑建议",
    "storyboard.shot_size": "景别",
    "storyboard.lighting": "灯光",
    "storyboard.camera_movement": "运镜",
    "storyboard.visual_style": "画风",
    "storyboard.technique": "手法",
}

FONT_CANDIDATES = (
    Path("C:/Windows/Fonts/msyh.ttc"),
    Path("C:/Windows/Fonts/simsun.ttc"),
    Path("C:/Windows/Fonts/simhei.ttf"),
    Path("/System/Library/Fonts/PingFang.ttc"),
    Path("/Library/Fonts/Arial Unicode.ttf"),
    Path("/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
)

PREFERRED_SUBTITLE_SUFFIXES = (
    "_ocr_corrected.srt",
    ".srt",
)

ONSCREEN_TEXT_SUFFIXES = (
    "_onscreen_text.srt",
    "_embedded.srt",
)


def parse_srt_timestamp(value: str) -> float:
    hours, minutes, rest = value.split(":")
    seconds, millis = rest.split(",")
    return (
        int(hours) * 3600
        + int(minutes) * 60
        + int(seconds)
        + int(millis) / 1000.0
    )


def format_srt_timestamp(seconds: float) -> str:
    safe_seconds = max(seconds, 0.0)
    hours = int(safe_seconds // 3600)
    minutes = int((safe_seconds % 3600) // 60)
    whole_seconds = int(safe_seconds % 60)
    millis = int(round((safe_seconds - int(safe_seconds)) * 1000))
    if millis == 1000:
        millis = 0
        whole_seconds += 1
    if whole_seconds == 60:
        whole_seconds = 0
        minutes += 1
    if minutes == 60:
        minutes = 0
        hours += 1
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d},{millis:03d}"


def format_timestamp_range(start_seconds: float, end_seconds: float) -> str:
    return f"{format_srt_timestamp(start_seconds)} --> {format_srt_timestamp(end_seconds)}"


def parse_timestamp_range(value: str) -> Optional[Tuple[float, float]]:
    if not value or "-->" not in value:
        return None
    start_text, end_text = [part.strip() for part in value.split("-->", 1)]
    try:
        return parse_srt_timestamp(start_text), parse_srt_timestamp(end_text)
    except ValueError:
        return None


def load_srt_segments(srt_path: Path) -> List[Dict]:
    if not srt_path.exists():
        return []

    content = srt_path.read_text(encoding="utf-8", errors="ignore").strip()
    if not content:
        return []

    blocks = re.split(r"\r?\n\r?\n", content)
    segments: List[Dict] = []
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if len(lines) < 2:
            continue
        timestamp_line = lines[1] if "-->" in lines[1] else lines[0]
        if "-->" not in timestamp_line:
            continue
        try:
            start_text, end_text = [part.strip() for part in timestamp_line.split("-->", 1)]
            start_seconds = parse_srt_timestamp(start_text)
            end_seconds = parse_srt_timestamp(end_text)
        except ValueError:
            continue
        text_lines = lines[2:] if timestamp_line == lines[1] else lines[1:]
        text = " ".join(text_lines).strip()
        if not text:
            continue
        segments.append(
            {
                "start": start_seconds,
                "end": end_seconds,
                "text": text,
            }
        )
    return segments


def resolve_storyboard_srt_path(video_dir: Path, video_id: str) -> Optional[Path]:
    for suffix in PREFERRED_SUBTITLE_SUFFIXES:
        candidate = video_dir / f"{video_id}{suffix}"
        if candidate.exists():
            return candidate
    return None


def resolve_onscreen_text_srt_path(video_dir: Path, video_id: str) -> Optional[Path]:
    for suffix in ONSCREEN_TEXT_SUFFIXES:
        candidate = video_dir / f"{video_id}{suffix}"
        if candidate.exists():
            return candidate
    return None


def probe_duration_seconds(media_path: Path) -> Optional[float]:
    if not str(media_path) or str(media_path) == "." or not media_path.exists() or not media_path.is_file():
        return None
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(media_path),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        return float(result.stdout.strip())
    except (subprocess.CalledProcessError, ValueError, OSError):
        return None


def _is_blank(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        stripped = value.strip()
        return not stripped or stripped.upper().startswith("TODO")
    return False


def _movement_group(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return "unknown"
    mapping = {
        "static": ("静止", "固定"),
        "scale_in": ("推进", "前推", "推近", "拉近", "zoom in"),
        "scale_out": ("拉远", "拉开", "后撤", "zoom out"),
        "horizontal": ("横移", "左移", "右移", "摇镜", "摇摄", "平移"),
        "vertical": ("俯仰", "上移", "下移"),
        "tracking": ("跟拍", "跟随", "跟镜"),
    }
    lowered = text.lower()
    for group, keywords in mapping.items():
        if any(keyword in text or keyword in lowered for keyword in keywords):
            return group
    return "unknown"


def _derive_frame_path(video_dir: Path, scene: Dict) -> str:
    existing = scene.get("frame_path")
    if existing:
        return existing

    frames_dir = video_dir / "frames"
    filename = scene.get("filename", "")
    if not filename:
        return ""
    frame_name = Path(filename).with_suffix(".jpg").name
    return str(frames_dir / frame_name)


def _resolve_media_path(path_text: object, base_dir: Path) -> Path:
    raw = str(path_text or "").strip()
    if not raw:
        return Path()
    path = Path(raw)
    if path.is_absolute():
        return path
    return base_dir / path


def _extract_voiceover(
    subtitle_segments: Sequence[Dict],
    start_seconds: float,
    end_seconds: float,
) -> str:
    overlapping: List[str] = []
    for segment in subtitle_segments:
        seg_start = segment.get("start", 0.0)
        seg_end = segment.get("end", 0.0)
        if seg_end < start_seconds or seg_start > end_seconds:
            continue
        text = str(segment.get("text", "")).strip()
        if text and text not in overlapping:
            overlapping.append(text)
    return " / ".join(overlapping)


def enrich_storyboard_data(data: Dict, video_dir: Path, force_text_refresh: bool = False) -> Dict:
    video_id = data.get("video_id", "")
    srt_path = resolve_storyboard_srt_path(video_dir, video_id)
    subtitle_segments = load_srt_segments(srt_path) if srt_path else []
    onscreen_srt_path = resolve_onscreen_text_srt_path(video_dir, video_id)
    onscreen_segments = load_srt_segments(onscreen_srt_path) if onscreen_srt_path else []
    has_corrected_subtitles = bool(srt_path and srt_path.name.endswith("_ocr_corrected.srt"))

    current_start = 0.0
    for scene in data.get("scenes", []):
        timestamp_range = parse_timestamp_range(str(scene.get("timestamp_range", "")))

        start_seconds = scene.get("start_time_seconds")
        end_seconds = scene.get("end_time_seconds")
        duration_seconds = scene.get("duration_seconds")

        if timestamp_range:
            start_seconds = timestamp_range[0] if start_seconds is None else start_seconds
            end_seconds = timestamp_range[1] if end_seconds is None else end_seconds

        if start_seconds is None:
            start_seconds = current_start

        if duration_seconds is None:
            file_path_value = scene.get("file_path", "")
            file_path = _resolve_media_path(file_path_value, video_dir)
            duration_seconds = probe_duration_seconds(file_path)

        if end_seconds is None:
            end_seconds = start_seconds + duration_seconds if duration_seconds is not None else start_seconds

        duration_seconds = max(float(end_seconds) - float(start_seconds), 0.0)
        current_start = float(end_seconds)

        scene["start_time_seconds"] = round(float(start_seconds), 3)
        scene["end_time_seconds"] = round(float(end_seconds), 3)
        scene["duration_seconds"] = round(duration_seconds, 3)
        scene["timestamp_range"] = format_timestamp_range(float(start_seconds), float(end_seconds))

        storyboard = scene.setdefault("storyboard", {})
        if _is_blank(storyboard.get("visual_description")):
            storyboard["visual_description"] = scene.get("description", "")

        motion_analysis = scene.get("motion_analysis", {})
        motion_label = str(motion_analysis.get("label", "")).strip()
        motion_confidence = str(motion_analysis.get("confidence", "")).strip().lower()
        current_camera_movement = str(storyboard.get("camera_movement", "")).strip()
        previous_hint = str(storyboard.get("camera_movement_hint", "")).strip()
        if _is_blank(current_camera_movement) and not _is_blank(motion_label):
            storyboard["camera_movement"] = motion_label
        elif (
            motion_label
            and motion_analysis.get("version")
            and current_camera_movement in {previous_hint, str(scene.get("camera_movement_hint", "")).strip()}
            and current_camera_movement != motion_label
        ):
            storyboard["camera_movement_previous"] = current_camera_movement
            storyboard["camera_movement"] = motion_label
        elif motion_label and current_camera_movement != motion_label and motion_confidence in {"medium", "high"}:
            if not storyboard.get("camera_movement_previous"):
                storyboard["camera_movement_previous"] = current_camera_movement
            storyboard["camera_movement"] = motion_label
        storyboard["camera_movement_hint"] = motion_label
        storyboard["camera_movement_rationale"] = str(motion_analysis.get("rationale", "")).strip()

        if force_text_refresh or has_corrected_subtitles or _is_blank(storyboard.get("voiceover")):
            storyboard["voiceover"] = _extract_voiceover(
                subtitle_segments,
                float(start_seconds),
                float(end_seconds),
            )
        if force_text_refresh or _is_blank(storyboard.get("onscreen_text")):
            storyboard["onscreen_text"] = _extract_voiceover(
                onscreen_segments,
                float(start_seconds),
                float(end_seconds),
            )

        for key in STORYBOARD_TEXT_FIELDS:
            storyboard.setdefault(key, "")
        storyboard.setdefault("onscreen_text", "")

        screenshot_path = _resolve_media_path(scene.get("frame_path") or _derive_frame_path(video_dir, scene), video_dir)
        if scene.get("frame_path"):
            scene["frame_path"] = str(_resolve_media_path(scene.get("frame_path"), video_dir))
        storyboard["screenshot_path"] = str(screenshot_path) if str(screenshot_path) else ""
        storyboard["timestamp"] = scene["timestamp_range"]

    return data


def scene_has_complete_analysis(scene: Dict) -> bool:
    return len(scene_missing_analysis_fields(scene)) == 0


def scene_missing_analysis_fields(scene: Dict) -> List[str]:
    scores = scene.get("scores", {})
    required_scores = (
        "aesthetic_beauty",
        "credibility",
        "impact",
        "memorability",
        "fun_interest",
    )
    missing: List[str] = []
    for key in required_scores:
        if not isinstance(scores.get(key), (int, float)) or scores.get(key, 0) <= 0:
            missing.append(f"scores.{key}")

    if _is_blank(scene.get("type_classification")) or _is_blank(scene.get("description")):
        if _is_blank(scene.get("type_classification")):
            missing.append("type_classification")
        if _is_blank(scene.get("description")):
            missing.append("description")

    if not isinstance(scene.get("weighted_score"), (int, float)) or scene.get("weighted_score", 0) <= 0:
        missing.append("weighted_score")

    if _is_blank(scene.get("selection")):
        missing.append("selection")
    if _is_blank(scene.get("selection_reasoning")):
        missing.append("selection_reasoning")
    if _is_blank(scene.get("edit_suggestion")):
        missing.append("edit_suggestion")

    storyboard = scene.get("storyboard", {})
    for key in STORYBOARD_TEXT_FIELDS:
        if _is_blank(storyboard.get(key)):
            missing.append(f"storyboard.{key}")
    return missing


def build_storyboard_rows(data: Dict) -> List[Dict]:
    rows: List[Dict] = []
    for scene in data.get("scenes", []):
        storyboard = scene.get("storyboard", {})
        rows.append(
            {
                "scene_number": scene.get("scene_number", 0),
                "timestamp": storyboard.get("timestamp") or scene.get("timestamp_range", ""),
                "screenshot_path": storyboard.get("screenshot_path") or scene.get("frame_path", ""),
                "visual_description": storyboard.get("visual_description") or scene.get("description", ""),
                "voiceover": storyboard.get("voiceover", ""),
                "onscreen_text": storyboard.get("onscreen_text", ""),
                "shot_size": storyboard.get("shot_size", ""),
                "lighting": storyboard.get("lighting", ""),
                "camera_movement": storyboard.get("camera_movement", ""),
                "visual_style": storyboard.get("visual_style", ""),
                "technique": storyboard.get("technique", ""),
            }
        )
    return rows


def _derive_story_role(scene: Dict, index: int, total: int) -> str:
    if total <= 1:
        return "开场建立"
    ratio = ((index + 1) / max(total, 1)) if total else 0.0
    storyboard = scene.get("storyboard", {})
    shot_size = str(storyboard.get("shot_size", "") or "")
    onscreen_text = str(storyboard.get("onscreen_text", "") or "")
    type_classification = str(scene.get("type_classification", "") or "")

    if "TYPE-D" in type_classification or "片名卡" in shot_size or "字幕卡" in shot_size or "信息卡" in shot_size:
        return "传播收口" if ratio >= 0.7 or onscreen_text else "信息提示"
    if ratio <= 0.2:
        return "开场建立"
    if ratio <= 0.45:
        return "世界展开"
    if ratio <= 0.8:
        return "中段推进"
    return "高潮收束"


def _derive_story_function(scene: Dict) -> str:
    storyboard = scene.get("storyboard", {})
    type_classification = str(scene.get("type_classification", "") or "")
    shot_size = str(storyboard.get("shot_size", "") or "")
    voiceover = str(storyboard.get("voiceover", "") or "")

    if "TYPE-D" in type_classification or "片名卡" in shot_size or "字幕卡" in shot_size or "信息卡" in shot_size:
        return "发行提示"
    if "TYPE-A" in type_classification:
        return "冲击强化"
    if "TYPE-B" in type_classification:
        return "情节推进"
    if "TYPE-C" in type_classification:
        if any(word in shot_size for word in ("远景", "大全景", "全景")):
            return "空间建立"
        return "氛围营造"
    if voiceover.strip():
        return "情节推进"
    return "状态交代"


def _derive_visual_summary(scene: Dict) -> str:
    storyboard = scene.get("storyboard", {})
    visual_description = str(
        storyboard.get("visual_description")
        or scene.get("description")
        or scene.get("visual_description")
        or ""
    ).strip()
    return visual_description


def build_storyboard_context_rows(data: Dict) -> List[Dict]:
    context_rows: List[Dict] = []
    total = len(data.get("scenes", []))
    for index, row in enumerate(build_storyboard_rows(data)):
        source_scene = data.get("scenes", [])[index] if index < total else {}
        context_rows.append(
            {
                "scene_number": row.get("scene_number", 0),
                "timestamp": row.get("timestamp", ""),
                "screenshot_path": row.get("screenshot_path", ""),
                "visual_summary": _derive_visual_summary(source_scene),
                "story_role": _derive_story_role(source_scene, index, total),
                "story_function": _derive_story_function(source_scene),
                "visual_description": row.get("visual_description", ""),
                "voiceover": row.get("voiceover", ""),
                "onscreen_text": row.get("onscreen_text", ""),
                "shot_size": row.get("shot_size", ""),
                "lighting": row.get("lighting", ""),
                "camera_movement": row.get("camera_movement", ""),
                "visual_style": row.get("visual_style", ""),
                "technique": row.get("technique", ""),
            }
        )
    return context_rows


def write_storyboard_context_markdown(data: Dict, output_path: Path) -> Path:
    rows = build_storyboard_context_rows(data)
    video_id = data.get("video_id", "unknown")
    title = data.get("title") or data.get("video_title") or video_id

    lines = [
        "# 视听剖析上下文",
        "",
        f"- 视频标题：{title}",
        f"- 视频 ID：{video_id}",
        f"- 场景数：{len(rows)}",
        "- 用途：这份文件来自分镜表提炼，适合在生成视听剖析时优先阅读，减少无关上下文干扰。",
        "",
    ]

    for row in rows:
        lines.append(
            "- Scene {scene:03d} | {timestamp} | 段落角色：{story_role} | 主要作用：{story_function} | 画面：{visual} | 旁白：{voiceover} | 画面文字：{onscreen_text} | 镜头：{shot} / {light} / {move} / {style} / {technique}".format(
                scene=int(row.get("scene_number", 0)),
                timestamp=row.get("timestamp", "") or "-",
                story_role=row.get("story_role", "") or "-",
                story_function=row.get("story_function", "") or "-",
                visual=str(row.get("visual_description", "") or "-").replace("\n", " "),
                voiceover=str(row.get("voiceover", "") or "-").replace("\n", " "),
                onscreen_text=str(row.get("onscreen_text", "") or "-").replace("\n", " "),
                shot=row.get("shot_size", "") or "-",
                light=row.get("lighting", "") or "-",
                move=row.get("camera_movement", "") or "-",
                style=row.get("visual_style", "") or "-",
                technique=row.get("technique", "") or "-",
            )
        )

    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output_path


def write_storyboard_context_json(data: Dict, output_path: Path) -> Path:
    payload = {
        "video_id": data.get("video_id", "unknown"),
        "video_title": data.get("title") or data.get("video_title") or data.get("video_id", "unknown"),
        "scene_count": len(data.get("scenes", [])),
        "rows": build_storyboard_context_rows(data),
    }
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def _escape_markdown_cell(value: object) -> str:
    text = str(value or "").replace("\n", "<br>")
    return text.replace("|", "\\|")


def write_storyboard_markdown(data: Dict, output_path: Path) -> Path:
    rows = build_storyboard_rows(data)
    video_id = data.get("video_id", "unknown")
    title = data.get("title") or data.get("video_title") or video_id

    lines = [
        "# 分镜表",
        "",
        f"- 视频标题：{title}",
        f"- 视频 ID：{video_id}",
        f"- 场景数：{len(rows)}",
        "",
        "| 场景 | 时间戳 | 画面截图 | 画面内容 | 旁白 | 画面文字 | 景别 | 灯光 | 运镜 | 画风 | 手法 |",
        "|------|--------|----------|----------|------|----------|------|------|------|------|------|",
    ]

    for row in rows:
        screenshot_path = row.get("screenshot_path", "")
        screenshot_cell = ""
        if screenshot_path:
            screenshot_file = _resolve_media_path(screenshot_path, output_path.parent)
            relative_path = screenshot_file
            if screenshot_file.is_absolute():
                try:
                    relative_path = screenshot_file.relative_to(output_path.parent)
                except ValueError:
                    relative_path = screenshot_file
            screenshot_cell = f"![Scene {int(row.get('scene_number', 0)):03d}](<{relative_path.as_posix()}>)"

        lines.append(
            "| {scene} | {timestamp} | {screenshot} | {visual_description} | {voiceover} | {onscreen_text} | {shot_size} | {lighting} | {camera_movement} | {visual_style} | {technique} |".format(
                scene=f"Scene {int(row.get('scene_number', 0)):03d}",
                timestamp=_escape_markdown_cell(row.get("timestamp", "")),
                screenshot=_escape_markdown_cell(screenshot_cell),
                visual_description=_escape_markdown_cell(row.get("visual_description", "")),
                voiceover=_escape_markdown_cell(row.get("voiceover", "")),
                onscreen_text=_escape_markdown_cell(row.get("onscreen_text", "")),
                shot_size=_escape_markdown_cell(row.get("shot_size", "")),
                lighting=_escape_markdown_cell(row.get("lighting", "")),
                camera_movement=_escape_markdown_cell(row.get("camera_movement", "")),
                visual_style=_escape_markdown_cell(row.get("visual_style", "")),
                technique=_escape_markdown_cell(row.get("technique", "")),
            )
        )

    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output_path


def _load_pillow():
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError as exc:
        raise RuntimeError("缺少 Pillow，无法生成 PDF 分镜表") from exc
    return Image, ImageDraw, ImageFont


def _pick_font_path() -> Optional[Path]:
    for candidate in FONT_CANDIDATES:
        if candidate.exists():
            return candidate
    return None


def _measure_text(draw, text: str, font) -> Tuple[int, int]:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def _wrap_text(draw, text: str, font, max_width: int, max_lines: int) -> List[str]:
    cleaned = str(text or "").replace("\r", " ").replace("\n", " ").strip()
    if not cleaned:
        return ["-"]

    lines: List[str] = []
    current = ""
    for char in cleaned:
        candidate = f"{current}{char}"
        width, _ = _measure_text(draw, candidate, font)
        if width <= max_width or not current:
            current = candidate
            continue
        lines.append(current)
        current = char
        if len(lines) >= max_lines:
            break

    if len(lines) < max_lines and current:
        lines.append(current)

    if len(lines) > max_lines:
        lines = lines[:max_lines]

    if len(lines) == max_lines:
        remaining = cleaned[len("".join(lines)) :]
        if remaining:
            last = lines[-1]
            while last and _measure_text(draw, f"{last}...", font)[0] > max_width:
                last = last[:-1]
            lines[-1] = f"{last}..."

    return lines


def _draw_multiline(draw, text_lines: Iterable[str], font, x: int, y: int, line_gap: int = 8):
    current_y = y
    sample_height = _measure_text(draw, "测试Ag", font)[1]
    for line in text_lines:
        draw.text((x, current_y), line, font=font, fill=(30, 30, 30))
        current_y += sample_height + line_gap
    return current_y


def _draw_image_placeholder(draw, font, x1: int, y1: int, x2: int, y2: int):
    lines = _wrap_text(draw, "无画面截图", font, max(x2 - x1 - 24, 40), 2)
    box_width = x2 - x1
    box_height = y2 - y1
    line_height = _measure_text(draw, "测试Ag", font)[1] + 6
    text_height = len(lines) * line_height - 6
    start_y = y1 + max((box_height - text_height) // 2, 12)
    _draw_multiline(draw, lines, font, x1 + 12, start_y, line_gap=6)


def _paste_screenshot(page, screenshot_path: Path, x1: int, y1: int, x2: int, y2: int):
    if not screenshot_path.exists() or not screenshot_path.is_file():
        return False

    try:
        from PIL import Image

        with Image.open(screenshot_path) as original:
            preview = original.convert("RGB")
            preview.thumbnail((max(x2 - x1 - 12, 40), max(y2 - y1 - 12, 40)))
            paste_x = x1 + (x2 - x1 - preview.width) // 2
            paste_y = y1 + (y2 - y1 - preview.height) // 2
            page.paste(preview, (paste_x, paste_y))
        return True
    except (ImportError, OSError):
        return False


def _format_timestamp_lines(value: str) -> List[str]:
    if "-->" not in value:
        return [value or "-"]
    start, end = [part.strip() for part in value.split("-->", 1)]
    return [start, end]


def _build_detail_lines(draw, row: Dict, font, max_width: int) -> List[str]:
    detail_specs = [
        ("景别", row.get("shot_size", ""), 1),
        ("灯光", row.get("lighting", ""), 2),
        ("运镜", row.get("camera_movement", ""), 1),
        ("画风", row.get("visual_style", ""), 2),
        ("手法", row.get("technique", ""), 2),
    ]
    lines: List[str] = []
    for label, value, max_lines in detail_specs:
        lines.extend(_wrap_text(draw, f"{label}：{value or '-'}", font, max_width, max_lines))
    return lines


def write_storyboard_pdf(data: Dict, output_path: Path) -> Path:
    Image, ImageDraw, ImageFont = _load_pillow()
    font_path = _pick_font_path()
    if font_path is None:
        raise RuntimeError("未找到可用中文字体，无法生成 PDF 分镜表")

    rows = build_storyboard_rows(data)
    if not rows:
        raise RuntimeError("没有可导出的分镜数据")

    title_font = ImageFont.truetype(str(font_path), 34)
    subtitle_font = ImageFont.truetype(str(font_path), 18)
    header_font = ImageFont.truetype(str(font_path), 19)
    body_font = ImageFont.truetype(str(font_path), 17)
    small_font = ImageFont.truetype(str(font_path), 15)

    page_width, page_height = 2000, 1400
    margin = 52
    header_block_height = 92
    table_header_height = 52
    footer_height = 28
    row_height = 250
    row_gap = 10

    table_width = page_width - margin * 2
    columns = [
        ("scene", "场景", 128),
        ("timestamp", "时间戳", 240),
        ("screenshot", "画面截图", 330),
        ("visual_description", "画面内容", 360),
        ("voiceover", "旁白", 420),
        ("details", "镜头信息", table_width - 128 - 240 - 330 - 360 - 420),
    ]

    available_height = page_height - margin * 2 - header_block_height - table_header_height - footer_height
    rows_per_page = max(1, available_height // (row_height + row_gap))
    page_count = (len(rows) + rows_per_page - 1) // rows_per_page

    pages = []
    title = data.get("title") or data.get("video_title") or data.get("video_id", "unknown")
    video_id = data.get("video_id", "unknown")

    for page_index in range(page_count):
        page = Image.new("RGB", (page_width, page_height), "white")
        draw = ImageDraw.Draw(page)

        draw.text((margin, margin), "分镜表", font=title_font, fill=(24, 24, 24))
        subtitle = f"{title} | {video_id} | 第 {page_index + 1}/{page_count} 页"
        draw.text((margin, margin + 42), subtitle, font=subtitle_font, fill=(96, 96, 96))

        table_top = margin + header_block_height
        draw.rounded_rectangle(
            (margin, table_top, page_width - margin, page_height - margin - footer_height + 8),
            radius=18,
            outline=(222, 226, 232),
            width=2,
            fill=(250, 251, 253),
        )

        header_top = table_top + 12
        current_x = margin + 12
        for _, label, width in columns:
            draw.rounded_rectangle(
                (current_x, header_top, current_x + width, header_top + table_header_height),
                radius=10,
                fill=(231, 235, 241),
            )
            draw.text((current_x + 14, header_top + 14), label, font=header_font, fill=(52, 60, 73))
            current_x += width

        start_index = page_index * rows_per_page
        page_rows = rows[start_index : start_index + rows_per_page]
        row_top = header_top + table_header_height + 12

        for row_number, row in enumerate(page_rows):
            fill_color = (255, 255, 255) if row_number % 2 == 0 else (246, 248, 251)
            row_bottom = row_top + row_height
            draw.rounded_rectangle(
                (margin + 12, row_top, page_width - margin - 12, row_bottom),
                radius=14,
                fill=fill_color,
                outline=(230, 233, 238),
            )

            current_x = margin + 12
            cell_lefts = {}
            for key, _, width in columns:
                cell_lefts[key] = current_x
                current_x += width
                if current_x < page_width - margin - 12:
                    draw.line((current_x, row_top + 12, current_x, row_bottom - 12), fill=(228, 232, 238), width=1)

            content_top = row_top + 14
            inner_padding = 14

            scene_lines = [f"Scene {int(row.get('scene_number', 0)):03d}"]
            _draw_multiline(
                draw,
                scene_lines,
                header_font,
                cell_lefts["scene"] + inner_padding,
                content_top + 4,
                line_gap=6,
            )

            timestamp_lines = _format_timestamp_lines(str(row.get("timestamp", "")))
            _draw_multiline(
                draw,
                timestamp_lines,
                body_font,
                cell_lefts["timestamp"] + inner_padding,
                content_top + 4,
                line_gap=6,
            )

            image_left = cell_lefts["screenshot"] + inner_padding
            image_top = content_top
            image_right = cell_lefts["screenshot"] + columns[2][2] - inner_padding
            image_bottom = row_bottom - inner_padding
            draw.rounded_rectangle(
                (image_left, image_top, image_right, image_bottom),
                radius=10,
                outline=(214, 219, 225),
                width=2,
                fill=(244, 246, 248),
            )
            screenshot_value = str(row.get("screenshot_path", "")).strip()
            screenshot_path = _resolve_media_path(screenshot_value, output_path.parent)
            if not screenshot_value or not _paste_screenshot(page, screenshot_path, image_left + 6, image_top + 6, image_right - 6, image_bottom - 6):
                _draw_image_placeholder(draw, body_font, image_left, image_top, image_right, image_bottom)

            visual_lines = _wrap_text(
                draw,
                row.get("visual_description", "") or "-",
                body_font,
                columns[3][2] - inner_padding * 2,
                8,
            )
            _draw_multiline(
                draw,
                visual_lines,
                body_font,
                cell_lefts["visual_description"] + inner_padding,
                content_top + 2,
                line_gap=5,
            )

            voiceover_lines = _wrap_text(
                draw,
                row.get("voiceover", "") or "-",
                body_font,
                columns[4][2] - inner_padding * 2,
                8,
            )
            _draw_multiline(
                draw,
                voiceover_lines,
                body_font,
                cell_lefts["voiceover"] + inner_padding,
                content_top + 2,
                line_gap=5,
            )

            detail_lines = _build_detail_lines(
                draw,
                row,
                small_font,
                columns[5][2] - inner_padding * 2,
            )
            _draw_multiline(
                draw,
                detail_lines,
                small_font,
                cell_lefts["details"] + inner_padding,
                content_top + 2,
                line_gap=4,
            )

            row_top = row_bottom + row_gap

        footer_text = f"共 {len(rows)} 个场景"
        draw.text((margin, page_height - margin - 8), footer_text, font=small_font, fill=(112, 118, 126))
        pages.append(page)

    first_page, *other_pages = pages
    candidate_paths = [output_path]
    candidate_paths.extend(
        output_path.with_name(f"{output_path.stem}_compact{suffix}.pdf")
        for suffix in ("", "_2", "_3", "_4", "_5")
    )

    last_error: Optional[Exception] = None
    for candidate_path in candidate_paths:
        try:
            first_page.save(
                candidate_path,
                "PDF",
                resolution=150.0,
                save_all=True,
                append_images=other_pages,
            )
            return candidate_path
        except PermissionError as exc:
            last_error = exc
            continue

    raise RuntimeError("PDF 文件被占用，无法写入新的分镜表") from last_error


def generate_storyboard_outputs(
    data: Dict,
    video_dir: Path,
    formats: Sequence[str] = ("md", "pdf"),
    *,
    skip_enrich: bool = False,
) -> Dict[str, Path]:
    enriched = data if skip_enrich else enrich_storyboard_data(data, video_dir)
    video_id = enriched.get("video_id", "unknown")
    generated: Dict[str, Path] = {}

    normalized = [item.strip().lower() for item in formats if item and item.strip()]
    if "md" in normalized:
        generated["md"] = write_storyboard_markdown(
            enriched,
            video_dir / f"{video_id}_storyboard.md",
        )

    if "pdf" in normalized:
        generated["pdf"] = write_storyboard_pdf(
            enriched,
            video_dir / f"{video_id}_storyboard.pdf",
        )

    generated["context_md"] = write_storyboard_context_markdown(
        enriched,
        video_dir / f"{video_id}_storyboard_context.md",
    )
    generated["context_json"] = write_storyboard_context_json(
        enriched,
        video_dir / f"{video_id}_storyboard_context.json",
    )

    return generated
