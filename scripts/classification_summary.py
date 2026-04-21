#!/usr/bin/env python3
"""Build a lightweight classification summary for video-type routing."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import re
from pathlib import Path
from typing import Dict, Iterable, List, Sequence

try:
    from storyboard_generator import build_storyboard_context_rows
except ImportError:
    import sys

    sys.path.insert(0, str(Path(__file__).parent))
    from storyboard_generator import build_storyboard_context_rows


DEFAULT_TARGET_GROUPS = 21
PHASE_LABELS = {
    "opening": "前段",
    "middle": "中段",
    "closing": "后段",
}
_TIMESTAMP_RE = re.compile(
    r"(?P<start>\d{2}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*(?P<end>\d{2}:\d{2}:\d{2}[,.]\d{3})"
)


def _safe_text(value: object) -> str:
    text = str(value or "").strip()
    if not text or text.upper().startswith("TODO"):
        return ""
    return text


def _video_title(data: Dict) -> str:
    return _safe_text(data.get("title") or data.get("video_title") or data.get("video_id")) or "unknown"


def _source_rows(data: Dict) -> List[Dict]:
    if isinstance(data.get("rows"), list) and data.get("rows"):
        rows = [dict(row) for row in data.get("rows", [])]
    else:
        rows = build_storyboard_context_rows(data)
    return sorted(rows, key=lambda row: int(row.get("scene_number", 0) or 0))


def _source_kind(data: Dict) -> str:
    if isinstance(data.get("rows"), list) and data.get("rows"):
        return "storyboard_context_json"
    if isinstance(data.get("scenes"), list) and data.get("scenes"):
        return "scene_scores_json"
    return "unknown"


def _chunk_rows(rows: Sequence[Dict], target_groups: int) -> List[List[Dict]]:
    if not rows:
        return []
    group_count = max(1, min(len(rows), int(target_groups or DEFAULT_TARGET_GROUPS)))
    buckets: List[List[Dict]] = []
    total = len(rows)
    for index in range(group_count):
        start = round(index * total / group_count)
        end = round((index + 1) * total / group_count)
        bucket = list(rows[start:end])
        if bucket:
            buckets.append(bucket)
    return buckets


def _phase_for_index(index: int, total: int) -> str:
    if total <= 1:
        return "opening"
    ratio = index / total
    if ratio < 1 / 3:
        return "opening"
    if ratio < 2 / 3:
        return "middle"
    return "closing"


def _unique_texts(values: Iterable[object], *, limit: int = 3, empty_fallback: str = "-") -> str:
    seen = set()
    items: List[str] = []
    for value in values:
        text = _safe_text(value).replace("\n", " ")
        if not text or text in seen:
            continue
        seen.add(text)
        items.append(text)
        if len(items) >= limit:
            break
    return " / ".join(items) if items else empty_fallback


def _timestamp_bounds(rows: Sequence[Dict]) -> Dict[str, str]:
    if not rows:
        return {"timestamp_start": "", "timestamp_end": "", "timestamp_range": ""}

    start_text = _safe_text(rows[0].get("timestamp"))
    end_text = _safe_text(rows[-1].get("timestamp"))

    start_match = _TIMESTAMP_RE.search(start_text)
    end_match = _TIMESTAMP_RE.search(end_text)

    timestamp_start = start_match.group("start") if start_match else start_text
    timestamp_end = end_match.group("end") if end_match else end_text

    if timestamp_start and timestamp_end:
        timestamp_range = f"{timestamp_start} --> {timestamp_end}"
    else:
        timestamp_range = start_text or end_text

    return {
        "timestamp_start": timestamp_start,
        "timestamp_end": timestamp_end,
        "timestamp_range": timestamp_range,
    }


def _detect_languages(texts: Sequence[str]) -> Dict[str, int]:
    counter = Counter()
    for text in texts:
        if re.search(r"[\u4e00-\u9fff]", text):
            counter["中文"] += 1
        if re.search(r"[\uac00-\ud7af]", text):
            counter["韩文"] += 1
        if re.search(r"[a-zA-Z]{3,}", text):
            counter["英文"] += 1
        if re.search(r"[\u3040-\u309f\u30a0-\u30ff]", text):
            counter["日文"] += 1
    return dict(counter)


def analyze_narration(rows: Sequence[Dict]) -> Dict[str, object]:
    voiceovers = [_safe_text(row.get("voiceover")) for row in rows]
    non_empty = [text for text in voiceovers if text]
    total = len(rows)
    coverage_ratio = (len(non_empty) / total) if total else 0.0
    languages = _detect_languages(non_empty)

    if not non_empty:
        narration_type = "无旁白"
    else:
        repetition_ratio = 1 - (len(set(non_empty)) / len(non_empty))
        avg_len = sum(len(text) for text in non_empty) / len(non_empty)
        has_mixed_lang = (
            bool(languages.get("韩文")) and bool(languages.get("英文"))
        ) or (
            bool(languages.get("日文")) and bool(languages.get("英文"))
        )

        if coverage_ratio > 0.7 and (repetition_ratio > 0.3 or (has_mixed_lang and avg_len < 30)):
            narration_type = "歌词"
        elif coverage_ratio > 0.7 and avg_len > 50:
            narration_type = "连续旁白/独白"
        elif coverage_ratio > 0.7:
            narration_type = "连续对白/口播"
        elif coverage_ratio > 0.4:
            narration_type = "间歇语言"
        else:
            narration_type = "稀疏语言"

    return {
        "with_voiceover": len(non_empty),
        "coverage_ratio": coverage_ratio,
        "coverage_text": f"{coverage_ratio * 100:.0f}%",
        "narration_type": narration_type,
        "languages": languages,
        "sample_voiceovers": non_empty[:5],
    }


def _type_distribution(data: Dict) -> List[Dict[str, object]]:
    scenes = data.get("scenes") or []
    counter = Counter(
        _safe_text(scene.get("type_classification"))
        for scene in scenes
        if _safe_text(scene.get("type_classification"))
    )
    return [{"label": label, "count": count} for label, count in counter.most_common()]


def classification_summary_hash(payload: Dict[str, object]) -> str:
    normalized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def build_classification_summary_payload(data: Dict, target_groups: int = DEFAULT_TARGET_GROUPS) -> Dict[str, object]:
    rows = _source_rows(data)
    groups: List[Dict[str, object]] = []

    for index, bucket in enumerate(_chunk_rows(rows, target_groups), start=1):
        phase = _phase_for_index(index - 1, max(1, min(len(rows), int(target_groups or DEFAULT_TARGET_GROUPS))))
        scene_numbers = [int(row.get("scene_number", 0) or 0) for row in bucket if int(row.get("scene_number", 0) or 0) > 0]
        timestamps = _timestamp_bounds(bucket)
        groups.append(
            {
                "group_id": f"G{index:02d}",
                "phase": phase,
                "phase_label": PHASE_LABELS[phase],
                "scene_start": scene_numbers[0] if scene_numbers else 0,
                "scene_end": scene_numbers[-1] if scene_numbers else 0,
                "scene_numbers": scene_numbers,
                **timestamps,
                "visual_summary": _unique_texts((row.get("visual_description") or row.get("visual_summary") for row in bucket)),
                "voiceover_summary": _unique_texts((row.get("voiceover") for row in bucket)),
                "onscreen_text_summary": _unique_texts((row.get("onscreen_text") for row in bucket)),
            }
        )

    narration = analyze_narration(rows)
    return {
        "video_id": _safe_text(data.get("video_id")) or "unknown",
        "video_title": _video_title(data),
        "scene_count": len(rows),
        "target_groups": int(target_groups or DEFAULT_TARGET_GROUPS),
        "group_count": len(groups),
        "source_kind": _source_kind(data),
        "narration": narration,
        "type_distribution": _type_distribution(data),
        "groups": groups,
    }


def render_classification_summary_markdown(payload: Dict[str, object]) -> str:
    narration = payload.get("narration") or {}
    languages = narration.get("languages") or {}
    type_distribution = payload.get("type_distribution") or []
    language_text = "、".join(f"{key}({value})" for key, value in languages.items()) if languages else "-"
    type_distribution_text = "、".join(
        f"{item['label']}({item['count']})" for item in type_distribution
    ) if type_distribution else "-"

    lines = [
        "# 视频分类摘要",
        "",
        f"- 视频标题：{payload.get('video_title', 'unknown')}",
        f"- 视频 ID：{payload.get('video_id', 'unknown')}",
        f"- 总场景数：{payload.get('scene_count', 0)}",
        f"- 分类分组数：{payload.get('group_count', 0)}",
        f"- 生成来源：{payload.get('source_kind', 'unknown')}",
        "",
        "## 全局信号",
        "",
        f"- 旁白覆盖率：{narration.get('coverage_text', '0%')}",
        f"- 旁白性质：{narration.get('narration_type', '无旁白')}",
        f"- 涉及语言：{language_text}",
        f"- 场景类型分布：{type_distribution_text}",
        "",
        "## 分类分组",
        "",
    ]

    for group in payload.get("groups", []):
        scene_range = f"Scene {int(group.get('scene_start', 0)):03d}"
        if int(group.get("scene_end", 0) or 0) > int(group.get("scene_start", 0) or 0):
            scene_range = f"{scene_range}-{int(group.get('scene_end', 0)):03d}"
        lines.extend(
            [
                f"### {group.get('group_id', '')} | {group.get('phase_label', '')} | {scene_range}",
                f"- 时间：{group.get('timestamp_range', '-') or '-'}",
                f"- 画面：{group.get('visual_summary', '-') or '-'}",
                f"- 旁白：{group.get('voiceover_summary', '-') or '-'}",
                f"- 画面文字：{group.get('onscreen_text_summary', '-') or '-'}",
                "",
            ]
        )

    return "\n".join(lines).rstrip() + "\n"


def write_classification_summary_outputs(
    data: Dict,
    video_dir: Path,
    *,
    target_groups: int = DEFAULT_TARGET_GROUPS,
) -> Dict[str, Path]:
    payload = build_classification_summary_payload(data, target_groups=target_groups)
    video_id = str(payload.get("video_id") or "unknown")
    md_path = video_dir / f"{video_id}_classification_summary.md"
    json_path = video_dir / f"{video_id}_classification_summary.json"

    md_path.write_text(render_classification_summary_markdown(payload), encoding="utf-8")
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "md": md_path,
        "json": json_path,
    }


def load_source_payload(input_path: Path) -> Dict:
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    if isinstance(payload.get("rows"), list) and payload.get("rows"):
        return payload
    if isinstance(payload.get("scenes"), list) and payload.get("scenes"):
        return payload
    raise ValueError("只支持 scene_scores.json 或 storyboard_context.json 这类结构化 JSON 输入")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate a lightweight classification summary from structured video outputs")
    parser.add_argument("input_path", help="scene_scores.json 或 storyboard_context.json")
    parser.add_argument("target_groups", nargs="?", type=int, default=DEFAULT_TARGET_GROUPS, help="目标分组数（默认 21）")
    parser.add_argument("output_path", nargs="?", help="可选：输出 markdown 路径")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    input_path = Path(args.input_path)
    payload = load_source_payload(input_path)

    if args.output_path:
        output_path = Path(args.output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        summary_payload = build_classification_summary_payload(payload, target_groups=args.target_groups)
        output_path.write_text(render_classification_summary_markdown(summary_payload), encoding="utf-8")
        json_path = output_path.with_suffix(".json")
        json_path.write_text(json.dumps(summary_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(output_path)
        print(json_path)
        return 0

    outputs = write_classification_summary_outputs(payload, input_path.parent, target_groups=args.target_groups)
    print(outputs["md"])
    print(outputs["json"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
