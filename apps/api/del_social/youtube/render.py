"""Thumbnails drawn by code (CLAUDE.md principle 8): the image model only ever makes a text-free
background; every letter is set here with real fonts that cover Azerbaijani and Cyrillic.

A thumbnail is layers: background (photo, frame or AI image, or a palette gradient) → darkening on
the text side → optional cut-out subject with outline and glow → text with outline, shadow and one
emphasised word → optional badge, arrow and frame. Output: 1280×720 JPEG under YouTube's 2 MB.
"""
import io
from functools import lru_cache
from pathlib import Path
from typing import Literal

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps
from pydantic import BaseModel, Field

LAYOUTS = ("left_text", "right_text", "center_big", "top_banner", "bottom_bar", "split", "corner_badge", "minimal")
PALETTES = ("red_white", "yellow_black", "neon", "clean_white", "dark_gold", "blue_orange", "pastel", "green_black")
W, H = 1280, 720
MAX_BYTES = 2 * 1024 * 1024
FONT_DIR = Path(__file__).parent / "fonts"
# style → (file, weight on the variable axis)
FONTS = {
    "bold": ("Montserrat.ttf", 900), "condensed": ("Oswald.ttf", 700), "wide": ("Unbounded.ttf", 800),
    "tech": ("Exo2.ttf", 850), "elegant": ("PlayfairDisplay.ttf", 900), "rounded": ("Comfortaa.ttf", 700),
}
# palette → text, emphasis, outline, band, gradient top, gradient bottom
PALETTE = {
    "red_white": ("#FFFFFF", "#FF2D2D", "#000000", "#E00000", "#3A0000", "#0A0A0A"),
    "yellow_black": ("#FFFFFF", "#FFD400", "#000000", "#FFD400", "#1B1B1B", "#000000"),
    "neon": ("#FFFFFF", "#39FF14", "#0A0A23", "#7B2FF7", "#1B0A3A", "#05010F"),
    "clean_white": ("#111111", "#E4002B", "#FFFFFF", "#FFFFFF", "#F4F4F4", "#D9D9D9"),
    "dark_gold": ("#FFFFFF", "#F5C542", "#000000", "#B8860B", "#1A1408", "#050505"),
    "blue_orange": ("#FFFFFF", "#FF8A00", "#0B1F4B", "#1463FF", "#0B1F4B", "#020814"),
    "pastel": ("#2B2B3A", "#FF5C8A", "#FFFFFF", "#FFD6E0", "#FDE2F3", "#C9E4FF"),
    "green_black": ("#FFFFFF", "#00E676", "#000000", "#00C853", "#062012", "#000000"),
}
FontStyle = Literal["bold", "condensed", "wide", "tech", "elegant", "rounded"]


class Spec(BaseModel):
    """Everything the owner can change; the render is a pure function of this and the layers."""

    text: str = Field(default="", max_length=60)
    language: Literal["az", "ru", "en", "tr"] = "az"  # capital letters follow the language (i → İ)
    emphasis: str = Field(default="", max_length=30)
    layout: Literal[LAYOUTS] = "left_text"  # type: ignore[valid-type]
    palette: Literal[PALETTES] = "red_white"  # type: ignore[valid-type]
    font: FontStyle = "bold"
    size: Literal["m", "l", "xl"] = "l"
    uppercase: bool = True
    outline: bool = True
    shadow: bool = True
    glow: bool = False
    darken: int = Field(default=35, ge=0, le=85)  # % on the text side
    blur: int = Field(default=0, ge=0, le=20)
    saturation: float = Field(default=1.15, ge=0.5, le=1.8)
    brightness: float = Field(default=1.0, ge=0.6, le=1.5)
    subject: Literal["none", "left", "right", "center"] = "none"  # where the cut-out goes
    subject_scale: float = Field(default=0.95, ge=0.5, le=1.2)
    subject_outline: bool = True
    badge: str = Field(default="", max_length=16)
    arrow: Literal["none", "left", "right"] = "none"
    frame: bool = False


def hex_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


@lru_cache(maxsize=64)
def font(style: str, size: int) -> ImageFont.FreeTypeFont:
    file, weight = FONTS[style]
    f = ImageFont.truetype(str(FONT_DIR / file), size)
    try:
        axes = f.get_variation_axes()
        f.set_variation_by_axes([max(a["minimum"], min(a["maximum"], weight)) if i == 0 else a["default"]
                                 for i, a in enumerate(axes)])
    except (OSError, AttributeError):
        pass  # not a variable font or FreeType without variations: the default weight
    return f


def cover(img: Image.Image, w: int = W, h: int = H) -> Image.Image:
    return ImageOps.fit(ImageOps.exif_transpose(img).convert("RGB"), (w, h), Image.LANCZOS)


def gradient(top: str, bottom: str) -> Image.Image:
    a, b = hex_rgb(top), hex_rgb(bottom)
    col = Image.new("RGB", (1, H))
    for y in range(H):
        k = y / (H - 1)
        col.putpixel((0, y), tuple(int(a[i] + (b[i] - a[i]) * k) for i in range(3)))
    return col.resize((W, H))


def _text_side(spec: Spec) -> str:
    if spec.layout in ("left_text",):
        return "left"
    if spec.layout == "right_text":
        return "right"
    if spec.layout in ("top_banner",):
        return "top"
    if spec.layout in ("bottom_bar", "minimal"):
        return "bottom"
    return "all"


def darken(img: Image.Image, side: str, strength: int) -> Image.Image:
    if strength <= 0:
        return img
    mask = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(mask)
    top = int(255 * strength / 100)
    for i in range(256):
        k = i / 255
        v = int(top * (1 - k) ** 1.4)
        if side == "left":
            x = int(W * 0.75 * k)
            d.line([(x, 0), (x, H)], fill=v, width=int(W * 0.75 / 255) + 2)
        elif side == "right":
            x = W - int(W * 0.75 * k)
            d.line([(x, 0), (x, H)], fill=v, width=int(W * 0.75 / 255) + 2)
        elif side == "top":
            y = int(H * 0.6 * k)
            d.line([(0, y), (W, y)], fill=v, width=int(H * 0.6 / 255) + 2)
        elif side == "bottom":
            y = H - int(H * 0.6 * k)
            d.line([(0, y), (W, y)], fill=v, width=int(H * 0.6 / 255) + 2)
    if side == "all":
        mask = Image.new("L", (W, H), int(top * 0.7))
    return Image.composite(Image.new("RGB", (W, H), (0, 0, 0)), img, mask)


def place_subject(base: Image.Image, cutout: Image.Image, spec: Spec, outline_rgb: tuple[int, int, int],
                  glow_rgb: tuple[int, int, int]) -> Image.Image:
    sub = cutout.convert("RGBA")
    bbox = sub.getchannel("A").getbbox()
    if bbox:
        sub = sub.crop(bbox)
    h = int(H * spec.subject_scale)
    w = max(1, int(sub.width * h / sub.height))
    if w > W * 0.7:
        w = int(W * 0.7)
        h = max(1, int(sub.height * w / sub.width))
    sub = sub.resize((w, h), Image.LANCZOS)
    x = {"left": int(W * 0.02), "right": W - w - int(W * 0.02), "center": (W - w) // 2}[spec.subject]
    y = H - h
    out = base.convert("RGBA")
    alpha = sub.getchannel("A")
    if spec.glow:
        g = alpha.filter(ImageFilter.MaxFilter(15)).filter(ImageFilter.GaussianBlur(28))
        layer = Image.new("RGBA", sub.size, glow_rgb + (0,))
        layer.putalpha(g)
        out.alpha_composite(layer, (x, y))
    if spec.subject_outline:
        ring = alpha.filter(ImageFilter.MaxFilter(13))
        layer = Image.new("RGBA", sub.size, outline_rgb + (0,))
        layer.putalpha(ring)
        out.alpha_composite(layer, (x, y))
    out.alpha_composite(sub, (x, y))
    return out.convert("RGB")


def upper(text: str, language: str) -> str:
    """Capitals as the language writes them: Azerbaijani and Turkish i → İ (ı → I stays)."""
    return (text.replace("i", "İ") if language in ("az", "tr") else text).upper()


def wrap(words: list[str], f: ImageFont.FreeTypeFont, max_w: int, max_lines: int) -> list[list[str]] | None:
    lines: list[list[str]] = [[]]
    for word in words:
        trial = " ".join(lines[-1] + [word])
        if lines[-1] and f.getlength(trial) > max_w:
            lines.append([word])
        else:
            lines[-1].append(word)
        if f.getlength(" ".join(lines[-1])) > max_w:
            return None
    return lines if len(lines) <= max_lines else None


def text_box(spec: Spec) -> tuple[int, int, int, int, str]:
    """(x0, y0, x1, y1, align) for the headline."""
    has_subject = spec.subject != "none"
    m = 56
    return {
        "left_text": (m, m, int(W * (0.58 if has_subject else 0.9)), H - m, "left"),
        "right_text": (int(W * (0.42 if has_subject else 0.1)), m, W - m, H - m, "right"),
        "center_big": (m, m, W - m, H - m, "center"),
        "top_banner": (m, 18, W - m, int(H * 0.36), "center"),
        "bottom_bar": (m, int(H * 0.66), W - m, H - 18, "center"),
        "split": (m, m, W - m, int(H * 0.42), "center"),
        "corner_badge": (m, m, int(W * 0.62), int(H * 0.5), "left"),
        "minimal": (m, int(H * 0.72), int(W * 0.8), H - 36, "left"),
    }[spec.layout]


def draw_text(img: Image.Image, spec: Spec) -> Image.Image:
    text = spec.text.strip()
    if not text:
        return img
    if spec.uppercase:
        text = upper(text, spec.language)
    words = text.split()
    emph = upper(spec.emphasis.strip(), spec.language) if spec.uppercase else spec.emphasis.strip()
    txt_c, emph_c, out_c, band_c, *_ = PALETTE[spec.palette]
    x0, y0, x1, y1, align = text_box(spec)
    box_w, box_h = x1 - x0, y1 - y0
    top_size = {"m": 110, "l": 150, "xl": 200}[spec.size] if spec.layout not in ("minimal",) else 64
    max_lines = 1 if spec.layout in ("top_banner", "bottom_bar", "minimal") else 3
    chosen = None
    for size in range(top_size, 28, -4):
        f = font(spec.font, size)
        lines = wrap(words, f, box_w, max_lines)
        if lines is None:
            continue
        line_h = int(size * 1.05)
        if line_h * len(lines) <= box_h:
            chosen = (f, size, lines, line_h)
            break
    if chosen is None:
        f = font(spec.font, 32)
        chosen = (f, 32, [words], 34)
    f, size, lines, line_h = chosen
    total_h = line_h * len(lines)
    ty = y0 + (box_h - total_h) // 2
    canvas = img.convert("RGBA")
    d = ImageDraw.Draw(canvas)
    shadow = spec.shadow
    if spec.layout in ("top_banner", "bottom_bar"):
        pad = 22
        d.rectangle([0, max(0, ty - pad), W, min(H, ty + total_h + pad)], fill=hex_rgb(band_c) + (235,))
        if spec.palette in ("yellow_black", "clean_white", "pastel"):
            # Dark letters on a light band: no dark outline or shadow, which would blur them together
            txt_c, out_c, shadow = "#111111", band_c, False
            if hex_rgb(emph_c) == hex_rgb(band_c):
                emph_c = "#E00000"
    stroke = max(3, size // 14) if spec.outline else 0
    for i, line in enumerate(lines):
        widths = [f.getlength(w) for w in line]
        space = f.getlength(" ")
        line_w = sum(widths) + space * (len(line) - 1)
        lx = {"left": x0, "right": x1 - line_w, "center": x0 + (box_w - line_w) / 2}[align]
        ly = ty + i * line_h
        for w, wd in zip(line, widths):
            colour = emph_c if emph and w.strip(".,!?:;").lower() == emph.lower() else txt_c
            if shadow:
                d.text((lx + size * 0.05, ly + size * 0.07), w, font=f, fill=(0, 0, 0, 170),
                       stroke_width=stroke, stroke_fill=(0, 0, 0, 170))
            d.text((lx, ly), w, font=f, fill=hex_rgb(colour) + (255,), stroke_width=stroke, stroke_fill=hex_rgb(out_c) + (255,))
            lx += wd + space
    return canvas.convert("RGB")


def draw_extras(img: Image.Image, spec: Spec) -> Image.Image:
    _, emph_c, out_c, band_c, *_ = PALETTE[spec.palette]
    canvas = img.convert("RGBA")
    d = ImageDraw.Draw(canvas)
    if spec.badge.strip():
        label = upper(spec.badge.strip(), spec.language)
        f = font(spec.font, 52)
        tw = int(f.getlength(label))
        right = spec.layout != "right_text"
        bx0 = W - tw - 110 if right else 40
        d.rounded_rectangle([bx0, 34, bx0 + tw + 64, 34 + 84], radius=22, fill=hex_rgb(emph_c) + (255,),
                            outline=hex_rgb(out_c) + (255,), width=5)
        d.text((bx0 + 32, 44), label, font=f, fill=(255, 255, 255, 255) if spec.palette != "yellow_black" else (0, 0, 0, 255),
               stroke_width=3, stroke_fill=hex_rgb(out_c) + (255,))
    if spec.arrow != "none":
        # A thick arrow pointing toward the subject side, in the emphasis colour with an outline
        cx, cy = (int(W * 0.56), int(H * 0.55))
        k = -1 if spec.arrow == "left" else 1
        pts = [(cx - k * 150, cy - 26), (cx + k * 20, cy - 26), (cx + k * 20, cy - 70), (cx + k * 130, cy),
               (cx + k * 20, cy + 70), (cx + k * 20, cy + 26), (cx - k * 150, cy + 26)]
        d.polygon(pts, fill=hex_rgb(emph_c) + (255,), outline=hex_rgb(out_c) + (255,), width=6)
    if spec.frame:
        d.rectangle([0, 0, W - 1, H - 1], outline=hex_rgb(band_c) + (255,), width=16)
    return canvas.convert("RGB")


def render(spec: Spec, background: Image.Image | None, cutout: Image.Image | None = None) -> bytes:
    txt_c, emph_c, out_c, band_c, top, bottom = PALETTE[spec.palette]
    base = cover(background) if background is not None else gradient(top, bottom)
    if spec.blur:
        base = base.filter(ImageFilter.GaussianBlur(spec.blur))
    if spec.saturation != 1:
        base = ImageEnhance.Color(base).enhance(spec.saturation)
    if spec.brightness != 1:
        base = ImageEnhance.Brightness(base).enhance(spec.brightness)
    base = darken(base, _text_side(spec), spec.darken)
    if cutout is not None and spec.subject != "none":
        base = place_subject(base, cutout, spec, (255, 255, 255) if spec.palette != "clean_white" else hex_rgb(emph_c), hex_rgb(emph_c))
    if spec.layout == "split":
        d = ImageDraw.Draw(base)
        d.line([(W // 2, int(H * 0.45)), (W // 2, H)], fill=hex_rgb(emph_c), width=10)
    base = draw_text(base, spec)
    base = draw_extras(base, spec)
    for q in (92, 85, 75):
        out = io.BytesIO()
        base.save(out, "JPEG", quality=q, optimize=True, progressive=True)
        if out.tell() <= MAX_BYTES:
            return out.getvalue()
    return out.getvalue()
