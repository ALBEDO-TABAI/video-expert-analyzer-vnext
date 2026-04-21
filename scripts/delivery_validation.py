#!/usr/bin/env python3
"""Delivery-time validation and reporting helpers.

Extracted from ai_analyzer.py to keep that module focused on the scoring
flow. Functions here answer "is this delivery complete and consistent?"
— resource paths, finalize readiness, batch receipts, output presence,
and the on-disk delivery report.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

try:
    from storyboard_generator import (
        ANALYSIS_FIELD_LABELS,
        scene_missing_analysis_fields,
    )
except ImportError:
    sys.path.insert(0, str(Path(__file__).parent))
    from storyboard_generator import (
        ANALYSIS_FIELD_LABELS,
        scene_missing_analysis_fields,
    )

try:
    from motion_analysis import build_frame_sample_paths
except ImportError:
    sys.path.insert(0, str(Path(__file__).parent))
    from motion_analysis import build_frame_sample_paths

try:
    from host_batching import _read_json, _receipt_blocking_reasons
except ImportError:
    sys.path.insert(0, str(Path(__file__).parent))
    from host_batching import _read_json, _receipt_blocking_reasons

try:
    from run_state import load_run_state
except ImportError:
    sys.path.insert(0, str(Path(__file__).parent))
    from run_state import load_run_state


REQUIRED_SAMPLE_KEYS = ("primary", "start", "mid", "end")


def delivery_report_path_for(video_dir: Path) -> Path:
    return video_dir / "delivery_report.json"


def _resolve_persistent_path(path_text: object, video_dir: Path) -> str:
    raw = str(path_text or "").strip()
    if not raw:
        return ""
    path = Path(raw)
    if path.is_absolute():
        return str(path)
    return str(video_dir / path)


def _candidate_scene_file_path(scene: Dict, video_dir: Path) -> str:
    existing = _resolve_persistent_path(scene.get("file_path", ""), video_dir)
    if existing:
        return existing
    filename = str(scene.get("filename", "")).strip()
    if not filename:
        return ""
    return str(video_dir / "scenes" / filename)


def _candidate_frame_path(scene: Dict, video_dir: Path) -> str:
    existing = _resolve_persistent_path(scene.get("frame_path", ""), video_dir)
    if existing:
        return existing
    scene_file = _candidate_scene_file_path(scene, video_dir)
    scene_stem = Path(str(scene.get("filename") or scene_file)).stem
    if not scene_stem:
        return ""
    return str(build_frame_sample_paths(video_dir / "frames", scene_stem)["primary"])


def _normalize_scene_resource_paths(data: Dict, video_dir: Path) -> Dict:
    for scene in data.get("scenes", []):
        file_path = _candidate_scene_file_path(scene, video_dir)
        if file_path:
            scene["file_path"] = file_path

        frame_path = _candidate_frame_path(scene, video_dir)
        if frame_path:
            scene["frame_path"] = frame_path

        scene_stem = Path(str(scene.get("filename") or file_path)).stem
        default_samples = build_frame_sample_paths(video_dir / "frames", scene_stem) if scene_stem else {}
        frame_samples = scene.get("frame_samples") or {}
        normalized_samples: Dict[str, str] = {}
        for key in REQUIRED_SAMPLE_KEYS:
            raw_value = frame_samples.get(key) if isinstance(frame_samples, dict) else ""
            if not raw_value and key in default_samples:
                raw_value = default_samples[key]
            resolved = _resolve_persistent_path(raw_value, video_dir)
            if resolved:
                normalized_samples[key] = resolved
        if normalized_samples:
            scene["frame_samples"] = normalized_samples

        storyboard = scene.setdefault("storyboard", {})
        screenshot_path = storyboard.get("screenshot_path") or scene.get("frame_path", "")
        resolved_screenshot = _resolve_persistent_path(screenshot_path, video_dir)
        if resolved_screenshot:
            storyboard["screenshot_path"] = resolved_screenshot

    return data


def collect_scene_resource_issues(data: Dict) -> List[Dict[str, object]]:
    issues: List[Dict[str, object]] = []
    for scene in data.get("scenes", []):
        scene_number = int(scene.get("scene_number", 0) or 0)
        storyboard = scene.get("storyboard", {})
        screenshot_path = str(storyboard.get("screenshot_path") or scene.get("frame_path") or "").strip()
        missing_screenshot = not screenshot_path or not Path(screenshot_path).exists()

        frame_samples = scene.get("frame_samples") or {}
        missing_samples = [
            key
            for key in REQUIRED_SAMPLE_KEYS
            if not str(frame_samples.get(key, "") or "").strip() or not Path(str(frame_samples.get(key, ""))).exists()
        ]

        if missing_screenshot or missing_samples:
            issues.append(
                {
                    "scene_number": scene_number,
                    "missing_screenshot": missing_screenshot,
                    "missing_samples": missing_samples,
                }
            )
    return issues


def _format_scene_issue_message(items: Sequence[Dict[str, object]], label: str, key: str) -> str:
    preview: List[str] = []
    for item in items[:5]:
        scene_label = f"Scene {int(item.get('scene_number', 0)):03d}"
        if key == "missing_screenshot":
            preview.append(scene_label)
        else:
            preview.append(f"{scene_label}({','.join(item.get(key, []))})")
    suffix = "；..." if len(items) > 5 else ""
    return f"{label}：" + "；".join(preview) + suffix


def validate_scene_resource_readiness(data: Dict) -> Tuple[List[str], List[Dict[str, object]]]:
    issues = collect_scene_resource_issues(data)
    screenshot_issues = [item for item in issues if item.get("missing_screenshot")]
    sample_issues = [item for item in issues if item.get("missing_samples")]

    problems: List[str] = []
    if screenshot_issues:
        problems.append(_format_scene_issue_message(screenshot_issues, "镜头截图缺失", "missing_screenshot"))
    if sample_issues:
        problems.append(_format_scene_issue_message(sample_issues, "镜头样本缺失", "missing_samples"))
    return problems, issues


def validate_next_batch_packet(video_dir: Path, next_batch: Optional[Dict]) -> List[str]:
    if not next_batch:
        return []

    host_dir = video_dir / "host_batches"
    checks = {
        "contact sheet": host_dir / str(next_batch.get("contact_sheet", "")),
        "input": host_dir / str(next_batch.get("input", "")),
        "output": host_dir / str(next_batch.get("output", "")),
        "brief": host_dir / str(next_batch.get("brief", "")),
    }
    missing = [label for label, path in checks.items() if not str(path.name).strip() or not path.exists()]
    if not missing:
        return []
    return [f"当前批次任务包缺失：{next_batch.get('batch_id', '')} 缺少 {', '.join(missing)}"]


def _expected_output_paths(video_dir: Path, video_id: str, requested_formats: Sequence[str]) -> Dict[str, Path]:
    outputs: Dict[str, Path] = {
        "scene_scores_json": video_dir / "scene_scores.json",
        "scene_reports_dir": video_dir / "scene_reports",
        "detailed_analysis_md": video_dir / f"{video_id}_detailed_analysis.md",
        "complete_analysis_md": video_dir / f"{video_id}_complete_analysis.md",
        "classification_summary_md": video_dir / f"{video_id}_classification_summary.md",
        "classification_summary_json": video_dir / f"{video_id}_classification_summary.json",
        "classification_result_json": video_dir / "classification_result.json",
        "storyboard_context_md": video_dir / f"{video_id}_storyboard_context.md",
        "storyboard_context_json": video_dir / f"{video_id}_storyboard_context.json",
        "best_shots_dir": video_dir / "scenes" / "best_shots",
    }
    if "md" in requested_formats:
        outputs["storyboard_md"] = video_dir / f"{video_id}_storyboard.md"
        outputs["audiovisual_md"] = video_dir / f"{video_id}_audiovisual_analysis.md"
    if "pdf" in requested_formats:
        outputs["storyboard_pdf"] = video_dir / f"{video_id}_storyboard.pdf"
        outputs["audiovisual_pdf"] = video_dir / f"{video_id}_audiovisual_analysis.pdf"
    return outputs


def _inspect_output_path(path: Path) -> Dict[str, object]:
    if path.is_dir():
        exists = path.exists()
        entries = len(list(path.iterdir())) if exists else 0
        return {
            "path": str(path),
            "exists": exists,
            "entries": entries,
            "ok": exists and entries > 0,
        }
    exists = path.exists()
    size = path.stat().st_size if exists else 0
    return {
        "path": str(path),
        "exists": exists,
        "size": size,
        "ok": exists and size > 0,
    }


def collect_incomplete_scenes(data: Dict) -> List[Dict]:
    incomplete = []
    for scene in data.get("scenes", []):
        missing_fields = scene_missing_analysis_fields(scene)
        if missing_fields:
            incomplete.append(
                {
                    "scene_number": scene.get("scene_number", 0),
                    "missing_fields": missing_fields,
                }
            )
    return incomplete


def collect_host_batch_receipt_issues(video_dir: Path) -> List[Dict[str, object]]:
    host_dir = video_dir / "host_batches"
    index_payload = _read_json(host_dir / "index.json", {"batches": []})
    issues: List[Dict[str, object]] = []
    for batch in index_payload.get("batches", []):
        batch_id = str(batch.get("batch_id", "") or "")
        output_name = str(batch.get("output", "") or "")
        if not batch_id or not output_name:
            continue
        output_payload = _read_json(host_dir / output_name, {})
        receipt = output_payload.get("receipt") or {}
        reasons = list(_receipt_blocking_reasons(receipt))
        if str(receipt.get("status", "") or "") == "blocked" and not reasons:
            reasons.append("blocked")
        if not reasons:
            continue
        issues.append(
            {
                "batch_id": batch_id,
                "reasons": reasons,
                "needs_review_count": len(receipt.get("needs_review") or []),
            }
        )
    return issues


def collect_audiovisual_handoff_status(video_dir: Path) -> Dict[str, object]:
    handoff_dir = video_dir / "audiovisual_handoff"
    receipt_path = handoff_dir / "receipt.json"
    if not receipt_path.exists():
        return {}
    receipt = _read_json(receipt_path, {})
    tasks = receipt.get("tasks") if isinstance(receipt, dict) else None
    if not isinstance(tasks, dict):
        return {}
    pending = [name for name, info in tasks.items() if isinstance(info, dict) and info.get("status") == "pending"]
    completed = [name for name, info in tasks.items() if isinstance(info, dict) and info.get("status") == "completed"]
    return {
        "handoff_dir": str(handoff_dir),
        "pending_tasks": pending,
        "completed_tasks": completed,
        "brief": str(handoff_dir / "brief.md") if (handoff_dir / "brief.md").exists() else "",
    }


def format_host_batch_receipt_issue_messages(issues: Sequence[Dict[str, object]]) -> List[str]:
    messages: List[str] = []
    for item in issues:
        batch_id = str(item.get("batch_id", "") or "unknown-batch")
        reasons = set(str(reason) for reason in item.get("reasons", []))
        if "needs_review" in reasons:
            count = int(item.get("needs_review_count", 0) or 0)
            messages.append(f"{batch_id} 仍有待复核镜头（{count}）")
        if "disallowed_local_fallback" in reasons:
            messages.append(f"{batch_id} 使用了禁用的本地特征兜底结果")
        if "blocked" in reasons:
            messages.append(f"{batch_id} 当前仍处于 blocked 状态")
    return messages


def format_incomplete_scene_message(incomplete: List[Dict]) -> str:
    preview = []
    for item in incomplete[:5]:
        labels = [ANALYSIS_FIELD_LABELS.get(name, name) for name in item["missing_fields"]]
        preview.append(f"Scene {item['scene_number']:03d} 缺少: {'、'.join(labels)}")
    suffix = "；..." if len(incomplete) > 5 else ""
    return "；".join(preview) + suffix


def build_verification_payload(
    video_dir: Path,
    data: Dict,
    requested_formats: Sequence[str],
    *,
    include_output_checks: bool = False,
) -> Dict[str, object]:
    resource_issues = collect_scene_resource_issues(data)
    batch_receipt_issues = collect_host_batch_receipt_issues(video_dir)
    missing_outputs: List[str] = []
    required_outputs: Dict[str, str] = {}

    if include_output_checks:
        output_paths = _expected_output_paths(video_dir, data.get("video_id", "unknown"), requested_formats)
        for name, path in output_paths.items():
            metadata = _inspect_output_path(path)
            required_outputs[name] = str(path)
            if not metadata["ok"]:
                missing_outputs.append(name)

    return {
        "requested_formats": list(requested_formats),
        "required_outputs": required_outputs,
        "missing_outputs": missing_outputs,
        "missing_screenshot_scenes": [
            int(item["scene_number"])
            for item in resource_issues
            if item.get("missing_screenshot")
        ],
        "missing_sample_scenes": [
            {
                "scene_number": int(item["scene_number"]),
                "missing": list(item.get("missing_samples", [])),
            }
            for item in resource_issues
            if item.get("missing_samples")
        ],
        "blocked_batches": [str(item["batch_id"]) for item in batch_receipt_issues],
        "checked_at": datetime.now().isoformat(),
        "passed": (
            not collect_incomplete_scenes(data)
            and not resource_issues
            and not batch_receipt_issues
            and (not include_output_checks or not missing_outputs)
        ),
    }


def write_delivery_report(video_dir: Path, data: Dict, requested_formats: Sequence[str]) -> Dict[str, object]:
    state = load_run_state(video_dir / "run_state.json")
    output_checks_enabled = state.get("current_stage") in {"finalize", "completed"} or state.get("status") in {"ready_to_finalize", "completed"}
    output_paths = _expected_output_paths(video_dir, data.get("video_id", "unknown"), requested_formats)
    required_outputs = {name: _inspect_output_path(path) for name, path in output_paths.items()}
    missing_outputs = [
        name
        for name, metadata in required_outputs.items()
        if output_checks_enabled and not metadata.get("ok")
    ]
    resource_issues = collect_scene_resource_issues(data)
    incomplete_scenes = collect_incomplete_scenes(data)
    batch_receipt_issues = collect_host_batch_receipt_issues(video_dir)
    audiovisual_handoff = collect_audiovisual_handoff_status(video_dir)

    report = {
        "video_id": data.get("video_id", "unknown"),
        "video_title": data.get("title") or data.get("video_title") or data.get("video_id", "unknown"),
        "status": state.get("status", ""),
        "current_stage": state.get("current_stage", ""),
        "scene_count": len(data.get("scenes", [])),
        "completed_scenes": state.get("completed_scenes", 0),
        "coverage_ratio": state.get("coverage_ratio", 0.0),
        "requested_formats": list(requested_formats),
        "required_outputs": required_outputs,
        "missing_outputs": missing_outputs,
        "missing_screenshot_scenes": [
            int(item["scene_number"])
            for item in resource_issues
            if item.get("missing_screenshot")
        ],
        "missing_sample_scenes": [
            {
                "scene_number": int(item["scene_number"]),
                "missing": list(item.get("missing_samples", [])),
            }
            for item in resource_issues
            if item.get("missing_samples")
        ],
        "blocked_batches": [str(item["batch_id"]) for item in batch_receipt_issues],
        "incomplete_scene_numbers": [int(item["scene_number"]) for item in incomplete_scenes],
        "audiovisual_handoff": audiovisual_handoff,
        "last_error": state.get("last_error", ""),
        "verification": state.get("verification", {}),
        "updated_at": datetime.now().isoformat(),
    }
    delivery_report_path_for(video_dir).write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return report


def validate_finalize_readiness(video_dir: Path, data: Dict) -> List[str]:
    problems: List[str] = []
    incomplete_scenes = collect_incomplete_scenes(data)
    if incomplete_scenes:
        problems.append(f"镜头分析未完成：{format_incomplete_scene_message(incomplete_scenes)}")

    index_path = video_dir / "host_batches" / "index.json"
    if index_path.exists():
        index_payload = json.loads(index_path.read_text(encoding="utf-8"))
        coverage = float(index_payload.get("coverage_ratio", 0.0) or 0.0)
        if coverage < 1.0:
            problems.append(f"批次覆盖率不足：{coverage * 100:.1f}%")
    problems.extend(format_host_batch_receipt_issue_messages(collect_host_batch_receipt_issues(video_dir)))
    resource_problems, _ = validate_scene_resource_readiness(data)
    problems.extend(resource_problems)
    return problems
