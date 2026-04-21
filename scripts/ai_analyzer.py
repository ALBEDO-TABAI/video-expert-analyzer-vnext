#!/usr/bin/env python3
"""
AI Scene Analyzer v2.2.1
默认使用自动并行评分链路完成场景分析，并通过文件驱动批次流程管理进度。
"""

import argparse
import base64
import json
import os
import re
import shutil
import sys
import threading
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

try:
    from storyboard_generator import (
        enrich_storyboard_data,
        generate_storyboard_outputs,
        ANALYSIS_FIELD_LABELS,
        scene_has_complete_analysis,
        scene_missing_analysis_fields,
    )
except ImportError:
    sys.path.insert(0, str(Path(__file__).parent))
    from storyboard_generator import (
        enrich_storyboard_data,
        generate_storyboard_outputs,
        ANALYSIS_FIELD_LABELS,
        scene_has_complete_analysis,
        scene_missing_analysis_fields,
    )

try:
    from detailed_report_builder import generate_detailed_analysis_outputs
except ImportError:
    sys.path.insert(0, str(Path(__file__).parent))
    from detailed_report_builder import generate_detailed_analysis_outputs

try:
    from classification_summary import write_classification_summary_outputs
except ImportError:
    sys.path.insert(0, str(Path(__file__).parent))
    from classification_summary import write_classification_summary_outputs

try:
    from video_type_router_runtime import generate_classification_result
except ImportError:
    sys.path.insert(0, str(Path(__file__).parent))
    from video_type_router_runtime import generate_classification_result

try:
    from audiovisual.reporting.builder import generate_audiovisual_report_outputs
    from audiovisual.reporting.handoff import AudiovisualHandoffPending
except ImportError:
    sys.path.insert(0, str(Path(__file__).parent))
    from audiovisual.reporting.builder import generate_audiovisual_report_outputs
    from audiovisual.reporting.handoff import AudiovisualHandoffPending

try:
    from motion_analysis import MOTION_ANALYSIS_VERSION, analyze_camera_motion, build_frame_sample_paths, extract_scene_sample_frames
except ImportError:
    sys.path.insert(0, str(Path(__file__).parent))
    from motion_analysis import MOTION_ANALYSIS_VERSION, analyze_camera_motion, build_frame_sample_paths, extract_scene_sample_frames

try:
    from lyric_ocr_refiner import refine_music_subtitles
except ImportError:
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from lyric_ocr_refiner import refine_music_subtitles
    except ImportError:
        refine_music_subtitles = None

try:
    from host_batching import (
        _apply_batch_item,
        _ensure_output_payload_shape,
        _is_scene_complete,
        _receipt_blocking_reasons,
        _read_json,
        _write_json_if_changed,
        get_next_pending_batch,
        merge_host_batch_outputs,
        prepare_host_batches,
        reset_stale_in_progress_receipts,
    )
except ImportError:
    sys.path.insert(0, str(Path(__file__).parent))
    from host_batching import (
        _apply_batch_item,
        _ensure_output_payload_shape,
        _is_scene_complete,
        _receipt_blocking_reasons,
        _read_json,
        _write_json_if_changed,
        get_next_pending_batch,
        merge_host_batch_outputs,
        prepare_host_batches,
        reset_stale_in_progress_receipts,
    )

try:
    from run_state import load_run_state, mark_stage
except ImportError:
    sys.path.insert(0, str(Path(__file__).parent))
    from run_state import load_run_state, mark_stage

try:
    from logger import get_logger
except ImportError:
    sys.path.insert(0, str(Path(__file__).parent))
    from logger import get_logger

try:
    from delivery_validation import (
        REQUIRED_SAMPLE_KEYS,
        _candidate_frame_path,
        _candidate_scene_file_path,
        _expected_output_paths,
        _format_scene_issue_message,
        _inspect_output_path,
        _normalize_scene_resource_paths,
        _resolve_persistent_path,
        build_verification_payload,
        collect_audiovisual_handoff_status,
        collect_host_batch_receipt_issues,
        collect_incomplete_scenes,
        collect_scene_resource_issues,
        delivery_report_path_for,
        format_host_batch_receipt_issue_messages,
        format_incomplete_scene_message,
        validate_finalize_readiness,
        validate_next_batch_packet,
        validate_scene_resource_readiness,
        write_delivery_report,
    )
except ImportError:
    sys.path.insert(0, str(Path(__file__).parent))
    from delivery_validation import (
        REQUIRED_SAMPLE_KEYS,
        _candidate_frame_path,
        _candidate_scene_file_path,
        _expected_output_paths,
        _format_scene_issue_message,
        _inspect_output_path,
        _normalize_scene_resource_paths,
        _resolve_persistent_path,
        build_verification_payload,
        collect_audiovisual_handoff_status,
        collect_host_batch_receipt_issues,
        collect_incomplete_scenes,
        collect_scene_resource_issues,
        delivery_report_path_for,
        format_host_batch_receipt_issue_messages,
        format_incomplete_scene_message,
        validate_finalize_readiness,
        validate_next_batch_packet,
        validate_scene_resource_readiness,
        write_delivery_report,
    )

log = get_logger("analyzer")


# ============================================================
# 术语对照表
# ============================================================
TERMINOLOGY = {
    "TYPE-A Hook": "TYPE-A Hook (钩子/开场型)",
    "TYPE-B Narrative": "TYPE-B Narrative (叙事/情感型)",
    "TYPE-C Aesthetic": "TYPE-C Aesthetic (氛围/空镜型)",
    "TYPE-D Commercial": "TYPE-D Commercial (商业/展示型)",
    "aesthetic_beauty": "美感 Aesthetic Beauty (构图/光影/色彩)",
    "credibility": "可信度 Credibility (真实感/表演自然度)",
    "impact": "冲击力 Impact (视觉显著性/动态张力)",
    "memorability": "记忆度 Memorability (独特符号/金句)",
    "fun_interest": "趣味度 Fun/Interest (参与感/娱乐价值)",
    "MUST KEEP": "MUST KEEP (强烈推荐保留)",
    "USABLE": "USABLE (可用素材)",
    "DISCARD": "DISCARD (建议舍弃)",
}


def get_term_chinese(term: str) -> str:
    return TERMINOLOGY.get(term, term)


def save_scores_data(data: Dict, scores_path: Path):
    scores_path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def parse_storyboard_formats(raw_value: str) -> List[str]:
    formats = [item.strip().lower() for item in raw_value.split(",") if item.strip()]
    return formats or ["md", "pdf"]


def run_state_path_for(scores_path: Path) -> Path:
    return scores_path.parent / "run_state.json"


def _batch_size_for_mode(explicit_batch_size: int, openclaw_mode: bool) -> int:
    if explicit_batch_size > 0:
        return explicit_batch_size
    return 4 if openclaw_mode else 6


def _chunk_scenes_for_batches(scenes: Sequence[Dict], batch_size: int) -> List[List[Dict]]:
    ordered = sorted(scenes, key=lambda scene: int(scene.get("scene_number", 0)))
    return [ordered[index:index + batch_size] for index in range(0, len(ordered), batch_size)]


def _next_pending_scene_numbers(data: Dict, batch_size: int) -> List[int]:
    for batch_scenes in _chunk_scenes_for_batches(data.get("scenes", []), batch_size):
        if not all(_is_scene_complete(scene) for scene in batch_scenes):
            return [int(scene.get("scene_number", 0)) for scene in batch_scenes]
    return []


def _next_batch_state(video_dir: Path, next_batch: Optional[Dict]) -> Optional[Dict]:
    if not next_batch:
        return None
    return {
        "batch_id": next_batch.get("batch_id", ""),
        "scene_numbers": next_batch.get("scene_numbers", []),
        "contact_sheet": str(video_dir / "host_batches" / str(next_batch.get("contact_sheet", ""))) if next_batch.get("contact_sheet") else "",
        "input": str(video_dir / "host_batches" / str(next_batch.get("input", ""))),
        "output": str(video_dir / "host_batches" / str(next_batch.get("output", ""))),
        "brief": str(video_dir / "host_batches" / str(next_batch.get("brief", ""))) if next_batch.get("brief") else "",
    }


AUTO_SCORING_MISSING_MESSAGE = "缺少自动评分配置"
AUTO_SCORING_VALIDATION_FILENAME = "auto_scoring_validation.json"
AUTO_SCORING_VALIDATION_SAMPLE_SIZE = 3
AUTO_SCORING_VALIDATION_MAX_TOTAL_DELTA = 4.0
DEFAULT_AUTO_SCORING_MAX_WORKERS = 4


def auto_scoring_setup_hints() -> List[str]:
    return [
        "OpenClaw 路径：确认本机存在 ~/.openclaw/agents/*/agent/models.json，且里面带有可用 provider 配置。",
        "环境变量路径：至少提供 API Key、模型名，以及需要时的 Base URL（例如 VIDEO_ANALYZER_API_KEY / VIDEO_ANALYZER_MODEL / VIDEO_ANALYZER_BASE_URL）。",
    ]


def is_missing_auto_scoring_config_error(message: object) -> bool:
    return AUTO_SCORING_MISSING_MESSAGE in str(message or "")


def _load_auto_scoring_settings() -> Tuple[Dict[str, Any], Dict[str, Any], Any]:
    try:
        from pipeline_enhanced import DEFAULT_AUTO_SCORING, load_config, save_config
    except ImportError:
        sys.path.insert(0, str(Path(__file__).parent))
        from pipeline_enhanced import DEFAULT_AUTO_SCORING, load_config, save_config

    config = load_config()
    auto_scoring = dict(DEFAULT_AUTO_SCORING)
    auto_scoring.update(config.get("auto_scoring") or {})
    auto_scoring["models_json_path"] = str(auto_scoring.get("models_json_path", "") or "").strip()
    auto_scoring["preferred_model"] = str(auto_scoring.get("preferred_model", DEFAULT_AUTO_SCORING["preferred_model"]) or "").strip()
    fallback_models = auto_scoring.get("fallback_models", DEFAULT_AUTO_SCORING["fallback_models"])
    auto_scoring["fallback_models"] = [str(item).strip() for item in fallback_models if str(item).strip()]
    try:
        auto_scoring["max_workers"] = max(1, int(auto_scoring.get("max_workers", DEFAULT_AUTO_SCORING["max_workers"])))
    except (TypeError, ValueError):
        auto_scoring["max_workers"] = DEFAULT_AUTO_SCORING["max_workers"]
    return config, auto_scoring, save_config


def _resolve_env_auto_scoring_config(auto_scoring: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    direct_api_key = str(os.getenv("VIDEO_ANALYZER_API_KEY", "") or "").strip()
    direct_model = str(os.getenv("VIDEO_ANALYZER_MODEL", "") or "").strip()
    if direct_api_key and direct_model:
        provider_name = str(os.getenv("VIDEO_ANALYZER_PROVIDER", "") or "env").strip() or "env"
        api_style = str(os.getenv("VIDEO_ANALYZER_API_STYLE", "") or "openai-completions").strip() or "openai-completions"
        base_url = str(os.getenv("VIDEO_ANALYZER_BASE_URL", "") or "").strip()
        return {
            "config_source": "env",
            "providers": {
                provider_name: {
                    "apiKey": direct_api_key,
                    "baseUrl": base_url,
                    "api": api_style,
                    "models": [{"id": direct_model, "api": api_style, "input": ["text", "image"]}],
                }
            },
            "preferred_model": f"{provider_name}/{direct_model}",
            "fallback_models": [],
            "max_workers": int(auto_scoring.get("max_workers", DEFAULT_AUTO_SCORING_MAX_WORKERS) or DEFAULT_AUTO_SCORING_MAX_WORKERS),
        }

    openai_api_key = str(os.getenv("OPENAI_API_KEY", "") or "").strip()
    openai_model = str(os.getenv("OPENAI_MODEL", "") or os.getenv("VIDEO_ANALYZER_MODEL", "") or "").strip()
    if openai_api_key and openai_model:
        return {
            "config_source": "env",
            "providers": {
                "openai": {
                    "apiKey": openai_api_key,
                    "baseUrl": str(os.getenv("OPENAI_BASE_URL", "") or "https://api.openai.com/v1").strip(),
                    "api": "openai-completions",
                    "models": [{"id": openai_model, "api": "openai-completions", "input": ["text", "image"]}],
                }
            },
            "preferred_model": f"openai/{openai_model}",
            "fallback_models": [],
            "max_workers": int(auto_scoring.get("max_workers", DEFAULT_AUTO_SCORING_MAX_WORKERS) or DEFAULT_AUTO_SCORING_MAX_WORKERS),
        }

    anthropic_api_key = str(os.getenv("ANTHROPIC_API_KEY", "") or "").strip()
    anthropic_model = str(os.getenv("ANTHROPIC_MODEL", "") or "").strip()
    if anthropic_api_key and anthropic_model:
        return {
            "config_source": "env",
            "providers": {
                "anthropic": {
                    "apiKey": anthropic_api_key,
                    "baseUrl": str(os.getenv("ANTHROPIC_BASE_URL", "") or "https://api.anthropic.com").strip(),
                    "api": "anthropic-messages",
                    "models": [{"id": anthropic_model, "api": "anthropic-messages", "input": ["text", "image"]}],
                }
            },
            "preferred_model": f"anthropic/{anthropic_model}",
            "fallback_models": [],
            "max_workers": int(auto_scoring.get("max_workers", DEFAULT_AUTO_SCORING_MAX_WORKERS) or DEFAULT_AUTO_SCORING_MAX_WORKERS),
        }
    return None


def resolve_auto_scoring_config() -> Dict[str, Any]:
    config, auto_scoring, save_config = _load_auto_scoring_settings()
    models_json_path = Path(auto_scoring.get("models_json_path", "")).expanduser() if auto_scoring.get("models_json_path") else None
    if models_json_path and models_json_path.exists():
        return {
            "config_source": "openclaw",
            "models_json_path": str(models_json_path.resolve()),
            "preferred_model": auto_scoring["preferred_model"],
            "fallback_models": list(auto_scoring["fallback_models"]),
            "max_workers": int(auto_scoring.get("max_workers", DEFAULT_AUTO_SCORING_MAX_WORKERS) or DEFAULT_AUTO_SCORING_MAX_WORKERS),
        }

    try:
        from openclaw_batch_probe import find_models_json_candidates
    except ImportError:
        sys.path.insert(0, str(Path(__file__).parent))
        from openclaw_batch_probe import find_models_json_candidates

    candidates = find_models_json_candidates()
    if candidates:
        chosen = candidates[0].resolve()
        auto_scoring["models_json_path"] = str(chosen)
        config["auto_scoring"] = auto_scoring
        save_config(config)
        return {
            "config_source": "openclaw",
            "models_json_path": str(chosen),
            "preferred_model": auto_scoring["preferred_model"],
            "fallback_models": list(auto_scoring["fallback_models"]),
            "max_workers": int(auto_scoring.get("max_workers", DEFAULT_AUTO_SCORING_MAX_WORKERS) or DEFAULT_AUTO_SCORING_MAX_WORKERS),
        }

    env_config = _resolve_env_auto_scoring_config(auto_scoring)
    if env_config:
        return env_config

    hints = "；".join(auto_scoring_setup_hints())
    return {
        "error": f"{AUTO_SCORING_MISSING_MESSAGE}：未找到可用的 OpenClaw models.json，也没有检测到可直连的 API Key / Base URL / 模型配置。{hints}",
        "max_workers": int(auto_scoring.get("max_workers", DEFAULT_AUTO_SCORING_MAX_WORKERS) or DEFAULT_AUTO_SCORING_MAX_WORKERS),
    }


def _collect_batch_packets(
    video_dir: Path,
    *,
    scene_numbers: Optional[Sequence[int]] = None,
    pending_only: bool = True,
) -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    host_dir = video_dir / "host_batches"
    index_payload = _read_json(host_dir / "index.json", {"batches": []})
    scene_packets: List[Dict[str, Any]] = []
    batch_context: Dict[str, Dict[str, Any]] = {}
    target_numbers = {int(number) for number in scene_numbers} if scene_numbers is not None else None

    for batch in index_payload.get("batches", []):
        batch_id = str(batch.get("batch_id", "") or "")
        input_path = host_dir / str(batch.get("input", "") or "")
        output_path = host_dir / str(batch.get("output", "") or "")
        input_payload = _read_json(input_path, {"scenes": []})
        batch_scenes = input_payload.get("scenes", [])
        output_payload = _ensure_output_payload_shape(batch_id, batch_scenes, _read_json(output_path, None))
        existing_by_number = {
            int(scene.get("scene_number", 0) or 0): scene
            for scene in output_payload.get("scenes", [])
        }
        batch_context[batch_id] = {
            "output_path": output_path,
            "output_payload": output_payload,
            "scenes_by_number": existing_by_number,
        }

        for scene in batch_scenes:
            scene_number = int(scene.get("scene_number", 0) or 0)
            if target_numbers is not None and scene_number not in target_numbers:
                continue
            if pending_only and _is_scene_complete(existing_by_number.get(scene_number, {})):
                continue
            packet = dict(scene)
            packet["batch_id"] = batch_id
            packet["frames"] = {
                key: str((video_dir / str(value)).resolve()) if value else ""
                for key, value in (scene.get("frames") or {}).items()
            }
            scene_packets.append(packet)

    scene_packets.sort(key=lambda item: int(item.get("scene_number", 0) or 0))
    return scene_packets, batch_context


def _build_auto_scoring_attempts(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    try:
        from openclaw_batch_probe import build_attempt_order, load_provider_catalog
    except ImportError:
        sys.path.insert(0, str(Path(__file__).parent))
        from openclaw_batch_probe import build_attempt_order, load_provider_catalog

    if config.get("config_source") == "openclaw":
        providers = load_provider_catalog(Path(str(config.get("models_json_path", ""))).expanduser())
    else:
        providers = dict(config.get("providers") or {})

    return build_attempt_order(
        providers,
        preferred_model=str(config.get("preferred_model", "") or ""),
        fallback_models=tuple(config.get("fallback_models", ()) or ()),
    )


def _validation_report_path(video_dir: Path) -> Path:
    return video_dir / AUTO_SCORING_VALIDATION_FILENAME


def _format_scene_number_labels(scene_numbers: Sequence[int]) -> str:
    ordered = [int(number) for number in scene_numbers if int(number) > 0]
    if not ordered:
        return ""
    return "、".join(f"Scene {number:03d}" for number in ordered)


def run_auto_scoring_validation(
    scores_path: Path,
    video_dir: Path,
    config: Dict[str, Any],
    *,
    scored_scene_numbers: Sequence[int],
    sample_size: int = AUTO_SCORING_VALIDATION_SAMPLE_SIZE,
    max_workers: int = 3,
) -> Dict[str, Any]:
    try:
        from openclaw_batch_probe import (
            analyze_scenes,
            build_validation_report,
            sample_scene_numbers,
        )
    except ImportError:
        sys.path.insert(0, str(Path(__file__).parent))
        from openclaw_batch_probe import (
            analyze_scenes,
            build_validation_report,
            sample_scene_numbers,
        )

    ordered_scored_numbers = sorted({int(number) for number in scored_scene_numbers if int(number) > 0})
    sampled_numbers = sample_scene_numbers(ordered_scored_numbers, sample_size)
    report_path = _validation_report_path(video_dir)
    if not sampled_numbers:
        payload = {
            "checked_at": datetime.now().isoformat(),
            "sample_scene_numbers": [],
            "needs_review_scene_numbers": [],
            "validation_failed_scene_numbers": [],
            "passed": True,
        }
        report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return {
            "report_path": str(report_path.resolve()),
            "sample_scene_numbers": [],
            "needs_review_scene_numbers": [],
            "validation_failed_scene_numbers": [],
            "passed": True,
        }

    attempts = _build_auto_scoring_attempts(config)
    sample_packets, _ = _collect_batch_packets(video_dir, scene_numbers=sampled_numbers, pending_only=False)
    scores_payload = json.loads(scores_path.read_text(encoding="utf-8"))
    reference_scenes = [
        scene
        for scene in scores_payload.get("scenes", [])
        if int(scene.get("scene_number", 0) or 0) in set(sampled_numbers)
    ]

    run_items, validation_scenes, failed_scenes = analyze_scenes(
        sample_packets,
        attempts=attempts,
        max_workers=min(max(1, int(max_workers or 1)), max(len(sample_packets), 1)),
    )
    report_payload = build_validation_report(
        generated_scenes=validation_scenes,
        reference_scenes=reference_scenes,
        sample_size=len(sampled_numbers),
        scene_packets=sample_packets,
    )
    failed_numbers = sorted({int(scene.get("scene_number", 0) or 0) for scene in failed_scenes})
    needs_review_numbers = sorted(
        {
            *failed_numbers,
            *[
                int(sample.get("scene_number", 0) or 0)
                for sample in report_payload.get("samples", [])
                if (not sample.get("type_matches")) or float(sample.get("total_score_delta", 0.0) or 0.0) > AUTO_SCORING_VALIDATION_MAX_TOTAL_DELTA
            ],
        }
    )
    report_payload.update(
        {
            "checked_at": datetime.now().isoformat(),
            "validation_run_items": run_items,
            "validation_failed_scene_numbers": failed_numbers,
            "needs_review_scene_numbers": needs_review_numbers,
            "passed": not needs_review_numbers and not failed_numbers and bool(report_payload.get("order_matches_reference", True)),
        }
    )
    report_path.write_text(json.dumps(report_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "report_path": str(report_path.resolve()),
        "sample_scene_numbers": list(report_payload.get("sample_scene_numbers", [])),
        "needs_review_scene_numbers": needs_review_numbers,
        "validation_failed_scene_numbers": failed_numbers,
        "passed": bool(report_payload.get("passed")),
    }


def auto_fill_pending_batches(
    scores_path: Path,
    video_dir: Path,
    config: Dict[str, Any],
    *,
    max_workers: int,
) -> Dict[str, Any]:
    del scores_path  # 当前自动评分只依赖 host_batches 协议文件

    try:
        from openclaw_batch_probe import analyze_scenes
    except ImportError:
        sys.path.insert(0, str(Path(__file__).parent))
        from openclaw_batch_probe import analyze_scenes

    recovered_batches = reset_stale_in_progress_receipts(video_dir / "host_batches")
    if recovered_batches:
        log.info("recovered stale in_progress batches: %s", recovered_batches)

    attempts = _build_auto_scoring_attempts(config)
    scene_packets, batch_context = _collect_batch_packets(video_dir, pending_only=True)
    if not scene_packets:
        return {
            "scored_scenes": 0,
            "failed_scenes": 0,
            "completed_batches": [],
            "failed_batches": [],
            "max_workers": max_workers,
            "scored_scene_numbers": [],
            "failed_scene_numbers": [],
        }

    now = datetime.now().isoformat()
    failure_map_by_batch: Dict[str, Dict[int, Dict[str, Any]]] = {}
    flush_locks: Dict[str, threading.Lock] = {
        batch_id: threading.Lock() for batch_id in batch_context
    }
    for batch_id, context in batch_context.items():
        output_payload = dict(context["output_payload"])
        receipt = output_payload.setdefault("receipt", {})
        receipt["status"] = "in_progress"
        receipt["has_todo"] = True
        receipt["started_at"] = str(receipt.get("started_at", "") or now)
        receipt["updated_at"] = now
        receipt["completed_at"] = ""
        receipt["needs_review"] = []
        context["output_payload"] = output_payload
        failure_map_by_batch[batch_id] = {}
        _write_json_if_changed(Path(context["output_path"]), output_payload)

    def flush_result(payload: Dict[str, Any]) -> None:
        run_item = payload.get("run_item") or {}
        batch_id = str(run_item.get("batch_id", "") or "")
        scene_number = int(run_item.get("scene_number", 0) or 0)
        context = batch_context.get(batch_id)
        if not context or scene_number <= 0:
            return

        lock = flush_locks.get(batch_id)
        if lock is None:
            return
        with lock:
            output_payload = dict(context["output_payload"])
            scenes_by_number = context["scenes_by_number"]
            receipt = output_payload.setdefault("receipt", {})
            successful = payload.get("scene_result")
            failed = payload.get("failed")
            if successful and scene_number in scenes_by_number:
                _apply_batch_item(scenes_by_number[scene_number], successful)
                failure_map_by_batch[batch_id].pop(scene_number, None)
            if failed:
                failure_map_by_batch[batch_id][scene_number] = {
                    "scene_number": scene_number,
                    "error": str((failed or {}).get("error", "") or ""),
                }
            receipt["needs_review"] = list(failure_map_by_batch[batch_id].values())
            receipt["status"] = "in_progress"
            receipt["has_todo"] = True
            receipt["updated_at"] = datetime.now().isoformat()
            done_count = sum(
                1
                for scene in output_payload.get("scenes", [])
                if _is_scene_complete(scene)
            )
            receipt["worker_summary"] = (
                f"auto parallel scoring in progress; "
                f"completed={done_count} failed={len(failure_map_by_batch[batch_id])}"
            )
            context["output_payload"] = output_payload
            _write_json_if_changed(Path(context["output_path"]), output_payload)

    run_items, successful_results, failed_results = analyze_scenes(
        scene_packets,
        attempts=attempts,
        max_workers=max(1, int(max_workers or 1)),
        on_result=flush_result,
    )
    successful_by_number = {
        int(scene.get("scene_number", 0) or 0): scene
        for scene in successful_results
    }
    run_items_by_batch: Dict[str, List[Dict[str, Any]]] = {}
    for item in run_items:
        run_items_by_batch.setdefault(str(item.get("batch_id", "") or ""), []).append(item)

    completed_batches: List[str] = []
    failed_batches: List[str] = []
    for batch_id, context in batch_context.items():
        output_payload = dict(context["output_payload"])
        receipt = output_payload.setdefault("receipt", {})
        receipt["updated_at"] = now

        batch_failed_items = [
            {
                "scene_number": int(item.get("scene_number", 0) or 0),
                "error": str(item.get("error", "") or ""),
            }
            for item in run_items_by_batch.get(batch_id, [])
            if not item.get("ok")
        ]
        incomplete_numbers = [
            int(scene.get("scene_number", 0) or 0)
            for scene in output_payload.get("scenes", [])
            if not _is_scene_complete(scene)
        ]
        model_usage = Counter(
            str(item.get("used_model", "") or "")
            for item in run_items_by_batch.get(batch_id, [])
            if str(item.get("used_model", "") or "")
        )
        receipt["needs_review"] = batch_failed_items
        receipt["worker_summary"] = (
            f"auto parallel scoring via {config.get('config_source', 'unknown')}; "
            f"success={sum(1 for item in run_items_by_batch.get(batch_id, []) if item.get('ok'))} "
            f"failed={len(batch_failed_items)} models={dict(model_usage)}"
        )

        if batch_failed_items:
            receipt["status"] = "blocked"
            receipt["has_todo"] = True
            receipt["completed_at"] = ""
            failed_batches.append(batch_id)
        elif not incomplete_numbers:
            receipt["status"] = "completed"
            receipt["has_todo"] = False
            receipt["completed_at"] = now
            completed_batches.append(batch_id)
        else:
            receipt["status"] = "pending"
            receipt["has_todo"] = True
            receipt["completed_at"] = ""

        _write_json_if_changed(Path(context["output_path"]), output_payload)

    return {
        "scored_scenes": len(successful_results),
        "failed_scenes": len(failed_results),
        "completed_batches": completed_batches,
        "failed_batches": failed_batches,
        "max_workers": max_workers,
        "config_source": str(config.get("config_source", "") or ""),
        "scored_scene_numbers": sorted(successful_by_number.keys()),
        "failed_scene_numbers": sorted(int(scene.get("scene_number", 0) or 0) for scene in failed_results),
    }


def resolve_stage(mode: str, scores_path: Path) -> str:
    if mode in {"host", "agent"}:
        return "score_batches"
    if mode != "auto":
        return mode

    state = load_run_state(run_state_path_for(scores_path))
    if state.get("status") == "completed" or state.get("current_stage") == "completed":
        return "completed"
    if state.get("can_finalize"):
        return "finalize"
    if state.get("completed_stages") and "prepare" in state.get("completed_stages", []):
        return "score_batches"
    return "score_batches"


# ============================================================
# System Prompt for Vision LLM
# ============================================================
SCORING_SYSTEM_PROMPT = """你是一位专业的视频剪辑/镜头分析专家，精通 Walter Murch 剪辑六法则。

准确性优先于速度。不要为了节省时间偷懒，不要用套路化空话敷衍，不要根据相邻场景或字幕去猜没看清的画面。

你会收到同一场景的首帧、中帧、尾帧。你必须结合三张图一起判断镜头内容，尤其是运镜，不允许只看单帧就下结论。

请把这一次返回视为这个 scene 的独立小报告：只有当这个小报告里的画面描述、分镜字段和评分都足够准确时，整份总报告才会准确。所以你必须先把当前 scene 看准，再输出结果。

请按以下维度打分（1-10 整数）：

1. **aesthetic_beauty** (美感): 构图（如三分法/对称）、光影质感、色彩和谐度
2. **credibility** (可信度): 画面真实感、物理逻辑、AI生成痕迹程度（痕迹越少分越高）
3. **impact** (冲击力): 第一眼视觉显著性、动态张力、能否瞬间吸引观众
4. **memorability** (记忆度): 独特视觉符号、冯·雷斯托夫效应、过目不忘程度
5. **fun_interest** (趣味度): 参与感、娱乐价值、社交货币潜力

同时判断场景类型：
- TYPE-A Hook: 高冲击力开场/高能片段
- TYPE-B Narrative: 叙事/情感表达
- TYPE-C Aesthetic: 空镜/氛围/纯美学
- TYPE-D Commercial: 产品展示/商业广告

你必须严格按以下 JSON 格式返回结果，不要附加任何其他文字：
```json
{
 "type_classification": "TYPE-X ...",
  "description": "一句话中文描述画面内容",
  "visual_summary": "视觉元素概要",
  "storyboard": {
    "shot_size": "景别，如远景/中景/特写",
    "lighting": "灯光，如自然光/侧逆光/硬光",
    "camera_movement": "运镜，如静止镜头/推进/摇镜/跟拍",
    "visual_style": "画风，如暖色纪实/黑白艺术感",
    "technique": "手法，如特写突出表情/留白营造氛围"
  },
  "scores": {
    "aesthetic_beauty": 8,
    "credibility": 7,
    "impact": 9,
    "memorability": 8,
    "fun_interest": 7
  },
  "selection_reasoning": "入选/淘汰理由（中文）",
  "edit_suggestion": "剪辑建议（中文）"
}
```"""


SCORING_USER_PROMPT_TEMPLATE = """请分析以下视频的第 {scene_num} 个场景。

视频标题：{video_title}
视频总场景数：{total_scenes}
场景时间范围：{scene_timestamp}
对应台词/字幕：{scene_voiceover}
自动运镜提示：{camera_motion_hint}
自动运镜依据：{camera_motion_rationale}
{transcript_info}

请综合首帧、中帧、尾帧与自动提示，认真完成这个 scene 的独立小报告。
不要在意耗时，重要的是这个 scene 的判断准确、具体、可落到画面。
如果自动提示和你看到的画面不一致，以你认真看图后的最终判断为准。
请严格按 JSON 格式返回分析结果。"""


# ============================================================
# API 模式：调用远程视觉大模型
# ============================================================
SCENE_REQUIRED_FIELDS = (
    "type_classification",
    "description",
    "visual_summary",
    "storyboard",
    "scores",
    "selection_reasoning",
    "edit_suggestion",
)

SCENE_REQUIRED_SCORE_FIELDS = (
    "aesthetic_beauty",
    "credibility",
    "impact",
    "memorability",
    "fun_interest",
)

SCENE_REQUIRED_STORYBOARD_FIELDS = (
    "shot_size",
    "lighting",
    "camera_movement",
    "visual_style",
    "technique",
)

# 上下文长度安全阈值：中文约 1 token ≈ 4 字符，3000 字符约 750 token，
# 留出足够空间给 system prompt + 3 帧 + JSON 输出
_TRANSCRIPT_MAX_CHARS = 3000
_SCENE_VOICEOVER_MAX_CHARS = 500


def _truncate_text(text: str, max_chars: int, label: str = "") -> str:
    """截断过长的文本并在末尾标注省略。"""
    if not text or len(text) <= max_chars:
        return text
    return text[:max_chars] + f"…（{label or '文本'}已截断，原文 {len(text)} 字符）"


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.IGNORECASE | re.DOTALL)


def _extract_json_object(content: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    text = (content or "").strip()
    if not text:
        return None, "响应为空"

    fence_match = _JSON_FENCE_RE.search(text)
    candidates: List[str] = []
    if fence_match:
        candidates.append(fence_match.group(1).strip())
    candidates.append(text)

    decoder = json.JSONDecoder()
    last_error: Optional[str] = None

    for candidate in candidates:
        for start_index, char in enumerate(candidate):
            if char != "{":
                continue
            try:
                parsed, _ = decoder.raw_decode(candidate[start_index:])
            except json.JSONDecodeError as exc:
                last_error = f"JSON解析失败 - {exc}"
                continue
            if isinstance(parsed, dict):
                return parsed, None
            last_error = "响应中的JSON不是对象"

    return None, last_error or "响应中未找到JSON对象"


def _validate_scene_json(result: Dict[str, Any], scene_num: int) -> Optional[Dict[str, Any]]:
    missing_fields = [field for field in SCENE_REQUIRED_FIELDS if field not in result]
    if missing_fields:
        log.warning("Scene %03d: JSON缺少必需字段 - %s", scene_num, ", ".join(missing_fields))
        return None

    scores = result.get("scores")
    if not isinstance(scores, dict):
        log.warning("Scene %03d: scores 字段必须是对象", scene_num)
        return None

    missing_scores = [field for field in SCENE_REQUIRED_SCORE_FIELDS if field not in scores]
    if missing_scores:
        log.warning("Scene %03d: scores缺少必需字段 - %s", scene_num, ", ".join(missing_scores))
        return None

    # 校验分数范围 1-10，越界则钳制
    for field in SCENE_REQUIRED_SCORE_FIELDS:
        raw = scores[field]
        if not isinstance(raw, (int, float)):
            scores[field] = 5
            log.warning("Scene %03d: %s 不是数字(%s)，已回退为 5", scene_num, field, raw)
        elif raw < 1 or raw > 10:
            clamped = max(1, min(10, int(raw)))
            log.warning("Scene %03d: %s=%s 超出 [1,10]，已钳制为 %d", scene_num, field, raw, clamped)
            scores[field] = clamped

    storyboard = result.get("storyboard")
    if not isinstance(storyboard, dict):
        log.warning("Scene %03d: storyboard 字段必须是对象", scene_num)
        return None

    missing_storyboard = [field for field in SCENE_REQUIRED_STORYBOARD_FIELDS if field not in storyboard]
    if missing_storyboard:
        log.warning("Scene %03d: storyboard缺少必需字段 - %s", scene_num, ", ".join(missing_storyboard))
        return None

    return result


def _parse_scene_response(content: str, scene_num: int) -> Optional[Dict[str, Any]]:
    result, error = _extract_json_object(content)
    if error:
        print(f"   ⚠️  Scene {scene_num:03d}: {error}")
        print(f"   原始响应: {content[:200]}...")
        return None
    return _validate_scene_json(result, scene_num)


def call_vision_api(
    frame_path: Path,
    sample_frame_paths: Dict[str, str],
    scene_num: int,
    video_title: str = "",
    total_scenes: int = 0,
    transcript_text: str = "",
    scene_timestamp: str = "",
    scene_voiceover: str = "",
    camera_motion_hint: str = "",
    camera_motion_rationale: str = "",
    api_key: str = "",
    base_url: str = "",
    model: str = "",
) -> Optional[Dict]:
    """通过 OpenAI 兼容 API 调用视觉大模型分析帧画面"""

    try:
        from openai import OpenAI
    except ImportError:
        print("   ⚠️  需要安装 openai 库: pip install openai")
        return None

    if not api_key:
        print("   ⚠️  未设置 VIDEO_ANALYZER_API_KEY 环境变量")
        return None

    def resolve_image_path(raw_path: str) -> Path:
        candidate = Path(raw_path) if raw_path else frame_path
        return candidate if candidate.exists() else frame_path

    def build_image_block(image_path: Path) -> Dict[str, str]:
        image_data = base64.b64encode(image_path.read_bytes()).decode("utf-8")
        mime_type = "image/jpeg" if image_path.suffix.lower() in (".jpg", ".jpeg") else "image/png"
        return {
            "type": "image_url",
            "image_url": {
                "url": f"data:{mime_type};base64,{image_data}",
            },
        }

    transcript_info = f"整体转录参考：{_truncate_text(transcript_text, _TRANSCRIPT_MAX_CHARS, '转录文本')}" if transcript_text else "（该视频暂无额外转录参考）"

    user_prompt = SCORING_USER_PROMPT_TEMPLATE.format(
        scene_num=scene_num,
        video_title=video_title,
        total_scenes=total_scenes,
        transcript_info=transcript_info,
        scene_timestamp=scene_timestamp or "未知",
        scene_voiceover=_truncate_text(scene_voiceover, _SCENE_VOICEOVER_MAX_CHARS, "字幕") or "（该场景暂无可对齐字幕）",
        camera_motion_hint=camera_motion_hint or "暂无自动提示",
        camera_motion_rationale=camera_motion_rationale or "暂无自动依据",
    )

    client = OpenAI(api_key=api_key, base_url=base_url)

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SCORING_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_prompt},
                        {"type": "text", "text": "首帧"},
                        build_image_block(resolve_image_path(sample_frame_paths.get("start", ""))),
                        {"type": "text", "text": "中帧"},
                        build_image_block(resolve_image_path(sample_frame_paths.get("mid", ""))),
                        {"type": "text", "text": "尾帧"},
                        build_image_block(resolve_image_path(sample_frame_paths.get("end", ""))),
                    ],
                },
            ],
            temperature=0.3,
            max_tokens=1024,
        )

        content = response.choices[0].message.content.strip()

        # 提取 JSON（可能包裹在 ```json ... ``` 中）
        json_match = re.search(r"\{[\s\S]*\}", content)
        if not json_match:
            log.warning("Scene %03d: 无法解析模型返回的 JSON - 响应中未找到JSON对象", scene_num)
            log.debug("Scene %03d 原始响应: %s...", scene_num, content[:200])
            return None

        try:
            result = json.loads(json_match.group())
        except json.JSONDecodeError as e:
            log.warning("Scene %03d: JSON解析失败 - %s", scene_num, e)
            log.debug("Scene %03d 提取的JSON: %s...", scene_num, json_match.group()[:200])
            return None

        # 验证必需字段
        required_fields = ["type_classification", "description", "visual_summary", "storyboard", "scores", "selection_reasoning", "edit_suggestion"]
        missing_fields = [f for f in required_fields if f not in result]
        if missing_fields:
            log.warning("Scene %03d: JSON缺少必需字段 - %s", scene_num, ", ".join(missing_fields))
            return None

        # 验证scores子字段
        required_scores = ["aesthetic_beauty", "credibility", "impact", "memorability", "fun_interest"]
        scores = result.get("scores", {})
        missing_scores = [s for s in required_scores if s not in scores]
        if missing_scores:
            log.warning("Scene %03d: scores缺少必需字段 - %s", scene_num, ", ".join(missing_scores))
            return None

        # 验证storyboard子字段
        required_storyboard = ["shot_size", "lighting", "camera_movement", "visual_style", "technique"]
        storyboard = result.get("storyboard", {})
        missing_storyboard = [s for s in required_storyboard if s not in storyboard]
        if missing_storyboard:
            log.warning("Scene %03d: storyboard缺少必需字段 - %s", scene_num, ", ".join(missing_storyboard))
            return None

        return result

    except Exception as e:
        log.error("Scene %03d: API 调用失败 - %s", scene_num, e)
        return None


# ============================================================
# 加权评分计算
# ============================================================
def compute_weighted_score(analysis: Dict) -> Dict:
    """根据场景类型计算加权分数并确定筛选等级"""

    scores = analysis.get("scores", {})
    type_class = analysis.get("type_classification", "")

    # 根据类型动态调整权重
    if "TYPE-A" in type_class:
        weighted = (
            scores.get("impact", 5) * 0.40
            + scores.get("memorability", 5) * 0.30
            + scores.get("aesthetic_beauty", 5) * 0.20
            + scores.get("fun_interest", 5) * 0.10
        )
    elif "TYPE-B" in type_class:
        weighted = (
            scores.get("credibility", 5) * 0.40
            + scores.get("memorability", 5) * 0.30
            + scores.get("aesthetic_beauty", 5) * 0.20
            + scores.get("fun_interest", 5) * 0.10
        )
    elif "TYPE-C" in type_class:
        weighted = (
            scores.get("aesthetic_beauty", 5) * 0.50
            + scores.get("impact", 5) * 0.20
            + scores.get("memorability", 5) * 0.20
            + scores.get("credibility", 5) * 0.10
        )
    else:  # TYPE-D Commercial
        weighted = (
            scores.get("credibility", 5) * 0.40
            + scores.get("memorability", 5) * 0.40
            + scores.get("aesthetic_beauty", 5) * 0.20
        )

    analysis["weighted_score"] = round(weighted, 2)

    # 确定筛选等级
    if weighted >= 8.5 or any(v == 10 for v in scores.values()):
        analysis["selection"] = "[MUST KEEP]"
    elif weighted >= 7.0:
        analysis["selection"] = "[USABLE]"
    else:
        analysis["selection"] = "[DISCARD]"

    return analysis


def recompute_scene_scores(data: Dict) -> Dict:
    required_scores = (
        "aesthetic_beauty",
        "credibility",
        "impact",
        "memorability",
        "fun_interest",
    )
    for scene in data.get("scenes", []):
        scores = scene.get("scores", {})
        if all(isinstance(scores.get(key), (int, float)) and scores.get(key, 0) > 0 for key in required_scores):
            compute_weighted_score(scene)
            storyboard = scene.setdefault("storyboard", {})
            storyboard.setdefault("visual_description", scene.get("description", ""))
    return data


def ensure_motion_analysis(
    data: Dict,
    video_dir: Path,
    *,
    scene_numbers: Optional[Sequence[int]] = None,
) -> Dict:
    frames_dir = video_dir / "frames"
    frames_dir.mkdir(exist_ok=True)
    if scene_numbers is not None:
        target_scene_numbers = {int(number) for number in scene_numbers}
        if not target_scene_numbers:
            return data
    else:
        target_scene_numbers = None

    for scene in data.get("scenes", []):
        scene_number = int(scene.get("scene_number", 0) or 0)
        if target_scene_numbers is not None and scene_number not in target_scene_numbers:
            continue
        file_path_value = scene.get("file_path", "")
        scene_file = Path(file_path_value) if file_path_value else Path()
        if not scene_file.exists():
            continue

        scene_stem = Path(scene.get("filename") or scene_file.name).stem
        sample_paths = scene.get("frame_samples") or {}
        sample_bundle = None
        required_keys = ("start", "mid", "end", "primary")
        if not all(sample_paths.get(key) and Path(sample_paths[key]).exists() for key in required_keys):
            sample_bundle = extract_scene_sample_frames(scene_file, frames_dir, scene_stem)
            sample_paths = sample_bundle["sample_paths"]
            scene["frame_samples"] = sample_paths

        duration_seconds = scene.get("duration_seconds")
        if sample_bundle is not None and not duration_seconds:
            duration_seconds = sample_bundle.get("duration_seconds", 0.0)
            if duration_seconds:
                scene["duration_seconds"] = duration_seconds

        motion_analysis = scene.get("motion_analysis") or {}
        previous_motion_label = str(motion_analysis.get("label", "")).strip()
        needs_refresh = (
            not motion_analysis
            or not motion_analysis.get("label")
            or motion_analysis.get("version") != MOTION_ANALYSIS_VERSION
        )
        if needs_refresh:
            motion_analysis = analyze_camera_motion(sample_paths, float(duration_seconds or 0.0))
            scene["motion_analysis"] = motion_analysis

        scene["frame_path"] = sample_paths.get("primary", scene.get("frame_path"))
        storyboard = scene.setdefault("storyboard", {})
        previous_hint = str(storyboard.get("camera_movement_hint", "")).strip()
        motion_label = str(motion_analysis.get("label", "")).strip()
        motion_confidence = str(motion_analysis.get("confidence", "")).strip().lower()
        storyboard["camera_movement_hint"] = motion_label
        storyboard["camera_movement_rationale"] = motion_analysis.get("rationale", "")
        storyboard["screenshot_path"] = sample_paths.get("primary", scene.get("frame_path", ""))
        current_camera_movement = str(storyboard.get("camera_movement", "")).strip()
        if not current_camera_movement or current_camera_movement.upper().startswith("TODO"):
            storyboard["camera_movement"] = motion_label or current_camera_movement
        elif needs_refresh and motion_label and current_camera_movement in {previous_motion_label, previous_hint}:
            if current_camera_movement != motion_label:
                storyboard["camera_movement_previous"] = current_camera_movement
            storyboard["camera_movement"] = motion_label
        elif motion_label and current_camera_movement != motion_label and motion_confidence in {"medium", "high"}:
            if not storyboard.get("camera_movement_previous"):
                storyboard["camera_movement_previous"] = current_camera_movement
            storyboard["camera_movement"] = motion_label

    return data


def movement_group(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return "unknown"
    mapping = {
        "static": ("静止", "固定"),
        "scale_in": ("推进", "前推", "推近", "拉近"),
        "scale_out": ("拉远", "拉开", "后撤"),
        "horizontal": ("横移", "左移", "右移", "摇镜", "摇摄", "平移"),
        "vertical": ("俯仰", "上移", "下移"),
        "tracking": ("跟拍", "跟随", "跟镜"),
    }
    lowered = text.lower()
    for group, keywords in mapping.items():
        if any(keyword in text or keyword in lowered for keyword in keywords):
            return group
    return "unknown"


def load_transcript_text(video_analysis_dir: Path, video_id: str) -> str:
    for ext in ["_ocr_corrected.txt", "_transcript.txt", "_ocr_corrected.srt", ".srt"]:
        transcript_file = video_analysis_dir / f"{video_id}{ext}"
        if transcript_file.exists():
            return transcript_file.read_text(encoding="utf-8")
    return ""


def refresh_analysis_data(
    scores_path: Path,
    video_analysis_dir: Path,
    *,
    force_text_refresh: bool = False,
    scene_numbers: Optional[Sequence[int]] = None,
) -> Dict:
    with open(scores_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    data = _normalize_scene_resource_paths(data, video_analysis_dir)

    if refine_music_subtitles is not None:
        try:
            refine_music_subtitles(
                scores_path=scores_path,
                video_dir=video_analysis_dir,
                title=data.get("title", data.get("video_title", "")) or video_analysis_dir.name,
                url=data.get("url", ""),
            )
        except Exception as exc:
            print(f"   ⚠️  OCR 矫正字幕阶段跳过: {exc}")

    data = ensure_motion_analysis(data, video_analysis_dir, scene_numbers=scene_numbers)
    data = _normalize_scene_resource_paths(data, video_analysis_dir)
    data = enrich_storyboard_data(data, video_analysis_dir, force_text_refresh=force_text_refresh)
    data = _normalize_scene_resource_paths(data, video_analysis_dir)
    data = recompute_scene_scores(data)
    save_scores_data(data, scores_path)
    return data


# ============================================================
# 主流程：自动评分
# ============================================================
def auto_score_scenes(
    scores_path: Path,
    video_analysis_dir: Path,
    mode: str = "score_batches",
    *,
    batch_size: int = 0,
    payload_style: str = "compact",
    openclaw_mode: bool = False,
    requested_formats: Optional[Sequence[str]] = None,
) -> Dict:
    """刷新派生数据，自动并行补完批次结果，并按显式阶段推进状态。"""

    state_path = run_state_path_for(scores_path)
    batch_size = _batch_size_for_mode(batch_size, openclaw_mode=openclaw_mode)
    frames_dir = video_analysis_dir / "frames"
    requested_formats = tuple(requested_formats or ())

    if mode == "finalize":
        data = refresh_analysis_data(scores_path, video_analysis_dir, force_text_refresh=True)
        total_scenes = len(data.get("scenes", []))
        print("\n🧾 Finalize 模式：已强制刷新旁白、时间戳和派生上下文，准备生成正式输出")
        readiness_problems = validate_finalize_readiness(video_analysis_dir, data)
        mark_stage(
            state_path,
            stage="finalize",
            status="ready_to_finalize" if not readiness_problems else "blocked",
            completed=False,
            next_batch=None,
            total_scenes=total_scenes,
            completed_scenes=total_scenes - len(collect_incomplete_scenes(data)),
            coverage_ratio=1.0 if not readiness_problems else load_run_state(state_path).get("coverage_ratio", 0.0),
            can_finalize=not readiness_problems,
            scores_path=str(scores_path),
            video_dir=str(video_analysis_dir),
            last_error="; ".join(readiness_problems) if readiness_problems else "",
            verification=build_verification_payload(
                video_analysis_dir,
                data,
                requested_formats,
                include_output_checks=False,
            ),
        )
        return data

    if mode in {"score_batches", "merge_validate"}:
        merged_data = merge_host_batch_outputs(scores_path, video_analysis_dir)
        data = refresh_analysis_data(
            scores_path,
            video_analysis_dir,
            force_text_refresh=True,
            # Auto-parallel scoring consumes every pending batch, so all pending
            # scenes need ready sample frames before we validate resources.
            scene_numbers=None,
        )
        total_scenes = len(data.get("scenes", []))
        index = prepare_host_batches(data, video_analysis_dir, batch_size=batch_size, payload_style=payload_style)
        next_batch = get_next_pending_batch(video_analysis_dir)
        resource_problems, _ = validate_scene_resource_readiness(data)
        packet_problems = validate_next_batch_packet(video_analysis_dir, next_batch)
        blocking_problems = resource_problems + packet_problems
        finalize_problems = validate_finalize_readiness(video_analysis_dir, data) if not next_batch else []
        auto_summary: Optional[Dict[str, Any]] = None
        validation_summary: Optional[Dict[str, Any]] = None

        if mode == "score_batches" and next_batch and not blocking_problems:
            runtime_config = resolve_auto_scoring_config()
            if runtime_config.get("error"):
                blocking_problems.append(str(runtime_config.get("error", "")))
            else:
                try:
                    auto_summary = auto_fill_pending_batches(
                        scores_path,
                        video_analysis_dir,
                        runtime_config,
                        max_workers=int(runtime_config.get("max_workers", DEFAULT_AUTO_SCORING_MAX_WORKERS) or DEFAULT_AUTO_SCORING_MAX_WORKERS),
                    )
                    merged_data = merge_host_batch_outputs(scores_path, video_analysis_dir)
                    data = refresh_analysis_data(scores_path, video_analysis_dir, force_text_refresh=True)
                    total_scenes = len(data.get("scenes", []))
                    index = prepare_host_batches(data, video_analysis_dir, batch_size=batch_size, payload_style=payload_style)
                    next_batch = get_next_pending_batch(video_analysis_dir)
                    resource_problems, _ = validate_scene_resource_readiness(data)
                    packet_problems = validate_next_batch_packet(video_analysis_dir, next_batch)
                    blocking_problems = resource_problems + packet_problems
                    finalize_problems = validate_finalize_readiness(video_analysis_dir, data) if not next_batch else []
                    if int(auto_summary.get("failed_scenes", 0) or 0) > 0:
                        blocking_problems.append(
                            f"自动并行评分仍有 {int(auto_summary.get('failed_scenes', 0) or 0)} 个场景失败，请检查 host_batches 输出"
                        )
                    elif auto_summary.get("scored_scene_numbers"):
                        validation_summary = run_auto_scoring_validation(
                            scores_path,
                            video_analysis_dir,
                            runtime_config,
                            scored_scene_numbers=auto_summary.get("scored_scene_numbers", []),
                            sample_size=min(
                                AUTO_SCORING_VALIDATION_SAMPLE_SIZE,
                                len(auto_summary.get("scored_scene_numbers", []) or []),
                            ),
                        )
                        if not validation_summary.get("passed"):
                            needs_review_labels = _format_scene_number_labels(
                                validation_summary.get("needs_review_scene_numbers", [])
                            )
                            if needs_review_labels:
                                blocking_problems.append(f"抽样校验发现需复核场景：{needs_review_labels}")
                            else:
                                blocking_problems.append("抽样校验未通过，请查看校验报告")
                except Exception as exc:
                    blocking_problems.append(f"自动并行评分失败：{type(exc).__name__}: {exc}")

        if next_batch:
            stage = "score_batches"
            status = "blocked" if blocking_problems else "running"
            can_finalize = False
            last_error = "; ".join(blocking_problems)
        else:
            final_stage_problems = finalize_problems + blocking_problems
            stage = "finalize"
            status = "blocked" if final_stage_problems else "ready_to_finalize"
            can_finalize = not final_stage_problems
            last_error = "; ".join(final_stage_problems)

        mark_stage(
            state_path,
            stage=stage,
            status=status,
            completed=False,
            next_batch=_next_batch_state(video_analysis_dir, next_batch),
            total_scenes=total_scenes,
            completed_scenes=int(index.get("completed_scenes", 0) or 0),
            coverage_ratio=float(index.get("coverage_ratio", 0.0) or 0.0),
            can_finalize=can_finalize,
            scores_path=str(scores_path),
            video_dir=str(video_analysis_dir),
            last_error=last_error,
            verification=build_verification_payload(
                video_analysis_dir,
                data,
                requested_formats,
                include_output_checks=False,
            ),
        )

        print(f"\n📦 Score batches 阶段：已刷新 {total_scenes} 个场景的自动评分批次")
        print(f"   帧图片目录: {frames_dir}")
        print(f"   批次目录: {video_analysis_dir / 'host_batches'}")
        print(f"   当前覆盖率: {index.get('coverage_ratio', 0.0) * 100:.1f}%")
        if auto_summary is not None:
            print(
                "   自动并行评分: "
                f"{int(auto_summary.get('scored_scenes', 0) or 0)} 个场景完成，"
                f"{int(auto_summary.get('failed_scenes', 0) or 0)} 个失败，"
                f"{int(auto_summary.get('max_workers', DEFAULT_AUTO_SCORING_MAX_WORKERS) or DEFAULT_AUTO_SCORING_MAX_WORKERS)} 路并行"
            )
        if validation_summary is not None:
            print(
                "   抽样校验: "
                f"抽查 {len(validation_summary.get('sample_scene_numbers', []))} 个场景，"
                f"{len(validation_summary.get('needs_review_scene_numbers', []))} 个需复核"
            )
            print(f"   校验报告: {validation_summary.get('report_path', '')}")
        if blocking_problems:
            print("   ❌ 当前阶段存在阻塞问题：")
            for problem in blocking_problems:
                print(f"   - {problem}")
        if next_batch:
            scene_numbers = [int(number) for number in next_batch.get("scene_numbers", [])]
            if scene_numbers:
                print(f"   下一批: {next_batch.get('batch_id', '')} | 场景 {scene_numbers[0]:03d}-{scene_numbers[-1]:03d}")
            else:
                print(f"   下一批: {next_batch.get('batch_id', '')}")
            print(f"   读入: {video_analysis_dir / 'host_batches' / next_batch['input']}")
            print(f"   写回: {video_analysis_dir / 'host_batches' / next_batch['output']}")
            if next_batch.get("brief"):
                print(f"   简报: {video_analysis_dir / 'host_batches' / next_batch['brief']}")
        else:
            print("   ✅ 所有批次结果都已写回，可以直接运行 finalize")
        return data

    raise ValueError(f"未知模式: {mode}")


# ============================================================
# 精选镜头筛选与复制
# ============================================================
def select_and_copy_best_shots(scores_path: Path, threshold: float = 7.0) -> List[Dict]:
    """选择最佳镜头并复制到 best_shots 目录"""

    with open(scores_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    scenes = data.get("scenes", [])
    video_dir = scores_path.parent
    best_shots_dir = video_dir / "scenes" / "best_shots"
    best_shots_dir.mkdir(exist_ok=True)

    # 清空旧的精选
    for old in best_shots_dir.glob("*.mp4"):
        old.unlink()

    must_keep = [scene for scene in scenes if "MUST KEEP" in str(scene.get("selection", ""))]
    usable_candidates = [
        scene
        for scene in scenes
        if "MUST KEEP" not in str(scene.get("selection", ""))
        and float(scene.get("weighted_score", 0) or 0) >= max(threshold, 8.0)
    ]
    must_keep.sort(key=lambda x: x.get("weighted_score", 0), reverse=True)
    usable_candidates.sort(key=lambda x: x.get("weighted_score", 0), reverse=True)
    cap = max(6, min(20, __import__("math").ceil(len(scenes) * 0.15))) if scenes else 0
    best_shots = must_keep[:cap]
    if len(best_shots) < cap:
        best_shots.extend(usable_candidates[: max(cap - len(best_shots), 0)])

    print(f"\n⭐ 发现 {len(best_shots)} 个精选镜头 (阈值: {threshold})")

    copied = []
    for i, scene in enumerate(best_shots, 1):
        src_path = Path(scene.get("file_path", ""))
        if src_path.exists():
            tag = scene.get("selection", "").replace("[", "").replace("]", "").replace(" ", "_")
            dst_name = f"{i:02d}_{tag}_{src_path.name}"
            dst_path = best_shots_dir / dst_name
            shutil.copy2(src_path, dst_path)
            copied.append(scene)
            desc = scene.get("description", "N/A")[:30]
            print(f"  {i}. Scene {scene.get('scene_number', 0):03d} | {scene.get('weighted_score', 0):.2f} | {desc}...")

    # 生成 README
    _generate_readme(best_shots_dir, copied, data.get("video_id", "unknown"))

    print(f"\n✅ 已复制 {len(copied)} 个精选镜头到: {best_shots_dir}")
    return copied


def _generate_readme(best_shots_dir: Path, best_shots: List[Dict], video_id: str):
    content = f"""# ⭐ 精选镜头 (Best Shots)

**视频 ID**: {video_id}
**入选数量**: {len(best_shots)} 个
**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## 当前规则

- 所有 `MUST KEEP` 镜头直接入选
- `USABLE` 镜头只有加权总分 >= 8.0 才进入候选
- 精选总量上限 = 总场景数的 15%
- 精选数量最少 6 个，最多 20 个

## 精选列表

| 排名 | 场景 | 加权分 | 类型 | 描述 |
|------|------|--------|------|------|
"""
    for i, s in enumerate(best_shots, 1):
        content += f"| {i} | Scene {s.get('scene_number', 0):03d} | {s.get('weighted_score', 0):.2f} | {s.get('type_classification', 'N/A')} | {s.get('description', '')[:40]} |\n"

    content += f"\n---\n*由 Video Expert Analyzer v2.0 筛选*\n"

    (best_shots_dir / "README.md").write_text(content, encoding="utf-8")


# ============================================================
# 分析报告生成
# ============================================================
def generate_complete_report(scores_path: Path) -> Path:
    with open(scores_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    data = recompute_scene_scores(data)
    save_scores_data(data, scores_path)

    video_id = data.get("video_id", "unknown")
    url = data.get("url", "")
    scenes = data.get("scenes", [])
    total = len(scenes)

    if total == 0:
        print("⚠️ 没有场景数据")
        return scores_path

    # 统计
    scored_scenes = [s for s in scenes if isinstance(s.get("weighted_score"), (int, float)) and s.get("weighted_score", 0) > 0]
    if not scored_scenes:
        print("⚠️ 没有已评分的场景")
        return scores_path

    must_keep = sum(1 for s in scored_scenes if "MUST KEEP" in s.get("selection", ""))
    usable = sum(1 for s in scored_scenes if "USABLE" in s.get("selection", ""))
    discard = sum(1 for s in scored_scenes if "DISCARD" in s.get("selection", ""))
    avg = sum(s["weighted_score"] for s in scored_scenes) / len(scored_scenes)

    # 各维度平均
    dims = ["aesthetic_beauty", "credibility", "impact", "memorability", "fun_interest"]
    dim_avgs = {}
    for d in dims:
        vals = [s.get("scores", {}).get(d, 0) for s in scored_scenes if s.get("scores", {}).get(d)]
        dim_avgs[d] = sum(vals) / len(vals) if vals else 0

    report_path = scores_path.parent / f"{video_id}_complete_analysis.md"

    sorted_scenes = sorted(scored_scenes, key=lambda x: x.get("weighted_score", 0), reverse=True)

    # 构建报告
    report = f"""# 🎬 视频专家分析报告 (Video Expert Analysis Report)

## 📋 基本信息

| 项目 | 内容 |
|------|------|
| **视频 ID** | {video_id} |
| **来源 URL** | {url} |
| **分析时间** | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} |
| **总场景数** | {total} |
| **已评分** | {len(scored_scenes)} |
| **平均加权得分** | {avg:.2f} |

### 筛选统计

| 等级 | 数量 | 占比 |
|------|------|------|
| 🌟 MUST KEEP | {must_keep} | {must_keep/len(scored_scenes)*100:.1f}% |
| 📁 USABLE | {usable} | {usable/len(scored_scenes)*100:.1f}% |
| 🗑️ DISCARD | {discard} | {discard/len(scored_scenes)*100:.1f}% |

### 各维度平均分

| 维度 | 平均分 |
|------|--------|
"""
    for d in dims:
        icon = "🟢" if dim_avgs[d] >= 7 else "🟡" if dim_avgs[d] >= 5 else "🔴"
        report += f"| {get_term_chinese(d)} | {dim_avgs[d]:.2f} {icon} |\n"

    report += f"""
---

## 🎞 场景排名

| 排名 | 场景 | 加权分 | 类型 | 等级 | 描述 |
|------|------|--------|------|------|------|
"""
    for i, s in enumerate(sorted_scenes, 1):
        desc = s.get("description", "N/A")[:30]
        report += f"| {i} | Scene {s.get('scene_number', 0):03d} | **{s.get('weighted_score', 0):.2f}** | {s.get('type_classification', 'N/A')} | {s.get('selection', '')} | {desc} |\n"

    report += f"""
---

## 📊 整体评价

### 综合评分: {avg:.2f} / 10

"""
    if avg >= 8:
        report += "🌟 **优秀** - 高质量素材，强烈推荐保留\n"
    elif avg >= 6.5:
        report += "📁 **良好** - 有可用价值，需要适当剪辑\n"
    else:
        report += "🗑️ **一般** - 整体质量较低\n"

    report += f"""
---
*本报告由 Video Expert Analyzer v2.0 自动生成*
*分析时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*
"""

    report_path.write_text(report, encoding="utf-8")
    print(f"✅ 完整分析报告已生成: {report_path}")
    return report_path


def mark_blocked_state(
    state_path: Path,
    scores_path: Path,
    video_dir: Path,
    data: Dict,
    requested_formats: Sequence[str],
    problems: Sequence[str],
    *,
    stage: str,
) -> Dict:
    state = mark_stage(
        state_path,
        stage=stage,
        status="blocked",
        completed=False,
        next_batch=None if stage == "finalize" else load_run_state(state_path).get("next_batch"),
        total_scenes=len(data.get("scenes", [])),
        completed_scenes=len(data.get("scenes", [])) - len(collect_incomplete_scenes(data)),
        coverage_ratio=load_run_state(state_path).get("coverage_ratio", 0.0),
        can_finalize=False,
        scores_path=str(scores_path),
        video_dir=str(video_dir),
        last_error="; ".join(problems),
        verification=build_verification_payload(
            video_dir,
            data,
            requested_formats,
            include_output_checks=(stage == "finalize"),
        ),
    )
    write_delivery_report(video_dir, data, requested_formats)
    return state


def mark_completed_state(
    state_path: Path,
    scores_path: Path,
    video_dir: Path,
    data: Dict,
    requested_formats: Sequence[str],
) -> Dict:
    state = mark_stage(
        state_path,
        stage="completed",
        status="completed",
        completed=True,
        next_batch=None,
        total_scenes=len(data.get("scenes", [])),
        completed_scenes=len(data.get("scenes", [])),
        coverage_ratio=1.0,
        can_finalize=True,
        scores_path=str(scores_path),
        video_dir=str(video_dir),
        last_error="",
        verification=build_verification_payload(
            video_dir,
            data,
            requested_formats,
            include_output_checks=True,
        ),
    )
    write_delivery_report(video_dir, data, requested_formats)
    return state


# ============================================================
# CLI 入口
# ============================================================
def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Staged scene analyzer with resumable orchestration",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
阶段模式:
  --mode score_batches   自动并行评分并刷新批次状态（默认）
  --mode merge_validate  只合并批次结果并校验是否可正式收尾
  --mode finalize        生成正式输出
  --mode auto            按 run_state.json 自动选择下一阶段
  --mode host            score_batches 的兼容别名
  --mode agent           score_batches 的兼容别名
  --mode api             已弃用，仅保留兼容提示
""",
    )
    parser.add_argument("scene_scores", help="scene_scores.json 路径")
    parser.add_argument(
        "--mode",
        choices=["score_batches", "merge_validate", "finalize", "auto", "host", "agent", "api"],
        default="score_batches",
        help="评分模式（默认: score_batches）",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=0,
        help="每批场景数（0 = 自动，OpenClaw 默认更保守）",
    )
    parser.add_argument(
        "--payload-style",
        choices=["compact", "full"],
        default="compact",
        help="批次输入格式（默认: compact）",
    )
    parser.add_argument(
        "--openclaw-mode",
        action="store_true",
        default=False,
        help="使用更保守的长任务批次策略（仅 OpenClaw 接力场景需要，默认关闭）",
    )
    parser.add_argument(
        "--no-openclaw-mode",
        action="store_false",
        dest="openclaw_mode",
        help="关闭保守批次策略",
    )
    parser.add_argument(
        "--storyboard-formats",
        default="md,pdf",
        help="分镜表输出格式，逗号分隔（默认: md,pdf）",
    )
    parser.add_argument(
        "--best-threshold",
        type=float,
        default=7.0,
        help="精选镜头阈值（默认: 7.0）",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    try:
        return _main_impl(argv)
    except (KeyboardInterrupt, SystemExit):
        raise
    except AudiovisualHandoffPending:
        raise
    except Exception as exc:
        message = f"意外异常：{type(exc).__name__}: {exc}"
        print(f"\n❌ {message}")
        try:
            argv_list = list(argv) if argv is not None else sys.argv[1:]
            scores_arg = next((item for item in argv_list if not item.startswith("-")), None)
            if scores_arg:
                scores_path_local = Path(scores_arg)
                state_path_local = run_state_path_for(scores_path_local)
                mark_stage(
                    state_path_local,
                    stage="score_batches",
                    status="blocked",
                    scores_path=str(scores_path_local),
                    video_dir=str(scores_path_local.parent),
                    last_error=message,
                )
        except Exception as save_exc:
            print(f"⚠️ 写回 run_state 失败：{save_exc}")
        return 2


def _main_impl(argv: Optional[List[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    scores_path = Path(args.scene_scores)
    video_dir = scores_path.parent
    storyboard_formats = parse_storyboard_formats(args.storyboard_formats)
    mode = resolve_stage(args.mode, scores_path)
    state_path = run_state_path_for(scores_path)

    print("=" * 60)
    print(f"🤖 AI Scene Analyzer v2.2.1 ({mode.upper()} 模式)")
    print("=" * 60)

    if mode == "api":
        print("\n⚠️ API 模式已弃用。请改用自动评分链路：")
        print(f"   python3 ai_analyzer.py {scores_path.name} --mode score_batches")
        return 2

    if mode == "completed":
        data = refresh_analysis_data(scores_path, video_dir, force_text_refresh=False)
        write_delivery_report(video_dir, data, storyboard_formats)
        print("\n✅ 当前任务已完成，无需重复 finalize")
        print(f"📦 交付报告: {delivery_report_path_for(video_dir)}")
        return 0

    data = auto_score_scenes(
        scores_path,
        video_dir,
        mode=mode,
        batch_size=args.batch_size,
        payload_style=args.payload_style,
        openclaw_mode=args.openclaw_mode,
        requested_formats=storyboard_formats,
    )

    if mode in {"score_batches", "merge_validate"}:
        state = load_run_state(state_path)
        write_delivery_report(video_dir, data, storyboard_formats)

        print("\n⚡ 自动并行评分：score_batches 会直接读配置、并行看图并写回批次结果")

        if state.get("status") == "blocked":
            print("\n" + "=" * 60)
            print("❌ 当前阶段已阻断")
            print("=" * 60)
            if state.get("last_error"):
                for item in str(state.get("last_error", "")).split("; "):
                    if item:
                        print(f"  - {item}")
            if is_missing_auto_scoring_config_error(state.get("last_error")):
                for hint in auto_scoring_setup_hints():
                    print(f"  - {hint}")
            print(f"📦 交付报告: {delivery_report_path_for(video_dir)}")
            return 2

        if state.get("can_finalize") or state.get("status") == "ready_to_finalize":
            if args.openclaw_mode:
                print("\n" + "=" * 60)
                print("✅ 所有批次已完成，可以 finalize")
                print("=" * 60)
                print(f"📦 交付报告: {delivery_report_path_for(video_dir)}")
                return 0

            print("\n" + "=" * 60)
            print("✅ 所有批次已完成，默认模式将立即进入 finalize")
            print("=" * 60)
            return main(
                [
                    str(scores_path),
                    "--mode",
                    "finalize",
                    "--storyboard-formats",
                    ",".join(storyboard_formats),
                    "--best-threshold",
                    str(args.best_threshold),
                    "--no-openclaw-mode",
                ]
            )

        print("\n" + "=" * 60)
        print("⚙️ 本轮自动评分已结束")
        print("=" * 60)
        if state.get("next_batch"):
            print("仍有未完成批次，重新运行 score_batches 会继续自动补齐。")
        else:
            print("当前没有待人工填写的批次文件，后续会继续自动推进。")
        print(f"📦 交付报告: {delivery_report_path_for(video_dir)}")
        return 0

    readiness_problems = validate_finalize_readiness(video_dir, data)
    if readiness_problems:
        print("\n❌ 收尾前检查未通过，已停止正式收尾")
        for problem in readiness_problems:
            print(f"   - {problem}")
        mark_blocked_state(
            state_path,
            scores_path,
            video_dir,
            data,
            storyboard_formats,
            readiness_problems,
            stage="finalize",
        )
        print(f"📦 交付报告: {delivery_report_path_for(video_dir)}")
        return 2

    print("\n" + "=" * 60)
    print("🧱 生成逐镜头分析文档")
    print("=" * 60)
    detailed_outputs = generate_detailed_analysis_outputs(data, video_dir, strict=True)
    detailed_report_path = detailed_outputs["detailed_report_path"]

    print("\n" + "=" * 60)
    print("⭐ 选择并复制精选镜头")
    print("=" * 60)
    select_and_copy_best_shots(scores_path, threshold=args.best_threshold)

    print("\n" + "=" * 60)
    print("📄 生成完整分析报告")
    print("=" * 60)
    report_path = generate_complete_report(scores_path)

    print("\n" + "=" * 60)
    print("🧾 生成分镜表")
    print("=" * 60)

    storyboard_paths: Dict[str, Path] = {}
    if "md" in storyboard_formats:
        try:
            md_paths = generate_storyboard_outputs(data, video_dir, formats=("md",), skip_enrich=True)
        except Exception as exc:
            problems = [f"分镜表(MD)生成失败：{exc}"]
            print(f"❌ {problems[0]}")
            mark_blocked_state(state_path, scores_path, video_dir, data, storyboard_formats, problems, stage="finalize")
            print(f"📦 交付报告: {delivery_report_path_for(video_dir)}")
            return 2
        storyboard_paths.update(md_paths)

    if "pdf" in storyboard_formats:
        try:
            pdf_paths = generate_storyboard_outputs(data, video_dir, formats=("pdf",), skip_enrich=True)
        except Exception as exc:
            problems = [f"分镜表(PDF)生成失败：{exc}"]
            print(f"❌ {problems[0]}")
            mark_blocked_state(state_path, scores_path, video_dir, data, storyboard_formats, problems, stage="finalize")
            print(f"📦 交付报告: {delivery_report_path_for(video_dir)}")
            return 2
        storyboard_paths.update(pdf_paths)

    print("\n" + "=" * 60)
    print("🧭 生成分类摘要")
    print("=" * 60)
    try:
        classification_summary_paths = write_classification_summary_outputs(data, video_dir)
    except Exception as exc:
        problems = [f"分类摘要生成失败：{exc}"]
        print(f"❌ {problems[0]}")
        mark_blocked_state(state_path, scores_path, video_dir, data, storyboard_formats, problems, stage="finalize")
        print(f"📦 交付报告: {delivery_report_path_for(video_dir)}")
        return 2

    print("\n" + "=" * 60)
    print("🧭 执行正式路由")
    print("=" * 60)
    try:
        routing_config = resolve_auto_scoring_config()
        classification_result = generate_classification_result(data, video_dir, routing_config)
        data["classification_result"] = classification_result
    except Exception as exc:
        problems = [f"正式路由生成失败：{exc}"]
        print(f"❌ {problems[0]}")
        mark_blocked_state(state_path, scores_path, video_dir, data, storyboard_formats, problems, stage="finalize")
        print(f"📦 交付报告: {delivery_report_path_for(video_dir)}")
        return 2

    print("\n" + "=" * 60)
    print("🎧 生成视听剖析报告")
    print("=" * 60)
    audiovisual_formats = tuple(fmt for fmt in ("md", "pdf") if fmt in storyboard_formats)
    try:
        audiovisual_outputs = generate_audiovisual_report_outputs(
            data,
            video_dir,
            formats=audiovisual_formats,
            runtime_config=routing_config,
        )
    except AudiovisualHandoffPending as pending:
        target = pending.task_path or pending.handoff_dir
        try:
            target_display = Path(target).relative_to(video_dir)
        except (TypeError, ValueError):
            target_display = target
        video_tag = f"[{pending.video_id}] " if pending.video_id else ""
        problems = [
            f"{video_tag}视听剖析子任务 `{pending.pending_task}` 待 agent 处理；请读取并完成 `{target_display}` 后重新运行 finalize。",
        ]
        print(f"⏸️ {problems[0]}")
        mark_blocked_state(
            state_path,
            scores_path,
            video_dir,
            data,
            storyboard_formats,
            problems,
            stage="finalize",
        )
        print(f"📦 交付报告: {delivery_report_path_for(video_dir)}")
        return 2
    except Exception as exc:
        problems = [f"视听剖析生成失败：{exc}"]
        print(f"❌ {problems[0]}")
        mark_blocked_state(state_path, scores_path, video_dir, data, storyboard_formats, problems, stage="finalize")
        print(f"📦 交付报告: {delivery_report_path_for(video_dir)}")
        return 2
    data = audiovisual_outputs["data"]
    print(f"🧾 报告链路: {audiovisual_outputs.get('report_mode', 'unknown')}")
    print(f"🗂️ 分类结果复用: {audiovisual_outputs.get('classification_result_cache_status', 'unknown')}")

    verification = build_verification_payload(
        video_dir,
        data,
        storyboard_formats,
        include_output_checks=True,
    )
    if not verification["passed"]:
        problems: List[str] = []
        if verification["missing_outputs"]:
            problems.append(f"必需结果缺失：{', '.join(verification['missing_outputs'])}")
        if verification["missing_screenshot_scenes"]:
            preview = ",".join(f"Scene {int(num):03d}" for num in verification["missing_screenshot_scenes"][:5])
            suffix = "..." if len(verification["missing_screenshot_scenes"]) > 5 else ""
            problems.append(f"镜头截图缺失：{preview}{suffix}")
        if verification["missing_sample_scenes"]:
            preview_items = verification["missing_sample_scenes"][:5]
            preview = ",".join(
                f"Scene {int(item['scene_number']):03d}({','.join(item['missing'])})"
                for item in preview_items
            )
            suffix = "..." if len(verification["missing_sample_scenes"]) > 5 else ""
            problems.append(f"镜头样本缺失：{preview}{suffix}")
        if not problems:
            problems.append("最终核对未通过")
        print("\n❌ 最终核对未通过，已停止交付")
        for problem in problems:
            print(f"   - {problem}")
        mark_blocked_state(state_path, scores_path, video_dir, data, storyboard_formats, problems, stage="finalize")
        print(f"📦 交付报告: {delivery_report_path_for(video_dir)}")
        return 2

    print("\n" + "=" * 60)
    print("✅ AI 分析完成!")
    print("=" * 60)
    print(f"\n📊 评分文件: {scores_path}")
    print(f"🧱 逐镜头汇总: {detailed_report_path}")
    print(f"⭐ 精选镜头: {video_dir}/scenes/best_shots/")
    print(f"📄 完整报告: {report_path}")
    if "md" in audiovisual_outputs:
        print(f"🎧 视听剖析(MD): {audiovisual_outputs['md']}")
    if "pdf" in audiovisual_outputs:
        print(f"📕 视听剖析(PDF): {audiovisual_outputs['pdf']}")
    if "md" in storyboard_paths:
        print(f"📝 分镜表(MD): {storyboard_paths['md']}")
    if "pdf" in storyboard_paths:
        print(f"📕 分镜表(PDF): {storyboard_paths['pdf']}")
    if "context_md" in storyboard_paths:
        print(f"🧠 分镜上下文(MD): {storyboard_paths['context_md']}")
    if "context_json" in storyboard_paths:
        print(f"🧠 分镜上下文(JSON): {storyboard_paths['context_json']}")
    print(f"🧭 分类摘要(MD): {classification_summary_paths['md']}")
    print(f"🧭 分类摘要(JSON): {classification_summary_paths['json']}")
    print(f"🧭 正式路由(JSON): {video_dir / 'classification_result.json'}")
    mark_completed_state(state_path, scores_path, video_dir, data, storyboard_formats)
    print(f"📦 交付报告: {delivery_report_path_for(video_dir)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
