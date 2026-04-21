#!/usr/bin/env python3
"""Runtime integration for the child video-type router."""

from __future__ import annotations

from datetime import datetime
import json
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from audiovisual.routing.constants import AUDIO_AXIS_LABELS, ROUTE_FRAMEWORKS, VISUAL_AXIS_LABELS
from classification_summary import build_classification_summary_payload, classification_summary_hash
from text_model_runtime import request_text_with_runtime


ROUTER_ROOT = Path(__file__).resolve().parents[1] / "chart" / "video-type-router"
TAXONOMY_PATH = ROUTER_ROOT / "references" / "taxonomy.md"
CLASSIFICATION_RESULT_FILENAME = "classification_result.json"
DEFAULT_MAX_OUTPUT_TOKENS = 1200
_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.IGNORECASE | re.DOTALL)

TYPE_LABELS = {
    "concept_mv": "概念 MV",
    "performance_mv": "表演 MV",
    "live_session": "现场演出",
    "narrative_short": "叙事短片",
    "narrative_trailer": "预告 / 先导片",
    "talking_head": "口播 / 讲述",
    "documentary_essay": "纪实 / 影像论文",
    "commentary_remix": "评论向二创",
    "brand_film": "品牌影片",
    "event_promo": "活动 / 促销广告",
    "explainer": "讲解 / 教学",
    "infographic_motion": "信息动画",
    "rhythm_remix": "节奏混剪",
    "mood_montage": "情绪蒙太奇",
    "cinematic_vlog": "生活影像 / Vlog",
    "reality_record": "现实纪录",
    "meme_viral": "梗 / 病毒内容",
    "motion_graphics": "纯动态图形",
    "experimental": "形式实验",
}

FRAMEWORK_FALLBACKS = {
    "technical_explainer": ("技术讲解 / 原理拆解", "技术讲解 / 原理拆解"),
    "event_brand_ad": ("节庆 / 活动品牌广告", "节庆 / 活动品牌广告"),
    "journey_brand_film": ("旅程型品牌短片", "旅程型品牌短片"),
    "narrative_trailer": ("剧情预告 / 叙事预告", "剧情预告 / 叙事预告"),
    "experimental": ("形式实验型 / 边界模糊型", "形式实验型 / 边界模糊型"),
}

ROUTER_SYSTEM_PROMPT = """你是 video-type-router。你的任务不是泛泛描述视频，而是根据“分类摘要”给出唯一的视频类型路由。

严格要求：
1. 只能从 19 个类型里选 1 个。
2. `visual_source` 只能是 R / P / S / D / H。
3. `audio_dominance` 只能是 L / M / E / LM / N。
4. 输出必须是 JSON，不要附加解释文字。
5. reasoning_summary 必须简洁说明标题、声音和画面三类依据。

输出格式：
{
  "classification": {
    "type": "concept_mv",
    "type_cn": "概念 MV",
    "confidence": "high"
  },
  "facets": {
    "visual_source": "P",
    "audio_dominance": "M"
  },
  "reasoning_summary": "……",
  "evidence": {
    "title_signals": ["……"],
    "audio_signals": ["……"],
    "visual_signals": ["……"]
  }
}
"""


def _safe_text(value: object) -> str:
    text = str(value or "").strip()
    if not text or text.upper().startswith("TODO"):
        return ""
    return text


def _normalize_confidence(value: object) -> str:
    text = _safe_text(value).lower()
    mapping = {
        "high": "high",
        "medium": "medium",
        "med": "medium",
        "mid": "medium",
        "low": "low",
        "高": "high",
        "中": "medium",
        "低": "low",
    }
    return mapping.get(text, "medium")


def _framework_defaults(framework: str) -> Tuple[str, str]:
    for item_framework, route_label, reference in ROUTE_FRAMEWORKS.values():
        if item_framework == framework:
            return route_label, reference
    return FRAMEWORK_FALLBACKS.get(framework, (framework, framework))


def _content_profile_for_type(type_key: str) -> Dict[str, str]:
    if type_key in {"concept_mv", "performance_mv", "live_session", "rhythm_remix"}:
        return {"key": "music_video", "label": "音乐视频", "reason": "主类型明显由音乐表达驱动。"}
    if type_key == "narrative_trailer":
        return {"key": "narrative_trailer", "label": "剧情预告", "reason": "结构和收口都指向预告片。"}
    if type_key == "explainer":
        return {"key": "technical_explainer", "label": "技术讲解", "reason": "主要任务是把信息或原理讲清楚。"}
    if type_key == "commentary_remix":
        return {"key": "commentary_analysis", "label": "评论解析", "reason": "主体是在拿现成素材做评论和判断。"}
    if type_key in {"documentary_essay", "reality_record"}:
        return {"key": "documentary_observation", "label": "纪实观察", "reason": "主体是跟随真实人物或真实现场。"}
    if type_key == "event_promo":
        return {"key": "event_brand_ad", "label": "活动 / 品牌广告", "reason": "明确带有传播和行动导向。"}
    if type_key == "cinematic_vlog":
        return {"key": "travel_short", "label": "旅行 / 生活短片", "reason": "主体是人物视角下的生活或旅程体验。"}
    if type_key == "meme_viral":
        return {"key": "meme_clip", "label": "梗视频", "reason": "主体依赖反差、梗点和即时反应。"}
    return {"key": "generic", "label": "通用视频", "reason": "当前仅确认主类型，不额外扩展画像。"}


def _dual_layer_for_framework(framework: str, reasoning: str) -> Dict[str, object]:
    if framework == "event_brand_ad":
        return {
            "enabled": True,
            "primary": "节庆氛围层",
            "secondary": "品牌记忆层",
            "reason": reasoning,
        }
    if framework == "journey_brand_film":
        return {
            "enabled": True,
            "primary": "旅程体验层",
            "secondary": "品牌气质层",
            "reason": reasoning,
        }
    if framework == "technical_explainer":
        return {
            "enabled": True,
            "primary": "信息解释层",
            "secondary": "观看快感层",
            "reason": reasoning,
        }
    if framework == "narrative_trailer":
        return {
            "enabled": True,
            "primary": "故事前提层",
            "secondary": "发行传播层",
            "reason": reasoning,
        }
    return {"enabled": False, "primary": "", "secondary": "", "reason": ""}


def _framework_for_type(type_key: str, visual_source: str, audio_dominance: str) -> str:
    if type_key == "concept_mv":
        return "concept_mv"
    if type_key in {"performance_mv", "live_session"}:
        return "narrative_performance" if audio_dominance in {"M", "LM", "L"} else "silent_performance"
    if type_key == "narrative_short":
        return "narrative_performance" if visual_source in {"P", "R"} else "narrative_mix"
    if type_key == "narrative_trailer":
        return "narrative_trailer"
    if type_key == "talking_head":
        return "lecture_performance" if visual_source in {"P", "R"} else "documentary_generic"
    if type_key == "documentary_essay":
        return "documentary_generic"
    if type_key == "commentary_remix":
        return "hybrid_commentary" if visual_source == "H" else "commentary_mix"
    if type_key == "brand_film":
        return "journey_brand_film"
    if type_key == "event_promo":
        return "event_brand_ad"
    if type_key == "explainer":
        return "technical_explainer"
    if type_key == "infographic_motion":
        return "infographic_animation"
    if type_key == "rhythm_remix":
        return "hybrid_music" if visual_source == "H" else "mix_music"
    if type_key == "mood_montage":
        if visual_source == "D":
            return "narrative_motion_graphics" if audio_dominance in {"L", "LM"} else "pure_motion_graphics"
        if visual_source == "S":
            return "mix_music" if audio_dominance in {"M", "LM"} else "pure_visual_mix"
        if visual_source == "R":
            return "cinematic_life" if audio_dominance in {"M", "LM", "N"} else "documentary_generic"
        if visual_source == "P":
            return "concept_mv" if audio_dominance in {"M", "LM"} else "silent_performance"
        return "hybrid_ambient"
    if type_key == "cinematic_vlog":
        return "cinematic_life"
    if type_key == "reality_record":
        return "silent_reality" if audio_dominance in {"N", "E"} else "documentary_generic"
    if type_key == "meme_viral":
        if visual_source == "H":
            return "hybrid_meme"
        if visual_source == "R" and audio_dominance == "E":
            return "reality_sfx"
        return "meme"
    if type_key == "motion_graphics":
        if audio_dominance == "L":
            return "infographic_animation"
        if audio_dominance == "LM":
            return "narrative_motion_graphics"
        if audio_dominance == "E":
            return "abstract_sfx"
        return "pure_motion_graphics"
    return "experimental"


def build_classification_result_payload(summary_payload: Dict[str, Any], llm_result: Dict[str, Any]) -> Dict[str, Any]:
    classification = dict(llm_result.get("classification") or {})
    facets = dict(llm_result.get("facets") or {})
    type_key = _safe_text(classification.get("type"))
    if type_key not in TYPE_LABELS:
        raise ValueError(f"不支持的视频类型: {type_key or '空'}")

    visual_source = _safe_text(facets.get("visual_source")).upper()
    audio_dominance = _safe_text(facets.get("audio_dominance")).upper()
    if visual_source not in VISUAL_AXIS_LABELS:
        raise ValueError(f"不支持的视觉来源: {visual_source or '空'}")
    if audio_dominance not in AUDIO_AXIS_LABELS:
        raise ValueError(f"不支持的听觉主导: {audio_dominance or '空'}")

    type_cn = _safe_text(classification.get("type_cn")) or TYPE_LABELS[type_key]
    reasoning = _safe_text(llm_result.get("reasoning_summary")) or "未提供明确理由。"
    framework = _framework_for_type(type_key, visual_source, audio_dominance)
    route_label, reference = _framework_defaults(framework)
    confidence = _normalize_confidence(classification.get("confidence"))
    confidence_score = {"high": 0.95, "medium": 0.75, "low": 0.55}[confidence]
    content_profile = _content_profile_for_type(type_key)

    applied_route = {
        "route_code": f"{visual_source} + {audio_dominance}",
        "framework": framework,
        "route_label": route_label,
        "route_subtype": type_cn,
        "child_type": type_key,
        "child_type_cn": type_cn,
        "reference": reference,
        "visual_axis": visual_source,
        "visual_label": VISUAL_AXIS_LABELS[visual_source],
        "audio_axis": audio_dominance,
        "audio_label": AUDIO_AXIS_LABELS[audio_dominance],
        "visual_rationale": f"子路由将视觉来源判为 {visual_source}（{VISUAL_AXIS_LABELS[visual_source]}）。",
        "visual_confidence": confidence_score,
        "audio_rationale": f"子路由将听觉主导判为 {audio_dominance}（{AUDIO_AXIS_LABELS[audio_dominance]}）。",
        "voiceover_ratio": float((summary_payload.get("narration") or {}).get("coverage_ratio") or 0.0),
        "dual_layer": _dual_layer_for_framework(framework, reasoning),
        "content_profile": content_profile,
        "fallback": framework == "experimental",
    }

    evidence = dict(llm_result.get("evidence") or {})
    return {
        "video_id": _safe_text(summary_payload.get("video_id")) or "unknown",
        "video_title": _safe_text(summary_payload.get("video_title")) or "unknown",
        "classification": {
            "type": type_key,
            "type_cn": type_cn,
            "confidence": confidence,
        },
        "facets": {
            "visual_source": visual_source,
            "audio_dominance": audio_dominance,
        },
        "reasoning_summary": reasoning,
        "evidence": {
            "title_signals": [str(item) for item in evidence.get("title_signals", []) if _safe_text(item)],
            "audio_signals": [str(item) for item in evidence.get("audio_signals", []) if _safe_text(item)],
            "visual_signals": [str(item) for item in evidence.get("visual_signals", []) if _safe_text(item)],
        },
        "summary_source": {
            "source_kind": _safe_text(summary_payload.get("source_kind")) or "unknown",
            "group_count": int(summary_payload.get("group_count", 0) or 0),
            "summary_hash": classification_summary_hash(summary_payload),
        },
        "applied_route": applied_route,
        "generated_by": "video-type-router-runtime",
        "generated_at": datetime.now().isoformat(),
    }


def _normalize_base_url(api_style: str, raw_url: str) -> str:
    base_url = str(raw_url or "").rstrip("/")
    if api_style == "anthropic-messages" and base_url.endswith("/v1"):
        return base_url[:-3]
    return base_url


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


def _extract_json_object(content: str) -> Dict[str, Any]:
    text = (content or "").strip()
    if not text:
        raise ValueError("响应为空")

    candidates: List[str] = []
    fence_match = _JSON_FENCE_RE.search(text)
    if fence_match:
        candidates.append(fence_match.group(1).strip())
    candidates.append(text)

    decoder = json.JSONDecoder()
    for candidate in candidates:
        for index, char in enumerate(candidate):
            if char != "{":
                continue
            try:
                parsed, _ = decoder.raw_decode(candidate[index:])
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed
    raise ValueError("响应中未找到合法 JSON")


def _load_provider_catalog(runtime_config: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    if runtime_config.get("config_source") == "openclaw":
        models_json_path = Path(str(runtime_config.get("models_json_path", ""))).expanduser()
        payload = json.loads(models_json_path.read_text(encoding="utf-8"))
        providers = payload.get("providers")
        if not isinstance(providers, dict):
            raise ValueError(f"models.json 缺少 providers: {models_json_path}")
        return providers
    providers = runtime_config.get("providers")
    if not isinstance(providers, dict):
        raise ValueError("runtime_config 缺少 providers")
    return providers


def _resolve_model_entry(
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


def _build_attempt_order(runtime_config: Dict[str, Any]) -> List[Dict[str, Any]]:
    providers = _load_provider_catalog(runtime_config)
    attempts: List[Dict[str, Any]] = []
    seen: set[str] = set()
    preferred_model = str(runtime_config.get("preferred_model", "") or "")
    fallback_models = tuple(runtime_config.get("fallback_models", ()) or ())

    for model_ref in (preferred_model, *fallback_models):
        if not model_ref or model_ref in seen:
            continue
        provider_name, provider_config, model_config = _resolve_model_entry(providers, model_ref)
        attempts.append(
            {
                "model_ref": model_ref,
                "provider_name": provider_name,
                "provider_config": provider_config,
                "model_config": model_config,
                "api_style": str(model_config.get("api") or provider_config.get("api") or ""),
            }
        )
        seen.add(model_ref)

    if not attempts:
        raise ValueError("没有可用于文本路由的模型配置")
    return attempts


def _call_openai_completions(
    provider_config: Dict[str, Any],
    model_config: Dict[str, Any],
    system_prompt: str,
    user_prompt: str,
) -> str:
    client = OpenAI(
        api_key=provider_config.get("apiKey", ""),
        base_url=_normalize_base_url("openai-completions", provider_config.get("baseUrl", "")),
        default_headers=provider_config.get("headers") or None,
    )
    response = client.chat.completions.create(
        model=str(model_config.get("id", "")),
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0,
        max_tokens=DEFAULT_MAX_OUTPUT_TOKENS,
    )
    return _extract_text_from_response(response)


def _call_openai_responses(
    provider_config: Dict[str, Any],
    model_config: Dict[str, Any],
    system_prompt: str,
    user_prompt: str,
) -> str:
    client = OpenAI(
        api_key=provider_config.get("apiKey", ""),
        base_url=_normalize_base_url("openai-responses", provider_config.get("baseUrl", "")),
        default_headers=provider_config.get("headers") or None,
    )
    response = client.responses.create(
        model=str(model_config.get("id", "")),
        input=[
            {"role": "system", "content": [{"type": "input_text", "text": system_prompt}]},
            {"role": "user", "content": [{"type": "input_text", "text": user_prompt}]},
        ],
        max_output_tokens=DEFAULT_MAX_OUTPUT_TOKENS,
    )
    return _extract_text_from_response(response)


def _call_anthropic_messages(
    provider_config: Dict[str, Any],
    model_config: Dict[str, Any],
    system_prompt: str,
    user_prompt: str,
) -> str:
    if Anthropic is None:  # pragma: no cover - runtime dependency exists in app
        raise RuntimeError("当前环境未安装 anthropic 库")
    client = Anthropic(
        api_key=provider_config.get("apiKey", ""),
        base_url=_normalize_base_url("anthropic-messages", provider_config.get("baseUrl", "")),
        default_headers=provider_config.get("headers") or None,
    )
    response = client.messages.create(
        model=str(model_config.get("id", "")),
        system=system_prompt,
        max_tokens=int(model_config.get("maxTokens", DEFAULT_MAX_OUTPUT_TOKENS) or DEFAULT_MAX_OUTPUT_TOKENS),
        temperature=0,
        messages=[{"role": "user", "content": [{"type": "text", "text": user_prompt}]}],
    )
    return _extract_text_from_response(response)


def _taxonomy_text() -> str:
    return TAXONOMY_PATH.read_text(encoding="utf-8")


def _build_user_prompt(summary_payload: Dict[str, Any]) -> str:
    compact_summary = {
        "video_title": summary_payload.get("video_title"),
        "scene_count": summary_payload.get("scene_count"),
        "group_count": summary_payload.get("group_count"),
        "narration": summary_payload.get("narration"),
        "groups": summary_payload.get("groups"),
    }
    return (
        "请根据下面的 taxonomy 和分类摘要，完成视频类型路由。\n\n"
        "分类时请按这个顺序想：标题快筛 → 声音判断 → 画面模式 → 交叉验证 → 分面标注 → 置信度。\n"
        "如果信息不足，也必须给出最接近的类型，但置信度降到 medium 或 low。\n\n"
        "## taxonomy\n"
        f"{_taxonomy_text()}\n\n"
        "## 分类摘要(JSON)\n"
        f"{json.dumps(compact_summary, ensure_ascii=False, indent=2)}\n"
    )


def classify_summary_with_model(summary_payload: Dict[str, Any], runtime_config: Dict[str, Any]) -> Dict[str, Any]:
    system_prompt = ROUTER_SYSTEM_PROMPT
    user_prompt = _build_user_prompt(summary_payload)
    raw_text = request_text_with_runtime(
        system_prompt,
        user_prompt,
        runtime_config,
        max_output_tokens=DEFAULT_MAX_OUTPUT_TOKENS,
        temperature=0,
    )
    return _extract_json_object(raw_text)


def load_classification_result(video_dir: Path) -> Optional[Dict[str, Any]]:
    path = video_dir / CLASSIFICATION_RESULT_FILENAME
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def generate_classification_result(
    data: Dict[str, Any],
    video_dir: Path,
    runtime_config: Optional[Dict[str, Any]] = None,
    *,
    classifier_fn: Optional[Callable[[Dict[str, Any], Dict[str, Any]], Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    summary_payload = build_classification_summary_payload(data)
    classifier = classifier_fn or classify_summary_with_model
    raw_result = classifier(summary_payload, runtime_config or {})
    final_result = build_classification_result_payload(summary_payload, raw_result)
    output_path = video_dir / CLASSIFICATION_RESULT_FILENAME
    output_path.write_text(json.dumps(final_result, ensure_ascii=False, indent=2), encoding="utf-8")
    return final_result
