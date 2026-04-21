#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import re
from typing import Dict, List, Optional, Tuple

from audiovisual.shared import _decode_markdown_media_path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    Image = ImageDraw = ImageFont = None

try:
    from audiovisual.routing.enrich import enrich_audiovisual_layers
except ImportError:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from audiovisual.routing.enrich import enrich_audiovisual_layers


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


FONT_CANDIDATES = (
    Path("C:/Windows/Fonts/msyh.ttc"),
    Path("C:/Windows/Fonts/simsun.ttc"),
    Path("C:/Windows/Fonts/simhei.ttf"),
    Path("/System/Library/Fonts/PingFang.ttc"),
    Path("/Library/Fonts/Arial Unicode.ttf"),
    Path("/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
)


def _find_font(size: int) -> Optional[ImageFont.FreeTypeFont]:
    if ImageFont is None:
        return None
    for candidate in FONT_CANDIDATES:
        if candidate.exists():
            try:
                return ImageFont.truetype(str(candidate), size)
            except Exception:
                continue
    return None


def _wrap_text_pdf(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int, max_lines: int = 999) -> List[str]:
    cleaned = str(text or "").replace("\r", " ").strip()
    if not cleaned:
        return [""]

    lines = []
    current_line = ""
    for char in cleaned:
        test_line = f"{current_line}{char}"
        bbox = draw.textbbox((0, 0), test_line, font=font)
        if bbox[2] - bbox[0] <= max_width:
            current_line = test_line
        else:
            if current_line:
                lines.append(current_line)
            current_line = char
        if len(lines) >= max_lines:
            break
    if current_line and len(lines) < max_lines:
        lines.append(current_line)
    if len(lines) == max_lines and "".join(lines) != cleaned:
        last = lines[-1]
        while last and draw.textbbox((0, 0), f"{last}...", font=font)[2] > max_width:
            last = last[:-1]
        lines[-1] = f"{last}..."
    return lines


def _draw_multiline_pdf(draw: ImageDraw.ImageDraw, lines: List[str], font: ImageFont.FreeTypeFont, x: int, y: int, line_gap: int = 6, fill=(52, 60, 73)):
    current_y = y
    for line in lines:
        draw.text((x, current_y), line, font=font, fill=fill)
        current_y += font.size + line_gap


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


def build_audiovisual_report_pdf_blocks(data: Dict, report_dir: Path | None = None, markdown_text: str | None = None) -> List[Dict[str, object]]:
    markdown = _build_report_markdown(data, report_dir=report_dir, markdown_text=markdown_text)
    image_pattern = re.compile(r"!\[[^\]]*\]\((?:<([^>]+)>|([^)]+))\)")
    blocks: List[Dict[str, object]] = []

    for raw_line in markdown.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            if not blocks or blocks[-1].get("type") != "spacer":
                blocks.append({"type": "spacer", "height": 18})
            continue
        if stripped == "---":
            blocks.append({"type": "spacer", "height": 24})
            continue

        image_match = image_pattern.search(stripped)
        if image_match:
            asset_path = _resolve_report_asset_path(image_match.group(1) or image_match.group(2) or "", report_dir)
            if asset_path:
                blocks.append({"type": "image", "path": str(asset_path)})
            continue

        if stripped.startswith("|"):
            if set(stripped.replace("|", "").replace("-", "").replace(" ", "")) == set():
                continue
            cells = [cell.strip() for cell in stripped.strip("|").split("|")]
            text = " | ".join(cell for cell in cells if cell)
            blocks.append({"type": "table", "text": text})
            continue

        if stripped.startswith("#"):
            level = len(stripped) - len(stripped.lstrip("#"))
            text = stripped[level:].strip()
            blocks.append({"type": "heading", "level": level, "text": text})
            continue

        if stripped.startswith("- "):
            blocks.append({"type": "bullet", "text": stripped})
            continue

        blocks.append({"type": "paragraph", "text": stripped})

    return blocks


def _pdf_text_style(block: Dict[str, object], title_font, header_font, body_font, small_font):
    block_type = block.get("type")
    if block_type == "heading":
        level = int(block.get("level", 2) or 2)
        if level == 1:
            return title_font, 14
        if level <= 2:
            return header_font, 10
        if level <= 4:
            return body_font, 8
        return small_font, 6
    if block_type == "table":
        return small_font, 6
    return body_font, 8


def _measure_wrapped_text_height(draw, text: str, font, max_width: int, line_gap: int) -> Tuple[List[str], int]:
    lines = _wrap_text_pdf(draw, text, font, max_width)
    height = len(lines) * (font.size + line_gap)
    return lines, height


def _image_target_height(image_path: Path, max_width: int, max_height: int = 520) -> int:
    try:
        with Image.open(image_path) as img:
            width, height = img.size
        if width <= 0 or height <= 0:
            return min(max_height, 360)
        scale = min(max_width / width, max_height / height)
        return max(160, int(height * scale))
    except Exception:
        return min(max_height, 360)


def _paste_screenshot_pdf(page: Image.Image, screenshot_path: Path, left: int, top: int, right: int, bottom: int) -> bool:
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


def write_audiovisual_report_pdf(data: Dict, output_path: Path, report_dir: Path | None = None, markdown_text: str | None = None) -> Path:
    if Image is None or ImageDraw is None or ImageFont is None:
        raise RuntimeError("Pillow 未安装，无法生成 PDF")

    enrich_audiovisual_layers(data)
    blocks = build_audiovisual_report_pdf_blocks(data, report_dir=report_dir, markdown_text=markdown_text)

    # 字体设置
    title_font = _find_font(28) or ImageFont.load_default()
    header_font = _find_font(18) or ImageFont.load_default()
    body_font = _find_font(14) or ImageFont.load_default()
    small_font = _find_font(11) or ImageFont.load_default()

    # 页面设置
    page_width, page_height = 2480, 3508  # A4 at 300 DPI
    margin = 120
    content_width = page_width - 2 * margin
    page_bottom = page_height - margin - 80
    pages = []

    def new_page():
        page = Image.new("RGB", (page_width, page_height), (255, 255, 255))
        draw = ImageDraw.Draw(page)
        return page, draw, margin

    page, draw, current_y = new_page()

    for block in blocks:
        block_type = block.get("type")
        if block_type == "spacer":
            current_y += int(block.get("height", 18) or 18)
            continue

        if block_type == "image":
            image_path = Path(str(block.get("path")))
            target_height = _image_target_height(image_path, content_width, max_height=560)
            if current_y + target_height > page_bottom:
                pages.append(page)
                page, draw, current_y = new_page()
            pasted = _paste_screenshot_pdf(page, image_path, margin, current_y, margin + content_width, current_y + target_height)
            current_y += (target_height if pasted else 180) + 18
            continue

        font, line_gap = _pdf_text_style(block, title_font, header_font, body_font, small_font)
        text = str(block.get("text", "") or "")
        lines, height = _measure_wrapped_text_height(draw, text, font, content_width, line_gap)
        if current_y + height > page_bottom:
            pages.append(page)
            page, draw, current_y = new_page()
            lines, height = _measure_wrapped_text_height(draw, text, font, content_width, line_gap)
        _draw_multiline_pdf(draw, lines, font, margin, current_y, line_gap=line_gap)
        current_y += height + (10 if block_type == "heading" else 6)

    pages.append(page)

    footer_text = f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    for page in pages:
        draw = ImageDraw.Draw(page)
        draw.text((margin, page_height - margin - 20), footer_text, font=small_font, fill=(112, 118, 126))

    # 保存 PDF
    first_page, *other_pages = pages
    candidate_paths = [output_path]
    candidate_paths.extend(
        output_path.with_name(f"{output_path.stem}_compact{suffix}.pdf")
        for suffix in ("", "_2", "_3", "_4", "_5")
    )

    last_error: Optional[Exception] = None
    for candidate_path in candidate_paths:
        try:
            first_page.save(
                candidate_path,
                "PDF",
                resolution=150.0,
                save_all=True,
                append_images=other_pages if other_pages else [],
            )
            return candidate_path
        except PermissionError as exc:
            last_error = exc
            continue

    raise RuntimeError("PDF 文件被占用，无法写入新的视听报告") from last_error
