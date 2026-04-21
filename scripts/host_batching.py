#!/usr/bin/env python3
"""
Host-model batching helpers for Video Expert Analyzer.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence


def _atomic_write_text(path: Path, text: str) -> None:
    """Write `text` to `path` atomically via tempfile + os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise

try:
    from motion_analysis import extract_scene_sample_frames
except ImportError:  # pragma: no cover - script execution fallback
    import sys

    sys.path.insert(0, str(Path(__file__).parent))
    from motion_analysis import extract_scene_sample_frames


ALLOWED_BATCH_FIELDS = {
    "type_classification",
    "description",
    "visual_summary",
    "scores",
    "selection_reasoning",
    "edit_suggestion",
    "notes",
}

ALLOWED_STORYBOARD_FIELDS = {
    "shot_size",
    "lighting",
    "camera_movement",
    "visual_style",
    "technique",
}

DISALLOWED_RECEIPT_SUMMARY_MARKERS = (
    "pil-based frame feature analysis",
    "pil image analysis",
    "brightness, color, contrast features",
)

STALE_IN_PROGRESS_MINUTES = 30
STALE_RECOVERY_MARKER = "[auto-recovered from stale in_progress] "


def _parse_receipt_timestamp(value: object) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _default_stale_minutes() -> int:
    raw = os.environ.get("VNEXT_STALE_MINUTES", "").strip()
    if not raw:
        return STALE_IN_PROGRESS_MINUTES
    try:
        value = int(raw)
    except ValueError:
        return STALE_IN_PROGRESS_MINUTES
    return value if value > 0 else STALE_IN_PROGRESS_MINUTES


def reset_stale_in_progress_receipts(
    host_batches_dir: Path,
    *,
    now: Optional[datetime] = None,
    stale_after_minutes: Optional[int] = None,
) -> List[str]:
    """
    Find batch-*-output.json files whose receipt is stuck in `in_progress`
    for longer than the stale threshold and reset them back to `pending`
    so the next run can retry them.

    The stale threshold comes from (in order): explicit `stale_after_minutes`
    argument → env var `VNEXT_STALE_MINUTES` → default `STALE_IN_PROGRESS_MINUTES`.
    Long-running batches should bump this or have the worker periodically
    update `receipt.heartbeat_at` (or `updated_at`) to avoid being reaped.

    Before writing, the receipt is re-read to confirm the status is still
    `in_progress` — this guards against racing with a worker that has just
    completed the batch.

    Returns the list of batch_ids that were reset.
    """
    dir_path = Path(host_batches_dir)
    if not dir_path.exists() or not dir_path.is_dir():
        return []

    threshold = int(stale_after_minutes) if stale_after_minutes is not None else _default_stale_minutes()
    cutoff = (now or datetime.now()) - timedelta(minutes=max(1, threshold))
    recovered: List[str] = []

    for output_path in sorted(dir_path.glob("batch-*-output.json")):
        try:
            payload = _read_json(output_path)
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        receipt = payload.get("receipt")
        if not isinstance(receipt, dict):
            continue
        if str(receipt.get("status", "")) != "in_progress":
            continue
        started_at = _parse_receipt_timestamp(receipt.get("started_at"))
        updated_at = _parse_receipt_timestamp(receipt.get("updated_at"))
        heartbeat_at = _parse_receipt_timestamp(receipt.get("heartbeat_at"))
        anchor = max(filter(None, [started_at, updated_at, heartbeat_at]), default=None)
        if anchor is None or anchor > cutoff:
            continue

        try:
            fresh_payload = _read_json(output_path)
        except (OSError, json.JSONDecodeError):
            continue
        fresh_receipt = fresh_payload.get("receipt") if isinstance(fresh_payload, dict) else None
        if not isinstance(fresh_receipt, dict) or str(fresh_receipt.get("status", "")) != "in_progress":
            continue

        fresh_receipt["status"] = "pending"
        fresh_receipt["has_todo"] = True
        fresh_receipt["updated_at"] = ""
        fresh_receipt["completed_at"] = ""
        existing_summary = str(fresh_receipt.get("worker_summary", "") or "")
        if not existing_summary.startswith(STALE_RECOVERY_MARKER):
            fresh_receipt["worker_summary"] = f"{STALE_RECOVERY_MARKER}{existing_summary}".rstrip()
        fresh_payload["receipt"] = fresh_receipt
        if _write_json_if_changed(output_path, fresh_payload):
            batch_id = str(fresh_payload.get("batch_id", "") or output_path.stem.replace("-output", ""))
            recovered.append(batch_id)

    return recovered


def _build_scene_output_skeletons(batch_scenes: Sequence[Dict]) -> List[Dict]:
    return [
        {
            "scene_number": scene.get("scene_number", 0),
            "type_classification": "",
            "description": "",
            "visual_summary": "",
            "storyboard": {key: "" for key in ALLOWED_STORYBOARD_FIELDS},
            "scores": {},
            "selection_reasoning": "",
            "edit_suggestion": "",
            "notes": "",
        }
        for scene in batch_scenes
    ]


def _default_receipt(batch_id: str, batch_scenes: Sequence[Dict]) -> Dict[str, object]:
    return {
        "batch_id": batch_id,
        "scene_numbers": [int(scene.get("scene_number", 0)) for scene in batch_scenes],
        "output_path": f"{batch_id}-output.json",
        "status": "pending",
        "has_todo": True,
        "needs_review": [],
        "worker_summary": "",
        "started_at": "",
        "updated_at": "",
        "completed_at": "",
    }


def _compute_weighted_score(scene: Dict) -> float:
    scores = scene.get("scores", {})
    scene_type = str(scene.get("type_classification", ""))
    if "TYPE-A" in scene_type:
        weighted = (
            float(scores.get("impact", 0)) * 0.40
            + float(scores.get("memorability", 0)) * 0.30
            + float(scores.get("aesthetic_beauty", 0)) * 0.20
            + float(scores.get("fun_interest", 0)) * 0.10
        )
    elif "TYPE-B" in scene_type:
        weighted = (
            float(scores.get("credibility", 0)) * 0.40
            + float(scores.get("memorability", 0)) * 0.30
            + float(scores.get("aesthetic_beauty", 0)) * 0.20
            + float(scores.get("fun_interest", 0)) * 0.10
        )
    elif "TYPE-C" in scene_type:
        weighted = (
            float(scores.get("aesthetic_beauty", 0)) * 0.50
            + float(scores.get("impact", 0)) * 0.20
            + float(scores.get("memorability", 0)) * 0.20
            + float(scores.get("credibility", 0)) * 0.10
        )
    else:
        weighted = (
            float(scores.get("credibility", 0)) * 0.40
            + float(scores.get("memorability", 0)) * 0.40
            + float(scores.get("aesthetic_beauty", 0)) * 0.20
        )
    return round(weighted, 2)


def _compute_selection(scene: Dict) -> str:
    scores = scene.get("scores", {})
    weighted = float(scene.get("weighted_score", 0.0))
    if weighted >= 8.5 or any(value == 10 for value in scores.values()):
        return "[MUST KEEP]"
    if weighted >= 7.0:
        return "[USABLE]"
    return "[DISCARD]"


def _hydrate_scene_completion_fields(scene: Dict) -> bool:
    if not str(scene.get("type_classification", "")).strip():
        return False
    scores = scene.get("scores", {})
    required_scores = (
        "aesthetic_beauty",
        "credibility",
        "impact",
        "memorability",
        "fun_interest",
    )
    if any(float(scores.get(key, 0) or 0) <= 0 for key in required_scores):
        return False
    weighted_score = _compute_weighted_score(scene)
    scene["weighted_score"] = weighted_score
    scene["selection"] = _compute_selection(scene)
    return True


def _is_scene_complete(scene: Dict) -> bool:
    scores = scene.get("scores", {})
    required_scores = (
        "aesthetic_beauty",
        "credibility",
        "impact",
        "memorability",
        "fun_interest",
    )
    if any(float(scores.get(key, 0) or 0) <= 0 for key in required_scores):
        return False
    if not str(scene.get("type_classification", "")).strip() or str(scene.get("type_classification", "")).startswith("TODO"):
        return False
    if not str(scene.get("description", "")).strip() or str(scene.get("description", "")).startswith("TODO"):
        return False
    if not str(scene.get("selection_reasoning", "")).strip() or str(scene.get("selection_reasoning", "")).startswith("TODO"):
        return False
    if not str(scene.get("edit_suggestion", "")).strip() or str(scene.get("edit_suggestion", "")).startswith("TODO"):
        return False
    storyboard = scene.get("storyboard", {})
    for key in ALLOWED_STORYBOARD_FIELDS:
        value = str(storyboard.get(key, "")).strip()
        if not value or value.startswith("TODO"):
            return False
    return float(scene.get("weighted_score", 0) or 0) > 0 and str(scene.get("selection", "")).startswith("[")


def _receipt_worker_summary_uses_disallowed_fallback(receipt: Dict) -> bool:
    summary = str(receipt.get("worker_summary", "") or "").strip().lower()
    return any(marker in summary for marker in DISALLOWED_RECEIPT_SUMMARY_MARKERS)


def _receipt_blocking_reasons(receipt: Dict) -> List[str]:
    reasons: List[str] = []
    if receipt.get("needs_review"):
        reasons.append("needs_review")
    if _receipt_worker_summary_uses_disallowed_fallback(receipt):
        reasons.append("disallowed_local_fallback")
    return reasons


def _derive_batch_status(receipt: Dict, batch_scenes: Sequence[Dict]) -> str:
    current_status = str(receipt.get("status", "pending") or "pending")
    if _receipt_blocking_reasons(receipt) or current_status == "blocked":
        return "blocked"
    if current_status == "in_progress":
        return "in_progress"
    if batch_scenes and all(_is_scene_complete(scene) for scene in batch_scenes):
        return "completed"
    return "pending"


def _chunk_scenes(scenes: Sequence[Dict], batch_size: int) -> List[List[Dict]]:
    ordered = sorted(scenes, key=lambda scene: int(scene.get("scene_number", 0)))
    return [ordered[index:index + batch_size] for index in range(0, len(ordered), batch_size)]


def _ensure_batch_scene_samples(batch_scenes: Sequence[Dict], video_dir: Path) -> None:
    frames_dir = video_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    for scene in batch_scenes:
        sample_paths = scene.get("frame_samples") or {}
        required_keys = ("primary", "start", "mid", "end")
        if all(sample_paths.get(key) and Path(str(sample_paths[key])).exists() for key in required_keys):
            continue

        scene_file_text = str(scene.get("file_path", "") or "").strip()
        if not scene_file_text:
            continue
        scene_file = Path(scene_file_text)
        if not scene_file.exists():
            continue

        scene_stem = Path(scene.get("filename") or scene_file.name).stem
        sample_bundle = extract_scene_sample_frames(scene_file, frames_dir, scene_stem)
        sample_paths = sample_bundle.get("sample_paths", {}) or {}
        scene["frame_samples"] = sample_paths
        primary_path = str(sample_paths.get("primary", "") or scene.get("frame_path", ""))
        if primary_path:
            scene["frame_path"] = primary_path
            storyboard = scene.setdefault("storyboard", {})
            storyboard["screenshot_path"] = primary_path
        duration_seconds = sample_bundle.get("duration_seconds")
        if duration_seconds and not scene.get("duration_seconds"):
            scene["duration_seconds"] = duration_seconds


def _render_contact_sheet(batch_scenes: Sequence[Dict], output_path: Path) -> None:
    from PIL import Image, ImageDraw, ImageFont

    font = ImageFont.load_default()
    cell_w = 300
    cell_h = 169
    margin = 10
    columns = ("start", "mid", "end", "primary")
    canvas = Image.new(
        "RGB",
        (60 + len(columns) * (cell_w + margin), margin + len(batch_scenes) * (cell_h + margin) + 24),
        "white",
    )
    draw = ImageDraw.Draw(canvas)
    for column_index, column_name in enumerate(columns):
        x = 60 + column_index * (cell_w + margin)
        draw.text((x, 4), column_name, fill="black", font=font)
    for row_index, scene in enumerate(batch_scenes):
        y = margin + 24 + row_index * (cell_h + margin)
        draw.text((6, y + cell_h // 2), f"{int(scene.get('scene_number', 0)):03d}", fill="black", font=font)
        frame_samples = scene.get("frame_samples", {})
        for column_index, key in enumerate(columns):
            x = 60 + column_index * (cell_w + margin)
            image_path = Path(str(frame_samples.get(key, "") or scene.get("frame_path", "")))
            frame = Image.new("RGB", (cell_w, cell_h), "#dddddd")
            if image_path.exists():
                image = Image.open(image_path).convert("RGB")
                image.thumbnail((cell_w, cell_h))
                offset_x = (cell_w - image.width) // 2
                offset_y = (cell_h - image.height) // 2
                frame.paste(image, (offset_x, offset_y))
            canvas.paste(frame, (x, y))
            draw.rectangle([x, y, x + cell_w, y + cell_h], outline="#999999", width=1)
    canvas.save(output_path)


def _ensure_contact_sheet(batch_scenes: Sequence[Dict], output_path: Path) -> None:
    output_path.parent.mkdir(exist_ok=True)
    _render_contact_sheet(batch_scenes, output_path)


def _relative_path(path_text: str, base_dir: Path) -> str:
    if not path_text:
        return ""
    path = Path(str(path_text))
    try:
        return str(path.relative_to(base_dir))
    except ValueError:
        return str(path)


def _non_empty_scores(scores: Dict) -> Dict:
    return {
        key: value
        for key, value in (scores or {}).items()
        if isinstance(value, (int, float)) and float(value) > 0
    }


def _build_batch_input_scene(scene: Dict, video_dir: Path, payload_style: str = "compact") -> Dict:
    storyboard = scene.get("storyboard", {})
    if payload_style == "full":
        return {
            "scene_number": scene.get("scene_number", 0),
            "filename": scene.get("filename", ""),
            "timestamp_range": scene.get("timestamp_range", ""),
            "duration_seconds": scene.get("duration_seconds"),
            "frame_path": scene.get("frame_path", ""),
            "frame_samples": scene.get("frame_samples", {}),
            "motion_analysis": scene.get("motion_analysis", {}),
            "voiceover": storyboard.get("voiceover", ""),
            "onscreen_text": storyboard.get("onscreen_text", ""),
            "camera_movement_hint": storyboard.get("camera_movement_hint", ""),
            "camera_movement_rationale": storyboard.get("camera_movement_rationale", ""),
            "existing_analysis": {
                "type_classification": scene.get("type_classification", ""),
                "description": scene.get("description", ""),
                "visual_summary": scene.get("visual_summary", ""),
                "storyboard": {key: storyboard.get(key, "") for key in ALLOWED_STORYBOARD_FIELDS},
                "scores": scene.get("scores", {}),
                "selection_reasoning": scene.get("selection_reasoning", ""),
                "edit_suggestion": scene.get("edit_suggestion", ""),
                "notes": scene.get("notes", ""),
            },
        }

    frame_samples = scene.get("frame_samples", {})
    return {
        "scene_number": scene.get("scene_number", 0),
        "time_range": scene.get("timestamp_range", ""),
        "duration_s": scene.get("duration_seconds"),
        "frames": {
            "primary": _relative_path(str(scene.get("frame_path", "")), video_dir),
            "start": _relative_path(str(frame_samples.get("start", "")), video_dir),
            "mid": _relative_path(str(frame_samples.get("mid", "")), video_dir),
            "end": _relative_path(str(frame_samples.get("end", "")), video_dir),
        },
        "hints": {
            "voiceover": storyboard.get("voiceover", ""),
            "onscreen_text": storyboard.get("onscreen_text", ""),
            "camera_movement_hint": storyboard.get("camera_movement_hint", ""),
        },
        "existing": {
            "type_classification": scene.get("type_classification", ""),
            "description": scene.get("description", ""),
            "scores": _non_empty_scores(scene.get("scores", {})),
        },
    }


def _build_batch_output_skeleton(batch_id: str, batch_scenes: Sequence[Dict]) -> Dict:
    return {
        "batch_id": batch_id,
        "receipt": _default_receipt(batch_id, batch_scenes),
        "scenes": _build_scene_output_skeletons(batch_scenes),
    }


def _derive_receipt_status(receipt: Dict, batch_scenes: Sequence[Dict], payload: Dict) -> str:
    if _receipt_blocking_reasons(receipt):
        return "blocked"
    if batch_scenes and all(_is_scene_complete(scene) for scene in batch_scenes):
        return "completed"
    payload_scenes = payload.get("scenes", [])
    if payload_scenes and all(_is_scene_complete(scene) for scene in payload_scenes):
        return "completed"
    if receipt.get("needs_review"):
        return "blocked"
    current_status = str(receipt.get("status", "pending") or "pending")
    if current_status in {"blocked", "in_progress"}:
        return current_status
    return "pending"


def _ensure_output_payload_shape(batch_id: str, batch_scenes: Sequence[Dict], payload: Dict | None) -> Dict:
    normalized = dict(payload or {})
    normalized.setdefault("batch_id", batch_id)
    normalized.setdefault("scenes", _build_scene_output_skeletons(batch_scenes))
    for scene in normalized.get("scenes", []):
        _hydrate_scene_completion_fields(scene)

    receipt = _default_receipt(batch_id, batch_scenes)
    receipt.update(normalized.get("receipt") or {})
    receipt["status"] = _derive_receipt_status(receipt, batch_scenes, normalized)
    receipt["has_todo"] = receipt["status"] != "completed"
    normalized["receipt"] = receipt
    return normalized


def _read_json(path: Path, default: Dict | None = None) -> Dict:
    if not path.exists():
        return default or {}
    return json.loads(path.read_text(encoding="utf-8"))


def _stable_json_text(payload: Dict) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)


def _write_json_if_changed(path: Path, payload: Dict) -> bool:
    serialized = _stable_json_text(payload)
    if path.exists() and path.read_text(encoding="utf-8") == serialized:
        return False
    _atomic_write_text(path, serialized)
    return True


def _write_text_if_changed(path: Path, text: str) -> bool:
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return False
    _atomic_write_text(path, text)
    return True


def _batch_output_digest(payload: Dict) -> str:
    digest_source = {
        "batch_id": payload.get("batch_id", ""),
        "scenes": payload.get("scenes", []),
    }
    return hashlib.sha1(_stable_json_text(digest_source).encode("utf-8")).hexdigest()


def _apply_batch_item(target_scene: Dict, item: Dict) -> bool:
    changed = False
    for key in ALLOWED_BATCH_FIELDS:
        if key not in item:
            continue
        incoming = item.get("scores", {}) if key == "scores" else item.get(key)
        if target_scene.get(key) != incoming:
            target_scene[key] = incoming
            changed = True

    storyboard_update = item.get("storyboard", {})
    storyboard = target_scene.setdefault("storyboard", {})
    for key in ALLOWED_STORYBOARD_FIELDS:
        if key not in storyboard_update:
            continue
        incoming = storyboard_update.get(key)
        if storyboard.get(key) != incoming:
            storyboard[key] = incoming
            changed = True
    previous_weighted = target_scene.get("weighted_score")
    previous_selection = target_scene.get("selection")
    if _hydrate_scene_completion_fields(target_scene):
        if target_scene.get("weighted_score") != previous_weighted:
            changed = True
        if target_scene.get("selection") != previous_selection:
            changed = True
    return changed


def _write_batch_brief(
    batch_id: str,
    batch_scenes: Sequence[Dict],
    host_dir: Path,
    contact_sheet_path: Path,
    input_path: Path,
    output_path: Path,
) -> Path:
    lines = [
        f"# {batch_id} host task",
        "",
        "只处理当前批次，不要回看整条长历史。",
        "",
        f"- contact sheet: `{contact_sheet_path.name}`",
        f"- input: `{input_path.name}`",
        f"- output: `{output_path.name}`",
        "- contact sheet 只用于总览，不允许只靠它写结果。",
        "- 必须逐个 scene 查看 start / mid / end 三帧；必要时再补看 primary 或 scene clip。",
        "- input.json 里的 frames 字段已经给出当前批次每个 scene 的 primary / start / mid / end 路径。",
        "- 每个 scene 都必须补全类型、画面描述、五维评分、筛选理由、剪辑建议、分镜字段。",
        "- 接手后先把 output.json 顶层 receipt.status 改成 `in_progress`，并写 started_at、updated_at。",
        "- 写完后把 receipt.status 改成 `completed`，把 has_todo 改成 false，并补全 worker_summary、updated_at、completed_at。",
        "- 如果中途发现缺素材或无法判断，就把 receipt.status 改成 `blocked`，把原因写进 worker_summary 和 needs_review 后退出。",
        "- 写完当前批次就结束当前任务。",
        "",
        "## Scenes",
    ]
    for scene in batch_scenes:
        lines.append(
            f"- Scene {int(scene.get('scene_number', 0)):03d} | {scene.get('timestamp_range', '')} | "
            f"{scene.get('storyboard', {}).get('voiceover', '')[:40]}"
        )
    brief_path = host_dir / f"{batch_id}-brief.md"
    _write_text_if_changed(brief_path, "\n".join(lines).strip() + "\n")
    return brief_path


def prepare_host_batches(
    data: Dict,
    video_dir: Path,
    batch_size: int = 10,
    payload_style: str = "compact",
) -> Dict[str, object]:
    scenes = data.get("scenes", [])
    host_dir = video_dir / "host_batches"
    host_dir.mkdir(exist_ok=True)
    batches = _chunk_scenes(scenes, batch_size)

    completed_scenes = 0
    index_payload = {
        "video_id": data.get("video_id", video_dir.name),
        "batch_size": batch_size,
        "total_scenes": len(scenes),
        "total_batches": len(batches),
        "completed_scenes": 0,
        "coverage_ratio": 0.0,
        "batches": [],
    }

    for batch_number, batch_scenes in enumerate(batches, 1):
        batch_id = f"batch-{batch_number:03d}"
        contact_sheet_path = host_dir / f"{batch_id}-contact-sheet.png"
        input_path = host_dir / f"{batch_id}-input.json"
        output_path = host_dir / f"{batch_id}-output.json"
        _ensure_batch_scene_samples(batch_scenes, video_dir)
        input_payload = {
            "batch_id": batch_id,
            "payload_style": payload_style,
            "contact_sheet": contact_sheet_path.name,
            "scene_numbers": [int(scene.get("scene_number", 0)) for scene in batch_scenes],
            "scenes": [_build_batch_input_scene(scene, video_dir, payload_style=payload_style) for scene in batch_scenes],
        }
        input_changed = _write_json_if_changed(input_path, input_payload)
        output_payload = _ensure_output_payload_shape(batch_id, batch_scenes, _read_json(output_path, None))
        _write_json_if_changed(output_path, output_payload)
        brief_path = _write_batch_brief(batch_id, batch_scenes, host_dir, contact_sheet_path, input_path, output_path)
        if input_changed or not contact_sheet_path.exists():
            _ensure_contact_sheet(batch_scenes, contact_sheet_path)
        batch_status = _derive_batch_status(output_payload.get("receipt", {}), batch_scenes)
        batch_completed = batch_status == "completed"
        if batch_completed:
            completed_scenes += len(batch_scenes)
        index_payload["batches"].append(
            {
                "batch_id": batch_id,
                "scene_numbers": [int(scene.get("scene_number", 0)) for scene in batch_scenes],
                "contact_sheet": contact_sheet_path.name,
                "input": input_path.name,
                "output": output_path.name,
                "brief": brief_path.name,
                "status": batch_status,
            }
        )

    index_payload["completed_scenes"] = completed_scenes
    index_payload["coverage_ratio"] = round(completed_scenes / max(len(scenes), 1), 4) if scenes else 0.0
    index_path = host_dir / "index.json"
    _write_json_if_changed(index_path, index_payload)
    return index_payload


def merge_host_batch_outputs(scores_path: Path, video_dir: Path) -> Dict:
    data = json.loads(scores_path.read_text(encoding="utf-8"))
    scenes_by_number = {int(scene.get("scene_number", 0)): scene for scene in data.get("scenes", [])}

    host_dir = video_dir / "host_batches"
    host_dir.mkdir(exist_ok=True)
    index_path = host_dir / "index.json"
    index_payload = _read_json(index_path, {"batches": []})

    completed_scenes = 0
    data_changed = False
    for batch in index_payload.get("batches", []):
        output_path = host_dir / str(batch.get("output", ""))
        output_payload = _read_json(output_path, {"scenes": []})
        merged_digest = _batch_output_digest(output_payload)
        if batch.get("merged_digest") != merged_digest:
            for item in output_payload.get("scenes", []):
                scene_number = int(item.get("scene_number", 0))
                target_scene = scenes_by_number.get(scene_number)
                if not target_scene:
                    continue
                data_changed = _apply_batch_item(target_scene, item) or data_changed
            batch["merged_digest"] = merged_digest

        batch_scene_numbers = [int(number) for number in batch.get("scene_numbers", [])]
        batch_scenes = [scenes_by_number[number] for number in batch_scene_numbers if number in scenes_by_number]
        batch["status"] = _derive_batch_status(output_payload.get("receipt", {}), batch_scenes)

    for scene in data.get("scenes", []):
        if _is_scene_complete(scene):
            weighted_score = _compute_weighted_score(scene)
            selection = _compute_selection(scene)
            if scene.get("weighted_score") != weighted_score:
                scene["weighted_score"] = weighted_score
                data_changed = True
            if scene.get("selection") != selection:
                scene["selection"] = selection
                data_changed = True
            completed_scenes += 1

    total_scenes = max(int(index_payload.get("total_scenes", len(data.get("scenes", [])))), 1)
    index_payload["completed_scenes"] = completed_scenes
    index_payload["coverage_ratio"] = round(completed_scenes / total_scenes, 4)
    _write_json_if_changed(index_path, index_payload)
    if data_changed:
        _write_json_if_changed(scores_path, data)
    return data


def get_next_pending_batch(video_dir: Path) -> Dict | None:
    index_payload = _read_json(video_dir / "host_batches" / "index.json", {"batches": []})
    for batch in index_payload.get("batches", []):
        if batch.get("status") != "completed":
            return batch
    return None


def expected_best_shot_count(total_scenes: int) -> int:
    capped = math.ceil(total_scenes * 0.15)
    return max(6, min(20, capped))
