#!/usr/bin/env python3
"""Probe OpenClaw-backed multimodal scoring against host_batches packets."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import mimetypes
import os
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Tuple

try:
    from anthropic import Anthropic
except ImportError:  # pragma: no cover - dependency is available in the app runtime
    Anthropic = None

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover - dependency is available in the app runtime
    OpenAI = None

from ai_analyzer import (
    SCORING_SYSTEM_PROMPT,
    SCORING_USER_PROMPT_TEMPLATE,
    _parse_scene_response,
    SCENE_REQUIRED_SCORE_FIELDS,
)


def _default_openclaw_root() -> Path:
    override = os.environ.get("OPENCLAW_ROOT")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".openclaw"


def _default_models_json() -> Path:
    override = os.environ.get("OPENCLAW_MODELS_JSON")
    if override:
        return Path(override).expanduser()
    return _default_openclaw_root() / "agents" / "main" / "agent" / "models.json"


DEFAULT_MODELS_JSON = _default_models_json()
DEFAULT_OPENCLAW_ROOT = _default_openclaw_root()
DEFAULT_PREFERRED_MODEL = "kcode/K2.6-code-preview"
DEFAULT_FALLBACK_MODELS = (
    "zai/GLM-5V-Turbo",
    "novacode-openai/gpt-5.4",
)
DEFAULT_COUNTS = (1, 5, 10)
DEFAULT_MAX_OUTPUT_TOKENS = 1200
DEFAULT_REQUEST_TIMEOUT_SECONDS = 90.0
VALIDATION_COMPATIBLE_TYPE_GROUPS = (
    frozenset({"TYPE-A Hook", "TYPE-B Narrative"}),
)


class ProbeFailure(RuntimeError):
    """Wrap failed model attempts so callers can persist the diagnostics."""

    def __init__(self, message: str, attempts: Sequence[Dict[str, Any]]) -> None:
        super().__init__(message)
        self.attempts = list(attempts)


def find_models_json_candidates(openclaw_root: Path | None = None) -> List[Path]:
    root = Path(openclaw_root or DEFAULT_OPENCLAW_ROOT).expanduser()
    agents_dir = root / "agents"
    candidates = [path for path in agents_dir.glob("*/agent/models.json") if path.exists()]
    return sorted(
        candidates,
        key=lambda path: (
            0 if path.parent.parent.name == "main" else 1,
            path.parent.parent.name,
        ),
    )


def _validate_provider_catalog(providers: Dict[str, Dict[str, Any]], source: Path) -> None:
    errors: List[str] = []
    for provider_name, config in providers.items():
        if not isinstance(config, dict):
            errors.append(f"{provider_name}: provider 配置必须是对象")
            continue
        if not str(config.get("baseUrl", "")).strip():
            errors.append(f"{provider_name}: 缺少 baseUrl")
        models = config.get("models")
        if not isinstance(models, list) or not models:
            errors.append(f"{provider_name}: models 必须是非空数组")
            continue
        for idx, model in enumerate(models):
            if not isinstance(model, dict) or not str(model.get("id", "")).strip():
                errors.append(f"{provider_name}.models[{idx}]: 缺少 id")
    if errors:
        raise ValueError(f"models.json schema 校验失败 ({source}): " + "；".join(errors))


def load_provider_catalog(models_json_path: Path) -> Dict[str, Dict[str, Any]]:
    payload = json.loads(models_json_path.read_text(encoding="utf-8"))
    providers = payload.get("providers")
    if not isinstance(providers, dict):
        raise ValueError(f"models.json 缺少 providers: {models_json_path}")
    _validate_provider_catalog(providers, models_json_path)
    return providers


def resolve_model_entry(
    providers: Dict[str, Dict[str, Any]],
    model_ref: str,
) -> Tuple[str, Dict[str, Any], Dict[str, Any]]:
    if "/" not in model_ref:
        raise ValueError(f"模型引用必须是 provider/model 形式: {model_ref}")
    provider_name, model_id = model_ref.split("/", 1)
    provider_config = providers.get(provider_name)
    if not isinstance(provider_config, dict):
        raise ValueError(f"未找到 provider: {provider_name}")

    for model_config in provider_config.get("models", []):
        if str(model_config.get("id", "")) == model_id:
            return provider_name, provider_config, model_config

    raise ValueError(f"provider {provider_name} 未配置模型 {model_id}")


def build_attempt_order(
    providers: Dict[str, Dict[str, Any]],
    preferred_model: str,
    fallback_models: Sequence[str],
) -> List[Dict[str, Any]]:
    attempts: List[Dict[str, Any]] = []
    seen: set[str] = set()

    for model_ref in (preferred_model, *fallback_models):
        if not model_ref or model_ref in seen:
            continue
        provider_name, provider_config, model_config = resolve_model_entry(providers, model_ref)
        attempts.append(
            {
                "model_ref": model_ref,
                "provider_name": provider_name,
                "provider_config": provider_config,
                "model_config": model_config,
                "declared_image_support": "image" in model_config.get("input", []),
                "api_style": str(model_config.get("api") or provider_config.get("api") or ""),
            }
        )
        seen.add(model_ref)

    if not attempts:
        raise ValueError("没有可用模型可供探针尝试")
    return attempts


def collect_probe_scenes(host_batches_dir: Path, target_count: int) -> List[Dict[str, Any]]:
    index_path = host_batches_dir / "index.json"
    index_payload = json.loads(index_path.read_text(encoding="utf-8"))
    video_dir = host_batches_dir.parent
    scenes: List[Dict[str, Any]] = []

    for batch in index_payload.get("batches", []):
        input_name = str(batch.get("input", "")).strip()
        if not input_name:
            continue
        input_path = host_batches_dir / input_name
        if not input_path.exists():
            continue
        input_payload = json.loads(input_path.read_text(encoding="utf-8"))
        batch_id = str(input_payload.get("batch_id") or batch.get("batch_id") or input_path.stem)
        for scene in input_payload.get("scenes", []):
            normalized = dict(scene)
            normalized["batch_id"] = batch_id
            normalized["frames"] = {
                key: str((video_dir / str(value)).resolve()) if value else ""
                for key, value in (scene.get("frames") or {}).items()
            }
            scenes.append(normalized)
            if len(scenes) >= target_count:
                return scenes
    return scenes


def build_batch_like_output(
    batch_id: str,
    scene_results: Sequence[Dict[str, Any]],
    model_ref: str,
    failed_scenes: Sequence[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    failed_scenes = list(failed_scenes or [])
    status = "blocked" if failed_scenes else "completed"
    now = datetime.now().isoformat()
    return {
        "batch_id": batch_id,
        "scenes": list(scene_results),
        "receipt": {
            "batch_id": batch_id,
            "scene_numbers": [int(scene.get("scene_number", 0) or 0) for scene in scene_results] + [int(scene.get("scene_number", 0) or 0) for scene in failed_scenes],
            "output_path": f"{batch_id}-output.json",
            "status": status,
            "has_todo": bool(failed_scenes),
            "needs_review": [
                {
                    "scene_number": int(scene.get("scene_number", 0) or 0),
                    "error": str(scene.get("error", "")),
                }
                for scene in failed_scenes
            ],
            "worker_summary": (
                f"probe completed with {model_ref}; "
                f"success={len(scene_results)} failed={len(failed_scenes)}"
            ),
            "started_at": now,
            "updated_at": now,
            "completed_at": now if not failed_scenes else "",
        },
    }


def _guess_media_type(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(str(path))
    return guessed or "image/jpeg"


def _load_data_url(path: Path) -> str:
    import base64

    raw = path.read_bytes()
    encoded = base64.b64encode(raw).decode("utf-8")
    return f"data:{_guess_media_type(path)};base64,{encoded}"


def _load_base64_image(path: Path) -> Tuple[str, str]:
    import base64

    return _guess_media_type(path), base64.b64encode(path.read_bytes()).decode("utf-8")


def _normalize_base_url(api_style: str, raw_url: str) -> str:
    base_url = str(raw_url or "").rstrip("/")
    if api_style == "anthropic-messages" and base_url.endswith("/v1"):
        return base_url[:-3]
    return base_url


def _scene_prompt(scene: Dict[str, Any], total_scenes: int) -> str:
    hints = scene.get("hints") or {}
    return SCORING_USER_PROMPT_TEMPLATE.format(
        scene_num=int(scene.get("scene_number", 0) or 0),
        video_title=f"Probe from {scene.get('batch_id', '')}",
        total_scenes=total_scenes,
        transcript_info="（probe 未提供额外整片转录）",
        scene_timestamp=scene.get("time_range", "") or "未知",
        scene_voiceover=hints.get("voiceover") or "（该场景暂无可对齐字幕）",
        camera_motion_hint=hints.get("camera_movement_hint") or "暂无自动提示",
        camera_motion_rationale="probe 未提供自动依据",
    )


def _scene_image_paths(scene: Dict[str, Any]) -> List[Tuple[str, Path]]:
    frames = scene.get("frames") or {}
    ordered = [("primary", frames.get("primary", "")), ("start", frames.get("start", "")), ("mid", frames.get("mid", "")), ("end", frames.get("end", ""))]
    paths: List[Tuple[str, Path]] = []
    for label, raw_path in ordered:
        if not raw_path:
            continue
        path = Path(str(raw_path))
        if path.exists():
            paths.append((label, path))
    if not paths:
        raise FileNotFoundError(f"Scene {scene.get('scene_number', 0)} 缺少可读图片")
    return paths


def _extract_text_from_response(response: Any) -> str:
    output_text = getattr(response, "output_text", "")
    if output_text:
        return str(output_text)

    choices = getattr(response, "choices", None)
    if choices:
        message = getattr(choices[0], "message", None)
        content = getattr(message, "content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            texts = []
            for item in content:
                text = getattr(item, "text", None)
                if text:
                    texts.append(text)
                elif isinstance(item, dict) and item.get("type") == "text":
                    texts.append(str(item.get("text", "")))
            return "\n".join(texts).strip()

    content = getattr(response, "content", None)
    if isinstance(content, list):
        texts = [getattr(block, "text", "") for block in content if getattr(block, "type", "") == "text"]
        return "\n".join(text for text in texts if text).strip()

    raise ValueError("响应中未找到可解析文本")


def _call_openai_completions(
    provider_config: Dict[str, Any],
    model_config: Dict[str, Any],
    prompt: str,
    image_paths: Sequence[Tuple[str, Path]],
) -> str:
    if OpenAI is None:  # pragma: no cover - runtime dependency exists in app
        raise RuntimeError("当前环境未安装 openai 库")
    client = OpenAI(
        api_key=provider_config.get("apiKey", ""),
        base_url=_normalize_base_url("openai-completions", provider_config.get("baseUrl", "")),
        default_headers=provider_config.get("headers") or None,
        max_retries=0,
        timeout=DEFAULT_REQUEST_TIMEOUT_SECONDS,
    )
    content: List[Dict[str, Any]] = [{"type": "text", "text": prompt}]
    for label, path in image_paths:
        content.append({"type": "text", "text": label})
        content.append({"type": "image_url", "image_url": {"url": _load_data_url(path)}})
    response = client.chat.completions.create(
        model=str(model_config.get("id", "")),
        messages=[
            {"role": "system", "content": SCORING_SYSTEM_PROMPT},
            {"role": "user", "content": content},
        ],
        max_tokens=DEFAULT_MAX_OUTPUT_TOKENS,
    )
    return _extract_text_from_response(response)


def _call_openai_responses(
    provider_config: Dict[str, Any],
    model_config: Dict[str, Any],
    prompt: str,
    image_paths: Sequence[Tuple[str, Path]],
) -> str:
    if OpenAI is None:  # pragma: no cover - runtime dependency exists in app
        raise RuntimeError("当前环境未安装 openai 库")
    client = OpenAI(
        api_key=provider_config.get("apiKey", ""),
        base_url=_normalize_base_url("openai-responses", provider_config.get("baseUrl", "")),
        default_headers=provider_config.get("headers") or None,
        max_retries=0,
        timeout=DEFAULT_REQUEST_TIMEOUT_SECONDS,
    )
    user_content: List[Dict[str, Any]] = [{"type": "input_text", "text": prompt}]
    for label, path in image_paths:
        user_content.append({"type": "input_text", "text": label})
        user_content.append({"type": "input_image", "image_url": _load_data_url(path)})
    response = client.responses.create(
        model=str(model_config.get("id", "")),
        input=[
            {"role": "system", "content": [{"type": "input_text", "text": SCORING_SYSTEM_PROMPT}]},
            {"role": "user", "content": user_content},
        ],
        max_output_tokens=DEFAULT_MAX_OUTPUT_TOKENS,
    )
    return _extract_text_from_response(response)


def _call_anthropic_messages(
    provider_config: Dict[str, Any],
    model_config: Dict[str, Any],
    prompt: str,
    image_paths: Sequence[Tuple[str, Path]],
) -> str:
    if Anthropic is None:  # pragma: no cover - runtime dependency exists in app
        raise RuntimeError("当前环境未安装 anthropic 库")
    client = Anthropic(
        api_key=provider_config.get("apiKey", ""),
        base_url=_normalize_base_url("anthropic-messages", provider_config.get("baseUrl", "")),
        default_headers=provider_config.get("headers") or None,
        timeout=DEFAULT_REQUEST_TIMEOUT_SECONDS,
    )
    content: List[Dict[str, Any]] = [{"type": "text", "text": prompt}]
    for label, path in image_paths:
        mime_type, data = _load_base64_image(path)
        content.append({"type": "text", "text": label})
        content.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": mime_type,
                    "data": data,
                },
            }
        )
    response = client.messages.create(
        model=str(model_config.get("id", "")),
        system=SCORING_SYSTEM_PROMPT,
        max_tokens=int(model_config.get("maxTokens", DEFAULT_MAX_OUTPUT_TOKENS) or DEFAULT_MAX_OUTPUT_TOKENS),
        messages=[{"role": "user", "content": content}],
    )
    return _extract_text_from_response(response)


def analyze_scene_with_attempts(
    scene: Dict[str, Any],
    attempts: Sequence[Dict[str, Any]],
    total_scenes: int,
) -> Dict[str, Any]:
    image_paths = _scene_image_paths(scene)
    prompt = _scene_prompt(scene, total_scenes=total_scenes)
    attempt_records: List[Dict[str, Any]] = []
    last_error = ""

    for attempt in attempts:
        started = time.perf_counter()
        error = ""
        raw_response = ""
        parsed = None
        try:
            api_style = attempt["api_style"]
            provider_config = attempt["provider_config"]
            model_config = attempt["model_config"]
            if api_style == "anthropic-messages":
                raw_response = _call_anthropic_messages(provider_config, model_config, prompt, image_paths)
            elif api_style == "openai-responses":
                raw_response = _call_openai_responses(provider_config, model_config, prompt, image_paths)
            elif api_style == "openai-completions":
                raw_response = _call_openai_completions(provider_config, model_config, prompt, image_paths)
            else:
                raise ValueError(f"暂不支持的 API 风格: {api_style}")
            parsed = _parse_scene_response(raw_response, int(scene.get("scene_number", 0) or 0))
            if parsed is None:
                error = "模型响应未通过 JSON 校验"
        except Exception as exc:  # pragma: no cover - exercised in live probe
            error = f"{type(exc).__name__}: {exc}"
        elapsed_s = round(time.perf_counter() - started, 3)
        attempt_records.append(
            {
                "model_ref": attempt["model_ref"],
                "declared_image_support": bool(attempt["declared_image_support"]),
                "elapsed_s": elapsed_s,
                "ok": parsed is not None,
                "error": error,
            }
        )
        if parsed is not None:
            parsed["scene_number"] = int(scene.get("scene_number", 0) or 0)
            return {
                "scene_result": parsed,
                "used_model": attempt["model_ref"],
                "attempts": attempt_records,
                "elapsed_s": round(sum(item["elapsed_s"] for item in attempt_records), 3),
            }
        last_error = error

    raise ProbeFailure(last_error or "所有候选模型都未返回有效结果", attempt_records)


def analyze_scenes(
    scenes: Sequence[Dict[str, Any]],
    attempts: Sequence[Dict[str, Any]],
    max_workers: int = 1,
    analyzer_fn: Any = analyze_scene_with_attempts,
    on_result: Any = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    indexed_results: Dict[int, Dict[str, Any]] = {}
    total_scenes = len(scenes)

    def run_one(index: int, scene: Dict[str, Any]) -> Dict[str, Any]:
        try:
            analysis = analyzer_fn(scene, attempts, total_scenes)
            return {
                "index": index,
                "run_item": {
                    "scene_number": int(scene.get("scene_number", 0) or 0),
                    "batch_id": scene.get("batch_id", ""),
                    "ok": True,
                    "used_model": analysis["used_model"],
                    "elapsed_s": analysis["elapsed_s"],
                    "attempts": analysis["attempts"],
                },
                "scene_result": analysis["scene_result"],
                "failed": None,
            }
        except ProbeFailure as exc:
            failed = {
                "scene_number": int(scene.get("scene_number", 0) or 0),
                "batch_id": scene.get("batch_id", ""),
                "ok": False,
                "used_model": "",
                "elapsed_s": 0.0,
                "attempts": exc.attempts,
                "error": f"{type(exc).__name__}: {exc}",
            }
            return {
                "index": index,
                "run_item": failed,
                "scene_result": None,
                "failed": failed,
            }
        except Exception as exc:  # pragma: no cover - exercised in live probe
            failed = {
                "scene_number": int(scene.get("scene_number", 0) or 0),
                "batch_id": scene.get("batch_id", ""),
                "ok": False,
                "used_model": "",
                "elapsed_s": 0.0,
                "attempts": [],
                "error": f"{type(exc).__name__}: {exc}",
            }
            return {
                "index": index,
                "run_item": failed,
                "scene_result": None,
                "failed": failed,
            }

    if max_workers <= 1:
        for index, scene in enumerate(scenes):
            payload = run_one(index, scene)
            indexed_results[index] = payload
            if on_result is not None:
                on_result(payload)
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_map = {
                executor.submit(run_one, index, scene): index
                for index, scene in enumerate(scenes)
            }
            for future in concurrent.futures.as_completed(future_map):
                payload = future.result()
                indexed_results[payload["index"]] = payload
                if on_result is not None:
                    on_result(payload)

    ordered_payloads = [indexed_results[index] for index in range(len(scenes))]
    run_items = [payload["run_item"] for payload in ordered_payloads]
    successful_results = [payload["scene_result"] for payload in ordered_payloads if payload["scene_result"] is not None]
    failed_results = [payload["failed"] for payload in ordered_payloads if payload["failed"] is not None]
    return run_items, successful_results, failed_results


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _parse_counts(raw: str) -> List[int]:
    counts = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        counts.append(int(item))
    return counts or list(DEFAULT_COUNTS)


def _build_summary(run_items: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    model_usage = Counter(item["used_model"] for item in run_items if item.get("used_model"))
    success_count = sum(1 for item in run_items if item.get("ok"))
    return {
        "requested_scenes": len(run_items),
        "successful_scenes": success_count,
        "failed_scenes": len(run_items) - success_count,
        "success_rate": round(success_count / max(len(run_items), 1), 4),
        "model_usage": dict(model_usage),
        "elapsed_s": round(sum(float(item.get("elapsed_s", 0.0) or 0.0) for item in run_items), 3),
    }


def sample_scene_numbers(scene_numbers: Sequence[int], sample_size: int) -> List[int]:
    ordered = list(scene_numbers)
    if not ordered or sample_size <= 0:
        return []
    if sample_size >= len(ordered):
        return ordered
    chosen_indexes: List[int] = []
    for offset in range(sample_size):
        if sample_size == 1:
            index = len(ordered) // 2
        else:
            index = round(offset * (len(ordered) - 1) / (sample_size - 1))
        if index not in chosen_indexes:
            chosen_indexes.append(index)
    return [ordered[index] for index in chosen_indexes]


def _validation_type_matches(generated_type: object, reference_type: object) -> bool:
    generated = str(generated_type or "").strip()
    reference = str(reference_type or "").strip()
    if not generated or not reference:
        return False
    if generated == reference:
        return True
    return frozenset({generated, reference}) in VALIDATION_COMPATIBLE_TYPE_GROUPS


def build_validation_report(
    generated_scenes: Sequence[Dict[str, Any]],
    reference_scenes: Sequence[Dict[str, Any]],
    sample_size: int = 3,
    scene_packets: Sequence[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    generated_order = [int(scene.get("scene_number", 0) or 0) for scene in generated_scenes]
    reference_order = [int(scene.get("scene_number", 0) or 0) for scene in reference_scenes]
    generated_by_number = {int(scene.get("scene_number", 0) or 0): scene for scene in generated_scenes}
    reference_by_number = {int(scene.get("scene_number", 0) or 0): scene for scene in reference_scenes}
    scene_packet_by_number = {
        int(scene.get("scene_number", 0) or 0): scene for scene in (scene_packets or [])
    }

    overlap_numbers = [number for number in generated_order if number in reference_by_number]
    reference_overlap_order = [number for number in reference_order if number in generated_by_number]
    type_match_count = 0
    score_delta_totals: List[float] = []

    for number in overlap_numbers:
        generated = generated_by_number[number]
        reference = reference_by_number[number]
        if _validation_type_matches(
            generated.get("type_classification", ""),
            reference.get("type_classification", ""),
        ):
            type_match_count += 1
        delta_total = 0.0
        for field in SCENE_REQUIRED_SCORE_FIELDS:
            delta_total += abs(float((generated.get("scores") or {}).get(field, 0) or 0) - float((reference.get("scores") or {}).get(field, 0) or 0))
        score_delta_totals.append(round(delta_total, 3))

    sample_numbers = sample_scene_numbers(overlap_numbers, sample_size)
    samples: List[Dict[str, Any]] = []
    for number in sample_numbers:
        generated = generated_by_number[number]
        reference = reference_by_number[number]
        score_deltas = {
            field: abs(float((generated.get("scores") or {}).get(field, 0) or 0) - float((reference.get("scores") or {}).get(field, 0) or 0))
            for field in SCENE_REQUIRED_SCORE_FIELDS
        }
        sample_payload = {
            "scene_number": number,
            "type_matches": _validation_type_matches(
                generated.get("type_classification", ""),
                reference.get("type_classification", ""),
            ),
            "generated_type": generated.get("type_classification", ""),
            "reference_type": reference.get("type_classification", ""),
            "score_deltas": score_deltas,
            "total_score_delta": round(sum(score_deltas.values()), 3),
            "generated_description": generated.get("description", ""),
            "reference_description": reference.get("description", ""),
            "generated_visual_summary": generated.get("visual_summary", ""),
            "reference_visual_summary": reference.get("visual_summary", ""),
        }
        scene_packet = scene_packet_by_number.get(number)
        if scene_packet:
            sample_payload["source"] = {
                "batch_id": scene_packet.get("batch_id", ""),
                "time_range": scene_packet.get("time_range", ""),
                "frames": scene_packet.get("frames", {}),
                "voiceover": (scene_packet.get("hints") or {}).get("voiceover", ""),
                "camera_movement_hint": (scene_packet.get("hints") or {}).get("camera_movement_hint", ""),
            }
        samples.append(sample_payload)

    return {
        "generated_scene_count": len(generated_scenes),
        "reference_scene_count": len(reference_scenes),
        "overlap_scene_count": len(overlap_numbers),
        "missing_in_reference": [number for number in generated_order if number not in reference_by_number],
        "extra_in_reference": [number for number in reference_order if number not in generated_by_number],
        "order_matches_reference": overlap_numbers == reference_overlap_order,
        "type_match_rate": round(type_match_count / max(len(overlap_numbers), 1), 4) if overlap_numbers else 0.0,
        "average_total_score_delta": round(sum(score_delta_totals) / max(len(score_delta_totals), 1), 3) if score_delta_totals else 0.0,
        "max_total_score_delta": round(max(score_delta_totals), 3) if score_delta_totals else 0.0,
        "sample_scene_numbers": sample_numbers,
        "samples": samples,
    }


def load_reference_scenes(reference_output_path: Path) -> List[Dict[str, Any]]:
    payload = json.loads(reference_output_path.read_text(encoding="utf-8"))
    scenes = payload.get("scenes")
    if isinstance(scenes, list):
        return scenes
    raise ValueError(f"参考输出里没有 scenes 列表: {reference_output_path}")


def run_probe(
    host_batches_dir: Path,
    counts: Sequence[int],
    preferred_model: str,
    fallback_models: Sequence[str],
    models_json_path: Path,
    max_workers: int = 1,
    reference_output_path: Path | None = None,
    validation_sample_size: int = 3,
    output_dir: Path | None = None,
) -> Path:
    providers = load_provider_catalog(models_json_path)
    attempts = build_attempt_order(providers, preferred_model=preferred_model, fallback_models=fallback_models)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = output_dir or host_batches_dir.parent / "probe_runs" / timestamp
    _ensure_dir(run_dir)

    summary_payload = {
        "host_batches_dir": str(host_batches_dir.resolve()),
        "models_json_path": str(models_json_path.resolve()),
        "attempt_order": [
            {
                "model_ref": attempt["model_ref"],
                "declared_image_support": bool(attempt["declared_image_support"]),
                "api_style": attempt["api_style"],
            }
            for attempt in attempts
        ],
        "max_workers": max_workers,
        "runs": [],
    }

    for count in counts:
        selected_scenes = collect_probe_scenes(host_batches_dir, target_count=count)
        started = time.perf_counter()
        run_items, successful_results, failed_results = analyze_scenes(
            selected_scenes,
            attempts=attempts,
            max_workers=max_workers,
        )

        run_elapsed = round(time.perf_counter() - started, 3)
        batch_payload = build_batch_like_output(
            batch_id=f"probe-n{count}",
            scene_results=successful_results,
            model_ref=run_items[-1]["used_model"] if run_items else preferred_model,
            failed_scenes=failed_results,
        )
        output_path = run_dir / f"probe-n{count}-output.json"
        output_path.write_text(json.dumps(batch_payload, ensure_ascii=False, indent=2), encoding="utf-8")

        validation_report_path = ""
        if reference_output_path:
            reference_scenes = load_reference_scenes(reference_output_path)
            validation_report = build_validation_report(
                generated_scenes=successful_results,
                reference_scenes=reference_scenes,
                sample_size=validation_sample_size,
                scene_packets=selected_scenes,
            )
            validation_report_path = str((run_dir / f"probe-n{count}-validation.json").resolve())
            Path(validation_report_path).write_text(
                json.dumps(validation_report, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        run_summary = _build_summary(run_items)
        run_summary.update(
            {
                "count": count,
                "actual_scene_count": len(selected_scenes),
                "output_path": str(output_path.resolve()),
                "validation_report_path": validation_report_path,
                "run_elapsed_s": run_elapsed,
                "scenes": run_items,
            }
        )
        summary_payload["runs"].append(run_summary)

    summary_path = run_dir / "probe-summary.json"
    summary_path.write_text(json.dumps(summary_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return run_dir


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Probe OpenClaw-backed scene scoring over host_batches packets")
    parser.add_argument("--host-batches", required=True, help="host_batches 目录路径")
    parser.add_argument("--counts", default="1,5,10", help="要测试的场景数，逗号分隔（默认: 1,5,10）")
    parser.add_argument("--preferred-model", default=DEFAULT_PREFERRED_MODEL, help=f"优先尝试的模型（默认: {DEFAULT_PREFERRED_MODEL}）")
    parser.add_argument("--fallback-model", action="append", default=[], help="回退模型，可重复传入")
    parser.add_argument("--models-json", default=str(DEFAULT_MODELS_JSON), help=f"OpenClaw models.json 路径（默认: {DEFAULT_MODELS_JSON}）")
    parser.add_argument("--max-workers", type=int, default=1, help="并行 worker 数（默认: 1）")
    parser.add_argument("--reference-output", default="", help="可选：参考 probe 输出文件，用于抽样校验")
    parser.add_argument("--validation-sample-size", type=int, default=3, help="抽样校验的 scene 数量（默认: 3）")
    parser.add_argument("--output-dir", default="", help="自定义输出目录")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    host_batches_dir = Path(args.host_batches).expanduser().resolve()
    models_json_path = Path(args.models_json).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve() if args.output_dir else None
    reference_output_path = Path(args.reference_output).expanduser().resolve() if args.reference_output else None
    fallback_models = tuple(args.fallback_model) if args.fallback_model else DEFAULT_FALLBACK_MODELS
    run_dir = run_probe(
        host_batches_dir=host_batches_dir,
        counts=_parse_counts(args.counts),
        preferred_model=args.preferred_model,
        fallback_models=fallback_models,
        models_json_path=models_json_path,
        max_workers=max(1, int(args.max_workers)),
        reference_output_path=reference_output_path,
        validation_sample_size=max(1, int(args.validation_sample_size)),
        output_dir=output_dir,
    )
    print(f"Probe outputs written to: {run_dir}")
    print(f"Summary: {run_dir / 'probe-summary.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
