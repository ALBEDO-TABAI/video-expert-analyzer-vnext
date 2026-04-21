#!/usr/bin/env python3
"""
Top-level orchestration helper for the vnext skill.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
from pathlib import Path
from typing import Any, List, Optional

try:
    from ai_analyzer import main as ai_main
except ImportError:
    sys.path.insert(0, str(Path(__file__).parent))
    from ai_analyzer import main as ai_main

try:
    from pipeline_enhanced import VideoAnalysisPipeline, get_output_directory
except ImportError:
    sys.path.insert(0, str(Path(__file__).parent))
    from pipeline_enhanced import VideoAnalysisPipeline, get_output_directory

try:
    from openclaw_dispatch import build_dispatch_packet
except ImportError:
    sys.path.insert(0, str(Path(__file__).parent))
    from openclaw_dispatch import build_dispatch_packet


def _is_scores_path(value: str) -> bool:
    path = Path(value)
    if not path.exists():
        return False
    if path.is_file() and path.name == "scene_scores.json":
        return True
    if path.is_dir() and (path / "scene_scores.json").is_file():
        return True
    return False


def _resolve_scores_path(value: str) -> Path:
    path = Path(value)
    if path.is_dir():
        return path / "scene_scores.json"
    return path


def _print_run_state(scores_path: Path) -> None:
    state_path = scores_path.parent / "run_state.json"
    if not state_path.exists():
        print("⚠️ 未找到 run_state.json")
        return
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    print(f"🧭 当前阶段: {payload.get('current_stage', '')}")
    print(f"📌 当前状态: {payload.get('status', '')}")
    print(f"📊 覆盖率: {float(payload.get('coverage_ratio', 0.0) or 0.0) * 100:.1f}%")
    next_batch = payload.get("next_batch") or {}
    if payload.get("status") == "blocked" and payload.get("last_error"):
        print(f"❌ 阻塞原因: {payload.get('last_error', '')}")
    if next_batch:
        print(f"🧩 下一批: {next_batch.get('batch_id', '')}")
        if next_batch.get("brief"):
            print(f"📄 简报: {next_batch.get('brief', '')}")
        if next_batch.get("input"):
            print(f"📥 输入: {next_batch.get('input', '')}")
        if next_batch.get("output"):
            print(f"📤 输出: {next_batch.get('output', '')}")
    elif payload.get("status") == "completed":
        print("✅ 当前任务已经完成")
    elif payload.get("can_finalize"):
        print("✅ 当前可以直接 finalize")

    delivery_report_path = scores_path.parent / "delivery_report.json"
    if delivery_report_path.exists():
        print(f"📦 交付报告: {delivery_report_path}")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="One-shot entrypoint for video-expert-analyzer-vnext")
    parser.add_argument("source", help="视频 URL、本地视频文件或 scene_scores.json 路径")
    parser.add_argument("-o", "--output", help="输出目录（仅 URL 模式需要）")
    parser.add_argument("--scene-threshold", type=float, default=27.0)
    parser.add_argument("--best-threshold", type=float, default=7.5)
    parser.add_argument("--batch-size", type=int, default=0)
    parser.add_argument("--storyboard-formats", default="md,pdf")
    parser.add_argument("--payload-style", choices=["compact", "full"], default="compact")
    parser.add_argument("--openclaw-mode", action="store_true", help="启用 OpenClaw 接力模式（默认关闭，使用 --dispatch-json 时自动启用）")
    parser.add_argument("--no-openclaw-mode", action="store_true", help="明确关闭 OpenClaw 接力模式")
    parser.add_argument("--dispatch-json", action="store_true", help="输出当前阶段派单信息，减少额外脚本调用（自动启用 openclaw-mode）")
    return parser


def _effective_openclaw_mode(args: argparse.Namespace) -> bool:
    return (args.openclaw_mode or args.dispatch_json) and not args.no_openclaw_mode


def _build_ai_main_args(source: str | Path, args: argparse.Namespace) -> List[str]:
    effective_openclaw = _effective_openclaw_mode(args)
    return [
        str(source),
        "--mode",
        "auto",
        "--batch-size",
        str(args.batch_size),
        "--storyboard-formats",
        args.storyboard_formats,
        "--payload-style",
        args.payload_style,
    ] + (["--openclaw-mode"] if effective_openclaw else ["--no-openclaw-mode"])


def _output_context(suppress_output: bool) -> contextlib.AbstractContextManager[Any]:
    if not suppress_output:
        return contextlib.nullcontext()

    stack = contextlib.ExitStack()
    stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
    stack.enter_context(contextlib.redirect_stderr(io.StringIO()))
    return stack


def _run_ai_flow(scores_path: Path, args: argparse.Namespace, *, suppress_output: bool = False) -> int:
    with _output_context(suppress_output):
        return ai_main(_build_ai_main_args(scores_path, args))


def _run_pipeline_flow(args: argparse.Namespace, *, suppress_output: bool = False) -> VideoAnalysisPipeline:
    output_dir = args.output or get_output_directory()
    with _output_context(suppress_output):
        pipeline = VideoAnalysisPipeline(
            url=args.source,
            output_dir=output_dir,
            scene_threshold=args.scene_threshold,
            best_threshold=args.best_threshold,
            openclaw_mode=_effective_openclaw_mode(args),
        )
        pipeline.run()
    return pipeline


def main(argv: Optional[List[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)

    if args.openclaw_mode and args.no_openclaw_mode:
        print("❌ --openclaw-mode 与 --no-openclaw-mode 不能同时指定", file=sys.stderr)
        return 2

    if _is_scores_path(args.source):
        scores_path = _resolve_scores_path(args.source)
        result = _run_ai_flow(scores_path, args, suppress_output=args.dispatch_json)
    else:
        pipeline = _run_pipeline_flow(args, suppress_output=args.dispatch_json)
        scores_path = pipeline.scores_path
        result = _run_ai_flow(scores_path, args, suppress_output=args.dispatch_json)

    if args.dispatch_json:
        print(json.dumps(build_dispatch_packet(scores_path), ensure_ascii=False, indent=2))
    else:
        _print_run_state(scores_path)

    return result


if __name__ == "__main__":
    sys.exit(main())
