#!/usr/bin/env python3
"""Vector PDF renderer for the audiovisual report.

Produces selectable, searchable PDFs via reportlab. Page geometry, type
scale, and color are tuned for long-form Chinese editorial reading at A4.
The legacy PIL-based rasterizer was replaced because raster pages can't
be selected, searched, or accessibly read.
"""
from __future__ import annotations

from datetime import datetime
from html import escape as _html_escape
import json
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Sequence

from audiovisual.shared import _decode_markdown_media_path

try:
    from PIL import Image
except ImportError:
    Image = None  # type: ignore[assignment]

try:
    from audiovisual.routing.enrich import enrich_audiovisual_layers
except ImportError:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from audiovisual.routing.enrich import enrich_audiovisual_layers


# ---------------------------------------------------------------------------
# Markdown → block parsing (kept stable; tests depend on this contract)
# ---------------------------------------------------------------------------


def _build_report_markdown(data: Dict, report_dir: Path | None = None, markdown_text: str | None = None) -> str:
    if markdown_text is not None:
        return markdown_text
    try:
        from audiovisual.reporting.markdown import build_audiovisual_report_markdown
    except ImportError:
        import sys

        sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
        from audiovisual.reporting.markdown import build_audiovisual_report_markdown

    return build_audiovisual_report_markdown(data, report_dir=report_dir)


def load_storyboard_context_rows(video_dir: Path, video_id: str) -> List[Dict]:
    context_path = video_dir / f"{video_id}_storyboard_context.json"
    if not context_path.exists():
        return []
    try:
        payload = json.loads(context_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    rows = payload.get("rows", [])
    return rows if isinstance(rows, list) else []


def _resolve_report_asset_path(path_text: str, report_dir: Path | None) -> Optional[Path]:
    if not path_text:
        return None
    path = Path(_decode_markdown_media_path(path_text))
    if path.is_absolute():
        return path if path.exists() else None
    if report_dir is None:
        return path if path.exists() else None
    candidate = report_dir / path
    return candidate if candidate.exists() else None


_BOLD_RE = re.compile(r"\*\*(?=\S)([^*\n]+?)(?<=\S)\*\*")
_ITALIC_RE = re.compile(r"(?<![*\w])\*(?=\S)([^*\n]+?)(?<=\S)\*(?![*\w])")


def _strip_md_emphasis(text: str) -> str:
    text = _BOLD_RE.sub(r"\1", text)
    text = _ITALIC_RE.sub(r"\1", text)
    return text


def _maybe_italic_caption(text: str) -> Optional[str]:
    """If `text` is a single-line `*…*` italic caption, return its inner text; else None."""
    stripped = text.strip()
    if len(stripped) < 3 or stripped.startswith("**") or stripped.endswith("**"):
        return None
    if not stripped.startswith("*") or not stripped.endswith("*"):
        return None
    inner = stripped[1:-1].strip()
    if not inner or "*" in inner:
        return None
    return inner


def _coalesce_image_caption_blocks(blocks: List[Dict[str, object]]) -> List[Dict[str, object]]:
    """Merge `image` + (optional spacer) + `*…*` paragraph into `image_with_caption`."""
    out: List[Dict[str, object]] = []
    i = 0
    n = len(blocks)
    while i < n:
        block = blocks[i]
        if block.get("type") == "image":
            j = i + 1
            if j < n and blocks[j].get("type") == "spacer":
                j += 1
            if j < n:
                next_block = blocks[j]
                if next_block.get("type") == "paragraph" and next_block.get("_caption"):
                    out.append(
                        {
                            "type": "image_with_caption",
                            "path": block.get("path"),
                            "caption": next_block.get("text", ""),
                        }
                    )
                    i = j + 1
                    continue
        out.append(block)
        i += 1
    return out


def build_audiovisual_report_pdf_blocks(data: Dict, report_dir: Path | None = None, markdown_text: str | None = None) -> List[Dict[str, object]]:
    markdown = _build_report_markdown(data, report_dir=report_dir, markdown_text=markdown_text)
    image_pattern = re.compile(r"!\[([^\]]*)\]\((?:<([^>]+)>|([^)]+))\)")
    blocks: List[Dict[str, object]] = []

    for raw_line in markdown.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            if not blocks or blocks[-1].get("type") != "spacer":
                blocks.append({"type": "spacer", "height": 10})
            continue
        if stripped == "---":
            blocks.append({"type": "spacer", "height": 16})
            continue

        image_match = image_pattern.search(stripped)
        if image_match:
            alt_text = image_match.group(1) or ""
            url_text = image_match.group(2) or image_match.group(3) or ""
            asset_path = _resolve_report_asset_path(url_text, report_dir)
            if asset_path:
                alt_caption = alt_text.strip() if "·" in alt_text else None
                if alt_caption:
                    blocks.append(
                        {
                            "type": "image_with_caption",
                            "path": str(asset_path),
                            "caption": alt_caption,
                        }
                    )
                else:
                    blocks.append({"type": "image", "path": str(asset_path)})
            continue

        if stripped.startswith("|"):
            if set(stripped.replace("|", "").replace("-", "").replace(" ", "")) == set():
                continue
            cells = [_strip_md_emphasis(cell.strip()) for cell in stripped.strip("|").split("|")]
            text = " | ".join(cell for cell in cells if cell)
            blocks.append({"type": "table", "text": text, "cells": cells})
            continue

        if stripped.startswith("#"):
            level = len(stripped) - len(stripped.lstrip("#"))
            text = _strip_md_emphasis(stripped[level:].strip())
            blocks.append({"type": "heading", "level": level, "text": text})
            continue

        if stripped.startswith("- "):
            blocks.append({"type": "bullet", "text": _strip_md_emphasis(stripped)})
            continue

        if stripped.startswith("> "):
            blocks.append({"type": "blockquote", "text": _strip_md_emphasis(stripped[2:].strip())})
            continue

        caption_inner = _maybe_italic_caption(stripped)
        if caption_inner is not None:
            blocks.append({"type": "paragraph", "text": caption_inner, "_caption": True})
        else:
            blocks.append({"type": "paragraph", "text": _strip_md_emphasis(stripped)})

    return _coalesce_image_caption_blocks(blocks)


# ---------------------------------------------------------------------------
# Legacy raster helper retained for backward-compat tests (not used by the
# vector renderer below).
# ---------------------------------------------------------------------------


def _paste_screenshot_pdf(page, screenshot_path: Path, left: int, top: int, right: int, bottom: int) -> bool:
    if Image is None:
        return False
    if not screenshot_path.exists():
        return False
    try:
        img = Image.open(screenshot_path)
        if img.mode in {"RGBA", "LA"} or (img.mode == "P" and "transparency" in img.info):
            rgba = img.convert("RGBA")
            background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
            img = Image.alpha_composite(background, rgba).convert("RGB")
        else:
            img = img.convert("RGB")
        target_width = right - left
        target_height = bottom - top
        img.thumbnail((target_width, target_height), Image.Resampling.LANCZOS)
        paste_x = left + (target_width - img.width) // 2
        paste_y = top + (target_height - img.height) // 2
        page.paste(img, (paste_x, paste_y))
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Vector PDF rendering (reportlab)
# ---------------------------------------------------------------------------


_FONT_REGULAR_NAME = "AVReportBody"
_FONT_BOLD_NAME = "AVReportBold"

_FONT_REGULAR_CANDIDATES = (
    Path("/System/Library/Fonts/STHeiti Light.ttc"),
    Path("/System/Library/Fonts/Hiragino Sans GB.ttc"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"),
    Path("C:/Windows/Fonts/msyh.ttc"),
    Path("C:/Windows/Fonts/simsun.ttc"),
)
_FONT_BOLD_CANDIDATES = (
    Path("/System/Library/Fonts/STHeiti Medium.ttc"),
    Path("/System/Library/Fonts/Hiragino Sans GB.ttc"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"),
    Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc"),
    Path("C:/Windows/Fonts/msyhbd.ttc"),
    Path("C:/Windows/Fonts/simhei.ttf"),
)


_fonts_registered = False


def _first_existing(paths: Sequence[Path]) -> Optional[Path]:
    for p in paths:
        if p.exists():
            return p
    return None


def _register_fonts_once() -> None:
    global _fonts_registered
    if _fonts_registered:
        return
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    regular = _first_existing(_FONT_REGULAR_CANDIDATES)
    bold = _first_existing(_FONT_BOLD_CANDIDATES)
    if regular is None:
        raise RuntimeError("找不到可嵌入的中文字体（PingFang/STHeiti/NotoCJK/msyh），无法生成 PDF")
    pdfmetrics.registerFont(TTFont(_FONT_REGULAR_NAME, str(regular), subfontIndex=0))
    pdfmetrics.registerFont(TTFont(_FONT_BOLD_NAME, str(bold or regular), subfontIndex=0))
    _fonts_registered = True


def _image_is_full_width_chart(image_path: Path) -> bool:
    """Diagram/overview PNGs are charts; they get full measure and a taller cap."""
    stem = image_path.stem.lower()
    return stem.endswith("_audiovisual_structure") or stem.endswith("_audiovisual_overview")


def _xml_escape(text: str) -> str:
    return _html_escape(str(text or ""), quote=False)


def _build_styles():
    from reportlab.lib.colors import HexColor
    from reportlab.lib.styles import ParagraphStyle

    color_ink = HexColor("#1A1F2C")
    color_heading = HexColor("#0E1320")
    color_muted = HexColor("#6B7280")
    color_quote_rule = HexColor("#9CA3AF")

    return {
        "color_ink": color_ink,
        "color_heading": color_heading,
        "color_muted": color_muted,
        "color_rule": HexColor("#E5E7EB"),
        "color_quote_rule": color_quote_rule,
        "color_subtle_fill": HexColor("#F8F9FB"),
        "h1": ParagraphStyle(
            "AVH1", fontName=_FONT_BOLD_NAME, fontSize=22, leading=28,
            textColor=color_heading, spaceBefore=4, spaceAfter=14,
        ),
        "h2": ParagraphStyle(
            "AVH2", fontName=_FONT_BOLD_NAME, fontSize=16, leading=22,
            textColor=color_heading, spaceBefore=22, spaceAfter=8,
        ),
        "h3": ParagraphStyle(
            "AVH3", fontName=_FONT_BOLD_NAME, fontSize=13, leading=19,
            textColor=color_heading, spaceBefore=16, spaceAfter=6,
        ),
        "h4": ParagraphStyle(
            "AVH4", fontName=_FONT_BOLD_NAME, fontSize=11, leading=16,
            textColor=color_heading, spaceBefore=10, spaceAfter=4,
        ),
        "body": ParagraphStyle(
            "AVBody", fontName=_FONT_REGULAR_NAME, fontSize=10, leading=17,
            textColor=color_ink, spaceAfter=8, firstLineIndent=0,
        ),
        "bullet": ParagraphStyle(
            "AVBullet", fontName=_FONT_REGULAR_NAME, fontSize=10, leading=17,
            textColor=color_ink, leftIndent=16, bulletIndent=2, spaceAfter=2,
        ),
        "caption": ParagraphStyle(
            "AVCaption", fontName=_FONT_REGULAR_NAME, fontSize=8.5, leading=12,
            textColor=color_muted, alignment=1, spaceAfter=12,
        ),
        "table_head": ParagraphStyle(
            "AVTH", fontName=_FONT_BOLD_NAME, fontSize=9, leading=13,
            textColor=color_heading,
        ),
        "table_cell": ParagraphStyle(
            "AVTD", fontName=_FONT_REGULAR_NAME, fontSize=9, leading=13,
            textColor=color_ink,
        ),
        "blockquote": ParagraphStyle(
            "AVQuote", fontName=_FONT_REGULAR_NAME, fontSize=9.5, leading=15,
            textColor=color_muted,
        ),
    }


def _make_image_flowable(path_str: str, content_width: float):
    from reportlab.lib.units import mm
    from reportlab.platypus import Image as RLImage

    if Image is None:
        return None
    image_path = Path(path_str)
    if not image_path.exists():
        return None
    try:
        with Image.open(image_path) as img:
            iw, ih = img.size
    except Exception:
        return None
    if iw <= 0 or ih <= 0:
        return None

    is_chart = _image_is_full_width_chart(image_path)
    target_w = content_width
    max_h = (130 if is_chart else 78) * mm
    aspect = ih / iw
    target_h = target_w * aspect
    if target_h > max_h:
        target_h = max_h
        target_w = target_h / aspect

    flow = RLImage(str(image_path), width=target_w, height=target_h)
    flow.hAlign = "CENTER"
    return flow


def _make_image_with_caption_flowables(block: Dict[str, Any], styles: Dict[str, Any], content_width: float):
    from reportlab.lib.units import mm
    from reportlab.platypus import KeepTogether, Paragraph, Spacer

    img_flow = _make_image_flowable(str(block.get("path") or ""), content_width)
    if img_flow is None:
        return None
    caption = _xml_escape(block.get("caption", ""))
    cap_para = Paragraph(caption, styles["caption"]) if caption else None
    parts = [img_flow, Spacer(1, 2 * mm)]
    if cap_para is not None:
        parts.append(cap_para)
    return KeepTogether(parts)


def _make_table_flowable(rows: List[List[str]], styles: Dict[str, Any], content_width: float):
    from reportlab.platypus import Paragraph, Table, TableStyle

    if not rows:
        return None
    n_cols = max(len(r) for r in rows)
    for r in rows:
        while len(r) < n_cols:
            r.append("")

    head_style = styles["table_head"]
    cell_style = styles["table_cell"]
    formatted = []
    for ri, row in enumerate(rows):
        style = head_style if ri == 0 else cell_style
        formatted.append([Paragraph(_xml_escape(c), style) for c in row])

    col_widths = [content_width / n_cols] * n_cols
    table = Table(formatted, colWidths=col_widths, repeatRows=1, hAlign="LEFT")
    rule = styles["color_rule"]
    table.setStyle(
        TableStyle(
            [
                ("LINEABOVE", (0, 0), (-1, 0), 1.0, rule),
                ("LINEBELOW", (0, 0), (-1, 0), 0.75, rule),
                ("LINEBELOW", (0, -1), (-1, -1), 0.75, rule),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("BACKGROUND", (0, 0), (-1, 0), styles["color_subtle_fill"]),
            ]
        )
    )
    return table


def _make_blockquote_flowable(text: str, styles: Dict[str, Any], content_width: float):
    """Render `> …` lines as a left-rule pull-quote with extra breathing room."""
    from reportlab.platypus import Paragraph, Table, TableStyle

    para = Paragraph(_xml_escape(text), styles["blockquote"])
    tbl = Table([[para]], colWidths=[content_width])
    tbl.setStyle(
        TableStyle(
            [
                ("LINEBEFORE", (0, 0), (0, 0), 2.5, styles["color_quote_rule"]),
                ("LEFTPADDING", (0, 0), (0, 0), 14),
                ("RIGHTPADDING", (0, 0), (0, 0), 8),
                ("TOPPADDING", (0, 0), (0, 0), 8),
                ("BOTTOMPADDING", (0, 0), (0, 0), 8),
                ("VALIGN", (0, 0), (0, 0), "TOP"),
            ]
        )
    )
    return tbl


def _bullet_text(raw: str) -> str:
    text = raw.strip()
    if text.startswith("- "):
        text = text[2:]
    elif text.startswith("-"):
        text = text[1:]
    return text.strip()


def _blocks_to_story(blocks: Sequence[Dict[str, Any]], styles: Dict[str, Any], content_width: float):
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, Spacer

    story: List[Any] = []
    i = 0
    n = len(blocks)
    while i < n:
        block = blocks[i]
        bt = block.get("type")

        if bt == "spacer":
            i += 1
            continue

        if bt == "table" and block.get("cells"):
            rows: List[List[str]] = []
            while i < n:
                cur = blocks[i]
                if cur.get("type") == "table" and cur.get("cells"):
                    rows.append([str(c) for c in cur.get("cells") or []])
                    i += 1
                    continue
                if cur.get("type") == "spacer":
                    look = i + 1
                    if look < n and blocks[look].get("type") == "table" and blocks[look].get("cells"):
                        i = look
                        continue
                break
            tbl = _make_table_flowable(rows, styles, content_width)
            if tbl is not None:
                story.extend([Spacer(1, 5 * mm), tbl, Spacer(1, 6 * mm)])
            continue

        if bt == "heading":
            level = max(1, min(int(block.get("level", 2) or 2), 4))
            style = styles[f"h{level}"]
            story.append(Paragraph(_xml_escape(block.get("text", "")), style))
            i += 1
            continue

        if bt == "paragraph":
            story.append(Paragraph(_xml_escape(block.get("text", "")), styles["body"]))
            i += 1
            continue

        if bt == "blockquote":
            qf = _make_blockquote_flowable(str(block.get("text", "")), styles, content_width)
            story.extend([Spacer(1, 4 * mm), qf, Spacer(1, 4 * mm)])
            i += 1
            continue

        if bt == "bullet":
            text = _xml_escape(_bullet_text(str(block.get("text", ""))))
            story.append(Paragraph(text, styles["bullet"], bulletText="•"))
            i += 1
            continue

        if bt == "image":
            flow = _make_image_flowable(str(block.get("path") or ""), content_width)
            if flow is not None:
                story.extend([flow, Spacer(1, 6 * mm)])
            i += 1
            continue

        if bt == "image_with_caption":
            grouped = _make_image_with_caption_flowables(block, styles, content_width)
            if grouped is not None:
                story.append(grouped)
            i += 1
            continue

        i += 1

    return story


def _draw_footer_factory(video_id: str):
    def _on_page(canvas, doc):
        from reportlab.lib.colors import HexColor
        from reportlab.lib.units import mm

        canvas.saveState()
        canvas.setFont(_FONT_REGULAR_NAME, 8)
        canvas.setFillColor(HexColor("#9CA3AF"))
        page_w, _ = doc.pagesize
        left = doc.leftMargin
        right = page_w - doc.rightMargin
        baseline = 12 * mm
        canvas.drawString(left, baseline, f"{video_id} · 视听剖析报告")
        canvas.drawRightString(right, baseline, f"第 {doc.page} 页")
        canvas.restoreState()

    return _on_page


def write_audiovisual_report_pdf(
    data: Dict,
    output_path: Path,
    report_dir: Path | None = None,
    markdown_text: str | None = None,
) -> Path:
    enrich_audiovisual_layers(data)
    blocks = build_audiovisual_report_pdf_blocks(data, report_dir=report_dir, markdown_text=markdown_text)

    _register_fonts_once()

    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate

    styles = _build_styles()
    left_margin = 22 * mm
    right_margin = 22 * mm
    top_margin = 24 * mm
    bottom_margin = 22 * mm
    page_w, _ = A4
    content_width = page_w - left_margin - right_margin

    video_id = str(data.get("video_id") or output_path.stem)

    candidate_paths = [output_path]
    candidate_paths.extend(
        output_path.with_name(f"{output_path.stem}_compact{suffix}.pdf")
        for suffix in ("", "_2", "_3", "_4", "_5")
    )

    last_error: Optional[Exception] = None
    for candidate_path in candidate_paths:
        try:
            doc = SimpleDocTemplate(
                str(candidate_path),
                pagesize=A4,
                leftMargin=left_margin,
                rightMargin=right_margin,
                topMargin=top_margin,
                bottomMargin=bottom_margin,
                title=f"{video_id} · 视听剖析报告",
                author="video-expert-analyzer-vnext",
            )
            story = _blocks_to_story(blocks, styles, content_width)
            on_page = _draw_footer_factory(video_id)
            doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
            return candidate_path
        except PermissionError as exc:
            last_error = exc
            continue

    raise RuntimeError("PDF 文件被占用，无法写入新的视听报告") from last_error
