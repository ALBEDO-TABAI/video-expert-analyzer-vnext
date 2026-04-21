#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import re
import subprocess
from typing import Any, Callable, Dict, List

from audiovisual.shared import _markdown_media_path, _safe_text

try:
    from video_type_router_runtime import TYPE_LABELS
except ImportError:
    TYPE_LABELS = {}


_SVG_FENCE_RE = re.compile(r"```(?:svg)?\s*(<svg[\s\S]*?</svg>)\s*```", re.IGNORECASE)
_SVG_RE = re.compile(r"(<svg[\s\S]*?</svg>)", re.IGNORECASE)
_SVG_TITLE_RE = re.compile(r"<title>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_SVG_DESC_RE = re.compile(r"<desc>(.*?)</desc>", re.IGNORECASE | re.DOTALL)
_SVG_STYLE_RE = re.compile(r"<style\b", re.IGNORECASE)
_PROMPT_TITLE_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
_PROMPT_HEADER_TEXT_RE = re.compile(r"<text class=\"ts\"[^>]*>([^<]+)</text>")
_SVG_LINE_RE = re.compile(r"<line\b[^>]*x1=\"([^\"]+)\"[^>]*y1=\"([^\"]+)\"[^>]*x2=\"([^\"]+)\"[^>]*y2=\"([^\"]+)\"[^>]*marker-end=", re.IGNORECASE)

_DIRECT_PROMPT_FILES = {
    "concept_mv": "concept-mv-svg-diagram-prompt.md",
    "live_session": "live-session-svg-diagram-prompt.md",
    "narrative_short": "narrative-short-svg-diagram-prompt.md",
    "narrative_trailer": "trailer-svg-diagram-prompt.md",
    "talking_head": "talking-head-svg-diagram-prompt.md",
    "documentary_essay": "documentary-svg-diagram-prompt.md",
    "event_promo": "event-promo-svg-diagram-prompt.md",
    "explainer": "explainer-svg-diagram-prompt.md",
    "infographic_motion": "infographic-motion-svg-diagram-prompt.md",
    "rhythm_remix": "rhythm-remix-svg-diagram-prompt.md",
    "mood_montage": "mood-montage-svg-diagram-prompt.md",
    "cinematic_vlog": "cinematic-vlog-svg-diagram-prompt.md",
    "reality_record": "reality-record-svg-diagram-prompt.md",
    "meme_viral": "meme-viral-svg-diagram-prompt.md",
    "motion_graphics": "motion-graphics-svg-diagram-prompt.md",
    "experimental": "experimental-svg-diagram-prompt.md",
}

_FALLBACK_PROMPT_FILES = {
    "brand_film": "ad-svg-diagram-prompt.md",
    "commentary_remix": "explainer-svg-diagram-prompt.md",
}

_SVG_COLOR_VARIABLES = {
    "--color-border-secondary": "#A6AFBC",
    "--color-border-tertiary": "#D1D7E0",
}

_SVG_BASE_STYLE = """
<style>
  svg {
    --color-border-secondary: #A6AFBC;
    --color-border-tertiary: #D1D7E0;
    font-family: "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", "Noto Sans CJK SC", sans-serif;
  }
  .th {
    fill: #2E3440;
    font-size: 13px;
    font-weight: 600;
  }
  .ts {
    fill: #5B6472;
    font-size: 12px;
  }
  .arr {
    fill: none;
    stroke-width: 1.3;
  }
  .node rect {
    stroke-width: 1;
  }
  .node.c-coral rect {
    fill: #FFF1EB;
    stroke: #E39C82;
  }
  .node.c-pink rect {
    fill: #FCE7F3;
    stroke: #D87BA2;
  }
  .node.c-purple rect {
    fill: #F3E8FF;
    stroke: #8D69C7;
  }
  .node.c-gray rect {
    fill: #F4F4F5;
    stroke: #9A9AA1;
  }
  .node.c-teal rect {
    fill: #E6FFFB;
    stroke: #3FA3A0;
  }
  .node.c-green rect {
    fill: #ECFDF5;
    stroke: #52A37A;
  }
</style>
""".strip()


def resolve_child_type_svg_prompt_path(
    data: Dict[str, Any],
    route: Dict[str, Any],
    prompts_dir: Path | None = None,
) -> Path | None:
    type_key = _child_type_key(data, route)
    prompt_name = _DIRECT_PROMPT_FILES.get(type_key) or _FALLBACK_PROMPT_FILES.get(type_key)
    if not prompt_name:
        return None

    base_dir = prompts_dir or Path(__file__).resolve().parents[3] / "chart" / "svg-prompt"
    prompt_path = base_dir / prompt_name
    if not prompt_path.exists():
        raise FileNotFoundError(f"SVG prompt not found for child type '{type_key}': {prompt_path}")
    return prompt_path


def child_type_supports_svg_diagram(data: Dict[str, Any], route: Dict[str, Any]) -> bool:
    return resolve_child_type_svg_prompt_path(data, route) is not None


def generate_child_type_svg_diagram_assets(
    report_markdown: str,
    data: Dict[str, Any],
    route: Dict[str, Any],
    output_dir: Path,
    request_fn: Callable[[str, str], str],
    prompts_dir: Path | None = None,
) -> Dict[str, Any]:
    prompt_path = resolve_child_type_svg_prompt_path(data, route, prompts_dir=prompts_dir)
    if prompt_path is None:
        return {}

    output_dir.mkdir(parents=True, exist_ok=True)
    prompt_text = prompt_path.read_text(encoding="utf-8")
    raw_text = request_fn(prompt_text, _build_structure_request(report_markdown, data, route))
    fallback_title = _prompt_diagram_title(prompt_text) or _safe_text(route.get("child_type_cn")) or "视频结构图"
    svg_text = _normalize_svg_payload(raw_text, fallback_title=fallback_title)
    _validate_svg_prompt_fidelity(svg_text, prompt_text)

    video_id = _safe_text(data.get("video_id"), "unknown")
    svg_path = output_dir / f"{video_id}_audiovisual_structure.svg"
    png_path = output_dir / f"{video_id}_audiovisual_structure.png"
    svg_path.write_text(svg_text, encoding="utf-8")
    _convert_svg_to_png(svg_path, png_path)

    return {
        "title": _extract_svg_title(svg_text) or fallback_title,
        "summary": "",
        "svg": svg_path,
        "png": png_path,
    }


def prepend_report_diagram(
    markdown: str,
    image_path: Path,
    title: str,
    summary: str = "",
    report_dir: Path | None = None,
) -> str:
    rel_path = _markdown_media_path(image_path, report_dir) or image_path.name
    lines = [
        f"## {title}",
        "",
    ]
    if summary:
        lines.extend([summary, ""])
    lines.extend([f"![{title}](<{rel_path}>)", ""])
    block = "\n".join(lines).strip()

    if markdown.startswith("# "):
        first_line, _, remainder = markdown.partition("\n")
        remainder = remainder.lstrip("\n")
        return f"{first_line}\n\n{block}\n\n{remainder}"
    return f"{block}\n\n{markdown.lstrip()}"


def _child_type_key(data: Dict[str, Any], route: Dict[str, Any]) -> str:
    classification_result = data.get("classification_result") or {}
    if isinstance(classification_result, dict):
        classification = classification_result.get("classification") or {}
        if isinstance(classification, dict):
            type_key = _safe_text(classification.get("type"))
            if type_key:
                return type_key

    if isinstance(route, dict):
        child_type = _safe_text(route.get("child_type"))
        if child_type:
            return child_type

        route_subtype = _safe_text(route.get("route_subtype"))
        if route_subtype:
            for type_key, type_cn in TYPE_LABELS.items():
                if route_subtype == _safe_text(type_cn):
                    return type_key
    return ""


def _build_structure_request(report_markdown: str, data: Dict[str, Any], route: Dict[str, Any]) -> str:
    type_key = _child_type_key(data, route)
    type_cn = _safe_text(route.get("child_type_cn")) or _safe_text(route.get("route_subtype")) or _safe_text(TYPE_LABELS.get(type_key))
    return "\n".join(
        [
            f"视频标题：{_safe_text(data.get('video_title')) or _safe_text(data.get('title')) or '未知标题'}",
            f"子类型：{type_cn or type_key or '未识别'}",
            f"路由名称：{_safe_text(route.get('route_label'), '未识别路由')}",
            "",
            "请严格根据下面已经完成的完整视听报告生成 SVG。",
            "只输出 SVG，不要附加解释，不要输出 Markdown 标题。",
            "",
            "完整视听报告如下：",
            "",
            report_markdown.strip(),
        ]
    )


def _prompt_diagram_title(prompt_text: str) -> str:
    match = _PROMPT_TITLE_RE.search(prompt_text)
    if not match:
        return ""
    heading = match.group(1).strip()
    heading = heading.removeprefix("SVG ").strip()
    heading = heading.replace("— AGENT PROMPT", "").replace("- AGENT PROMPT", "").strip()
    return heading


def _normalize_svg_payload(raw_text: str, fallback_title: str) -> str:
    text = raw_text.strip()
    fence_match = _SVG_FENCE_RE.search(text)
    if fence_match:
        text = fence_match.group(1).strip()
    else:
        svg_match = _SVG_RE.search(text)
        if not svg_match:
            raise ValueError("SVG 图表响应里没有找到合法的 <svg> 元素")
        text = svg_match.group(1).strip()

    text = _ensure_svg_accessibility(text, fallback_title=fallback_title)
    text = _inline_svg_color_variables(text)
    text = _ensure_embedded_svg_styles(text)
    return text.rstrip() + "\n"


def _extract_prompt_header_labels(prompt_text: str) -> List[str]:
    title_section_match = re.search(r"### 标题行规格(.*?)(?:\n---|\n### )", prompt_text, re.DOTALL)
    search_text = title_section_match.group(1) if title_section_match else prompt_text
    labels: List[str] = []
    for match in _PROMPT_HEADER_TEXT_RE.finditer(search_text):
        label = match.group(1).strip()
        if label and label not in labels:
            labels.append(label)
    return labels


def _prompt_requires_bidirectional_arrows(prompt_text: str) -> bool:
    return "水平箭头为**双向**" in prompt_text or "方向必须为双向" in prompt_text


def _prompt_requires_single_direction(prompt_text: str) -> bool:
    return "严格为 左→中→右" in prompt_text


def _parse_svg_horizontal_arrow_directions(svg_text: str) -> List[int]:
    directions: List[int] = []
    for match in _SVG_LINE_RE.finditer(svg_text):
        x1 = float(match.group(1))
        y1 = float(match.group(2))
        x2 = float(match.group(3))
        y2 = float(match.group(4))
        if abs(y1 - y2) > 8:
            continue
        if x2 > x1:
            directions.append(1)
        elif x2 < x1:
            directions.append(-1)
    return directions


def _validate_svg_prompt_fidelity(svg_text: str, prompt_text: str) -> None:
    required_headers = _extract_prompt_header_labels(prompt_text)
    missing_headers = [header for header in required_headers if header not in svg_text]
    if missing_headers:
        raise ValueError(f"SVG prompt fidelity failure: missing header labels: {', '.join(missing_headers)}")

    directions = _parse_svg_horizontal_arrow_directions(svg_text)
    if _prompt_requires_bidirectional_arrows(prompt_text) and -1 not in directions:
        raise ValueError("SVG prompt fidelity failure: bidirectional prompt requires reverse horizontal arrows")
    if _prompt_requires_single_direction(prompt_text) and -1 in directions:
        raise ValueError("SVG prompt fidelity failure: single-direction prompt contains reverse horizontal arrows")


def _ensure_svg_accessibility(svg_text: str, fallback_title: str) -> str:
    if "<svg" not in svg_text.lower():
        raise ValueError("SVG 图表响应缺少 <svg> 根节点")

    if re.search(r"<svg\b[^>]*\brole=", svg_text, re.IGNORECASE) is None:
        svg_text = re.sub(r"<svg\b", '<svg role="img"', svg_text, count=1, flags=re.IGNORECASE)

    if _SVG_TITLE_RE.search(svg_text) is None:
        svg_text = re.sub(r"(<svg\b[^>]*>)", rf"\1<title>{fallback_title}</title>", svg_text, count=1, flags=re.IGNORECASE)
    if _SVG_DESC_RE.search(svg_text) is None:
        svg_text = re.sub(
            r"(<svg\b[^>]*>(?:\s*<title>.*?</title>)?)",
            rf"\1<desc>{fallback_title}的结构图。</desc>",
            svg_text,
            count=1,
            flags=re.IGNORECASE | re.DOTALL,
        )
    return svg_text


def _extract_svg_title(svg_text: str) -> str:
    match = _SVG_TITLE_RE.search(svg_text)
    return match.group(1).strip() if match else ""


def _inline_svg_color_variables(svg_text: str) -> str:
    for variable_name, color_value in _SVG_COLOR_VARIABLES.items():
        svg_text = svg_text.replace(f"var({variable_name})", color_value)
    return svg_text


def _ensure_embedded_svg_styles(svg_text: str) -> str:
    if _SVG_STYLE_RE.search(svg_text):
        return svg_text
    if not _svg_uses_class_palette(svg_text):
        return svg_text
    return re.sub(
        r"(<svg\b[^>]*>(?:\s*<title>.*?</title>)?(?:\s*<desc>.*?</desc>)?)",
        rf"\1\n{_SVG_BASE_STYLE}",
        svg_text,
        count=1,
        flags=re.IGNORECASE | re.DOTALL,
    )


def _svg_uses_class_palette(svg_text: str) -> bool:
    return any(
        token in svg_text
        for token in (
            'class="node',
            "class='node",
            'class="th"',
            "class='th'",
            'class="ts"',
            "class='ts'",
            'class="arr"',
            "class='arr'",
            "context-stroke",
        )
    )


def _convert_svg_to_png(svg_path: Path, png_path: Path) -> None:
    # `sips` 不认 SVG 里的 CSS 类选择器和 `var(...)`，也没 CJK 字体回退，
    # 会把 `.node.c-coral rect { fill: ... }` 全退成黑底、把中文渲成 Latin 乱码。
    # 改用 WebKit 内核的 `qlmanage` 生成缩略图，CSS / 字体链都正常。
    import shutil
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        subprocess.run(
            ["qlmanage", "-t", "-s", "1600", "-o", tmpdir, str(svg_path)],
            check=True,
            capture_output=True,
            text=True,
        )
        produced = Path(tmpdir) / f"{svg_path.name}.png"
        if not produced.exists():
            raise RuntimeError(
                f"qlmanage 未生成预期的 PNG：{produced}（SVG: {svg_path}）"
            )
        png_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(produced), str(png_path))
