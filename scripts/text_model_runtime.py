#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

try:
    from anthropic import Anthropic
except ImportError:  # pragma: no cover - dependency is available in the app runtime
    Anthropic = None

from openai import OpenAI


DEFAULT_MAX_OUTPUT_TOKENS = 1200
DEFAULT_REQUEST_TIMEOUT_SECONDS = 90.0
_TRANSIENT_ERROR_KEYWORDS = (
    "rate limit",
    "rate_limit",
    "overloaded",
    "timeout",
    "timed out",
    "503",
    "502",
    "429",
)


def _is_transient_error(exc: BaseException) -> bool:
    message = f"{type(exc).__name__}: {exc}".lower()
    return any(keyword in message for keyword in _TRANSIENT_ERROR_KEYWORDS)


def _max_retries_for_attempts() -> int:
    try:
        return max(0, int(os.environ.get("VNEXT_TEXT_MODEL_RETRIES", "2")))
    except (TypeError, ValueError):
        return 2


def _retry_with_backoff(fn: Callable[[], str], *, model_ref: str) -> str:
    retries = _max_retries_for_attempts()
    delay = 1.0
    last_exc: BaseException | None = None
    for attempt in range(retries + 1):
        try:
            return fn()
        except Exception as exc:
            last_exc = exc
            if attempt >= retries or not _is_transient_error(exc):
                raise
            time.sleep(delay)
            delay *= 2
    assert last_exc is not None
    raise last_exc


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


def build_attempt_order(runtime_config: Dict[str, Any]) -> List[Dict[str, Any]]:
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
    *,
    max_output_tokens: int,
    temperature: float,
) -> str:
    client = OpenAI(
        api_key=provider_config.get("apiKey", ""),
        base_url=_normalize_base_url("openai-completions", provider_config.get("baseUrl", "")),
        default_headers=provider_config.get("headers") or None,
        max_retries=0,
        timeout=DEFAULT_REQUEST_TIMEOUT_SECONDS,
    )
    response = client.chat.completions.create(
        model=str(model_config.get("id", "")),
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=temperature,
        max_tokens=max_output_tokens,
    )
    return _extract_text_from_response(response)


def _call_openai_responses(
    provider_config: Dict[str, Any],
    model_config: Dict[str, Any],
    system_prompt: str,
    user_prompt: str,
    *,
    max_output_tokens: int,
) -> str:
    client = OpenAI(
        api_key=provider_config.get("apiKey", ""),
        base_url=_normalize_base_url("openai-responses", provider_config.get("baseUrl", "")),
        default_headers=provider_config.get("headers") or None,
        max_retries=0,
        timeout=DEFAULT_REQUEST_TIMEOUT_SECONDS,
    )
    response = client.responses.create(
        model=str(model_config.get("id", "")),
        input=[
            {"role": "system", "content": [{"type": "input_text", "text": system_prompt}]},
            {"role": "user", "content": [{"type": "input_text", "text": user_prompt}]},
        ],
        max_output_tokens=max_output_tokens,
    )
    return _extract_text_from_response(response)


def _call_anthropic_messages(
    provider_config: Dict[str, Any],
    model_config: Dict[str, Any],
    system_prompt: str,
    user_prompt: str,
    *,
    max_output_tokens: int,
    temperature: float,
) -> str:
    if Anthropic is None:  # pragma: no cover - runtime dependency exists in app
        raise RuntimeError("当前环境未安装 anthropic 库")
    client = Anthropic(
        api_key=provider_config.get("apiKey", ""),
        base_url=_normalize_base_url("anthropic-messages", provider_config.get("baseUrl", "")),
        default_headers=provider_config.get("headers") or None,
        timeout=DEFAULT_REQUEST_TIMEOUT_SECONDS,
    )
    response = client.messages.create(
        model=str(model_config.get("id", "")),
        system=system_prompt,
        max_tokens=int(model_config.get("maxTokens", max_output_tokens) or max_output_tokens),
        temperature=temperature,
        messages=[{"role": "user", "content": [{"type": "text", "text": user_prompt}]}],
    )
    return _extract_text_from_response(response)


def request_text_with_runtime(
    system_prompt: str,
    user_prompt: str,
    runtime_config: Dict[str, Any],
    *,
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
    temperature: float = 0,
) -> str:
    if runtime_config is None:
        raise ValueError("缺少文本路由配置")
    if runtime_config.get("error"):
        raise RuntimeError(str(runtime_config.get("error")))

    errors: List[str] = []
    for attempt in build_attempt_order(runtime_config):
        api_style = str(attempt.get("api_style", "") or "")

        def _call() -> str:
            if api_style == "openai-responses":
                return _call_openai_responses(
                    attempt["provider_config"],
                    attempt["model_config"],
                    system_prompt,
                    user_prompt,
                    max_output_tokens=max_output_tokens,
                )
            if api_style == "anthropic-messages":
                return _call_anthropic_messages(
                    attempt["provider_config"],
                    attempt["model_config"],
                    system_prompt,
                    user_prompt,
                    max_output_tokens=max_output_tokens,
                    temperature=temperature,
                )
            return _call_openai_completions(
                attempt["provider_config"],
                attempt["model_config"],
                system_prompt,
                user_prompt,
                max_output_tokens=max_output_tokens,
                temperature=temperature,
            )

        try:
            return _retry_with_backoff(_call, model_ref=attempt["model_ref"])
        except Exception as exc:  # pragma: no cover - failure path depends on provider
            errors.append(f"{attempt['model_ref']}: {type(exc).__name__}: {exc}")

    raise RuntimeError("文本模型调用失败：" + " | ".join(errors))
