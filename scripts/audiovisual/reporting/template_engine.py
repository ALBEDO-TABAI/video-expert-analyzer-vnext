#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import re
from typing import Any, Callable, Dict, List, Sequence

from . import raw_prompt_adapter as _raw_prompt_adapter
from . import scene_utils as _scene_utils
from audiovisual.reporting.common import (
    _abstract_sfx_failure_risk,
    _abstract_sfx_sync_analysis,
    _alignment_summary,
    _atmospheric_groups,
    _atmospheric_summary,
    _documentary_credibility_assessment,
    _documentary_information_completeness,
    _event_brand_groups,
    _event_brand_story_summary,
    _experimental_focus_advice,
    _experimental_route_diagnosis,
    _experimental_viewing_advice,
    _graphic_summary,
    _highlight_specs_for_route,
    _hybrid_ambient_failure_risk,
    _hybrid_ambient_layering_analysis,
    _hybrid_ambient_viewing_advice,
    _hybrid_commentary_failure_risk,
    _hybrid_commentary_mix_value,
    _hybrid_commentary_viewing_advice,
    _hybrid_meme_failure_risk,
    _hybrid_meme_mix_analysis,
    _hybrid_meme_viewing_advice,
    _hybrid_music_failure_risk,
    _hybrid_narrative_failure_risk,
    _hybrid_narrative_layering_analysis,
    _infographic_clarity_analysis,
    _infographic_failure_risk,
    _infographic_hierarchy_analysis,
    _journey_brand_groups,
    _journey_brand_story_summary,
    _language_led_groups,
    _language_led_summary,
    _lecture_performance_failure_risk,
    _lecture_performance_groups,
    _lecture_performance_stage_analysis,
    _main_summary,
    _meme_density_analysis,
    _meme_failure_points,
    _meme_subculture_markers,
    _meme_timing_analysis,
    _motion_graphics_failure_risk,
    _motion_graphics_flow_analysis,
    _narrative_groups,
    _narrative_mix_failure_risk,
    _narrative_mix_integrity,
    _narrative_mix_story_reframing,
    _narrative_motion_graphics_failure_risk,
    _narrative_motion_graphics_integrity,
    _narrative_motion_graphics_story_role,
    _pure_visual_mix_failure_risk,
    _pure_visual_mix_rhythm_analysis,
    _pure_visual_mix_viewing_advice,
    _reality_sfx_distortion_analysis,
    _reality_sfx_failure_risk,
    _reality_sfx_viewing_advice,
    _report_voiceover,
    _scene_refs,
    _silent_performance_body_analysis,
    _silent_performance_failure_risk,
    _silent_performance_viewing_advice,
    _silent_reality_failure_risk,
    _silent_reality_pacing_analysis,
    _silent_reality_viewing_advice,
    _technical_explainer_groups,
    _technical_explainer_story_summary,
    _trailer_groups,
    _trailer_sell_paragraph,
    _trailer_story_summary,
)
from audiovisual.routing.constants import (
    ATMOSPHERIC_FRAMEWORKS as _ATMOSPHERIC_FRAMEWORKS,
    GRAPHIC_FRAMEWORKS as _GRAPHIC_FRAMEWORKS,
    LANGUAGE_LED_FRAMEWORKS as _LANGUAGE_LED_FRAMEWORKS,
    MEME_FRAMEWORKS as _MEME_FRAMEWORKS,
)
from audiovisual.reporting.mv_overview import (
    generate_mv_overview_assets as _generate_mv_overview_assets,
    prepend_mv_overview as _prepend_mv_overview,
    route_supports_mv_overview as _route_supports_mv_overview,
)
from audiovisual.reporting.svg_diagram import (
    child_type_supports_svg_diagram as _child_type_supports_svg_diagram,
    generate_child_type_svg_diagram_assets as _generate_child_type_svg_diagram_assets,
    prepend_report_diagram as _prepend_report_diagram,
    resolve_child_type_svg_prompt_path as _resolve_child_type_svg_prompt_path,
)
from audiovisual.shared import _analysis_rows, _avg, _markdown_media_path, _onscreen_text, _relative_media_path, _safe_text, _scene_desc, _scene_screenshot, _title_text, _top_text, _voiceover
from text_model_runtime import request_text_with_runtime

_INCLUDE_RE = re.compile(r"<!--\s*INCLUDE:(.*?)\s*-->")
_SECTION_RE = re.compile(r"<!--\s*(SYSTEM|DATA|TASKS)\s*-->(.*?)<!--\s*/\1\s*-->", re.DOTALL)
_PYTHON_DIRECT_RE = re.compile(r"<!--\s*PYTHON_DIRECT:(\w+)\s*-->(.*?)<!--\s*/PYTHON_DIRECT\s*-->", re.DOTALL)
_FIGURE_RE = re.compile(r"<!--\s*FIGURE:([a-zA-Z0-9_\-]+)\s*-->")
_UNRESOLVED_PLACEHOLDER_RE = re.compile(r"\{\{(\w+)\}\}")
_REQUIRED_SECTION_RE = re.compile(r"^##\s+.+$", re.MULTILINE)
_SCENE_EVIDENCE_RE = re.compile(
    r"Scene\s+\d{3}|(?:\d{2}:)?\d{2}:\d{2}(?:[,.:]\d{2,3})?(?:\s*[–-]\s*(?:\d{2}:)?\d{2}:\d{2}(?:[,.:]\d{2,3})?)?"
)
_FIGURE_MARKER_RATIONALES = {
    "opening": "对应开场入口的关键镜头，用来钉住后文分析的观看起点。",
    "setup": "对应前提建立段落的关键镜头，用来说明后文如何搭起分析框架。",
    "evidence_peak": "对应证据最集中的节点，用来支撑这一节的判断依据。",
    "motif_peak": "对应母题最清晰的峰值镜头，用来说明这一节的视觉母题如何成立。",
    "atmosphere_peak": "对应氛围最强的一段，用来解释这一节的感受是怎样被抬起来的。",
    "rhythm_peak": "对应节奏或冲击的峰值镜头，用来支撑这一节的节奏判断。",
    "narrative_peak": "对应叙事推进的关键镜头，用来说明这一节的结构转折。",
    "performance_peak": "对应表演能量最高的节点，用来说明人物或动作怎样把这一节推起来。",
    "spatial_peak": "对应空间特征最清楚的镜头，用来说明这一节的场域判断。",
    "question": "对应这一节提出核心问题的关键镜头，用来明确分析焦点。",
    "detail": "对应这一节最值得放大的细节镜头，用来解释判断落点。",
    "recap": "对应这一节回看总结的镜头，用来收束前文的判断。",
    "escalation": "对应升级或加压节点的镜头，用来说明这一节为何转强。",
    "payoff": "对应结果兑现的关键镜头，用来支撑这一节的高潮判断。",
    "conclusion": "对应结论落下的关键镜头，用来稳住这一节的判断收口。",
    "spectacle": "对应奇观段落的关键镜头，用来说明这一节的场面调度。",
    "product": "对应产品或品牌信号最清楚的镜头，用来说明这一节的品牌着陆。",
    "closing": "对应收尾节点的关键镜头，用来说明这一节如何完成退出。",
    "arrival": "对应抵达或进入状态的镜头，用来说明这一节的转入时刻。",
    "brand_tail": "对应品牌收尾节点的镜头，用来说明品牌如何在尾段锁定。",
    "source_quality": "对应素材质感最能说明问题的镜头，用来支撑这一节的质量判断。",
}


def load_route_template(framework: str, templates_dir: Path | None = None) -> str:
    base_dir = templates_dir or Path(__file__).resolve().parents[2] / "templates"
    template_path = _resolve_template_path(framework, base_dir)
    return _resolve_includes(
        template_path.read_text(encoding="utf-8"),
        template_path.parent,
        include_stack=(template_path.resolve(),),
    )


def load_route_template_for_data(data: Dict[str, Any], route: Dict[str, Any], templates_dir: Path | None = None) -> str:
    base_dir = templates_dir or Path(__file__).resolve().parents[2] / "templates"
    template_path = _resolve_template_path_for_route(data, route, base_dir)
    return _resolve_includes(
        template_path.read_text(encoding="utf-8"),
        template_path.parent,
        include_stack=(template_path.resolve(),),
    )


def _resolve_template_path(framework: str, base_dir: Path) -> Path:
    primary_path = base_dir / f"template_{framework}.md"
    if primary_path.exists():
        return primary_path

    family = _framework_family_name(framework)
    family_path = base_dir / f"_family_{family}.md"
    if family != "generic" and family_path.exists():
        return family_path

    attempted = [str(primary_path)]
    if family != "generic":
        attempted.append(str(family_path))
    raise FileNotFoundError(f"Template for route '{framework}' not found. Tried: {', '.join(attempted)}")


def _resolve_template_path_for_route(data: Dict[str, Any], route: Dict[str, Any], base_dir: Path) -> Path:
    framework = _safe_text(route.get("framework"))
    type_key = _template_type_key(data, route)
    candidates: List[Path] = []

    if type_key and framework:
        candidates.append(base_dir / f"template_type_{type_key}_{framework}.md")
    if type_key:
        candidates.append(base_dir / f"template_type_{type_key}.md")
    if framework:
        candidates.append(base_dir / f"template_{framework}.md")
        family = _framework_family_name(framework)
        if family != "generic":
            candidates.append(base_dir / f"_family_{family}.md")

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return _resolve_template_path(framework, base_dir)


def _template_type_key(data: Dict[str, Any], route: Dict[str, Any] | None = None) -> str:
    classification_result = data.get("classification_result") or {}
    if isinstance(classification_result, dict):
        classification = classification_result.get("classification") or {}
        if isinstance(classification, dict):
            type_key = _safe_text(classification.get("type"))
            if type_key:
                return type_key

    route = route or data.get("audiovisual_route") or {}
    if isinstance(route, dict):
        child_type = _safe_text(route.get("child_type"))
        if child_type:
            return child_type

        route_subtype = _safe_text(route.get("route_subtype"))
        if route_subtype:
            try:
                from video_type_router_runtime import TYPE_LABELS
            except ImportError:
                TYPE_LABELS = {}
            for type_key, type_cn in TYPE_LABELS.items():
                if route_subtype == _safe_text(type_cn):
                    return type_key
    return ""


def _framework_family_name(framework: str) -> str:
    if framework in _LANGUAGE_LED_FRAMEWORKS:
        return "language_led"
    if framework in _ATMOSPHERIC_FRAMEWORKS:
        return "atmospheric"
    if framework in _MEME_FRAMEWORKS:
        return "meme"
    if framework in _GRAPHIC_FRAMEWORKS:
        return "graphic"
    return "generic"


def _resolve_includes(text: str, base_dir: Path, include_stack: Sequence[Path] | None = None) -> str:
    stack = tuple(include_stack or ())

    def _replace(match: re.Match[str]) -> str:
        include_name = match.group(1).strip()
        include_path = base_dir / include_name
        resolved_path = include_path.resolve()
        if resolved_path in stack:
            chain = " -> ".join(path.name for path in (*stack, resolved_path))
            raise RuntimeError(f"Cyclic template include detected: {chain}")
        if not include_path.exists():
            source_name = stack[-1].name if stack else "inline template"
            raise FileNotFoundError(
                f"Included template '{include_name}' not found while resolving '{source_name}': {include_path}"
            )
        included = include_path.read_text(encoding="utf-8")
        return _resolve_includes(included, include_path.parent, include_stack=(*stack, resolved_path))

    return _INCLUDE_RE.sub(_replace, text)


def _split_template_sections(template_text: str) -> Dict[str, Any]:
    sections: Dict[str, Any] = {"system": "", "data": "", "tasks": "", "python_direct": []}
    for match in _SECTION_RE.finditer(template_text):
        sections[match.group(1).lower()] = match.group(2).strip()
    sections["python_direct"] = [
        {"name": match.group(1), "template": match.group(2).strip()}
        for match in _PYTHON_DIRECT_RE.finditer(template_text)
    ]
    return sections


def fill_template(template_text: str, context: Dict[str, Any]) -> str:
    for key, value in context.items():
        template_text = template_text.replace(f"{{{{{key}}}}}", str(value))
    unresolved = _UNRESOLVED_PLACEHOLDER_RE.findall(template_text)
    if unresolved:
        import logging as _logging

        _logging.getLogger(__name__).warning("未解析的模板占位符: %s", ", ".join(unresolved))
    return template_text


def route_supports_template(route: Dict[str, Any]) -> bool:
    return _safe_text(route.get("framework")) in _ROUTE_CONTEXT_BUILDERS


def route_supports_mv_overview(route: Dict[str, Any]) -> bool:
    return _route_supports_mv_overview(route)


def resolve_child_type_svg_prompt_path(
    data: Dict[str, Any],
    route: Dict[str, Any],
    prompts_dir: Path | None = None,
) -> Path | None:
    return _resolve_child_type_svg_prompt_path(data, route, prompts_dir=prompts_dir)


def child_type_supports_svg_diagram(data: Dict[str, Any], route: Dict[str, Any]) -> bool:
    return _child_type_supports_svg_diagram(data, route)


def generate_child_type_svg_diagram_assets(
    report_markdown: str,
    data: Dict[str, Any],
    route: Dict[str, Any],
    output_dir: Path,
    client: Any | None = None,
    runtime_config: Dict[str, Any] | None = None,
    request_fn: Callable[[str, str], str] | None = None,
) -> Dict[str, Any]:
    if request_fn is None:
        def request_fn(system_prompt: str, user_message: str) -> str:
            return _request_agent_report(
                system_prompt,
                user_message,
                client=client,
                runtime_config=runtime_config,
            )
    return _generate_child_type_svg_diagram_assets(
        report_markdown,
        data,
        route,
        output_dir,
        request_fn=request_fn,
    )


def prepend_report_diagram(
    markdown: str,
    image_path: Path,
    title: str,
    summary: str = "",
    report_dir: Path | None = None,
) -> str:
    return _prepend_report_diagram(markdown, image_path, title, summary=summary, report_dir=report_dir)


def generate_mv_overview_assets(
    report_markdown: str,
    data: Dict[str, Any],
    route: Dict[str, Any],
    output_dir: Path,
    client: Any | None = None,
    runtime_config: Dict[str, Any] | None = None,
    request_fn: Callable[[str, str], str] | None = None,
) -> Dict[str, Any]:
    if request_fn is None:
        def request_fn(system_prompt: str, user_message: str) -> str:
            return _request_agent_report(
                system_prompt,
                user_message,
                client=client,
                runtime_config=runtime_config,
            )
    return _generate_mv_overview_assets(
        report_markdown,
        data,
        route,
        output_dir,
        request_fn=request_fn,
    )


def prepend_mv_overview(
    markdown: str,
    image_path: Path,
    title: str,
    summary: str,
    report_dir: Path | None = None,
) -> str:
    return _prepend_mv_overview(markdown, image_path, title, summary, report_dir=report_dir)


def build_template_context(data: Dict, route: Dict[str, Any]) -> Dict[str, str]:
    ordered = _analysis_rows(data)
    scenes = data.get("scenes", [])
    alignment = _alignment_summary(data)
    context = {
        "route_label": _safe_text(route.get("route_label"), "未识别路由"),
        "route_subtype_str": f"（{route['route_subtype']}）" if _safe_text(route.get("route_subtype")) else "",
        "total_scenes": str(len(scenes)),
        "weighted_avg": _fmt_avg([float(scene.get("weighted_score") or 0.0) for scene in scenes if float(scene.get("weighted_score") or 0.0) > 0]),
        "usable_ratio": _fmt_pct(
            sum(1 for scene in scenes if "[MUST KEEP]" in _safe_text(scene.get("selection")) or "[USABLE]" in _safe_text(scene.get("selection"))),
            len(scenes),
        ),
        "avg_aesthetic": _fmt_avg([float(scene.get("scores", {}).get("aesthetic_beauty") or 0.0) for scene in scenes]),
        "avg_impact": _fmt_avg([float(scene.get("scores", {}).get("impact") or 0.0) for scene in scenes]),
        "avg_memorability": _fmt_avg([float(scene.get("scores", {}).get("memorability") or 0.0) for scene in scenes]),
        "avg_fun": _fmt_avg([float(scene.get("scores", {}).get("fun_interest") or 0.0) for scene in scenes]),
        "avg_credibility": _fmt_avg([float(scene.get("scores", {}).get("credibility") or 0.0) for scene in scenes]),
        "avg_info_efficiency": _fmt_avg([float(scene.get("analysis_dimensions", {}).get("information_efficiency") or 0.0) for scene in scenes]),
        "alignment_level": alignment["level"],
        "visual_peak_scenes": _scene_number_list(alignment["visual_peaks"]),
        "language_peak_scenes": _scene_number_list(alignment["language_peaks"]),
        "highlight_specs_list": _format_highlight_specs_for_template(data, route),
        "content_synopsis_data": _build_content_synopsis_data(data, route, scenes),
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    context.update(_dimension_eval_context({}))
    builder = _ROUTE_CONTEXT_BUILDERS.get(_safe_text(route.get("framework")))
    if builder is None:
        raise KeyError(f"Unsupported template route: {route.get('framework')}")
    builder(context, data, ordered)
    return context


def _build_mix_music_context(context: Dict[str, str], data: Dict, ordered: Sequence[Dict]) -> None:
    durations = [float(scene.get("duration_seconds") or 0.0) for scene in ordered if float(scene.get("duration_seconds") or 0.0) > 0]
    avg_duration = _avg(durations)
    short_cuts = [scene for scene in ordered if float(scene.get("duration_seconds") or 0.0) < avg_duration * 0.6]
    beat_hits = [scene for scene in short_cuts if float(scene.get("scores", {}).get("impact") or 0.0) >= 7.0]
    rhythm_consistency = 1.0 - (max(durations) - min(durations)) / (max(durations) + 0.1) if durations else 0.0
    high_score_scenes = [scene for scene in ordered if float(scene.get("weighted_score") or 0.0) >= 7.0]
    style_keywords = [_safe_text(scene.get("storyboard", {}).get("visual_style")) for scene in ordered if _safe_text(scene.get("storyboard", {}).get("visual_style"))]
    style_diversity = len(set(style_keywords)) / len(style_keywords) if style_keywords else 1.0
    emotional_curve = [float(scene.get("analysis_dimensions", {}).get("emotional_effect") or 0.0) for scene in ordered]
    peak_scenes = [ordered[index] for index, score in enumerate(emotional_curve) if score >= 7.5]

    context.update(
        {
            "avg_duration": f"{avg_duration:.1f}",
            "short_cut_ratio": _fmt_pct(len(short_cuts), len(ordered)),
            "beat_hit_scenes": _scene_refs(beat_hits[:4], 4) if beat_hits else "未检测到明显卡点",
            "rhythm_consistency": f"{rhythm_consistency * 10:.1f}",
            "high_score_ratio": _fmt_pct(len(high_score_scenes), len(ordered)),
            "high_score_scene_refs": _scene_refs(high_score_scenes[:5], 5),
            "style_consistency": f"{(1 - style_diversity) * 10:.1f}",
            "top_visual_styles": _top_text(style_keywords, limit=3) if style_keywords else "多种风格混合",
            "emotion_variance": f"{(max(emotional_curve) - min(emotional_curve)):.1f}" if emotional_curve else "0.0",
            "emotion_peak_count": str(len(peak_scenes)),
            "emotion_peak_scene_refs": _scene_refs(peak_scenes[:4], 4) if peak_scenes else "未检测到明显峰值",
            "scenes_by_dimension": _format_scenes_by_dimension(
                ordered,
                {
                    "节奏相关": lambda scene: float(scene.get("duration_seconds") or 0.0) < avg_duration * 0.6
                    or float(scene.get("scores", {}).get("impact") or 0.0) >= 7.0,
                    "素材质量相关": lambda scene: float(scene.get("weighted_score") or 0.0) >= 7.0,
                    "情绪相关": lambda scene: float(scene.get("analysis_dimensions", {}).get("emotional_effect") or 0.0) >= 7.0,
                },
                limit_per_group=5,
            ),
        }
    )


def _build_concept_mv_context(context: Dict[str, str], data: Dict, ordered: Sequence[Dict]) -> None:
    groups = _atmospheric_groups(data)
    descriptions = [_scene_desc(scene) for scene in ordered]
    all_text = " ".join(descriptions)
    imagery_keywords = ["光", "影", "水", "火", "镜", "窗", "路", "门", "手", "眼"]
    detected = {keyword: all_text.count(keyword) for keyword in imagery_keywords if all_text.count(keyword) > 0}
    dominant = max(detected, key=detected.get) if detected else ""
    style_keywords = [_safe_text(scene.get("storyboard", {}).get("visual_style")) for scene in ordered if _safe_text(scene.get("storyboard", {}).get("visual_style"))]
    style_diversity = len(set(style_keywords)) / len(style_keywords) if style_keywords else 1.0
    emotion_curve = [
        (float(scene.get("scores", {}).get("impact") or 0.0) + float(scene.get("scores", {}).get("memorability") or 0.0)) / 2.0
        for scene in ordered
    ]
    peak_scenes = [ordered[index] for index, score in enumerate(emotion_curve) if score >= 7.5]

    motif_numbers = {int(scene.get("scene_number", 0)) for scene in groups["motif"]}
    rhythm_numbers = {int(scene.get("scene_number", 0)) for scene in groups["rhythm"]}
    peak_numbers = {int(scene.get("scene_number", 0)) for scene in peak_scenes}

    context.update(
        {
            "imagery_type_count": str(len(detected)),
            "imagery_keywords_summary": "、".join(detected.keys()) if detected else "未检测到稳定意象",
            "dominant_imagery": dominant or "未形成主导意象",
            "dominant_imagery_count": str(detected.get(dominant, 0)),
            "style_consistency": f"{(1 - style_diversity) * 10:.1f}",
            "motif_scene_refs": _scene_refs(groups["motif"], 4),
            "rhythm_scene_refs": _scene_refs(groups["rhythm"], 4),
            "crest_scene_refs": _scene_refs(groups["crest"], 4),
            "emotion_variance": f"{(max(emotion_curve) - min(emotion_curve)):.1f}" if emotion_curve else "0.0",
            "emotion_peak_count": str(len(peak_scenes)),
            "emotion_peak_scene_refs": _scene_refs(peak_scenes[:4], 4) if peak_scenes else "未检测到明显峰值",
            "scenes_by_dimension": _format_scenes_by_dimension(
                ordered,
                {
                    "意象相关": lambda scene: int(scene.get("scene_number", 0)) in motif_numbers,
                    "节奏抬升": lambda scene: int(scene.get("scene_number", 0)) in rhythm_numbers,
                    "情绪高点": lambda scene: int(scene.get("scene_number", 0)) in peak_numbers,
                },
                limit_per_group=5,
            ),
        }
    )


def _build_narrative_performance_context(context: Dict[str, str], data: Dict, ordered: Sequence[Dict]) -> None:
    route = data.get("audiovisual_route") or {}
    groups = _narrative_groups(data)
    dual_layer = route.get("dual_layer") or {}
    narrative_scores = [float(scene.get("analysis_dimensions", {}).get("narrative_function") or 0.0) for scene in ordered]
    dialogue_scenes = [scene for scene in groups["key_moments"] if _report_voiceover(scene)]
    shot_sizes = [_safe_text(scene.get("storyboard", {}).get("shot_size")) for scene in ordered if _safe_text(scene.get("storyboard", {}).get("shot_size"))]
    lighting = [_safe_text(scene.get("storyboard", {}).get("lighting")) for scene in ordered if _safe_text(scene.get("storyboard", {}).get("lighting"))]
    movement = [_safe_text(scene.get("storyboard", {}).get("camera_movement")) for scene in ordered if _safe_text(scene.get("storyboard", {}).get("camera_movement"))]
    styles = [_safe_text(scene.get("storyboard", {}).get("visual_style")) for scene in ordered if _safe_text(scene.get("storyboard", {}).get("visual_style"))]
    setup_numbers = {int(scene.get("scene_number", 0)) for scene in groups["setup"]}
    conflict_numbers = {int(scene.get("scene_number", 0)) for scene in groups["conflict"]}
    climax_numbers = {int(scene.get("scene_number", 0)) for scene in groups["climax"]}
    resolution_numbers = {int(scene.get("scene_number", 0)) for scene in groups["resolution"]}
    avg_narrative = _avg(narrative_scores)

    context.update(
        {
            "setup_scene_refs": _scene_refs(groups["setup"], 4),
            "conflict_scene_refs": _scene_refs(groups["conflict"], 4),
            "climax_scene_refs": _scene_refs(groups["climax"], 4),
            "resolution_scene_refs": _scene_refs(groups["resolution"], 4),
            "setup_desc": _scene_phrase(groups["setup"]),
            "conflict_desc": _scene_phrase(groups["conflict"]),
            "climax_desc": _scene_phrase(groups["climax"]),
            "resolution_desc": _scene_phrase(groups["resolution"]),
            "setup_story_functions": _top_text([_safe_text(scene.get("story_function")) for scene in groups["setup"]], 2),
            "conflict_story_functions": _top_text([_safe_text(scene.get("story_function")) for scene in groups["conflict"]], 2),
            "climax_story_functions": _top_text([_safe_text(scene.get("story_function")) for scene in groups["climax"]], 2),
            "resolution_story_functions": _top_text([_safe_text(scene.get("story_function")) for scene in groups["resolution"]], 2),
            "shot_size_summary": _top_text(shot_sizes, 3) if shot_sizes else "未知",
            "lighting_summary": _top_text(lighting, 3) if lighting else "未知",
            "movement_summary": _top_text(movement, 3) if movement else "未知",
            "visual_style_summary": _top_text(styles, 3) if styles else "未知",
            "narrative_avg": f"{avg_narrative:.1f}",
            "narrative_integrity_level": "高" if avg_narrative >= 7.2 else ("中" if avg_narrative >= 6.0 else "偏弱"),
            "key_voiceover_scene_refs": _scene_refs(dialogue_scenes[:5], 5) if dialogue_scenes else "未检测到稳定语言高点",
            "key_voiceover_samples": " / ".join(_report_voiceover(scene)[:20] for scene in dialogue_scenes[:2] if _report_voiceover(scene)) or "暂无可靠歌词/对白样本",
            "secondary_layer_status": "已触发" if dual_layer.get("enabled") else "未触发",
            "secondary_layer_name": _safe_text(dual_layer.get("secondary"), "叙事外的表达层"),
            "secondary_section_heading": f"第二层：作为{_safe_text(dual_layer.get('secondary'), '叙事外的表达层')}",
            "secondary_layer_reason": _safe_text(dual_layer.get("reason"), "当前样本里未形成稳定的第二表达层。"),
            "key_moment_scene_refs": _scene_refs(groups["key_moments"], 5),
            "scenes_by_dimension": _format_scenes_by_dimension(
                ordered,
                {
                    "开场建立": lambda scene: int(scene.get("scene_number", 0)) in setup_numbers,
                    "中段推进": lambda scene: int(scene.get("scene_number", 0)) in conflict_numbers,
                    "高点抬升": lambda scene: int(scene.get("scene_number", 0)) in climax_numbers,
                    "尾声收束": lambda scene: int(scene.get("scene_number", 0)) in resolution_numbers,
                },
                limit_per_group=4,
            ),
        }
    )


def _build_cinematic_life_context(context: Dict[str, str], data: Dict, ordered: Sequence[Dict]) -> None:
    lighting_keywords = ["逆光", "暖色", "冷色", "剪影", "光影", "质感", "氛围"]
    life_keywords = ["日常", "生活", "记录", "真实", "现场"]
    aesthetic_scores = [float(scene.get("scores", {}).get("aesthetic_beauty") or 0.0) for scene in ordered]
    credibility_scores = [float(scene.get("scores", {}).get("credibility") or 0.0) for scene in ordered]
    lighting_scenes = [scene for scene in ordered if any(keyword in _scene_desc(scene) for keyword in lighting_keywords)]
    life_scenes = [scene for scene in ordered if any(keyword in _scene_desc(scene) for keyword in life_keywords)]
    consistency = 1.0 - (max(aesthetic_scores) - min(aesthetic_scores)) / 10.0 if aesthetic_scores else 0.0
    avg_aesthetic = _avg(aesthetic_scores)
    avg_credibility = _avg(credibility_scores)
    balance = abs(avg_aesthetic - avg_credibility)
    lighting_numbers = {int(scene.get("scene_number", 0)) for scene in lighting_scenes}
    life_numbers = {int(scene.get("scene_number", 0)) for scene in life_scenes}
    crest_numbers = {int(scene.get("scene_number", 0)) for scene in _atmospheric_groups(data)["crest"]}

    context.update(
        {
            "atmosphere_consistency": f"{consistency * 10:.1f}",
            "lighting_scene_count": str(len(lighting_scenes)),
            "lighting_scene_refs": _scene_refs(lighting_scenes[:4], 4) if lighting_scenes else "未检测到稳定光影场景",
            "life_scene_count": str(len(life_scenes)),
            "life_scene_refs": _scene_refs(life_scenes[:4], 4) if life_scenes else "未检测到稳定生活场景",
            "aesthetic_credibility_gap": f"{balance:.1f}",
            "scenes_by_dimension": _format_scenes_by_dimension(
                ordered,
                {
                    "氛围相关": lambda scene: int(scene.get("scene_number", 0)) in lighting_numbers,
                    "真实感相关": lambda scene: int(scene.get("scene_number", 0)) in life_numbers,
                    "情绪高点": lambda scene: int(scene.get("scene_number", 0)) in crest_numbers,
                },
                limit_per_group=5,
            ),
        }
    )


def _build_commentary_mix_context(context: Dict[str, str], data: Dict, ordered: Sequence[Dict]) -> None:
    voiceover_scenes = [scene for scene in ordered if _voiceover(scene)]
    argument_keywords = ["因为", "所以", "但是", "然而", "原因", "结果", "问题", "证明"]
    visual_info_keywords = ["画面", "镜头", "场景", "看到", "展示"]
    argument_scenes = [scene for scene in voiceover_scenes if any(keyword in _voiceover(scene) for keyword in argument_keywords)]
    conflict_scenes = [scene for scene in voiceover_scenes if any(keyword in _voiceover(scene) for keyword in visual_info_keywords)]
    evidence_scenes = [scene for scene in ordered if "证据" in _voiceover(scene) or "对照" in _scene_desc(scene) or "问题" in _voiceover(scene)]
    total_duration = sum(float(scene.get("duration_seconds") or 0.0) for scene in ordered)
    argument_duration = sum(float(scene.get("duration_seconds") or 0.0) for scene in argument_scenes)
    argument_density = len(argument_scenes) / (total_duration / 60) if total_duration > 0 else 0.0
    opening = list(ordered[: max(1, min(2, len(ordered)))])
    closing = list(ordered[-max(1, min(2, len(ordered))):])
    voiceover_numbers = {int(scene.get("scene_number", 0)) for scene in argument_scenes}
    evidence_numbers = {int(scene.get("scene_number", 0)) for scene in (evidence_scenes or argument_scenes)}
    conflict_numbers = {int(scene.get("scene_number", 0)) for scene in conflict_scenes}

    context.update(
        {
            "opening_scene_refs": _scene_refs(opening, 4),
            "closing_scene_refs": _scene_refs(closing, 4),
            "argument_scene_count": str(len(argument_scenes)),
            "argument_density": f"{argument_density:.1f}",
            "argument_duration_ratio": _fmt_pct(int(round(argument_duration * 10)), int(round(total_duration * 10))) if total_duration > 0 else "0",
            "argument_scene_refs": _scene_refs(argument_scenes[:5], 5) if argument_scenes else "未检测到稳定论点场景",
            "evidence_scene_refs": _scene_refs((evidence_scenes or argument_scenes)[:5], 5) if (evidence_scenes or argument_scenes) else "未检测到稳定证据场景",
            "conflict_scene_count": str(len(conflict_scenes)),
            "conflict_scene_refs": _scene_refs(conflict_scenes[:4], 4) if conflict_scenes else "未检测到明显信息冲突场景",
            "voiceover_scene_refs": _scene_refs(voiceover_scenes[:5], 5) if voiceover_scenes else "未检测到稳定语言场景",
            "key_voiceover_samples": " / ".join(_voiceover(scene)[:30] for scene in voiceover_scenes[:2] if _voiceover(scene)) or "暂无可靠语言样本",
            "scenes_by_dimension": _format_scenes_by_dimension(
                ordered,
                {
                    "论点相关": lambda scene: int(scene.get("scene_number", 0)) in voiceover_numbers,
                    "证据相关": lambda scene: int(scene.get("scene_number", 0)) in evidence_numbers,
                    "信息冲突相关": lambda scene: int(scene.get("scene_number", 0)) in conflict_numbers,
                },
                limit_per_group=5,
            ),
        }
    )


def _build_atmospheric_family_context(context: Dict[str, str], data: Dict, ordered: Sequence[Dict]) -> None:
    groups = _atmospheric_groups(data)
    route = data.get("audiovisual_route") or {}
    style_keywords = [_safe_text(scene.get("storyboard", {}).get("visual_style")) for scene in ordered if _safe_text(scene.get("storyboard", {}).get("visual_style"))]
    style_diversity = len(set(style_keywords)) / len(style_keywords) if style_keywords else 1.0
    emotional_curve = [float(scene.get("analysis_dimensions", {}).get("emotional_effect") or 0.0) for scene in ordered]
    peak_scenes = [ordered[index] for index, score in enumerate(emotional_curve) if score >= 7.0]
    route_metric_note = {
        "hybrid_music": _atmospheric_summary(data, route),
        "hybrid_ambient": _hybrid_ambient_layering_analysis(data),
        "pure_visual_mix": _pure_visual_mix_rhythm_analysis(data),
        "silent_reality": _silent_reality_pacing_analysis(data),
        "silent_performance": _silent_performance_body_analysis(data),
        "narrative_mix": _narrative_mix_story_reframing(data),
    }.get(_safe_text(route.get("framework")), _atmospheric_summary(data, route))
    route_support_note = {
        "hybrid_music": "重点看多种风格切换之后，是不是还在推同一股情绪。",
        "hybrid_ambient": _hybrid_ambient_viewing_advice(data),
        "pure_visual_mix": _pure_visual_mix_viewing_advice(data),
        "silent_reality": _silent_reality_viewing_advice(data),
        "silent_performance": _silent_performance_viewing_advice(data),
        "narrative_mix": _narrative_mix_integrity(data),
    }.get(_safe_text(route.get("framework")), "重点看它是不是一直守住同一股感觉，而不是段段都有味道但整条不成气候。")
    route_risk_note = {
        "hybrid_music": _hybrid_music_failure_risk(data),
        "hybrid_ambient": _hybrid_ambient_failure_risk(data),
        "pure_visual_mix": _pure_visual_mix_failure_risk(data),
        "silent_reality": _silent_reality_failure_risk(data),
        "silent_performance": _silent_performance_failure_risk(data),
        "narrative_mix": _narrative_mix_failure_risk(data),
    }.get(_safe_text(route.get("framework")), "最大的风险通常不是画面不好，而是氛围或节奏没有在后段继续往前推。")
    context.update(
        {
            "route_template_focus": {
                "hybrid_music": "多风格混合后，情绪方向还能不能保持统一。",
                "hybrid_ambient": "不同材质的画面和声音，最后有没有收成同一股气压。",
                "pure_visual_mix": "没有语言和强听觉托底时，画面本身还能不能持续加压。",
                "silent_reality": "没有台词时，观察顺序和空间变化还能不能把人带进去。",
                "silent_performance": "身体和表情能不能独立承担情绪推进，不靠对白补救。",
                "narrative_mix": "素材重排以后，有没有真正生成新的故事理解，而不只是重新拼接。",
            }.get(_safe_text(route.get("framework")), "它有没有把意象、节奏和情绪真正收成一条线。"),
            "style_consistency": f"{(1 - style_diversity) * 10:.1f}",
            "atmosphere_opening_refs": _scene_refs(groups["opening"], 4),
            "motif_scene_refs": _scene_refs(groups["motif"], 4),
            "rhythm_scene_refs": _scene_refs(groups["rhythm"], 4),
            "crest_scene_refs": _scene_refs(groups["crest"], 4),
            "closing_scene_refs": _scene_refs(groups["closing"], 4),
            "emotion_variance": f"{(max(emotional_curve) - min(emotional_curve)):.1f}" if emotional_curve else "0.0",
            "emotion_peak_count": str(len(peak_scenes)),
            "emotion_peak_scene_refs": _scene_refs(peak_scenes[:4], 4) if peak_scenes else "未检测到明显峰值",
            "route_metric_note": route_metric_note,
            "route_support_note": route_support_note,
            "route_risk_note": route_risk_note,
            "scenes_by_dimension": _format_scenes_by_dimension(
                ordered,
                {
                    "气氛开场": lambda scene: int(scene.get("scene_number", 0)) in {int(item.get("scene_number", 0)) for item in groups["opening"]},
                    "意象锚点": lambda scene: int(scene.get("scene_number", 0)) in {int(item.get("scene_number", 0)) for item in groups["motif"]},
                    "节奏抬升": lambda scene: int(scene.get("scene_number", 0)) in {int(item.get("scene_number", 0)) for item in groups["crest"]},
                    "尾声收束": lambda scene: int(scene.get("scene_number", 0)) in {int(item.get("scene_number", 0)) for item in groups["closing"]},
                },
                limit_per_group=5,
            ),
        }
    )
    # Per-route extensions for dedicated templates
    framework = _safe_text(route.get("framework"))
    high_score_scenes = [s for s in ordered if float(s.get("weighted_score") or 0.0) >= 7.0]

    if framework == "hybrid_music":
        context["visual_style_list"] = "、".join(set(style_keywords)) if style_keywords else "多种风格混合"
        context["high_score_scene_refs"] = _scene_refs(high_score_scenes[:5], 5)

    elif framework == "hybrid_ambient":
        high_aesthetic = [s for s in ordered if float(s.get("scores", {}).get("aesthetic_beauty") or 0.0) >= 7.0]
        context["high_aesthetic_scene_refs"] = _scene_refs(high_aesthetic[:5], 5)
        context["high_score_scene_refs"] = _scene_refs(high_score_scenes[:5], 5)

    elif framework == "pure_visual_mix":
        durations = [float(s.get("duration_seconds") or 0.0) for s in ordered if float(s.get("duration_seconds") or 0.0) > 0]
        context["avg_duration"] = f"{_avg(durations):.1f}" if durations else "0.0"
        high_impact = [s for s in ordered if float(s.get("scores", {}).get("impact") or 0.0) >= 7.0]
        context["high_impact_scene_refs"] = _scene_refs(high_impact[:5], 5)
        shot_sizes = [_safe_text(s.get("storyboard", {}).get("shot_size")) for s in ordered if _safe_text(s.get("storyboard", {}).get("shot_size"))]
        size_counts: Dict[str, int] = {}
        for sz in shot_sizes:
            size_counts[sz] = size_counts.get(sz, 0) + 1
        context["shot_size_distribution"] = "、".join(f"{k} {v}" for k, v in sorted(size_counts.items(), key=lambda x: -x[1])) if size_counts else "未知"
        context["high_score_scene_refs"] = _scene_refs(high_score_scenes[:5], 5)

    elif framework == "silent_reality":
        durations = [float(s.get("duration_seconds") or 0.0) for s in ordered if float(s.get("duration_seconds") or 0.0) > 0]
        context["avg_duration"] = f"{_avg(durations):.1f}" if durations else "0.0"
        moving = [s for s in ordered if _safe_text(s.get("storyboard", {}).get("camera_movement")) not in ("", "固定", "静止")]
        static = [s for s in ordered if _safe_text(s.get("storyboard", {}).get("camera_movement")) in ("", "固定", "静止")]
        context["moving_ratio"] = _fmt_pct(len(moving), len(ordered))
        context["moving_scene_refs"] = _scene_refs(moving[:4], 4) if moving else "未检测到运动镜头"
        context["static_ratio"] = _fmt_pct(len(static), len(ordered))
        spatial_keywords = ("全景", "远景", "环境", "空间", "建筑", "场景", "室内", "室外")
        spatial_scenes = [s for s in ordered if any(k in _scene_desc(s) or k in _safe_text(s.get("storyboard", {}).get("shot_size")) for k in spatial_keywords)]
        context["spatial_scene_refs"] = _scene_refs(spatial_scenes[:4], 4) if spatial_scenes else "未检测到空间建立场景"

    elif framework == "silent_performance":
        high_impact = [s for s in ordered if float(s.get("scores", {}).get("impact") or 0.0) >= 7.0]
        context["high_impact_scene_refs"] = _scene_refs(high_impact[:5], 5)
        action_keywords = ("动作", "转身", "跳跃", "奔跑", "打斗", "舞蹈", "旋转")
        high_action = [s for s in ordered if any(k in _scene_desc(s) for k in action_keywords) or float(s.get("scores", {}).get("impact") or 0.0) >= 7.5]
        context["high_action_scene_refs"] = _scene_refs(high_action[:5], 5)
        context["scene_desc_samples"] = "；".join(_scene_desc(s)[:40] for s in ordered[:4]) if ordered else "暂无场景描述"


def _build_meme_family_context(context: Dict[str, str], data: Dict, ordered: Sequence[Dict]) -> None:
    route = data.get("audiovisual_route") or {}
    fun_scores = [float(scene.get("scores", {}).get("fun_interest") or 0.0) for scene in ordered]
    high_fun = [scene for scene in ordered if float(scene.get("scores", {}).get("fun_interest") or 0.0) >= 7.0]
    contrast_scenes = [scene for scene in ordered if float(scene.get("scores", {}).get("fun_interest") or 0.0) >= 7.0 and float(scene.get("scores", {}).get("credibility") or 0.0) <= 4.5]
    voiceover_scenes = [scene for scene in ordered if _voiceover(scene)]
    sync_ratio = (
        len([scene for scene in voiceover_scenes if float(scene.get("scores", {}).get("fun_interest") or 0.0) >= 7.0]) / len(voiceover_scenes)
        if voiceover_scenes
        else 0.0
    )
    total_duration = sum(float(scene.get("duration_seconds") or 0.0) for scene in ordered)
    fun_density = len(high_fun) / (total_duration / 60) if total_duration > 0 else 0.0
    route_metric_note = {
        "meme": _meme_density_analysis(data),
        "hybrid_meme": _hybrid_meme_mix_analysis(data),
        "reality_sfx": _reality_sfx_distortion_analysis(data),
        "abstract_sfx": _abstract_sfx_sync_analysis(data),
    }.get(_safe_text(route.get("framework")), _meme_density_analysis(data))
    route_support_note = {
        "meme": _meme_timing_analysis(data),
        "hybrid_meme": _hybrid_meme_viewing_advice(data),
        "reality_sfx": _reality_sfx_viewing_advice(data),
        "abstract_sfx": "重点看声音变化和图形变化是不是在同一拍落下来，而不是谁都很响但彼此不搭。",
    }.get(_safe_text(route.get("framework")), _meme_timing_analysis(data))
    route_risk_note = {
        "meme": _meme_failure_points(data),
        "hybrid_meme": _hybrid_meme_failure_risk(data),
        "reality_sfx": _reality_sfx_failure_risk(data),
        "abstract_sfx": _abstract_sfx_failure_risk(data),
    }.get(_safe_text(route.get("framework")), _meme_failure_points(data))
    context.update(
        {
            "route_template_focus": {
                "meme": "笑点是不是在高密度、强反差和好时机里一起成立。",
                "hybrid_meme": "多种梗法叠在一起时，是互相加码，还是互相抢戏。",
                "reality_sfx": "现实动作和夸张音效之间，有没有形成真正的重新解释。",
                "abstract_sfx": "声音和抽象视觉之间，是不是反复遵守同一套变化规则。",
            }.get(_safe_text(route.get("framework")), "反差和节奏是不是一起把观众反应顶起来。"),
            "meme_peak_refs": _scene_refs(high_fun[:5], 5) if high_fun else "未检测到稳定高趣味场景",
            "contrast_scene_refs": _scene_refs(contrast_scenes[:4], 4) if contrast_scenes else "未检测到明显反差场景",
            "fun_density": f"{fun_density:.1f}",
            "sync_ratio": f"{sync_ratio * 100:.0f}",
            "subculture_signal_summary": _meme_subculture_markers(data),
            "route_metric_note": route_metric_note,
            "route_support_note": route_support_note,
            "route_risk_note": route_risk_note,
            "scenes_by_dimension": _format_scenes_by_dimension(
                ordered,
                {
                    "高密度笑点": lambda scene: int(scene.get("scene_number", 0)) in {int(item.get("scene_number", 0)) for item in high_fun},
                    "反差场景": lambda scene: int(scene.get("scene_number", 0)) in {int(item.get("scene_number", 0)) for item in contrast_scenes},
                    "高冲击段落": lambda scene: float(scene.get("scores", {}).get("impact") or 0.0) >= 7.5,
                },
                limit_per_group=5,
            ),
        }
    )


def _build_language_led_family_context(context: Dict[str, str], data: Dict, ordered: Sequence[Dict]) -> None:
    route = data.get("audiovisual_route") or {}
    framework = _safe_text(route.get("framework"))
    if framework == "technical_explainer":
        groups = _technical_explainer_groups(data)
        issue = groups["question"]
        overview = groups["overview"]
        detail = groups["detail"]
        proof = groups["step"]
        recap = groups["recap"]
    elif framework == "lecture_performance":
        groups = _lecture_performance_groups(data)
        issue = groups["opening"]
        overview = groups["story"]
        detail = groups["performance"]
        proof = groups["interaction"]
        recap = groups["closing"]
    else:
        groups = _language_led_groups(data)
        issue = groups["issue"]
        overview = groups["overview"]
        detail = groups["detail"]
        proof = groups["proof"]
        recap = groups["recap"]

    route_metric_note = {
        "technical_explainer": _technical_explainer_story_summary(data),
        "documentary_generic": _documentary_information_completeness(data),
        "hybrid_commentary": _hybrid_commentary_mix_value(data),
        "lecture_performance": _lecture_performance_stage_analysis(data),
    }.get(framework, _language_led_summary(data, route))
    route_support_note = {
        "technical_explainer": "重点看问题、整体、细节和回看四段是不是把一件复杂事情真正讲顺了。",
        "documentary_generic": _documentary_credibility_assessment(data),
        "hybrid_commentary": _hybrid_commentary_viewing_advice(data),
        "lecture_performance": "重点看讲述、表演和互动是不是都在托同一条主线，而不是各做各的。",
    }.get(framework, "重点看语言是不是一直在往前送信息，而不是说一段、散一段。")
    route_risk_note = {
        "technical_explainer": _alignment_summary(data)["summary"],
        "documentary_generic": "纪实类最容易失效的地方，是信息要素不全或者现场感不够，导致观众无法真正相信内容。",
        "hybrid_commentary": _hybrid_commentary_failure_risk(data),
        "lecture_performance": _lecture_performance_failure_risk(data),
    }.get(framework, "最容易掉线的地方，通常是信息多了，但先后顺序和主次关系没有讲清。")
    context.update(
        {
            "route_template_focus": {
                "technical_explainer": "复杂内容有没有被拆成一条能跟懂的解释线。",
                "documentary_generic": "事实、现场感和可信度有没有一起站住。",
                "hybrid_commentary": "多种素材来源，最后有没有一起托住同一条判断。",
                "lecture_performance": "讲述和表演有没有一起把内容往更强的感染力上抬。",
            }.get(framework, "语言是不是一直在把一件事讲得更清楚。"),
            "issue_scene_refs": _scene_refs(issue, 4),
            "overview_scene_refs": _scene_refs(overview, 4),
            "detail_scene_refs": _scene_refs(detail, 4),
            "proof_scene_refs": _scene_refs(proof, 4),
            "recap_scene_refs": _scene_refs(recap, 4),
            "route_metric_note": route_metric_note,
            "route_support_note": route_support_note,
            "route_risk_note": route_risk_note,
            "scenes_by_dimension": _format_scenes_by_dimension(
                ordered,
                {
                    "问题抛出": lambda scene: int(scene.get("scene_number", 0)) in {int(item.get("scene_number", 0)) for item in issue},
                    "整体框架": lambda scene: int(scene.get("scene_number", 0)) in {int(item.get("scene_number", 0)) for item in overview},
                    "关键细节": lambda scene: int(scene.get("scene_number", 0)) in {int(item.get("scene_number", 0)) for item in detail},
                    "收束回看": lambda scene: int(scene.get("scene_number", 0)) in {int(item.get("scene_number", 0)) for item in recap},
                },
                limit_per_group=5,
            ),
        }
    )
    # Per-route extensions for dedicated templates
    voiceover_scenes_ll = [s for s in ordered if _voiceover(s)]

    if framework == "technical_explainer":
        tgroups = _technical_explainer_groups(data)
        context.update({
            "question_scene_refs": _scene_refs(tgroups["question"], 4),
            "question_desc": _scene_phrase(tgroups["question"]),
            "overview_desc": _scene_phrase(tgroups["overview"]),
            "detail_desc": _scene_phrase(tgroups["detail"]),
            "step_scene_refs": _scene_refs(tgroups["step"], 4),
            "step_desc": _scene_phrase(tgroups["step"]),
            "recap_desc": _scene_phrase(tgroups["recap"]),
            "voiceover_scene_count": str(len(voiceover_scenes_ll)),
            "key_voiceover_samples": " / ".join(_voiceover(s)[:30] for s in voiceover_scenes_ll[:2] if _voiceover(s)) or "暂无可靠语言样本",
        })

    elif framework == "documentary_generic":
        credibility_scores = [float(s.get("scores", {}).get("credibility") or 0.0) for s in ordered]
        high_credibility = [s for s in ordered if float(s.get("scores", {}).get("credibility") or 0.0) >= 7.0]
        real_keywords = ("实拍", "现场", "采访", "记录", "真实", "跟踪", "监控", "手机", "素材")
        real_scenes = [s for s in ordered if any(k in _scene_desc(s) for k in real_keywords)]
        interview_keywords = ("采访", "访谈", "受访", "对话", "发言", "讲述")
        interview_scenes = [s for s in ordered if any(k in _scene_desc(s) or k in _voiceover(s) for k in interview_keywords)]
        evidence_scenes = high_credibility or real_scenes or ordered[:2]
        opening = list(ordered[: max(1, min(2, len(ordered)))])
        closing = list(ordered[-max(1, min(2, len(ordered))):])
        w5h1 = _assess_w5h1_coverage(ordered, voiceover_scenes_ll)
        context.update({
            "w5h1_covered_count": str(w5h1["covered_count"]),
            "w5h1_covered_items": w5h1["covered_items"],
            "w5h1_missing_items": w5h1["missing_items"],
            "key_voiceover_samples": " / ".join(_voiceover(s)[:30] for s in voiceover_scenes_ll[:2] if _voiceover(s)) or "暂无可靠语言样本",
            "opening_scene_refs": _scene_refs(opening, 4),
            "closing_scene_refs": _scene_refs(closing, 4),
            "voiceover_scene_refs": _scene_refs(voiceover_scenes_ll[:5], 5) if voiceover_scenes_ll else "未检测到稳定语言场景",
            "interview_scene_refs": _scene_refs(interview_scenes[:5], 5) if interview_scenes else "未检测到明显访谈场景",
            "evidence_scene_refs": _scene_refs(evidence_scenes[:5], 5),
            "high_credibility_scene_count": str(len(high_credibility)),
            "high_credibility_scene_refs": _scene_refs(high_credibility[:5], 5),
            "real_scene_count": str(len(real_scenes)),
            "real_scene_refs": _scene_refs(real_scenes[:5], 5) if real_scenes else "未检测到现场感场景",
        })

    elif framework == "hybrid_commentary":
        high_score_scenes_hc = [s for s in ordered if float(s.get("weighted_score") or 0.0) >= 7.0]
        argument_scenes = [s for s in voiceover_scenes_ll if any(k in _voiceover(s) for k in ("因为", "所以", "但是", "然而", "原因", "结果", "问题", "证明"))]
        total_duration = sum(float(s.get("duration_seconds") or 0.0) for s in ordered)
        argument_density = len(argument_scenes) / (total_duration / 60) if total_duration > 0 else 0.0
        voiceover_dense = sorted(voiceover_scenes_ll, key=lambda s: len(_voiceover(s)), reverse=True)
        context.update({
            "high_score_scene_refs": _scene_refs(high_score_scenes_hc[:5], 5),
            "voiceover_dense_scene_refs": _scene_refs(voiceover_dense[:5], 5) if voiceover_dense else "未检测到语言密场景",
            "key_voiceover_samples": " / ".join(_voiceover(s)[:30] for s in voiceover_scenes_ll[:2] if _voiceover(s)) or "暂无可靠语言样本",
            "argument_density": f"{argument_density:.1f}",
            "argument_scene_refs": _scene_refs(argument_scenes[:5], 5) if argument_scenes else "未检测到论点场景",
            "source_switch_count": str(_count_source_switches(ordered)),
        })

    elif framework == "lecture_performance":
        lgroups = _lecture_performance_groups(data)
        context.update({
            "opening_scene_refs": _scene_refs(lgroups["opening"], 4),
            "opening_desc": _scene_phrase(lgroups["opening"]),
            "story_scene_refs": _scene_refs(lgroups["story"], 4),
            "story_desc": _scene_phrase(lgroups["story"]),
            "performance_scene_refs": _scene_refs(lgroups["performance"], 4),
            "performance_desc": _scene_phrase(lgroups["performance"]),
            "interaction_scene_refs": _scene_refs(lgroups["interaction"], 4),
            "interaction_desc": _scene_phrase(lgroups["interaction"]),
            "closing_scene_refs": _scene_refs(lgroups["closing"], 4),
            "closing_desc": _scene_phrase(lgroups["closing"]),
            "story_scene_count": str(len(lgroups["story"])),
            "performance_scene_count": str(len(lgroups["performance"])),
            "interaction_scene_count": str(len(lgroups["interaction"])),
            "key_voiceover_samples": " / ".join(_voiceover(s)[:30] for s in voiceover_scenes_ll[:2] if _voiceover(s)) or "暂无可靠语言样本",
        })


def _build_graphic_family_context(context: Dict[str, str], data: Dict, ordered: Sequence[Dict]) -> None:
    route = data.get("audiovisual_route") or {}
    framework = _safe_text(route.get("framework"))
    groups = _language_led_groups(data)
    route_metric_note = {
        "infographic_animation": _infographic_clarity_analysis(data),
        "narrative_motion_graphics": _narrative_motion_graphics_story_role(data),
        "pure_motion_graphics": _motion_graphics_flow_analysis(data),
    }.get(framework, _graphic_summary(data, route))
    route_support_note = {
        "infographic_animation": _infographic_hierarchy_analysis(data),
        "narrative_motion_graphics": _narrative_motion_graphics_integrity(data),
        "pure_motion_graphics": "重点看纯视觉的转场、层级和运动方向是不是一直在带路。",
    }.get(framework, "重点看注意力是不是一直被往前送，而不是每段都像重新开始。")
    route_risk_note = {
        "infographic_animation": _infographic_failure_risk(data),
        "narrative_motion_graphics": _narrative_motion_graphics_failure_risk(data),
        "pure_motion_graphics": _motion_graphics_failure_risk(data),
    }.get(framework, "这类内容最容易失效在结构不清，观众不知道先看什么。")
    context.update(
        {
            "route_template_focus": {
                "infographic_animation": "信息是不是被层级、位置和动效真的讲清楚了。",
                "narrative_motion_graphics": "图形是不是已经不只是装饰，而是在帮故事推进关系。",
                "pure_motion_graphics": "纯视觉的运动和转场，能不能独立撑住观看连续性。",
            }.get(framework, "结构和动效是不是一起把观众往前带。"),
            "structure_scene_refs": _scene_refs(groups["overview"], 4),
            "detail_scene_refs": _scene_refs(groups["detail"], 4),
            "recap_scene_refs": _scene_refs(groups["recap"], 4),
            "route_metric_note": route_metric_note,
            "route_support_note": route_support_note,
            "route_risk_note": route_risk_note,
            "scenes_by_dimension": _format_scenes_by_dimension(
                ordered,
                {
                    "结构建立": lambda scene: int(scene.get("scene_number", 0)) in {int(item.get("scene_number", 0)) for item in groups["overview"]},
                    "细节推进": lambda scene: int(scene.get("scene_number", 0)) in {int(item.get("scene_number", 0)) for item in groups["detail"]},
                    "总结回看": lambda scene: int(scene.get("scene_number", 0)) in {int(item.get("scene_number", 0)) for item in groups["recap"]},
                },
                limit_per_group=5,
            ),
        }
    )
    # Per-route extension for infographic_animation
    if framework == "infographic_animation":
        high_info = [s for s in ordered if float(s.get("analysis_dimensions", {}).get("information_efficiency") or 0.0) >= 7.0]
        context["high_info_scene_refs"] = _scene_refs(high_info[:5], 5) if high_info else "未检测到高信息效率场景"
        context["hierarchy_scene_refs"] = _scene_refs(groups["overview"], 4)


def _generic_phase_groups(ordered: Sequence[Dict]) -> Dict[str, Sequence[Dict]]:
    total = len(ordered)
    opening = list(ordered[:max(1, int(total * 0.2))])
    middle = list(ordered[max(1, int(total * 0.2)):max(2, int(total * 0.7))])
    peak = list(sorted(ordered, key=lambda scene: float(scene.get("weighted_score") or 0.0), reverse=True)[: max(1, min(4, total))])
    closing = list(ordered[max(1, int(total * 0.75)):]) or list(ordered[-1:])
    return {"opening": opening or list(ordered[:1]), "middle": middle or list(ordered[:1]), "peak": peak or list(ordered[:1]), "closing": closing or list(ordered[-1:])}


def _build_narrative_family_context(context: Dict[str, str], data: Dict, ordered: Sequence[Dict]) -> None:
    route = data.get("audiovisual_route") or {}
    framework = _safe_text(route.get("framework"))
    if framework == "narrative_trailer":
        groups = _trailer_groups(data)
        opening = groups["opening"]
        middle = groups["investigation"] or groups["escalation"]
        peak = groups["payoff"] or groups["peaks"]
        closing = groups["cards"] or groups["payoff"]
    elif framework == "event_brand_ad":
        groups = _event_brand_groups(data)
        opening = groups["opening"]
        middle = groups["crowd"] or groups["human"]
        peak = groups["spectacle"] or groups["product"]
        closing = groups["closing"] or groups["product"]
    elif framework == "journey_brand_film":
        groups = _journey_brand_groups(data)
        opening = groups["opening"] or groups["clue"]
        middle = groups["arrival"] or groups["portrait"]
        peak = groups["poetic"] or groups["portrait"]
        closing = groups["brand_tail"] or groups["poetic"]
    else:
        generic = _generic_phase_groups(ordered)
        opening = generic["opening"]
        middle = generic["middle"]
        peak = generic["peak"]
        closing = generic["closing"]

    route_metric_note = {
        "narrative_trailer": _trailer_story_summary(data),
        "event_brand_ad": _event_brand_story_summary(data),
        "journey_brand_film": _journey_brand_story_summary(data),
        "hybrid_narrative": _hybrid_narrative_layering_analysis(data),
        "narrative_mix": _narrative_mix_story_reframing(data),
    }.get(framework, _main_summary(data, route))
    route_support_note = {
        "narrative_trailer": _trailer_sell_paragraph(data),
        "event_brand_ad": "重点看群体热闹和品牌落点是不是接到同一股情绪上。",
        "journey_brand_film": "重点看地点、人物和品牌气质是不是慢慢长成同一种味道。",
        "hybrid_narrative": "重点看不同手法是不是都在推同一条主线，而不是各自表演。",
        "narrative_mix": _narrative_mix_integrity(data),
    }.get(framework, "重点看开场、中段、高点和收束是不是一条能跟下去的线。")
    route_risk_note = {
        "narrative_trailer": _alignment_summary(data)["summary"],
        "event_brand_ad": _alignment_summary(data)["summary"],
        "journey_brand_film": _alignment_summary(data)["summary"],
        "hybrid_narrative": _hybrid_narrative_failure_risk(data),
        "narrative_mix": _narrative_mix_failure_risk(data),
    }.get(framework, "最容易失效的地方，通常不是没有高点，而是段落之间没有真正接成一条线。")
    context.update(
        {
            "route_template_focus": {
                "narrative_trailer": "它有没有把前提、危险感和最后一击排成越来越想看的线。",
                "event_brand_ad": "热闹、人的温度和品牌落点有没有一起站住。",
                "journey_brand_film": "人物、地点和品牌气质有没有慢慢长成同一种味道。",
                "hybrid_narrative": "多手法混合之后，主叙事有没有更清楚，而不是更散。",
                "narrative_mix": "重排后的素材，最终有没有生成一条新的故事理解。",
            }.get(framework, "叙事推进有没有从开场一路带到收束。"),
            "opening_scene_refs": _scene_refs(opening, 4),
            "middle_scene_refs": _scene_refs(middle, 4),
            "peak_scene_refs": _scene_refs(peak, 4),
            "closing_scene_refs": _scene_refs(closing, 4),
            "route_metric_note": route_metric_note,
            "route_support_note": route_support_note,
            "route_risk_note": route_risk_note,
            "scenes_by_dimension": _format_scenes_by_dimension(
                ordered,
                {
                    "开场建立": lambda scene: int(scene.get("scene_number", 0)) in {int(item.get("scene_number", 0)) for item in opening},
                    "中段推进": lambda scene: int(scene.get("scene_number", 0)) in {int(item.get("scene_number", 0)) for item in middle},
                    "高点抬升": lambda scene: int(scene.get("scene_number", 0)) in {int(item.get("scene_number", 0)) for item in peak},
                    "尾声收束": lambda scene: int(scene.get("scene_number", 0)) in {int(item.get("scene_number", 0)) for item in closing},
                },
                limit_per_group=5,
            ),
        }
    )
    # Per-route extensions for dedicated templates
    emotional_curve = [float(s.get("analysis_dimensions", {}).get("emotional_effect") or 0.0) for s in ordered]
    peak_scenes = [ordered[i] for i, score in enumerate(emotional_curve) if score >= 7.0]
    high_impact_scenes = [s for s in ordered if float(s.get("scores", {}).get("impact") or 0.0) >= 7.0]
    emotion_variance_val = f"{(max(emotional_curve) - min(emotional_curve)):.1f}" if emotional_curve else "0.0"
    emotion_peak_refs = _scene_refs(peak_scenes[:4], 4) if peak_scenes else "未检测到明显峰值"

    if framework == "narrative_trailer":
        tgroups = _trailer_groups(data)
        context.update({
            "opening_desc": _scene_phrase(tgroups["opening"]),
            "setup_scene_refs": _scene_refs(tgroups["setup"], 4),
            "setup_desc": _scene_phrase(tgroups["setup"]),
            "investigation_scene_refs": _scene_refs(tgroups["investigation"], 4),
            "investigation_desc": _scene_phrase(tgroups["investigation"]),
            "escalation_scene_refs": _scene_refs(tgroups["escalation"], 4),
            "escalation_desc": _scene_phrase(tgroups["escalation"]),
            "payoff_scene_refs": _scene_refs(tgroups["payoff"], 4),
            "payoff_desc": _scene_phrase(tgroups["payoff"]),
            "cards_scene_refs": _scene_refs(tgroups["cards"], 3),
            "emotion_peak_scene_refs": emotion_peak_refs,
            "emotion_variance": emotion_variance_val,
            "max_impact_scene_ref": _scene_refs([max(ordered, key=lambda s: float(s.get("scores", {}).get("impact") or 0.0))], 1),
        })

    elif framework == "event_brand_ad":
        egroups = _event_brand_groups(data)
        context.update({
            "opening_desc": _scene_phrase(egroups["opening"]),
            "spectacle_scene_refs": _scene_refs(egroups["spectacle"], 4),
            "spectacle_desc": _scene_phrase(egroups["spectacle"]),
            "crowd_scene_refs": _scene_refs(egroups["crowd"], 4),
            "crowd_desc": _scene_phrase(egroups["crowd"]),
            "human_scene_refs": _scene_refs(egroups["human"], 4),
            "human_desc": _scene_phrase(egroups["human"]),
            "product_scene_refs": _scene_refs(egroups["product"], 4),
            "product_desc": _scene_phrase(egroups["product"]),
            "closing_desc": _scene_phrase(egroups["closing"] or egroups["product"]),
            "emotion_peak_scene_refs": emotion_peak_refs,
            "emotion_variance": emotion_variance_val,
            "high_impact_scene_refs": _scene_refs(high_impact_scenes[:5], 5),
        })

    elif framework == "journey_brand_film":
        jgroups = _journey_brand_groups(data)
        style_keywords_j = [_safe_text(s.get("storyboard", {}).get("visual_style")) for s in ordered if _safe_text(s.get("storyboard", {}).get("visual_style"))]
        style_diversity_j = len(set(style_keywords_j)) / len(style_keywords_j) if style_keywords_j else 1.0
        context.update({
            "clue_scene_refs": _scene_refs(jgroups["clue"], 4),
            "clue_desc": _scene_phrase(jgroups["clue"]),
            "arrival_scene_refs": _scene_refs(jgroups["arrival"], 4),
            "arrival_desc": _scene_phrase(jgroups["arrival"]),
            "portrait_scene_refs": _scene_refs(jgroups["portrait"], 4),
            "portrait_desc": _scene_phrase(jgroups["portrait"]),
            "poetic_scene_refs": _scene_refs(jgroups["poetic"], 4),
            "poetic_desc": _scene_phrase(jgroups["poetic"]),
            "brand_tail_scene_refs": _scene_refs(jgroups["brand_tail"], 4),
            "brand_tail_desc": _scene_phrase(jgroups["brand_tail"]),
            "emotion_peak_scene_refs": emotion_peak_refs,
            "emotion_variance": emotion_variance_val,
            "style_consistency": f"{(1 - style_diversity_j) * 10:.1f}",
        })

    elif framework == "narrative_mix":
        narrative_scores = [float(s.get("analysis_dimensions", {}).get("narrative_function") or 0.0) for s in ordered]
        high_narrative = [s for s in ordered if float(s.get("analysis_dimensions", {}).get("narrative_function") or 0.0) >= 7.0]
        voiceover_scenes = [s for s in ordered if _voiceover(s)]
        style_keywords_n = [_safe_text(s.get("storyboard", {}).get("visual_style")) for s in ordered if _safe_text(s.get("storyboard", {}).get("visual_style"))]
        style_diversity_n = len(set(style_keywords_n)) / len(style_keywords_n) if style_keywords_n else 1.0
        context.update({
            "narrative_avg": f"{_avg(narrative_scores):.1f}",
            "high_narrative_scene_refs": _scene_refs(high_narrative[:5], 5),
            "voiceover_scene_refs": _scene_refs(voiceover_scenes[:5], 5) if voiceover_scenes else "未检测到语言参与场景",
            "key_voiceover_samples": " / ".join(_voiceover(s)[:30] for s in voiceover_scenes[:2] if _voiceover(s)) or "暂无可靠语言样本",
            "emotion_peak_scene_refs": emotion_peak_refs,
            "emotion_variance": emotion_variance_val,
            "style_consistency": f"{(1 - style_diversity_n) * 10:.1f}",
        })


def _build_experimental_context(context: Dict[str, str], data: Dict, ordered: Sequence[Dict]) -> None:
    route = data.get("audiovisual_route") or {}
    groups = _generic_phase_groups(ordered)
    durations = [float(scene.get("duration_seconds") or 0.0) for scene in ordered if float(scene.get("duration_seconds") or 0.0) > 0]
    style_keywords = [_safe_text(scene.get("storyboard", {}).get("visual_style")) for scene in ordered if _safe_text(scene.get("storyboard", {}).get("visual_style"))]
    high_impact = [scene for scene in ordered if float(scene.get("scores", {}).get("impact") or 0.0) >= 7.0]
    opening_numbers = {int(scene.get("scene_number", 0)) for scene in groups["opening"]}
    middle_numbers = {int(scene.get("scene_number", 0)) for scene in groups["middle"]}
    peak_numbers = {int(scene.get("scene_number", 0)) for scene in groups["peak"]}
    closing_numbers = {int(scene.get("scene_number", 0)) for scene in groups["closing"]}

    context.update(
        {
            "route_template_focus": "它是不是一直用同一套形式规则在干预观众感知，而不只是不断换花样。",
            "opening_scene_refs": _scene_refs(groups["opening"], 4),
            "middle_scene_refs": _scene_refs(groups["middle"], 4),
            "peak_scene_refs": _scene_refs(groups["peak"], 4),
            "closing_scene_refs": _scene_refs(groups["closing"], 4),
            "avg_duration": f"{_avg(durations):.1f}",
            "style_summary": _top_text(style_keywords, 3) if style_keywords else "未知",
            "high_impact_scene_refs": _scene_refs(high_impact[:5], 5) if high_impact else "未检测到稳定高冲击场景",
            "route_metric_note": _experimental_route_diagnosis(data, route),
            "route_support_note": _experimental_focus_advice(data),
            "viewing_advice": _experimental_viewing_advice(data),
            "route_risk_note": "最大的风险不是看不懂，而是形式变化很多，却没有守住同一条感知干预逻辑。",
            "scenes_by_dimension": _format_scenes_by_dimension(
                ordered,
                {
                    "规则建立": lambda scene: int(scene.get("scene_number", 0)) in opening_numbers,
                    "过程展开": lambda scene: int(scene.get("scene_number", 0)) in middle_numbers,
                    "感知高压": lambda scene: int(scene.get("scene_number", 0)) in peak_numbers,
                    "边界收束": lambda scene: int(scene.get("scene_number", 0)) in closing_numbers,
                },
                limit_per_group=5,
            ),
        }
    )


def _build_content_synopsis_data(data: Dict, route: Dict[str, Any], scenes: Sequence[Dict]) -> str:
    """Build a compact content synopsis block from scene descriptions, voiceover, and on-screen text."""
    title = _title_text(data) or "未知标题"
    profile = route.get("content_profile") or data.get("content_profile") or {}
    profile_key = _safe_text(profile.get("key"), "generic")
    profile_label = _safe_text(profile.get("label"), "通用视频")
    profile_reason = _safe_text(profile.get("reason"), "")

    lines: List[str] = [
        f"**视频标题**: {title}",
        f"**内容画像**: {profile_label}（{profile_key}）" + (f" — {profile_reason}" if profile_reason else ""),
        "**场景内容摘要**:",
    ]

    # Cap at 15 representative scenes; if more, sample evenly
    scene_list = list(scenes)
    if len(scene_list) > 15:
        step = len(scene_list) / 15
        scene_list = [scene_list[int(i * step)] for i in range(15)]

    for scene in scene_list:
        num = int(scene.get("scene_number", 0))
        desc = _scene_desc(scene)[:80] or "—"
        vo = _voiceover(scene)
        ot = _onscreen_text(scene)
        parts = [f"Scene {num:03d}: {desc}"]
        if vo:
            parts.append(f"旁白: {vo[:50]}")
        if ot:
            parts.append(f"屏幕文字: {ot[:40]}")
        lines.append("- " + " | ".join(parts))

    return "\n".join(lines)


_ROUTE_CONTEXT_BUILDERS: Dict[str, Callable[[Dict[str, str], Dict, Sequence[Dict]], None]] = {
    "mix_music": _build_mix_music_context,
    "concept_mv": _build_concept_mv_context,
    "narrative_performance": _build_narrative_performance_context,
    "cinematic_life": _build_cinematic_life_context,
    "commentary_mix": _build_commentary_mix_context,
    "hybrid_music": _build_atmospheric_family_context,
    "hybrid_ambient": _build_atmospheric_family_context,
    "pure_visual_mix": _build_atmospheric_family_context,
    "silent_reality": _build_atmospheric_family_context,
    "silent_performance": _build_atmospheric_family_context,
    "narrative_mix": _build_narrative_family_context,
    "meme": _build_meme_family_context,
    "hybrid_meme": _build_meme_family_context,
    "reality_sfx": _build_meme_family_context,
    "abstract_sfx": _build_meme_family_context,
    "technical_explainer": _build_language_led_family_context,
    "documentary_generic": _build_language_led_family_context,
    "hybrid_commentary": _build_language_led_family_context,
    "lecture_performance": _build_language_led_family_context,
    "infographic_animation": _build_graphic_family_context,
    "narrative_motion_graphics": _build_graphic_family_context,
    "pure_motion_graphics": _build_graphic_family_context,
    "narrative_trailer": _build_narrative_family_context,
    "event_brand_ad": _build_narrative_family_context,
    "journey_brand_film": _build_narrative_family_context,
    "hybrid_narrative": _build_narrative_family_context,
    "experimental": _build_experimental_context,
}


def build_audiovisual_body_prompt(
    data: Dict,
    route: Dict[str, Any],
) -> Dict[str, Any]:
    """Return the system+user prompt plus required-section list for the report body."""
    context = build_template_context(data, route)
    template_text = load_route_template_for_data(data, route)
    template_sections = _split_template_sections(template_text)
    if _raw_prompt_adapter.raw_prompt_available_for_data(data, route):
        prompt_text = _raw_prompt_adapter.load_sanitized_raw_prompt_for_data(data, route)
        required_headings = _raw_prompt_adapter.extract_required_sections_from_raw_prompt(prompt_text)
        required_sections = [f"## {heading}" for heading in required_headings]
        validation_rules = _raw_prompt_adapter.extract_prompt_fidelity_rules(prompt_text)
        user_message = _raw_prompt_adapter.build_raw_prompt_user_message(
            data,
            route,
            context,
            required_headings,
            required_subsections=validation_rules.get("required_subsections") or {},
            min_chars_per_section=int(validation_rules.get("min_chars_per_section") or 700),
            min_subsection_chars=int(validation_rules.get("min_subsection_chars") or 180),
            min_scene_evidence_per_section=int(validation_rules.get("min_scene_evidence_per_section") or 3),
        )
        return {
            "system_prompt": prompt_text.strip(),
            "user_message": user_message,
            "required_sections": required_sections,
            "context": context,
            "python_direct": template_sections["python_direct"],
            "source": "raw_prompt",
            "validation_rules": validation_rules,
        }

    system_prompt = fill_template(template_sections["system"], context).strip()
    data_text = fill_template(template_sections["data"], context).strip()
    tasks_text = fill_template(_strip_python_direct_blocks(template_sections["tasks"]), context).strip()
    required_sections = _extract_required_sections(tasks_text)
    user_message = f"## 分析数据\n\n{data_text}\n\n## 写作任务\n\n{tasks_text}"
    return {
        "system_prompt": system_prompt,
        "user_message": user_message,
        "required_sections": required_sections,
        "context": context,
        "python_direct": template_sections["python_direct"],
        "source": "template",
        "validation_rules": {},
    }


def synthesize_audiovisual_report(
    data: Dict,
    route: Dict[str, Any],
    report_dir: Path | None = None,
    client: Any | None = None,
    runtime_config: Dict[str, Any] | None = None,
    request_fn: Callable[[str, str], str] | None = None,
) -> str:
    spec = build_audiovisual_body_prompt(data, route)
    if request_fn is None:
        def _default_request(system_prompt: str, user_message: str) -> str:
            return _request_agent_report(
                system_prompt,
                user_message,
                client=client,
                runtime_config=runtime_config,
            )
        request_fn = _default_request
    agent_text = request_fn(spec["system_prompt"], spec["user_message"])
    return _assemble_final_report(
        agent_text,
        spec["context"],
        spec["python_direct"],
        data,
        route,
        report_dir=report_dir,
        required_sections=spec["required_sections"],
        source=spec["source"],
        validation_rules=spec.get("validation_rules") or {},
    )


def _request_agent_report(
    system_prompt: str,
    user_message: str,
    client: Any | None = None,
    runtime_config: Dict[str, Any] | None = None,
) -> str:
    if client is None:
        if runtime_config is None:
            from ai_analyzer import resolve_auto_scoring_config

            runtime_config = resolve_auto_scoring_config()
        return request_text_with_runtime(
            system_prompt,
            user_message,
            runtime_config,
            max_output_tokens=int(os.environ.get("AUDIOVISUAL_REPORT_MAX_TOKENS", "4000")),
            temperature=0,
        )

    model = os.environ.get("AUDIOVISUAL_REPORT_MODEL", "claude-sonnet-4-5")
    message = client.messages.create(
        model=model,
        max_tokens=int(os.environ.get("AUDIOVISUAL_REPORT_MAX_TOKENS", "4000")),
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )
    return _message_text(message)


def _message_text(message: Any) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content

    parts: List[str] = []
    for item in content or []:
        text = getattr(item, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts).strip()


def _assemble_final_report(
    agent_text: str,
    context: Dict[str, str],
    python_direct_blocks: Sequence[Dict[str, str]],
    data: Dict,
    route: Dict[str, Any],
    report_dir: Path | None = None,
    required_sections: Sequence[str] | None = None,
    source: str = "template",
    validation_rules: Dict[str, Any] | None = None,
) -> str:
    body = agent_text.strip()
    try:
        body = _validate_required_sections(body, required_sections or (), source=source, validation_rules=validation_rules or {})
    except ValueError as exc:
        _dump_validation_errors(report_dir, body, required_sections or (), str(exc))
        raise
    body, dimension_evals = _extract_dimension_evaluations(body)
    context = {**context, **_dimension_eval_context(dimension_evals)}
    body = _inject_figure_blocks(body, data, route, report_dir)
    body = _inject_python_direct_blocks(body, python_direct_blocks, context)
    body = _cleanup_markers(body)

    final_parts = [
        "# 视听剖析报告",
        "",
        _route_judgement_block(route),
        "",
        body.strip(),
        "",
        f"*生成时间：{context['generated_at']}*",
    ]
    return "\n".join(part for part in final_parts if part is not None) + "\n"


def _inject_figure_blocks(body: str, data: Dict, route: Dict[str, Any], report_dir: Path | None) -> str:
    specs = _highlight_specs_for_route(data, route)
    markers = _FIGURE_RE.findall(body)
    if not markers:
        return body

    # Build a name-based lookup from specs
    spec_by_name: Dict[str, Any] = {}
    slot_names = ("opening", "evidence_peak", "motif_peak", "atmosphere_peak", "rhythm_peak",
                  "narrative_peak", "performance_peak", "spatial_peak", "question", "detail",
                  "recap", "setup", "escalation", "payoff", "conclusion", "spectacle",
                  "product", "closing", "arrival", "brand_tail", "source_quality")
    for i, spec in enumerate(specs):
        if i < len(slot_names):
            spec_by_name[slot_names[i]] = spec

    used_names: set[str] = set()
    used_blocks: set[str] = set()
    for idx, marker in enumerate(markers):
        token = f"<!-- FIGURE:{marker} -->"
        if marker in used_names and marker in spec_by_name:
            body = body.replace(token, "", 1)
            continue
        spec = spec_by_name.get(marker)
        if spec is None and idx < len(specs):
            spec = specs[idx]
        replacement = _render_figure_block(_with_marker_rationale(spec, marker), report_dir) if spec is not None else ""
        if not replacement or replacement in used_blocks:
            body = body.replace(token, "", 1)
            continue
        body = body.replace(token, replacement, 1)
        used_names.add(marker)
        used_blocks.add(replacement)
    return body


def _inject_python_direct_blocks(body: str, python_direct_blocks: Sequence[Dict[str, str]], context: Dict[str, str]) -> str:
    for block in python_direct_blocks:
        marker = f"<!-- PYTHON_DIRECT:{block['name']} -->"
        filled = fill_template(block["template"], context)
        if marker in body:
            body = body.replace(marker, filled)
        else:
            body = body.rstrip() + "\n\n" + filled
    return body


def _cleanup_markers(body: str) -> str:
    body = _FIGURE_RE.sub("", body)
    body = re.sub(r"<!--\s*PYTHON_DIRECT:\w+\s*-->", "", body)
    body = re.sub(r"\n{3,}", "\n\n", body)
    return body.strip()


def _extract_required_sections(tasks_text: str) -> List[str]:
    required: List[str] = []
    for match in _REQUIRED_SECTION_RE.finditer(tasks_text):
        heading = match.group(0).strip()
        if heading not in required:
            required.append(heading)
    return required


_SCENE_NUMBER_RE = re.compile(r"Scene\s+(\d{2,4})")


def _split_body_sections(text: str) -> Dict[str, str]:
    return {heading: info["body"] for heading, info in _split_body_sections_detailed(text).items()}


def _split_body_sections_detailed(text: str) -> Dict[str, Dict[str, Any]]:
    """Split body text by ## sections, and each section by ### subsections.

    Returns: {"## Heading": {"body": str, "subsections": {"### Sub": str, ...}}}
    """
    sections: Dict[str, Dict[str, Any]] = {}
    current_h2 = ""
    current_h3 = ""
    body_lines: Dict[str, List[str]] = {}
    sub_lines: Dict[str, Dict[str, List[str]]] = {}

    for line in text.splitlines():
        stripped = line.strip()
        is_h2 = stripped.startswith("## ") and not stripped.startswith("### ")
        is_h3 = stripped.startswith("### ") and not stripped.startswith("#### ")
        if is_h2:
            current_h2 = stripped
            current_h3 = ""
            body_lines.setdefault(current_h2, [])
            sub_lines.setdefault(current_h2, {})
            continue
        if not current_h2:
            continue
        body_lines[current_h2].append(line)
        if is_h3:
            current_h3 = stripped
            sub_lines[current_h2].setdefault(current_h3, [])
        elif current_h3:
            sub_lines[current_h2][current_h3].append(line)

    for heading, lines in body_lines.items():
        sections[heading] = {
            "body": "\n".join(lines).strip(),
            "subsections": {
                sub_heading: "\n".join(sub).strip()
                for sub_heading, sub in sub_lines.get(heading, {}).items()
            },
        }
    return sections


def _distinct_scene_numbers(text: str) -> set[str]:
    return {match.group(1).lstrip("0") or "0" for match in _SCENE_NUMBER_RE.finditer(text)}


_DIMENSION_LABELS: Sequence[tuple[str, str]] = (
    ("impact", "冲击力"),
    ("aesthetic", "美学"),
    ("memorability", "记忆度"),
    ("fun", "趣味性"),
    ("credibility", "可信度"),
    ("info_efficiency", "信息效率"),
)
_DIMENSION_FALLBACK_DESCRIPTIONS: Dict[str, str] = {
    "impact": "未给出本片冲击力评价。",
    "aesthetic": "未给出本片美学评价。",
    "memorability": "未给出本片记忆度评价。",
    "fun": "未给出本片趣味性评价。",
    "credibility": "未给出本片可信度评价。",
    "info_efficiency": "未给出本片信息效率评价。",
}
_DIMENSION_EVAL_HEADING = "## 维度速评"
_DIMENSION_EVAL_LINE_RE = re.compile(
    r"^\s*[-*+]\s*\**\s*(冲击力|美学|记忆度|趣味性|可信度|信息效率)\s*[**]*\s*[:：]\s*(.+?)\s*$"
)


def _extract_dimension_evaluations(body: str) -> tuple[str, Dict[str, str]]:
    """Pull the trailing `## 维度速评` block out of the agent body and parse its 6 lines.

    Returns (body_without_block, {english_key: chinese_eval}).
    Returns the original body unchanged when the block is missing or empty.
    """
    sections = _split_body_sections_detailed(body)
    section_info = sections.get(_DIMENSION_EVAL_HEADING)
    if not section_info:
        return body, {}

    label_to_key = {label: key for key, label in _DIMENSION_LABELS}
    parsed: Dict[str, str] = {}
    for line in section_info["body"].splitlines():
        match = _DIMENSION_EVAL_LINE_RE.match(line.strip())
        if not match:
            continue
        key = label_to_key.get(match.group(1))
        if key and key not in parsed:
            parsed[key] = match.group(2).strip()

    if not parsed:
        return body, {}

    new_lines: List[str] = []
    skipping = False
    for line in body.splitlines():
        stripped = line.strip()
        if stripped == _DIMENSION_EVAL_HEADING:
            skipping = True
            continue
        if skipping and stripped.startswith("## ") and stripped != _DIMENSION_EVAL_HEADING:
            skipping = False
        if skipping:
            continue
        new_lines.append(line)

    return "\n".join(new_lines).rstrip() + "\n", parsed


def _dimension_eval_context(dimension_evals: Dict[str, str]) -> Dict[str, str]:
    """Build {{eval_*}} placeholders for the scoring table; fall back to fixed descriptions."""
    return {
        f"eval_{key}": dimension_evals.get(key) or _DIMENSION_FALLBACK_DESCRIPTIONS[key]
        for key, _label in _DIMENSION_LABELS
    }


def _strip_formatting_for_count(text: str) -> str:
    text = re.sub(r"```[\s\S]*?```", " ", text)
    text = re.sub(r"<!--[\s\S]*?-->", " ", text)
    text = re.sub(r"[`*_>#\-|]", " ", text)
    return re.sub(r"\s+", "", text)


def _dump_validation_errors(
    report_dir: Path | None,
    body: str,
    required_sections: Sequence[str],
    message: str,
) -> None:
    if report_dir is None:
        return
    try:
        target_dir = Path(report_dir) / "audiovisual_handoff" / "body"
        target_dir.mkdir(parents=True, exist_ok=True)
        present = set(_split_body_sections_detailed(body).keys())
        missing = [section for section in required_sections if section not in present]
        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "error": message,
            "required_sections": list(required_sections),
            "missing_sections": missing,
            "present_sections": sorted(present),
        }
        (target_dir / "validation_errors.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except Exception:
        logging.getLogger(__name__).exception("failed to write validation_errors.json")


def _validate_required_sections(
    text: str,
    required_sections: Sequence[str],
    *,
    source: str = "template",
    validation_rules: Dict[str, Any] | None = None,
) -> str:
    if not required_sections:
        return text

    rules = validation_rules or {}
    section_map_detailed = _split_body_sections_detailed(text)
    present = set(section_map_detailed.keys())
    missing = [section for section in required_sections if section not in present]
    if missing:
        raise ValueError(f"Missing required sections: {', '.join(missing)}")

    if source != "raw_prompt":
        return text

    section_map = {heading: info["body"] for heading, info in section_map_detailed.items()}

    required_subsections_by_module: Dict[str, List[str]] = rules.get("required_subsections") or {}
    subsection_failures: List[str] = []
    for section in required_sections:
        module_name = section.removeprefix("## ").strip()
        expected = required_subsections_by_module.get(module_name) or []
        if not expected:
            continue
        present_subs = set(section_map_detailed.get(section, {}).get("subsections", {}).keys())
        missing_subs = [f"### {title}" for title in expected if f"### {title}" not in present_subs]
        if missing_subs:
            subsection_failures.append(f"{section}: 缺子条目 " + "、".join(missing_subs))
    if subsection_failures:
        raise ValueError("Prompt fidelity failure: " + "；".join(subsection_failures))

    min_subsection_chars = int(rules.get("min_subsection_chars") or 0)
    if min_subsection_chars > 0 and required_subsections_by_module:
        thin_subs: List[str] = []
        for section in required_sections:
            module_name = section.removeprefix("## ").strip()
            expected = required_subsections_by_module.get(module_name) or []
            sub_map = section_map_detailed.get(section, {}).get("subsections", {})
            for title in expected:
                key = f"### {title}"
                body = sub_map.get(key, "")
                if len(_strip_formatting_for_count(body)) < min_subsection_chars:
                    thin_subs.append(f"{section} > {key} (<{min_subsection_chars}字)")
        if thin_subs:
            raise ValueError("Prompt fidelity failure: 子条目正文不足 — " + "；".join(thin_subs))

    min_chars_per_section = int(rules.get("min_chars_per_section") or 0)
    if min_chars_per_section > 0:
        thin_sections: List[str] = []
        for section in required_sections:
            body = section_map.get(section, "")
            if len(_strip_formatting_for_count(body)) < min_chars_per_section:
                thin_sections.append(f"{section} (<{min_chars_per_section}字)")
        if thin_sections:
            raise ValueError("Prompt fidelity failure: 模块正文不足 — " + "；".join(thin_sections))

    if rules.get("require_scene_evidence_per_section"):
        missing_evidence = [
            section
            for section in required_sections
            if not _SCENE_EVIDENCE_RE.search(section_map.get(section, ""))
        ]
        if missing_evidence:
            raise ValueError(f"Prompt fidelity failure: sections missing scene/timestamp evidence: {', '.join(missing_evidence)}")

        min_scene_evidence = int(rules.get("min_scene_evidence_per_section") or 0)
        if min_scene_evidence > 0:
            thin_evidence: List[str] = []
            for section in required_sections:
                scenes = _distinct_scene_numbers(section_map.get(section, ""))
                if len(scenes) < min_scene_evidence:
                    thin_evidence.append(f"{section} (仅 {len(scenes)} 个不同 Scene，需 ≥{min_scene_evidence})")
            if thin_evidence:
                raise ValueError("Prompt fidelity failure: 不同场景证据不足 — " + "；".join(thin_evidence))

        section_anchor_terms = rules.get("section_anchor_terms") or {}
        anchor_failures: List[str] = []
        for section in required_sections:
            section_name = section.removeprefix("## ").strip()
            terms = section_anchor_terms.get(section_name) or []
            if not terms:
                continue
            section_text = section_map.get(section, "")
            hits = [term for term in terms if term in section_text]
            min_hits = 2 if len(terms) >= 3 else 1
            if len(hits) < min_hits:
                anchor_failures.append(f"{section} (expected anchors: {'/'.join(terms[:4])})")
        if anchor_failures:
            raise ValueError(f"Prompt fidelity failure: sections missing prompt anchors: {', '.join(anchor_failures)}")
    return text


def _figure_rationale(marker: str, title: str, fallback_note: str) -> str:
    rationale = _FIGURE_MARKER_RATIONALES.get(_safe_text(marker).lower())
    if rationale:
        return rationale
    if title:
        return f"对应“{title}”这一节的关键镜头，用来支撑当前分析落点。"
    return fallback_note


def _with_marker_rationale(spec: Any, marker: str) -> Any:
    if not isinstance(spec, tuple) or len(spec) != 3:
        return spec
    title, scene, note = spec
    return (title, scene, _figure_rationale(marker, _safe_text(title), _safe_text(note)))


def _route_judgement_block(route: Dict[str, Any]) -> str:
    lines = ["## 路由判断", ""]
    if _safe_text(route.get("visual_axis")) and _safe_text(route.get("visual_label")):
        lines.append(f"- 视觉主体：{route['visual_axis']} · {route['visual_label']}")
    if _safe_text(route.get("audio_axis")) and _safe_text(route.get("audio_label")):
        lines.append(f"- 听觉主体：{route['audio_axis']} · {route['audio_label']}")
    lines.append(f"- 路由结果：{_safe_text(route.get('route_label'), '未识别路由')}" + (f"（{route['route_subtype']}）" if _safe_text(route.get("route_subtype")) else ""))
    if _safe_text(route.get("reference")):
        lines.append(f"- 参考框架：{route['reference']}")
    if _safe_text(route.get("visual_rationale")):
        lines.append(f"- 视觉判断依据：{route['visual_rationale']}")
    if _safe_text(route.get("audio_rationale")):
        lines.append(f"- 听觉判断依据：{route['audio_rationale']}")
    if route.get("voiceover_ratio") is not None:
        lines.append(f"- 语音 / 字幕覆盖率：{float(route.get('voiceover_ratio') or 0.0) * 100:.1f}%")
    dual_layer = route.get("dual_layer") or {}
    if dual_layer.get("enabled"):
        lines.append(f"- 双层分析：已触发（{dual_layer.get('primary')} + {dual_layer.get('secondary')}）")
        if _safe_text(dual_layer.get("reason")):
            lines.append(f"- 触发原因：{dual_layer['reason']}")
    else:
        lines.append("- 双层分析：未触发")
    return "\n".join(lines)


def _render_figure_block(spec: tuple[str, Dict, str], report_dir: Path | None) -> str:
    title, scene, note = spec
    if report_dir is None or scene is None:
        return ""

    screenshot = _scene_screenshot(scene)
    rel_path = _markdown_media_path(screenshot, report_dir)
    if not rel_path:
        return ""

    scene_num = int(scene.get("scene_number", 0))
    return "\n".join(
        [
            f"##### Scene {scene_num:03d} · {title}",
            "",
            f"![Scene {scene_num:03d}](<{rel_path}>)",
            "",
            f"- 图注：{_scene_desc(scene)}",
            f"- 为什么放这里：{note}",
        ]
    )


def _strip_python_direct_blocks(text: str) -> str:
    def _replace(match: re.Match[str]) -> str:
        return f"<!-- PYTHON_DIRECT:{match.group(1)} -->"

    return _PYTHON_DIRECT_RE.sub(_replace, text)


def _fmt_avg(values: Sequence[float]) -> str:
    return f"{_avg(values):.1f}" if values else "0.0"


def _fmt_pct(numerator: int, denominator: int) -> str:
    return f"{numerator / max(denominator, 1) * 100:.0f}"


def _scene_number_list(scene_numbers: Sequence[int]) -> str:
    return "、".join(f"Scene {int(num):03d}" for num in scene_numbers if int(num) > 0) or "无"


def _format_highlight_specs_for_template(data: Dict, route: Dict[str, Any]) -> str:
    specs = _highlight_specs_for_route(data, route)
    lines = []
    for title, scene, note in specs:
        if not scene:
            continue
        lines.append(f"- Scene {int(scene.get('scene_number', 0)):03d} · {title}：{note}")
    return "\n".join(lines) if lines else "- 暂无高光场景数据"


def _format_scenes_by_dimension(
    scenes: Sequence[Dict],
    groups: Dict[str, Callable[[Dict], bool]],
    limit_per_group: int = 5,
) -> str:
    parts: List[str] = []
    for group_name, predicate in groups.items():
        matched = [scene for scene in scenes if predicate(scene)][:limit_per_group]
        if not matched:
            continue
        parts.append(f"**{group_name}**")
        for scene in matched:
            parts.append(
                " | ".join(
                    [
                        f"Scene {int(scene.get('scene_number', 0)):03d}",
                        f"{float(scene.get('duration_seconds') or 0.0):.1f}s",
                        _scene_desc(scene)[:60],
                        f"冲击 {float(scene.get('scores', {}).get('impact') or 0.0):.1f}",
                        f"记忆 {float(scene.get('scores', {}).get('memorability') or 0.0):.1f}",
                        f"美学 {float(scene.get('scores', {}).get('aesthetic_beauty') or 0.0):.1f}",
                    ]
                )
            )
        parts.append("")
    return "\n".join(parts).strip() or "暂无代表场景数据"


def _scene_phrase(scenes: Sequence[Dict], limit: int = 2, max_length: int = 24) -> str:
    return _scene_utils._scene_phrase(scenes, limit=limit, max_length=max_length, default="暂无描述")


def _assess_w5h1_coverage(ordered: Sequence[Dict], voiceover_scenes: Sequence[Dict]) -> Dict[str, object]:
    all_text = " ".join(_voiceover(s) for s in voiceover_scenes) + " ".join(_scene_desc(s) for s in ordered)
    elements = {
        "谁": any(k in all_text for k in ("人", "角色", "主角", "他", "她", "谁", "人物", "女孩", "男生", "男子", "女子", "孩子", "母亲", "父亲")),
        "什么": any(k in all_text for k in ("事情", "事件", "发生", "什么", "发现", "出现")),
        "何时": any(k in all_text for k in ("时", "年", "月", "日", "今天", "昨天", "早上", "晚上", "后来", "之后", "以前")),
        "何地": any(k in all_text for k in ("地", "这里", "那里", "城市", "国家", "家", "学校", "街", "路", "工厂", "村")),
        "为何": any(k in all_text for k in ("因为", "所以", "为什么", "原因", "为了", "导致")),
        "如何": any(k in all_text for k in ("如何", "怎么", "方式", "方法", "步骤", "过程")),
    }
    covered = [k for k, v in elements.items() if v]
    missing = [k for k, v in elements.items() if not v]
    return {"covered_count": len(covered), "covered_items": "、".join(covered) if covered else "无", "missing_items": "、".join(missing) if missing else "全部覆盖"}


def _count_source_switches(ordered: Sequence[Dict]) -> int:
    styles = [_safe_text(s.get("storyboard", {}).get("visual_style")) for s in ordered]
    switches = 0
    for i in range(1, len(styles)):
        if styles[i] and styles[i - 1] and styles[i] != styles[i - 1]:
            switches += 1
    return switches
