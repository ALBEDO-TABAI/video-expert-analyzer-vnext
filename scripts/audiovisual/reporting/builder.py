#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Sequence

from audiovisual.reporting import markdown as _markdown
from audiovisual.reporting import raw_prompt_adapter as _raw_prompt_adapter
from audiovisual.reporting import template_engine as _template_engine
from audiovisual.reporting.handoff import AudiovisualHandoffCoordinator, AudiovisualHandoffPending
from audiovisual.rendering.pdf import load_storyboard_context_rows, write_audiovisual_report_pdf
from audiovisual.routing.enrich import enrich_audiovisual_layers
from audiovisual.shared import (
    _analysis_rows,
    _markdown_media_path,
    _normalize_markdown_image_links,
    _safe_text,
    _scene_desc,
    _scene_screenshot,
)
from classification_summary import build_classification_summary_payload, classification_summary_hash


def _resolve_runtime_config() -> Dict[str, Any]:
    from ai_analyzer import resolve_auto_scoring_config

    return resolve_auto_scoring_config()


def _require_new_route_contract(data: Dict[str, Any]) -> str:
    route = data.get("audiovisual_route") or {}
    classification_result = data.get("classification_result") or {}
    classification = classification_result.get("classification") if isinstance(classification_result, dict) else {}

    type_key = ""
    if isinstance(classification, dict):
        type_key = _safe_text(classification.get("type"))
    if not type_key and isinstance(route, dict):
        type_key = _safe_text(route.get("child_type"))

    if not type_key:
        raise RuntimeError("视听剖析要求子类型路由结果，拒绝旧的 framework-only 路线")

    if not _raw_prompt_adapter.raw_prompt_available_for_data(data, route):
        raise FileNotFoundError(f"新路线缺少 raw prompt，无法继续生成视听剖析：{type_key}")

    return type_key


def _classification_cache_status(
    data: Dict,
    video_dir: Path,
) -> tuple[Dict[str, Any] | None, str]:
    route_result_path = video_dir / "classification_result.json"
    if not route_result_path.exists():
        return None, "absent"

    cached = json.loads(route_result_path.read_text(encoding="utf-8"))
    if not isinstance(cached, dict):
        return None, "unverifiable"

    cached_summary_source = cached.get("summary_source") or {}
    cached_hash = _safe_text(cached_summary_source.get("summary_hash")) if isinstance(cached_summary_source, dict) else ""
    if not cached_hash:
        return None, "unverifiable"

    current_hash = classification_summary_hash(build_classification_summary_payload(data))
    if cached_hash != current_hash:
        return None, "stale"
    return cached, "fresh"


def build_audiovisual_report_markdown(
    data: Dict,
    report_dir: Path | None = None,
    runtime_config: Dict[str, Any] | None = None,
    request_fn: Callable[[str, str], str] | None = None,
) -> str:
    original_enrich = _markdown.enrich_audiovisual_layers
    _markdown.enrich_audiovisual_layers = enrich_audiovisual_layers
    try:
        return _markdown.build_audiovisual_report_markdown(
            data,
            report_dir=report_dir,
            runtime_config=runtime_config,
            request_fn=request_fn,
        )
    finally:
        _markdown.enrich_audiovisual_layers = original_enrich


def _resolve_raw_prompt_source(data: Dict, route: Dict[str, Any]) -> str | None:
    prompt_path = _raw_prompt_adapter.resolve_raw_prompt_path_for_data(data, route)
    if prompt_path is None:
        return None
    project_root = Path(__file__).resolve().parents[3]
    try:
        return prompt_path.resolve().relative_to(project_root).as_posix()
    except ValueError:
        return prompt_path.name


def assemble_audiovisual_report_markdown(
    data: Dict,
    report_dir: Path | None = None,
    runtime_config: Dict[str, Any] | None = None,
    coordinator: AudiovisualHandoffCoordinator | None = None,
) -> tuple[str, Dict[str, Path]]:
    route = data.get("audiovisual_route") or {}
    body_request_fn: Callable[[str, str], str] | None = None
    if coordinator is not None:
        body_prompt_source = _resolve_raw_prompt_source(data, route)

        def body_request_fn(system_prompt: str, user_message: str) -> str:
            return coordinator.request_body(
                system_prompt,
                user_message,
                prompt_source=body_prompt_source,
            )
    markdown = build_audiovisual_report_markdown(
        data,
        report_dir=report_dir,
        runtime_config=runtime_config,
        request_fn=body_request_fn,
    )
    diagram_assets: Dict[str, Path] = {}

    if report_dir is None:
        return markdown, diagram_assets

    diagram_request_fn: Callable[[str, str], str] | None = (
        coordinator.request_diagram if coordinator is not None else None
    )
    overview_request_fn: Callable[[str, str], str] | None = (
        coordinator.request_overview if coordinator is not None else None
    )

    generated: Dict[str, Any] = {}
    if _template_engine.child_type_supports_svg_diagram(data, route):
        generated = _template_engine.generate_child_type_svg_diagram_assets(
            markdown,
            data,
            route,
            report_dir,
            runtime_config=runtime_config,
            request_fn=diagram_request_fn,
        )
        image_path = generated.get("png")
        if image_path:
            markdown = _template_engine.prepend_report_diagram(
                markdown,
                image_path,
                generated.get("title") or "视频结构图",
                generated.get("summary") or "",
                report_dir=report_dir,
            )
    elif _template_engine.route_supports_mv_overview(route):
        generated = _template_engine.generate_mv_overview_assets(
            markdown,
            data,
            route,
            report_dir,
            runtime_config=runtime_config,
            request_fn=overview_request_fn,
        )
        image_path = generated.get("png")
        if image_path:
            markdown = _template_engine.prepend_mv_overview(
                markdown,
                image_path,
                generated.get("title") or "视频内容架构总览",
                generated.get("summary") or "",
                report_dir=report_dir,
            )

    diagram_assets = {key: value for key, value in generated.items() if isinstance(value, Path)}
    return markdown, diagram_assets


_ILLUSTRATE_SYSTEM_PROMPT = (
    "你是视听剖析报告的配图编辑。你的唯一职责是在给定的 Markdown 正文中，"
    "于被引用到的 Scene 段落附近插入对应的截图，让长文图文并茂。"
    "严禁改写任何文字、删除任何段落、重排任何结构。"
    "若一个段落同时提及多个 Scene，只挑其中一张最有代表性的插入，不要堆图。"
    "若同一张图在最近几段刚出现过，就跳过以免重复。"
    "如果某段落未提及任何 Scene，不要在其后插图。"
    "最终输出必须是完整的 Markdown 全文，不要用代码块围栏包裹。"
)


def _iter_analysis_rows(data: Dict) -> List[Dict[str, Any]]:
    try:
        return _analysis_rows(data)
    except Exception:
        return []


def _scene_weighted_score(scene: Dict[str, Any]) -> float:
    try:
        return float(scene.get("weighted_score") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _scene_visual_line(scene: Dict[str, Any]) -> str:
    text = _scene_desc(scene) or _safe_text(scene.get("visual_summary"))
    if not text:
        return ""
    first = text.replace("\r\n", "\n").split("\n", 1)[0].strip()
    return first[:80]


def _build_scene_image_catalog(data: Dict, report_dir: Path) -> List[Dict[str, Any]]:
    rows = _iter_analysis_rows(data)
    catalog: List[Dict[str, Any]] = []
    for scene in rows:
        try:
            scene_number = int(scene.get("scene_number", 0))
        except (TypeError, ValueError):
            continue
        if scene_number <= 0:
            continue
        raw_path = _scene_screenshot(scene)
        if not raw_path:
            continue
        absolute = Path(raw_path)
        if not absolute.is_absolute():
            absolute = (report_dir / absolute).resolve()
        if not absolute.exists() or not absolute.is_file():
            continue
        rel_path = _markdown_media_path(str(absolute), report_dir)
        if not rel_path:
            continue
        storyboard = scene.get("storyboard") or {}
        timestamp = _safe_text(
            scene.get("timestamp")
            or scene.get("timestamp_range")
            or storyboard.get("timestamp")
        )
        catalog.append(
            {
                "scene_number": scene_number,
                "timestamp": timestamp,
                "visual": _scene_visual_line(scene),
                "rel_path": rel_path,
                "weighted": _scene_weighted_score(scene),
            }
        )
    return catalog


def _format_scene_catalog_block(catalog: Sequence[Dict[str, Any]]) -> str:
    lines: List[str] = []
    for item in catalog:
        parts = [
            f"Scene {item['scene_number']:03d}",
            item.get("timestamp") or "-",
        ]
        weighted = item.get("weighted") or 0.0
        if weighted > 0:
            parts.append(f"加权分 {weighted:.1f}")
        visual = item.get("visual") or ""
        if visual:
            parts.append(f"画面: {visual}")
        parts.append(f"截图: <{item['rel_path']}>")
        lines.append("- " + " | ".join(parts))
    return "\n".join(lines)


def _build_illustrate_user_message(markdown_text: str, catalog: Sequence[Dict[str, Any]]) -> str:
    catalog_block = _format_scene_catalog_block(catalog) or "- （无可用截图，不要强行插图）"
    return "\n".join(
        [
            "## 任务",
            "",
            "下方是一份视听剖析 Markdown 报告。请仅在 `## 正文模块` 里被提及到 Scene 的段落之后，"
            "按「场景目录」里给出的截图路径，插入一行 `![简短说明](<截图路径>)`。保留其余所有字符不变。",
            "",
            "## 插图规则",
            "",
            "1. 只在段落（自然段或列表项）紧跟其后的空行位置插入图片行；图片之前保留一个空行，之后也保留一个空行。",
            "2. 同一段提及多个 Scene 时，只选最能代表段落核心论点的那张：优先看段落文字本身的侧重，其次参考「加权分」。",
            "3. 同一张图不要在连续 3 段之内重复出现；若只能用同一张，就跳过后出现的那次。",
            "4. `## 路由判断`、`## 视听剖析概览 / 视频结构图 / 视频内容架构总览` 等已带自有图示的模块不要再追加截图；"
            "报告首尾的标题、生成时间、代码块、表格内部也不要插图。",
            "5. 简短说明控制在 20 个汉字以内，格式建议：`Scene NNN · 时间戳 · 画面要点`；画面要点可压缩自「场景目录」。",
            "6. 截图路径必须来自下方目录，不要凭空编造；找不到对应 Scene 就跳过插图。",
            "7. 不要重写、合并、删减任何原文，也不要改动已有 Markdown 图片链接；脚本会在之后再跑一次链接规范化。",
            "",
            "## 场景目录",
            "",
            catalog_block,
            "",
            "## 待配图的 Markdown 原文",
            "",
            markdown_text.strip(),
        ]
    )


_IMAGE_LINK_RE = re.compile(r"!\[[^\]]*\]\(<?([^)>]+)>?\)")


def _extract_image_paths(markdown_text: str) -> List[str]:
    return [match.group(1).strip() for match in _IMAGE_LINK_RE.finditer(markdown_text)]


def _validate_illustrated_markdown(
    illustrated: str,
    original: str,
    catalog: Sequence[Dict[str, Any]],
) -> None:
    allowed_paths = {str(item.get("rel_path", "")).strip() for item in catalog}
    allowed_paths.discard("")
    pre_existing = set(_extract_image_paths(original))
    new_paths = [
        path for path in _extract_image_paths(illustrated) if path not in pre_existing
    ]

    fabricated = [path for path in new_paths if path not in allowed_paths]
    if fabricated:
        raise ValueError(
            "illustrate 输出包含目录外的截图路径："
            + "、".join(sorted(set(fabricated)))
        )

    paragraphs = [block.strip() for block in illustrated.split("\n\n")]
    window: List[str] = []
    for block in paragraphs:
        paths_in_block = [path for path in _extract_image_paths(block) if path not in pre_existing]
        for path in paths_in_block:
            if path in window:
                raise ValueError(f"illustrate 输出在 3 段以内重复插入同一张图：{path}")
        window.extend(paths_in_block)
        if len(window) > 3:
            window = window[-3:]


def _maybe_illustrate_markdown(
    markdown_text: str,
    data: Dict,
    report_dir: Path,
    coordinator: AudiovisualHandoffCoordinator,
) -> str:
    catalog = _build_scene_image_catalog(data, report_dir)
    if not catalog:
        return markdown_text
    user_message = _build_illustrate_user_message(markdown_text, catalog)
    illustrated = coordinator.request_illustrate(_ILLUSTRATE_SYSTEM_PROMPT, user_message)
    _validate_illustrated_markdown(illustrated, markdown_text, catalog)
    return illustrated


def generate_audiovisual_report_outputs(
    data: Dict,
    video_dir: Path,
    formats: Sequence[str] = ("md", "pdf"),
    runtime_config: Dict[str, Any] | None = None,
) -> Dict[str, object]:
    enriched = dict(data)
    video_id = _safe_text(enriched.get("video_id"), "unknown")
    if runtime_config is None:
        runtime_config = _resolve_runtime_config()

    cache_status = "provided" if isinstance(enriched.get("classification_result"), dict) else "absent"
    if not isinstance(enriched.get("classification_result"), dict):
        cached_result, cache_status = _classification_cache_status(enriched, video_dir)
        if cached_result is not None:
            enriched["classification_result"] = cached_result
    context_rows = load_storyboard_context_rows(video_dir, video_id)
    if context_rows:
        enriched["storyboard_context_rows"] = context_rows
    enriched = enrich_audiovisual_layers(enriched)
    _require_new_route_contract(enriched)
    enriched["_classification_result_cache_status"] = cache_status

    coordinator = AudiovisualHandoffCoordinator(video_dir, video_id)

    generated: Dict[str, Path] = {}
    normalized = [item.strip().lower() for item in formats if item and item.strip()]
    markdown_text, diagram_assets = assemble_audiovisual_report_markdown(
        enriched,
        report_dir=video_dir,
        runtime_config=runtime_config,
        coordinator=coordinator,
    )
    markdown_text = _maybe_illustrate_markdown(
        markdown_text,
        enriched,
        video_dir,
        coordinator,
    )
    markdown_text = _normalize_markdown_image_links(markdown_text, video_dir)

    if "md" in normalized:
        md_path = video_dir / f"{video_id}_audiovisual_analysis.md"
        md_path.write_text(markdown_text, encoding="utf-8")
        generated["md"] = md_path

    if "pdf" in normalized:
        pdf_path = video_dir / f"{video_id}_audiovisual_analysis.pdf"
        generated["pdf"] = write_audiovisual_report_pdf(enriched, pdf_path, report_dir=video_dir, markdown_text=markdown_text)

    generated.update(diagram_assets)

    if "md" in generated:
        generated["report_path"] = generated["md"]

    return {
        "data": enriched,
        "report_mode": "template",
        "classification_result_cache_status": cache_status,
        **generated,
    }
