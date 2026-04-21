#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any, Callable, Dict, List, Sequence
from xml.sax.saxutils import escape as _xml_escape

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:  # pragma: no cover - Pillow is already a runtime dependency for PDF output
    Image = ImageDraw = ImageFont = None

from audiovisual.shared import _markdown_media_path, _safe_text

MV_OVERVIEW_FRAMEWORKS = {"mix_music", "concept_mv", "hybrid_music"}
_OVERVIEW_PROMPT = "prompt_mv_overview_chart.md"
_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*\})\s*```", re.IGNORECASE | re.DOTALL)

_BASE_WIDTH = 680
_HEADER_Y = 28
_HEADER_LINE_Y = 35
_ROW_TOP = 50
_ROW_GAP = 90
_CARD_WIDTH = 168
_CARD_HEIGHT = 56
_CARD_X = {"visual": 40, "theme": 256, "language": 472}
_CARD_CENTER_X = {"visual": 124, "theme": 340, "language": 556}
_LEFT_ARROW = (208, 254)
_RIGHT_ARROW = (424, 470)
_COLOR_SEQUENCE = ("coral", "pink", "purple", "gray", "teal", "green")
_COLOR_STYLES = {
    "coral": {"fill": "#FFF1EB", "stroke": "#E39C82"},
    "pink": {"fill": "#FCE7F3", "stroke": "#D87BA2"},
    "purple": {"fill": "#F3E8FF", "stroke": "#8D69C7"},
    "gray": {"fill": "#F4F4F5", "stroke": "#9A9AA1"},
    "teal": {"fill": "#E6FFFB", "stroke": "#3FA3A0"},
    "green": {"fill": "#ECFDF5", "stroke": "#52A37A"},
}
_TEXT_PRIMARY = "#2E3440"
_TEXT_SECONDARY = "#5B6472"
_LINE_COLOR = "#A6AFBC"
_HEADER_LINE_COLOR = "#D1D7E0"
_FONT_CANDIDATES = (
    Path("C:/Windows/Fonts/msyh.ttc"),
    Path("C:/Windows/Fonts/simsun.ttc"),
    Path("C:/Windows/Fonts/simhei.ttf"),
    Path("/System/Library/Fonts/PingFang.ttc"),
    Path("/Library/Fonts/Arial Unicode.ttf"),
    Path("/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
)


def route_supports_mv_overview(route: Dict[str, Any]) -> bool:
    framework = _safe_text(route.get("framework")).lower()
    if framework in MV_OVERVIEW_FRAMEWORKS:
        return True
    if framework != "narrative_performance":
        return False
    subtype = _safe_text(route.get("route_subtype")).lower()
    profile_key = _safe_text((route.get("content_profile") or {}).get("key")).lower()
    return "mv" in subtype or profile_key == "music_video"


def generate_mv_overview_assets(
    report_markdown: str,
    data: Dict[str, Any],
    route: Dict[str, Any],
    output_dir: Path,
    request_fn: Callable[[str, str], str],
    templates_dir: Path | None = None,
) -> Dict[str, Any]:
    if not route_supports_mv_overview(route):
        return {}

    output_dir.mkdir(parents=True, exist_ok=True)
    system_prompt = _load_overview_prompt(templates_dir=templates_dir)
    user_message = _build_overview_request(report_markdown, route)
    raw_text = request_fn(system_prompt, user_message)
    overview = _normalize_overview_payload(_parse_overview_payload(raw_text))

    video_id = _safe_text(data.get("video_id"), "unknown")
    svg_path = output_dir / f"{video_id}_audiovisual_overview.svg"
    png_path = output_dir / f"{video_id}_audiovisual_overview.png"
    svg_path.write_text(_render_overview_svg(overview), encoding="utf-8")
    _write_overview_png(overview, png_path)

    return {
        "title": overview["overview_title"],
        "summary": overview["overview_summary"],
        "svg": svg_path,
        "png": png_path,
    }


def prepend_mv_overview(
    markdown: str,
    image_path: Path,
    title: str,
    summary: str,
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


def _load_overview_prompt(templates_dir: Path | None = None) -> str:
    base_dir = templates_dir or Path(__file__).resolve().parents[2] / "templates"
    prompt_path = base_dir / _OVERVIEW_PROMPT
    return prompt_path.read_text(encoding="utf-8")


def _build_overview_request(report_markdown: str, route: Dict[str, Any]) -> str:
    return "\n".join(
        [
            f"路由名称：{_safe_text(route.get('route_label'), '未识别路由')}",
            f"路由细分：{_safe_text(route.get('route_subtype'), '无')}",
            "",
            "完整视听报告如下：",
            "",
            report_markdown.strip(),
        ]
    )


def _parse_overview_payload(raw_text: str) -> Dict[str, Any]:
    match = _JSON_FENCE_RE.search(raw_text)
    json_text = match.group(1) if match else raw_text
    start = json_text.find("{")
    end = json_text.rfind("}")
    if start < 0 or end < 0 or end <= start:
        raise ValueError("MV 架构图响应里没有找到合法 JSON 对象")
    return json.loads(json_text[start : end + 1])


def _normalize_overview_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    acts = payload.get("acts")
    if not isinstance(acts, list) or len(acts) < 3:
        raise ValueError("MV 架构图至少需要 3 幕")

    seen_colors: set[str] = set()
    normalized_acts: List[Dict[str, str]] = []
    for index, item in enumerate(acts[:6]):
        if not isinstance(item, dict):
            continue
        color = _pick_color(_safe_text(item.get("color")).lower(), seen_colors, index)
        seen_colors.add(color)
        normalized_acts.append(
            {
                "visual_title": _trim_text(_safe_text(item.get("visual_title"), f"画面段落{index + 1}"), 10),
                "visual_subtitle": _trim_text(_safe_text(item.get("visual_subtitle"), "画面推进"), 16),
                "theme_title": _trim_text(_safe_text(item.get("theme_title"), f"叙事阶段{index + 1}"), 10),
                "theme_subtitle": _trim_text(_safe_text(item.get("theme_subtitle"), "00:00 - 00:00"), 16),
                "language_title": _trim_text(_safe_text(item.get("language_title"), "语言重点"), 16),
                "language_subtitle": _trim_text(_safe_text(item.get("language_subtitle"), "语言功能"), 16),
                "color": color,
            }
        )
    if len(normalized_acts) < 3:
        raise ValueError("MV 架构图有效幕数不足")

    return {
        "overview_title": _safe_text(payload.get("overview_title"), "视频内容架构总览"),
        "overview_summary": _safe_text(payload.get("overview_summary"), ""),
        "acts": normalized_acts,
    }


def _pick_color(candidate: str, seen_colors: set[str], index: int) -> str:
    if candidate in _COLOR_STYLES and candidate not in seen_colors:
        return candidate
    for color in _COLOR_SEQUENCE[index:]:
        if color not in seen_colors:
            return color
    for color in _COLOR_SEQUENCE:
        if color not in seen_colors:
            return color
    return _COLOR_SEQUENCE[index % len(_COLOR_SEQUENCE)]


def _trim_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(limit - 1, 1)] + "…"


def _render_overview_svg(overview: Dict[str, Any]) -> str:
    acts = overview["acts"]
    height = _ROW_TOP + len(acts) * _ROW_GAP + 20
    title = _xml_escape(overview["overview_title"])
    desc = _xml_escape(overview["overview_summary"] or "MV 内容架构总览")
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="100%" viewBox="0 0 {_BASE_WIDTH} {height}" role="img">',
        f"  <title>{title}</title>",
        f"  <desc>{desc}</desc>",
        '  <defs>',
        '    <marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">',
        '      <path d="M2 1L8 5L2 9" fill="none" stroke="context-stroke" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>',
        '    </marker>',
        "  </defs>",
        '  <text x="124" y="28" text-anchor="middle" font-size="12" font-weight="600" fill="#4C5563">画面线</text>',
        '  <text x="340" y="28" text-anchor="middle" font-size="12" font-weight="600" fill="#4C5563">叙事弧线（主题）</text>',
        '  <text x="556" y="28" text-anchor="middle" font-size="12" font-weight="600" fill="#4C5563">语言线</text>',
        f'  <line x1="40" y1="{_HEADER_LINE_Y}" x2="640" y2="{_HEADER_LINE_Y}" stroke="{_HEADER_LINE_COLOR}" stroke-width="0.5"/>',
    ]

    for index, act in enumerate(acts):
        y = _ROW_TOP + index * _ROW_GAP
        center_y = y + _CARD_HEIGHT / 2
        lines.extend(_render_svg_card(_CARD_X["visual"], y, act["visual_title"], act["visual_subtitle"], act["color"]))
        lines.extend(_render_svg_card(_CARD_X["theme"], y, act["theme_title"], act["theme_subtitle"], act["color"]))
        lines.extend(_render_svg_card(_CARD_X["language"], y, act["language_title"], act["language_subtitle"], act["color"]))
        lines.append(
            f'  <line x1="{_LEFT_ARROW[0]}" y1="{center_y}" x2="{_LEFT_ARROW[1]}" y2="{center_y}" stroke="{_LINE_COLOR}" stroke-width="1.3" marker-end="url(#arrow)"/>'
        )
        lines.append(
            f'  <line x1="{_RIGHT_ARROW[0]}" y1="{center_y}" x2="{_RIGHT_ARROW[1]}" y2="{center_y}" stroke="{_LINE_COLOR}" stroke-width="1.3" marker-end="url(#arrow)"/>'
        )
        if index < len(acts) - 1:
            next_y = _ROW_TOP + (index + 1) * _ROW_GAP
            for column in _CARD_CENTER_X.values():
                lines.append(
                    f'  <line x1="{column}" y1="{y + _CARD_HEIGHT + 2}" x2="{column}" y2="{next_y - 2}" stroke="{_LINE_COLOR}" stroke-width="1.2" marker-end="url(#arrow)"/>'
                )

    lines.append("</svg>")
    return "\n".join(lines) + "\n"


def _render_svg_card(x: int, y: int, title: str, subtitle: str, color: str) -> List[str]:
    style = _COLOR_STYLES[color]
    return [
        f'  <g>',
        f'    <rect x="{x}" y="{y}" width="{_CARD_WIDTH}" height="{_CARD_HEIGHT}" rx="8" fill="{style["fill"]}" stroke="{style["stroke"]}" stroke-width="1"/>',
        f'    <text x="{x + _CARD_WIDTH / 2}" y="{y + 19}" text-anchor="middle" dominant-baseline="middle" font-size="13" font-weight="600" fill="{_TEXT_PRIMARY}">{_xml_escape(title)}</text>',
        f'    <text x="{x + _CARD_WIDTH / 2}" y="{y + 39}" text-anchor="middle" dominant-baseline="middle" font-size="11" fill="{_TEXT_SECONDARY}">{_xml_escape(subtitle)}</text>',
        "  </g>",
    ]


def _write_overview_png(overview: Dict[str, Any], output_path: Path) -> None:
    if Image is None or ImageDraw is None or ImageFont is None:
        raise RuntimeError("Pillow 未安装，无法生成 MV 架构图 PNG")

    scale = 3
    base_height = _ROW_TOP + len(overview["acts"]) * _ROW_GAP + 20
    image = Image.new("RGBA", (_BASE_WIDTH * scale, base_height * scale), (255, 255, 255, 0))
    draw = ImageDraw.Draw(image)
    title_font = _find_font(13 * scale, bold=True) or ImageFont.load_default()
    subtitle_font = _find_font(11 * scale) or ImageFont.load_default()
    header_font = _find_font(12 * scale, bold=True) or ImageFont.load_default()

    _draw_centered(draw, "画面线", 124 * scale, _HEADER_Y * scale, header_font, _TEXT_SECONDARY)
    _draw_centered(draw, "叙事弧线（主题）", 340 * scale, _HEADER_Y * scale, header_font, _TEXT_SECONDARY)
    _draw_centered(draw, "语言线", 556 * scale, _HEADER_Y * scale, header_font, _TEXT_SECONDARY)
    draw.line((40 * scale, _HEADER_LINE_Y * scale, 640 * scale, _HEADER_LINE_Y * scale), fill=_HEADER_LINE_COLOR, width=max(scale, 1))

    for index, act in enumerate(overview["acts"]):
        y = (_ROW_TOP + index * _ROW_GAP) * scale
        center_y = y + (_CARD_HEIGHT * scale) // 2
        _draw_png_card(draw, _CARD_X["visual"] * scale, y, act["visual_title"], act["visual_subtitle"], act["color"], title_font, subtitle_font, scale)
        _draw_png_card(draw, _CARD_X["theme"] * scale, y, act["theme_title"], act["theme_subtitle"], act["color"], title_font, subtitle_font, scale)
        _draw_png_card(draw, _CARD_X["language"] * scale, y, act["language_title"], act["language_subtitle"], act["color"], title_font, subtitle_font, scale)
        _draw_arrow(draw, _LEFT_ARROW[0] * scale, center_y, _LEFT_ARROW[1] * scale, center_y, scale)
        _draw_arrow(draw, _RIGHT_ARROW[0] * scale, center_y, _RIGHT_ARROW[1] * scale, center_y, scale)
        if index < len(overview["acts"]) - 1:
            next_y = (_ROW_TOP + (index + 1) * _ROW_GAP) * scale
            for column in _CARD_CENTER_X.values():
                _draw_arrow(draw, column * scale, y + _CARD_HEIGHT * scale + 2 * scale, column * scale, next_y - 2 * scale, scale)

    image.save(output_path)


def _draw_png_card(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    title: str,
    subtitle: str,
    color: str,
    title_font: ImageFont.FreeTypeFont,
    subtitle_font: ImageFont.FreeTypeFont,
    scale: int,
) -> None:
    width = _CARD_WIDTH * scale
    height = _CARD_HEIGHT * scale
    radius = 8 * scale
    style = _COLOR_STYLES[color]
    draw.rounded_rectangle((x, y, x + width, y + height), radius=radius, fill=style["fill"], outline=style["stroke"], width=max(scale, 1))
    _draw_centered(draw, title, x + width // 2, y + 19 * scale, title_font, _TEXT_PRIMARY)
    _draw_centered(draw, subtitle, x + width // 2, y + 39 * scale, subtitle_font, _TEXT_SECONDARY)


def _draw_arrow(draw: ImageDraw.ImageDraw, x1: int, y1: int, x2: int, y2: int, scale: int) -> None:
    draw.line((x1, y1, x2, y2), fill=_LINE_COLOR, width=max(scale, 1))
    size = 4 * scale
    if x1 == x2:
        points = [(x2, y2), (x2 - size, y2 - size), (x2 + size, y2 - size)]
    else:
        points = [(x2, y2), (x2 - size, y2 - size), (x2 - size, y2 + size)]
    draw.polygon(points, fill=_LINE_COLOR)


def _draw_centered(draw: ImageDraw.ImageDraw, text: str, x: int, y: int, font: ImageFont.FreeTypeFont, fill: str) -> None:
    bbox = draw.textbbox((0, 0), text, font=font)
    width = bbox[2] - bbox[0]
    height = bbox[3] - bbox[1]
    draw.text((x - width / 2, y - height / 2), text, font=font, fill=fill)


def _find_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | None:
    if ImageFont is None:
        return None
    for candidate in _FONT_CANDIDATES:
        if not candidate.exists():
            continue
        try:
            return ImageFont.truetype(str(candidate), size)
        except Exception:
            continue
    return None
