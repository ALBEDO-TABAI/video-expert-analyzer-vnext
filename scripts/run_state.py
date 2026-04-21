#!/usr/bin/env python3
"""
Lightweight run-state helpers for staged orchestration.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional


def _atomic_write_text(path: Path, text: str) -> None:
    """Write `text` to `path` atomically.

    Using a same-directory tempfile + os.replace avoids the read-half-update
    race that occurs when the orchestrator and ai_analyzer both touch
    run_state.json concurrently.
    """
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


VALID_STAGES = {"prepare", "score_batches", "merge_validate", "finalize", "completed"}
VALID_STATUSES = {"running", "waiting_for_batches", "blocked", "ready_to_finalize", "completed", "paused", "failed"}


def _timestamp() -> str:
    return datetime.now().isoformat()


def _normalize_video_dir(value: str) -> str:
    """Make video_dir absolute + strip `.`/`..`, but skip symlink resolution.

    Path.resolve() canonicalizes drive-letter case on Windows and follows
    symlinks; both make stored paths brittle when the user moves the
    project. os.path.abspath + normpath gives a stable absolute string.
    """
    if not value:
        return ""
    return os.path.normpath(os.path.abspath(value))


def _normalize_scores_path(value: str, video_dir: str) -> str:
    """Store scores_path as relative-to-video_dir when possible.

    Keeping the path relative makes the run_state file portable across
    machines / OSes (no leaked drive letters or absolute prefixes). Falls
    back to a normalized absolute path when video_dir is unknown or the
    scores file lives outside it.
    """
    if not value:
        return ""
    absolute = os.path.normpath(os.path.abspath(value))
    if not video_dir:
        return absolute
    try:
        return os.path.relpath(absolute, video_dir)
    except ValueError:
        # Different drives on Windows -> relpath raises.
        return absolute


def default_verification() -> Dict:
    return {
        "requested_formats": [],
        "required_outputs": {},
        "missing_outputs": [],
        "missing_screenshot_scenes": [],
        "missing_sample_scenes": [],
        "checked_at": "",
        "passed": False,
    }


def default_run_state() -> Dict:
    return {
        "version": "vnext",
        "status": "running",
        "current_stage": "prepare",
        "completed_stages": [],
        "total_scenes": 0,
        "completed_scenes": 0,
        "coverage_ratio": 0.0,
        "next_batch": None,
        "can_finalize": False,
        "scores_path": "",
        "video_dir": "",
        "last_error": "",
        "verification": default_verification(),
        "updated_at": _timestamp(),
    }


def load_run_state(path: Path) -> Dict:
    if not path.exists():
        return default_run_state()
    raw = ""
    try:
        raw = path.read_text(encoding="utf-8")
        payload = json.loads(raw)
    except OSError as exc:
        print(f"⚠️ run_state: 无法读取 {path}: {exc}")
        return default_run_state()
    except json.JSONDecodeError as exc:
        print(f"⚠️ run_state: {path} JSON 格式错误 (行 {exc.lineno}): {exc.msg}")
        return default_run_state()

    if not isinstance(payload, dict):
        print(f"⚠️ run_state: {path} 内容不是 JSON 对象，已忽略")
        return default_run_state()

    state = default_run_state()
    state.update(payload)
    return state


def save_run_state(path: Path, state: Dict) -> None:
    payload = default_run_state()
    payload.update(state)
    payload["verification"] = {
        **default_verification(),
        **(payload.get("verification") or {}),
    }
    payload["updated_at"] = _timestamp()
    _atomic_write_text(path, json.dumps(payload, indent=2, ensure_ascii=False))


def mark_stage(
    path: Path,
    *,
    stage: str,
    status: Optional[str] = None,
    completed: bool = False,
    next_batch: Optional[Dict] = None,
    total_scenes: Optional[int] = None,
    completed_scenes: Optional[int] = None,
    coverage_ratio: Optional[float] = None,
    can_finalize: Optional[bool] = None,
    scores_path: Optional[str] = None,
    video_dir: Optional[str] = None,
    last_error: Optional[str] = None,
    verification: Optional[Dict] = None,
) -> Dict:
    state = load_run_state(path)

    if stage not in VALID_STAGES:
        print(f"⚠️ mark_stage: 未知阶段 '{stage}'，合法值: {', '.join(sorted(VALID_STAGES))}")
    state["current_stage"] = stage

    if status is not None:
        if status not in VALID_STATUSES:
            print(f"⚠️ mark_stage: 未知状态 '{status}'，合法值: {', '.join(sorted(VALID_STATUSES))}")
        state["status"] = status
    if completed and stage not in state["completed_stages"]:
        state["completed_stages"].append(stage)
    if next_batch is not None:
        state["next_batch"] = next_batch
    if stage == "completed" or status == "completed" or status == "ready_to_finalize" or can_finalize is True:
        state["next_batch"] = None
    if total_scenes is not None:
        state["total_scenes"] = total_scenes
    if completed_scenes is not None:
        state["completed_scenes"] = completed_scenes
    if coverage_ratio is not None:
        state["coverage_ratio"] = round(float(coverage_ratio), 4)
    if can_finalize is not None:
        state["can_finalize"] = bool(can_finalize)
    if video_dir is not None:
        state["video_dir"] = _normalize_video_dir(video_dir)
    if scores_path is not None:
        state["scores_path"] = _normalize_scores_path(scores_path, state.get("video_dir", ""))
    if last_error is not None:
        state["last_error"] = last_error
    if verification is not None:
        state["verification"] = {
            **default_verification(),
            **verification,
        }

    save_run_state(path, state)
    return state
