#!/usr/bin/env python3
"""
Scene-frame OCR subtitle refinement for music-style videos.
"""

from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence


MUSIC_VIDEO_KEYWORDS = (
    " mv",
    "mv ",
    "官方mv",
    "music video",
    "lyric",
    "lyrics",
    "歌词",
    "歌曲",
    "音乐",
    "演唱会",
    "live",
)

TRUSTED_SUBTITLE_SOURCE_MODES = {
    "bilibili_api",
    "bilibili_api_fallback",
    "embedded",
    "embedded_fallback",
    "platform_subtitles",
}


def is_music_video(title: str = "", url: str = "") -> bool:
    haystack = f" {title.lower()} {url.lower()} "
    return any(keyword in haystack for keyword in MUSIC_VIDEO_KEYWORDS)


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


def load_srt_segments(srt_path: Path) -> List[Dict]:
    if not srt_path.exists():
        return []

    content = srt_path.read_text(encoding="utf-8", errors="ignore").strip()
    if not content:
        return []

    segments: List[Dict] = []
    for block in re.split(r"\r?\n\r?\n", content):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if len(lines) < 2:
            continue
        timestamp_line = lines[1] if "-->" in lines[1] else lines[0]
        if "-->" not in timestamp_line:
            continue
        start_text, end_text = [part.strip() for part in timestamp_line.split("-->", 1)]
        try:
            start_seconds = parse_srt_timestamp(start_text)
            end_seconds = parse_srt_timestamp(end_text)
        except ValueError:
            continue
        text_lines = lines[2:] if timestamp_line == lines[1] else lines[1:]
        text = " ".join(text_lines).strip()
        if not text:
            continue
        segments.append({"start": start_seconds, "end": end_seconds, "text": text})
    return segments


def _resolve_source_mode(video_dir: Path, video_id: str, source_mode: str = "") -> str:
    normalized = str(source_mode or "").strip()
    if normalized:
        return normalized

    metadata_path = video_dir / f"{video_id}_subtitle_source.json"
    if not metadata_path.exists():
        return ""

    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""

    return str(payload.get("mode", "")).strip()


def _normalize_text(text: str) -> str:
    cleaned = re.sub(r"\s+", "", str(text or ""))
    cleaned = cleaned.replace("—", "-").replace("–", "-")
    return cleaned.strip(" /|·•，,。.!！？?；;：:")


def _is_lyric_like_text(text: str) -> bool:
    normalized = _normalize_text(text)
    if len(normalized) < 4 or len(normalized) > 36:
        return False

    cjk_count = len(re.findall(r"[\u4e00-\u9fff]", normalized))
    alpha_count = len(re.findall(r"[A-Za-z]", normalized))
    digit_count = len(re.findall(r"\d", normalized))
    valid_count = cjk_count + alpha_count + digit_count

    if valid_count / max(len(normalized), 1) < 0.5:
        return False
    if digit_count / max(len(normalized), 1) > 0.35:
        return False
    if normalized.isupper() and alpha_count >= 6:
        return False
    return True


def _build_default_ocr_runner() -> Callable[[Path], List[Dict]]:
    from PIL import Image
    from rapidocr_onnxruntime import RapidOCR

    ocr_engine = RapidOCR()

    def run_ocr(frame_path: Path) -> List[Dict]:
        if not frame_path.exists():
            return []

        with Image.open(frame_path) as image:
            image_height = image.height

        result = ocr_engine(str(frame_path))
        raw_lines = result[0] if result else []
        parsed_lines: List[Dict] = []
        for item in raw_lines or []:
            if not item or len(item) < 3:
                continue
            box, text, confidence = item[0], str(item[1]).strip(), item[2]
            try:
                score = float(confidence)
            except (TypeError, ValueError):
                score = 0.0

            try:
                y_center = sum(point[1] for point in box) / len(box)
            except Exception:
                y_center = 0.0

            parsed_lines.append(
                {
                    "text": text,
                    "confidence": score,
                    "y_ratio": y_center / max(image_height, 1),
                }
            )
        return parsed_lines

    return run_ocr


def _merge_candidate_lines(lines: Sequence[Dict]) -> Optional[Dict]:
    filtered = [
        line
        for line in lines
        if line.get("confidence", 0.0) >= 0.72
        and line.get("y_ratio", 0.0) >= 0.58
        and _is_lyric_like_text(str(line.get("text", "")))
    ]
    if not filtered:
        return None

    filtered = sorted(filtered, key=lambda item: (item.get("y_ratio", 0.0), item.get("text", "")))
    texts: List[str] = []
    for line in filtered:
        text = str(line.get("text", "")).strip()
        if not text:
            continue
        if texts and SequenceMatcher(None, _normalize_text(texts[-1]), _normalize_text(text)).ratio() >= 0.92:
            continue
        texts.append(text)

    if not texts:
        return None

    avg_confidence = sum(line.get("confidence", 0.0) for line in filtered) / len(filtered)
    return {"text": " / ".join(texts), "confidence": round(avg_confidence, 3)}


def _merge_subtitle_entries(entries: Sequence[Dict]) -> List[Dict]:
    merged: List[Dict] = []
    for entry in entries:
        if not merged:
            merged.append(dict(entry))
            continue

        previous = merged[-1]
        same_text = SequenceMatcher(
            None,
            _normalize_text(previous["text"]),
            _normalize_text(entry["text"]),
        ).ratio() >= 0.88
        close_enough = entry["start"] - previous["end"] <= 0.8

        if same_text and close_enough:
            previous["end"] = entry["end"]
            previous["scene_numbers"].append(entry["scene_numbers"][0])
            previous["confidence"] = round(max(previous["confidence"], entry["confidence"]), 3)
            continue

        merged.append(dict(entry))
    return merged


def _write_srt(entries: Sequence[Dict], output_path: Path) -> None:
    with output_path.open("w", encoding="utf-8") as handle:
        for index, entry in enumerate(entries, 1):
            handle.write(f"{index}\n")
            handle.write(
                f"{format_srt_timestamp(entry['start'])} --> {format_srt_timestamp(entry['end'])}\n"
            )
            handle.write(f"{entry['text']}\n\n")


def _write_transcript(entries: Sequence[Dict], output_path: Path) -> None:
    full_text = " ".join(entry["text"] for entry in entries)
    output_path.write_text(full_text + "\n", encoding="utf-8")


def refine_music_subtitles(
    scores_path: Path,
    video_dir: Path,
    title: str = "",
    url: str = "",
    source_mode: str = "",
    ocr_runner: Optional[Callable[[Path], List[Dict]]] = None,
) -> Dict:
    if not is_music_video(title, url):
        return {"status": "skipped", "reason": "not_music_video"}

    source_srt_path = video_dir / f"{video_dir.name}.srt"
    video_id = video_dir.name

    with scores_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    video_id = data.get("video_id", video_id)
    source_mode = _resolve_source_mode(video_dir, video_id, source_mode=source_mode)
    if source_mode in TRUSTED_SUBTITLE_SOURCE_MODES:
        return {"status": "skipped", "reason": f"source_mode_{source_mode}_trusted"}

    source_srt_path = video_dir / f"{video_id}.srt"
    corrected_srt_path = video_dir / f"{video_id}_ocr_corrected.srt"
    corrected_transcript_path = video_dir / f"{video_id}_ocr_corrected.txt"
    review_json_path = video_dir / f"{video_id}_ocr_review.json"

    try:
        from storyboard_generator import enrich_storyboard_data
    except ImportError:
        import sys

        sys.path.insert(0, str(Path(__file__).parent))
        from storyboard_generator import enrich_storyboard_data

    enriched = enrich_storyboard_data(data, video_dir)
    subtitle_segments = load_srt_segments(source_srt_path)
    first_audio_start = subtitle_segments[0]["start"] if subtitle_segments else 0.0
    ocr = ocr_runner or _build_default_ocr_runner()

    records: List[Dict] = []
    entries: List[Dict] = []
    started = False

    for scene in enriched.get("scenes", []):
        start_seconds = float(scene.get("start_time_seconds", 0.0) or 0.0)
        end_seconds = float(scene.get("end_time_seconds", start_seconds) or start_seconds)
        if end_seconds < first_audio_start:
            continue

        frame_path_value = scene.get("frame_path") or scene.get("storyboard", {}).get("screenshot_path") or ""
        frame_path = Path(str(frame_path_value)) if frame_path_value else Path()
        raw_lines = ocr(frame_path) if frame_path_value else []
        merged_candidate = _merge_candidate_lines(raw_lines)

        record = {
            "scene_number": scene.get("scene_number"),
            "timestamp_range": scene.get("timestamp_range", ""),
            "frame_path": str(frame_path) if frame_path_value else "",
            "ocr_text": merged_candidate["text"] if merged_candidate else "",
            "confidence": merged_candidate["confidence"] if merged_candidate else 0.0,
            "used": False,
        }

        if merged_candidate and not started:
            started = True

        if started and merged_candidate:
            record["used"] = True
            entries.append(
                {
                    "start": start_seconds,
                    "end": end_seconds,
                    "text": merged_candidate["text"],
                    "confidence": merged_candidate["confidence"],
                    "scene_numbers": [int(scene.get("scene_number", 0))],
                }
            )

        records.append(record)

    merged_entries = _merge_subtitle_entries(entries)
    review_payload = {
        "status": "corrected" if merged_entries else "skipped",
        "video_id": video_id,
        "source_mode": source_mode or "unknown",
        "first_audio_start": first_audio_start,
        "scene_records": records,
        "merged_entries": merged_entries,
    }
    review_json_path.write_text(json.dumps(review_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    if len(merged_entries) < 1:
        return {
            "status": "skipped",
            "reason": "insufficient_ocr_lyrics",
            "review_path": str(review_json_path),
            "candidate_count": len(merged_entries),
        }

    _write_srt(merged_entries, corrected_srt_path)
    _write_transcript(merged_entries, corrected_transcript_path)
    return {
        "status": "corrected",
        "subtitle_path": str(corrected_srt_path),
        "transcript_path": str(corrected_transcript_path),
        "review_path": str(review_json_path),
        "candidate_count": len(merged_entries),
        "source_mode": source_mode or "unknown",
    }
