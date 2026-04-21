#!/usr/bin/env python3
"""Generate a lightweight routing summary for the video-type-router skill."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, Sequence


ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from classification_summary import (  # noqa: E402
    DEFAULT_TARGET_GROUPS,
    build_classification_summary_payload,
    load_source_payload,
    render_classification_summary_markdown,
)


def parse_storyboard_md(md_text: str) -> Dict:
    """Parse storyboard markdown into the structured shape used by the summary builder."""
    lines = md_text.strip().split("\n")

    title = ""
    for line in lines[:15]:
        line_s = line.strip()
        if "视频标题" in line_s:
            matched = re.search(r"视频标题[：:]\s*(.+)", line_s)
            if matched:
                title = matched.group(1).strip()
                break
    if not title:
        for line in lines[:10]:
            line_s = line.strip()
            if line_s.startswith("# ") and "分镜表" not in line_s:
                title = line_s.lstrip("# ").strip()
                break

    scenes = []
    header_found = False
    col_map: Dict[str, int] = {}

    for line in lines:
        line_s = line.strip()
        if not line_s:
            continue

        if not header_found and "|" in line_s and "场景" in line_s:
            parts = line_s.split("|")
            for index, part in enumerate(parts):
                col = part.strip()
                if col == "场景":
                    col_map["scene"] = index
                elif col in ("时间戳", "时间截"):
                    col_map["timestamp"] = index
                elif col == "画面内容":
                    col_map["visual_description"] = index
                elif col == "旁白":
                    col_map["voiceover"] = index
                elif col == "画面文字":
                    col_map["onscreen_text"] = index
            header_found = True
            continue

        if header_found and re.match(r"^[\|\s\-:]+$", line_s):
            continue

        if header_found and line_s.startswith("|"):
            parts = line_s.split("|")
            scene_payload = {}
            for key, index in col_map.items():
                scene_payload[key] = parts[index].strip() if index < len(parts) else ""

            scene_label = scene_payload.get("scene", "")
            match = re.search(r"(\d+)", scene_label)
            scene_number = int(match.group(1)) if match else len(scenes) + 1
            visual_description = scene_payload.get("visual_description", "")
            voiceover = scene_payload.get("voiceover", "")
            onscreen_text = scene_payload.get("onscreen_text", "")

            if not visual_description and not voiceover and not onscreen_text:
                continue

            scenes.append(
                {
                    "scene_number": scene_number,
                    "timestamp_range": scene_payload.get("timestamp", ""),
                    "description": visual_description,
                    "storyboard": {
                        "visual_description": visual_description,
                        "voiceover": "" if voiceover in {"-", "—", "无", "N/A"} else voiceover,
                        "onscreen_text": "" if onscreen_text in {"-", "—", "无", "N/A"} else onscreen_text,
                        "shot_size": "",
                        "lighting": "",
                        "camera_movement": "",
                        "visual_style": "",
                        "technique": "",
                    },
                }
            )

    return {
        "video_id": "storyboard",
        "title": title,
        "video_title": title,
        "scenes": scenes,
    }


def _write_summary_files(summary_payload: Dict, output_path: Path) -> Dict[str, Path]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    json_path = output_path.with_suffix(".json")
    output_path.write_text(render_classification_summary_markdown(summary_payload), encoding="utf-8")
    json_path.write_text(json.dumps(summary_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "md": output_path,
        "json": json_path,
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="从结构化结果或分镜表 markdown 生成 video-type-router 分类摘要"
    )
    parser.add_argument("input_path", help="scene_scores.json、storyboard_context.json 或 storyboard.md")
    parser.add_argument(
        "target_groups",
        nargs="?",
        type=int,
        default=DEFAULT_TARGET_GROUPS,
        help=f"目标分组数（默认 {DEFAULT_TARGET_GROUPS}）",
    )
    parser.add_argument("output_path", nargs="?", help="可选：输出 markdown 路径")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    input_path = Path(args.input_path)

    if not input_path.exists():
        print(f"错误: 找不到文件 {input_path}")
        return 1

    if input_path.suffix.lower() == ".json":
        data = load_source_payload(input_path)
    elif input_path.suffix.lower() == ".md":
        data = parse_storyboard_md(input_path.read_text(encoding="utf-8"))
    else:
        print("错误: 只支持 scene_scores.json / storyboard_context.json / storyboard.md")
        return 1

    summary_payload = build_classification_summary_payload(data, target_groups=args.target_groups)
    if not summary_payload.get("groups"):
        print("错误: 未能提取出可用于路由的摘要分组")
        return 1

    default_name = f"{summary_payload.get('video_id') or input_path.stem}_classification_summary.md"
    output_path = Path(args.output_path) if args.output_path else input_path.parent / default_name
    outputs = _write_summary_files(summary_payload, output_path)

    print(f"✓ 已生成分类摘要: {outputs['md']}")
    print(f"✓ 已生成分类摘要(JSON): {outputs['json']}")
    print(
        f"  总场景: {summary_payload.get('scene_count', 0)}，"
        f"分组: {summary_payload.get('group_count', 0)}，"
        f"来源: {summary_payload.get('source_kind', 'unknown')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
