from pathlib import Path
import sys

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from audiovisual.rendering import pdf as pdf_rendering


def test_paste_screenshot_pdf_keeps_transparent_png_background_white(tmp_path: Path) -> None:
    image_path = tmp_path / "transparent.png"
    image = Image.new("RGBA", (20, 20), (0, 0, 0, 0))
    for x in range(5, 15):
        for y in range(5, 15):
            image.putpixel((x, y), (255, 0, 0, 255))
    image.save(image_path)

    page = Image.new("RGB", (40, 40), (255, 255, 255))

    pasted = pdf_rendering._paste_screenshot_pdf(page, image_path, 0, 0, 40, 40)

    assert pasted is True
    assert page.getpixel((2, 2)) == (255, 255, 255)
    red_pixel = page.getpixel((20, 20))
    assert red_pixel[0] > 200
    assert red_pixel[1] < 80
    assert red_pixel[2] < 80


def test_build_pdf_blocks_resolves_plain_markdown_image_links(tmp_path: Path) -> None:
    frames_dir = tmp_path / "frames"
    frames_dir.mkdir()
    image_path = frames_dir / "scene 001.png"
    Image.new("RGB", (12, 12), (12, 34, 56)).save(image_path)

    markdown = "# 视听剖析报告\n\n![Scene 001](frames/scene%20001.png)\n"
    blocks = pdf_rendering.build_audiovisual_report_pdf_blocks(
        {"video_id": "demo", "scenes": []},
        report_dir=tmp_path,
        markdown_text=markdown,
    )

    assert any(block.get("type") == "image" and block.get("path") == str(image_path) for block in blocks)
