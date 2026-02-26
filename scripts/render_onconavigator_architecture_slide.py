#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter

WIDTH = 1920
HEIGHT = 1080
OUTPUT = Path('/Users/meledre/PycharmProjects/OncoAI/output/pitch/onconavigator_architecture_business_slide.png')

FONT_CANDIDATES = [
    '/System/Library/Fonts/Supplemental/Arial.ttf',
    '/System/Library/Fonts/Supplemental/Arial Unicode.ttf',
    '/Library/Fonts/Arial Unicode.ttf',
]


def pick_font_path() -> str:
    for p in FONT_CANDIDATES:
        if Path(p).exists():
            return p
    raise FileNotFoundError('No suitable font found for Cyrillic text rendering')


def load_font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size=size)


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip('#')
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))


def blend(c1: tuple[int, int, int], c2: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return (
        int(c1[0] * (1 - t) + c2[0] * t),
        int(c1[1] * (1 - t) + c2[1] * t),
        int(c1[2] * (1 - t) + c2[2] * t),
    )


def draw_vertical_gradient(img: Image.Image, top: str, bottom: str) -> None:
    top_rgb = hex_to_rgb(top)
    bottom_rgb = hex_to_rgb(bottom)
    draw = ImageDraw.Draw(img)
    for y in range(HEIGHT):
        t = y / max(HEIGHT - 1, 1)
        color = blend(top_rgb, bottom_rgb, t)
        draw.line((0, y, WIDTH, y), fill=color)


def draw_background() -> Image.Image:
    img = Image.new('RGBA', (WIDTH, HEIGHT), (255, 255, 255, 255))
    draw_vertical_gradient(img, '#F3F7FC', '#E6EDF7')

    # Soft ambient geometric accents.
    accent = Image.new('RGBA', (WIDTH, HEIGHT), (0, 0, 0, 0))
    ad = ImageDraw.Draw(accent)
    ad.ellipse((-220, -260, 680, 620), fill=(36, 87, 141, 42))
    ad.ellipse((1240, -200, 2140, 700), fill=(20, 133, 152, 32))
    ad.ellipse((580, 760, 1620, 1460), fill=(31, 68, 119, 26))
    accent = accent.filter(ImageFilter.GaussianBlur(radius=42))
    return Image.alpha_composite(img, accent)


def draw_shadow(base: Image.Image, box: tuple[int, int, int, int], radius: int, dy: int = 10, alpha: int = 65) -> None:
    shadow = Image.new('RGBA', (WIDTH, HEIGHT), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    x1, y1, x2, y2 = box
    sd.rounded_rectangle((x1, y1 + dy, x2, y2 + dy), radius=radius, fill=(10, 28, 54, alpha))
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=10))
    base.alpha_composite(shadow)


def center_text_block(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    lines: list[tuple[str, ImageFont.FreeTypeFont, tuple[int, int, int]]],
    line_gap: int = 8,
) -> None:
    x1, y1, x2, y2 = box
    widths = []
    heights = []
    for text, font, _ in lines:
        bbox = draw.textbbox((0, 0), text, font=font)
        widths.append(bbox[2] - bbox[0])
        heights.append(bbox[3] - bbox[1])

    total_h = sum(heights) + line_gap * (len(lines) - 1)
    y = y1 + (y2 - y1 - total_h) // 2

    for i, (text, font, color) in enumerate(lines):
        w = widths[i]
        h = heights[i]
        x = x1 + (x2 - x1 - w) // 2
        draw.text((x, y), text, font=font, fill=color)
        y += h + line_gap


def draw_card(
    base: Image.Image,
    box: tuple[int, int, int, int],
    fill: str,
    stroke: str,
    title: str,
    body: list[str],
    title_font: ImageFont.FreeTypeFont,
    body_font: ImageFont.FreeTypeFont,
) -> None:
    radius = 28
    draw_shadow(base, box, radius=radius)
    draw = ImageDraw.Draw(base)
    draw.rounded_rectangle(box, radius=radius, fill=hex_to_rgb(fill), outline=hex_to_rgb(stroke), width=2)

    lines: list[tuple[str, ImageFont.FreeTypeFont, tuple[int, int, int]]] = [(title, title_font, (244, 248, 255))]
    for line in body:
        lines.append((line, body_font, (229, 240, 255)))

    center_text_block(draw, box, lines, line_gap=10)


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    font_path = pick_font_path()

    f_title = load_font(font_path, 72)
    f_subtitle = load_font(font_path, 52)
    f_top_title = load_font(font_path, 33)
    f_top_body = load_font(font_path, 22)
    f_card_title = load_font(font_path, 36)
    f_card_body = load_font(font_path, 27)
    f_footer = load_font(font_path, 32)

    img = draw_background()
    draw = ImageDraw.Draw(img)

    # Header
    draw.text((90, 54), 'ОнкоНавигатор', font=f_title, fill=(24, 48, 86))
    draw.text((92, 145), 'Архитектура платформы клинической верификации', font=f_subtitle, fill=(57, 89, 129))

    # Geometry
    top_box = (620, 238, 1300, 394)
    left_box = (90, 430, 500, 802)
    center_box = (560, 410, 1360, 790)
    right_box = (1420, 430, 1830, 802)
    bottom_box = (460, 838, 1460, 992)

    draw_card(
        img,
        top_box,
        fill='#355D92',
        stroke='#6D8DB7',
        title='Deployment & Scale',
        body=['Cloud UI + Local Core   •   BFF/API Layer', 'Quality Gates & Observability'],
        title_font=f_top_title,
        body_font=f_top_body,
    )

    draw_card(
        img,
        left_box,
        fill='#2E466A',
        stroke='#5A7398',
        title='Channels',
        body=['Врач', 'Пациент', 'Администратор'],
        title_font=f_card_title,
        body_font=f_card_body,
    )

    draw_card(
        img,
        center_box,
        fill='#1E6D77',
        stroke='#5FA9B2',
        title='ОнкоНавигатор Clinical Intelligence Core',
        body=['Analyze Orchestration   •   Decision Support', 'Role-Aware Responses'],
        title_font=load_font(font_path, 34),
        body_font=load_font(font_path, 26),
    )

    draw_card(
        img,
        right_box,
        fill='#225B74',
        stroke='#5D8CA3',
        title='AI & Evidence Engine',
        body=['RAG Retrieval + Rerank', 'LLM + Deterministic Fallback', 'Evidence Integrity'],
        title_font=load_font(font_path, 31),
        body_font=load_font(font_path, 23),
    )

    draw_card(
        img,
        bottom_box,
        fill='#344A67',
        stroke='#6F87A6',
        title='Trust & Security',
        body=['RBAC & Session Controls   •   PII Redaction   •   Audit Trail & Compliance'],
        title_font=load_font(font_path, 33),
        body_font=load_font(font_path, 22),
    )

    # Connectors
    connector = (69, 94, 128)
    draw.line((500, 615, 560, 615), fill=connector, width=7)
    draw.line((1360, 615, 1420, 615), fill=connector, width=7)
    draw.line((960, 394, 960, 410), fill=connector, width=7)
    draw.line((960, 790, 960, 838), fill=connector, width=7)

    # Footer
    draw.text(
        (170, 1022),
        'Быстрее клиническая верификация, объяснимые рекомендации, governance-by-design',
        font=f_footer,
        fill=(33, 63, 101),
    )

    img.save(OUTPUT)


if __name__ == '__main__':
    main()
