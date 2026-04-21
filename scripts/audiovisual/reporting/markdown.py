#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict

from audiovisual.reporting import template_engine as _template_engine
from audiovisual.routing.enrich import enrich_audiovisual_layers
from audiovisual.shared import _safe_text


def _template_build_audiovisual_report_markdown(
    data: Dict,
    route: Dict[str, object],
    report_dir: Path | None = None,
    runtime_config: Dict[str, Any] | None = None,
    request_fn: Callable[[str, str], str] | None = None,
) -> str:
    return _template_engine.synthesize_audiovisual_report(
        data,
        route,
        report_dir=report_dir,
        runtime_config=runtime_config,
        request_fn=request_fn,
    )


def build_audiovisual_report_markdown(
    data: Dict,
    report_dir: Path | None = None,
    runtime_config: Dict[str, Any] | None = None,
    request_fn: Callable[[str, str], str] | None = None,
) -> str:
    enrich_audiovisual_layers(data)
    route = data["audiovisual_route"]

    if not _template_engine.route_supports_template(route):
        raise RuntimeError(f"模板引擎暂不支持当前路由: {_safe_text(route.get('framework')) or 'unknown'}")

    return _template_build_audiovisual_report_markdown(
        data,
        route,
        report_dir=report_dir,
        runtime_config=runtime_config,
        request_fn=request_fn,
    )
