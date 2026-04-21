#!/usr/bin/env python3
"""
Build a thin-controller dispatch packet for OpenClaw orchestration.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional

try:
    from run_state import load_run_state
except ImportError:
    sys.path.insert(0, str(Path(__file__).parent))
    from run_state import load_run_state


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _resolve_scores_path(source: str) -> Path:
    path = Path(source)
    if path.is_dir():
        candidate = path / "scene_scores.json"
        if candidate.exists():
            return candidate.resolve()
    if path.is_file() and path.name == "scene_scores.json":
        return path.resolve()
    raise FileNotFoundError(f"未找到 scene_scores.json: {source}")


def _resolve_batch_path(video_dir: Path, value: str) -> str:
    if not value:
        return ""
    path = Path(value)
    if not path.is_absolute():
        if path.parts and path.parts[0] == "host_batches":
            path = video_dir / path
        else:
            path = video_dir / "host_batches" / path
    return str(path.resolve())


def _load_index_batch(video_dir: Path, batch_id: str) -> Dict[str, Any]:
    index_payload = _read_json(video_dir / "host_batches" / "index.json", {"batches": []})
    for batch in index_payload.get("batches", []):
        if str(batch.get("batch_id", "")) == batch_id:
            return dict(batch)
    return {}


def _resolve_next_batch(video_dir: Path, state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    next_batch = dict(state.get("next_batch") or {})
    if not next_batch:
        return None

    batch_id = str(next_batch.get("batch_id", ""))
    index_batch = _load_index_batch(video_dir, batch_id)
    merged = {**index_batch, **next_batch}
    scene_numbers = merged.get("scene_numbers") or []

    resolved: Dict[str, Any] = {
        "batch_id": batch_id,
        "scene_numbers": list(scene_numbers),
        "brief": _resolve_batch_path(video_dir, str(merged.get("brief", ""))),
        "contact_sheet": _resolve_batch_path(video_dir, str(merged.get("contact_sheet", ""))),
        "input": _resolve_batch_path(video_dir, str(merged.get("input", ""))),
        "output": _resolve_batch_path(video_dir, str(merged.get("output", ""))),
    }
    resolved["index_missing"] = not bool(index_batch)
    output_path = resolved["output"]
    resolved["output_missing"] = bool(output_path) and not Path(output_path).exists()
    resolved["resource_invalid"] = (
        resolved["index_missing"]
        or not output_path
        or resolved["output_missing"]
    )
    return resolved


def _all_batches_blocked(video_dir: Path) -> bool:
    index_payload = _read_json(video_dir / "host_batches" / "index.json", {"batches": []})
    batches = index_payload.get("batches") or []
    if not batches:
        return False
    return all(str(batch.get("status", "")) == "blocked" for batch in batches)


def _scene_has_content(scene: Dict[str, Any]) -> bool:
    if any(str(scene.get(key, "")).strip() for key in ("type_classification", "description", "visual_summary", "selection_reasoning", "edit_suggestion", "notes")):
        return True
    if any(bool(value) for value in (scene.get("scores") or {}).values()):
        return True
    if any(str(value).strip() for value in (scene.get("storyboard") or {}).values()):
        return True
    return False


def _default_receipt(batch: Dict[str, Any], output_payload: Dict[str, Any]) -> Dict[str, Any]:
    batch_id = str(batch.get("batch_id", "") or output_payload.get("batch_id", ""))
    output_path = Path(str(batch.get("output", "") or "")).name
    scene_numbers = batch.get("scene_numbers") or [
        int(scene.get("scene_number", 0))
        for scene in output_payload.get("scenes", [])
        if int(scene.get("scene_number", 0) or 0) > 0
    ]
    return {
        "batch_id": batch_id,
        "scene_numbers": list(scene_numbers),
        "output_path": output_path,
        "status": "",
        "has_todo": True,
        "needs_review": [],
        "worker_summary": "",
        "started_at": "",
        "updated_at": "",
        "completed_at": "",
    }


def _derive_receipt_status(receipt: Dict[str, Any], output_payload: Dict[str, Any]) -> str:
    explicit = str(receipt.get("status", "")).strip()
    if explicit:
        return explicit
    if receipt.get("has_todo") is False:
        return "completed"
    if any(_scene_has_content(scene) for scene in output_payload.get("scenes", [])):
        return "in_progress"
    return "pending"


def _load_batch_receipt(batch: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not batch or not batch.get("output"):
        return None
    output_path = Path(str(batch.get("output", "")))
    payload = _read_json(output_path, {"scenes": []})
    receipt = _default_receipt(batch, payload)
    receipt.update(payload.get("receipt") or {})
    receipt["status"] = _derive_receipt_status(receipt, payload)
    return receipt


def _worker_prompt(skill_root: Path, scores_path: Path, batch: Dict[str, Any]) -> str:
    video_dir = scores_path.parent
    return (
        f"Use $video-expert-analyzer-vnext at {skill_root} to finish only {batch['batch_id']} for {scores_path}. "
        f"Start from these files: {batch['brief']}, {batch['contact_sheet']}, {batch['input']}, {batch['output']}. "
        f"Frame paths listed in the input JSON are relative to {video_dir}. "
        "For every scene, inspect its primary, start, mid, and end frames before writing any description or camera judgement. "
        "Do not rely on the contact sheet alone; it is only a quick overview. "
        "Before analyzing, set receipt.status to in_progress and write started_at plus updated_at. "
        "Complete every scene in the output file. "
        "When done, set receipt.status to completed, set has_todo to false, fill worker_summary, updated_at, completed_at, and keep needs_review only for real unresolved items. "
        "If blocked, set receipt.status to blocked, keep has_todo true, explain the blocker in worker_summary and needs_review, then stop. "
        "Do not run the next batch. Do not run finalize."
    )


def _controller_action(
    state: Dict[str, Any],
    receipt: Optional[Dict[str, Any]],
    next_batch: Optional[Dict[str, Any]],
    *,
    all_batches_blocked: bool = False,
) -> str:
    status = str(state.get("status", ""))
    stage = str(state.get("current_stage", ""))

    if status == "completed" or stage == "completed":
        return "done"
    if status == "blocked":
        return "resolve_blocker"
    if next_batch:
        if next_batch.get("resource_invalid"):
            return "resolve_blocker"
        receipt_status = str((receipt or {}).get("status", "pending"))
        if receipt_status == "completed":
            return "resume_orchestrator"
        if receipt_status == "in_progress":
            return "wait_current_worker"
        if receipt_status == "blocked":
            return "repair_current_batch"
        return "spawn_batch_worker"
    if state.get("can_finalize") or status == "ready_to_finalize" or stage == "finalize":
        return "run_finalize"
    if stage == "prepare":
        return "run_prepare"
    if all_batches_blocked:
        return "resolve_blocker"
    if stage == "score_batches":
        return "diagnose_environment"
    return "resume_orchestrator"


def _action_summary(action: str, next_batch: Optional[Dict[str, Any]], state: Dict[str, Any]) -> str:
    if action == "spawn_batch_worker" and next_batch:
        return f"当前应派发 {next_batch['batch_id']} 给一个短生命周期子 agent。"
    if action == "wait_current_worker" and next_batch:
        return f"{next_batch['batch_id']} 已在处理中，主控现在只需要跟进这个 worker。"
    if action == "resume_orchestrator":
        return "当前批次已经写回，主控应立即重新运行总控，合并结果并准备下一步。"
    if action == "run_finalize":
        return "所有批次都已完成，主控现在应正式收尾并生成最终结果。"
    if action == "resolve_blocker":
        if next_batch and next_batch.get("resource_invalid"):
            reason = "index.json 找不到该 batch" if next_batch.get("index_missing") else "output 文件缺失或路径无效"
            return f"{next_batch['batch_id']} 资源异常（{reason}），先修 host_batches/ 下的 index / 任务包再继续。"
        return f"当前流程被阻塞，先解决 run_state.json / delivery_report.json 里记录的问题：{state.get('last_error', '')}"
    if action == "repair_current_batch" and next_batch:
        return f"{next_batch['batch_id']} 已标成 blocked，先修当前批次问题，不要派下一批。"
    if action == "done":
        return "当前任务已经完成，无需继续派发。"
    if action == "diagnose_environment":
        return "状态机没有可推进的下一步（无 next_batch 也不能 finalize），主控应先检查 host_batches 索引和自动评分配置。"
    return "主控应重新运行总控，刷新状态后再决定下一步。"


def _recommended_command(action: str, scores_path: Path) -> str:
    if action == "run_finalize":
        return f'python3 scripts/ai_analyzer.py "{scores_path}" --mode finalize'
    return f'python3 scripts/orchestrate_vnext.py "{scores_path}"'


def build_dispatch_packet(scores_path: Path) -> Dict[str, Any]:
    skill_root = Path(__file__).resolve().parents[1]
    video_dir = scores_path.parent.resolve()
    run_state_path = video_dir / "run_state.json"
    delivery_report_path = video_dir / "delivery_report.json"

    state = load_run_state(run_state_path)
    next_batch = _resolve_next_batch(video_dir, state)
    receipt = _load_batch_receipt(next_batch)
    action = _controller_action(
        state,
        receipt,
        next_batch,
        all_batches_blocked=_all_batches_blocked(video_dir),
    )

    packet: Dict[str, Any] = {
        "scores_path": str(scores_path),
        "video_dir": str(video_dir),
        "run_state_path": str(run_state_path),
        "delivery_report_path": str(delivery_report_path),
        "stage": str(state.get("current_stage", "")),
        "status": str(state.get("status", "")),
        "coverage_ratio": float(state.get("coverage_ratio", 0.0) or 0.0),
        "completed_scenes": int(state.get("completed_scenes", 0) or 0),
        "total_scenes": int(state.get("total_scenes", 0) or 0),
        "controller_action": action,
        "summary": _action_summary(action, next_batch, state),
        "recommended_command": _recommended_command(action, scores_path),
        "watch_files": {
            "run_state": str(run_state_path),
            "delivery_report": str(delivery_report_path),
            "batch_output": str(next_batch.get("output", "")) if next_batch else "",
        },
        "next_batch": next_batch,
        "receipt": receipt,
    }

    if next_batch:
        packet["worker_prompt"] = _worker_prompt(skill_root, scores_path, next_batch)
        packet["follow_up_command"] = f'python3 scripts/orchestrate_vnext.py "{scores_path}"'

    return packet


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build OpenClaw dispatch packet for the next vnext action")
    parser.add_argument("source", help="scene_scores.json 路径或其所在目录")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    scores_path = _resolve_scores_path(args.source)
    packet = build_dispatch_packet(scores_path)
    print(json.dumps(packet, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
