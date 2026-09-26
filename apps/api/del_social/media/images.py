"""Photo preparation by code, never by an image model (docs/phase-1-plan.md §3, CLAUDE.md rule 8).

inspect(): validates an upload (real image, allowed format, size limits).
render():  one publishable variant: EXIF orientation, sRGB, crop to the target ratio
           around a focal point, resize, optional gentle tone correction (luminance only,
           colours unchanged), optional logo in a corner, JPEG without metadata.
The product in the photo is never altered: only framing, overall tone and the logo.
"""
import io
from dataclasses import dataclass

from PIL import Image, ImageCms, ImageOps
from pillow_heif import register_heif_opener

register_heif_opener()  # iPhone photos (HEIC)

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_PIXELS = 60_000_000  # decompression-bomb guard (≈ 60 MP)
MIN_SIDE = 320  # photos
MIN_LOGO_SIDE = 64
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP", "HEIF", "MPO"}
Image.MAX_IMAGE_PIXELS = MAX_PIXELS

# name → (width, height); height None = fit inside a width×width box without cropping
VARIANTS: dict[str, tuple[int, int | None]] = {
    "thumb": (480, None),
    "full": (2048, None),  # input for AI edits: large, uncropped, untouched tone
    "analysis": (1280, None),  # what the Photo Analyst sees (not served publicly)
    "feed": (1080, 1350),  # Instagram portrait 4:5
    "square": (1080, 1080),
    "landscape": (1080, 566),  # Instagram's widest ratio, 1.91:1 (wide renders keep their width)
}
ENHANCE_STRENGTH = 0.5
LOGO_WIDTH = 0.16  # of the image width
LOGO_MARGIN = 0.04


class ImageRejected(ValueError):
    """Safe to show to the user."""


@dataclass(frozen=True)
class ImageInfo:
    format: str
    width: int
    height: int
    has_alpha: bool


def inspect(data: bytes, min_side: int = MIN_SIDE) -> ImageInfo:
    if len(data) > MAX_UPLOAD_BYTES:
        raise ImageRejected(f"File is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB")
    try:
        with Image.open(io.BytesIO(data)) as img:
            img.verify()
        with Image.open(io.BytesIO(data)) as img:  # verify() leaves the image unusable
            fmt = img.format or ""
            img = ImageOps.exif_transpose(img)
            width, height = img.size
            has_alpha = img.mode in ("RGBA", "LA", "PA") or "transparency" in img.info
    except Image.DecompressionBombError:
        raise ImageRejected("Image has too many pixels") from None
    except Exception:
        raise ImageRejected("This file is not a readable image") from None
    if fmt not in ALLOWED_FORMATS:
        raise ImageRejected("Use JPEG, PNG, WEBP or HEIC")
    if min(width, height) < min_side:
        raise ImageRejected(f"Image is too small (minimum {min_side} px on the short side)")
    return ImageInfo(fmt, width, height, has_alpha)


def _to_srgb(img: Image.Image) -> Image.Image:
    icc = img.info.get("icc_profile")
    if icc:
        try:
            src = ImageCms.ImageCmsProfile(io.BytesIO(icc))
            dst = ImageCms.createProfile("sRGB")
            img = ImageCms.profileToProfile(img, src, dst, outputMode="RGB")
        except Exception:
            pass  # unreadable profile: keep the pixels as they are
    return img


def _load(data: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(data))
    img = ImageOps.exif_transpose(img)
    img = _to_srgb(img)
    if img.mode in ("RGBA", "LA", "PA", "P"):
        img = img.convert("RGBA")
        background = Image.new("RGB", img.size, (255, 255, 255))
        background.paste(img, mask=img.getchannel("A"))
        return background
    return img.convert("RGB")


def _crop(img: Image.Image, ratio: float, fx: float, fy: float) -> Image.Image:
    """Largest crop with the target ratio, centred on the focal point as far as possible."""
    w, h = img.size
    if w / h > ratio:
        cw, ch = round(h * ratio), h
    else:
        cw, ch = w, round(w / ratio)
    left = min(max(round(fx * w - cw / 2), 0), w - cw)
    top = min(max(round(fy * h - ch / 2), 0), h - ch)
    return img.crop((left, top, left + cw, top + ch))


def _logo(img: Image.Image, logo_data: bytes) -> Image.Image:
    logo = Image.open(io.BytesIO(logo_data))
    logo = ImageOps.exif_transpose(logo).convert("RGBA")
    target_w = max(1, round(img.width * LOGO_WIDTH))
    logo = logo.resize((target_w, max(1, round(logo.height * target_w / logo.width))), Image.LANCZOS)
    margin = round(img.width * LOGO_MARGIN)
    out = img.convert("RGBA")
    out.alpha_composite(logo, (img.width - logo.width - margin, img.height - logo.height - margin))
    return out.convert("RGB")


def render(
    data: bytes,
    variant: str,
    *,
    focal: tuple[float, float] = (0.5, 0.5),
    enhance: bool = True,
    logo_data: bytes | None = None,
) -> bytes:
    width, height = VARIANTS[variant]
    img = _load(data)
    if height is None:
        img.thumbnail((width, width), Image.LANCZOS)
    else:
        img = _crop(img, width / height, *focal).resize((width, height), Image.LANCZOS)
    if enhance:
        # Brightness/contrast stretch on luminance only (preserve_tone), applied at half strength
        # so flat or dark photos are lifted gently and colours stay true
        stretched = ImageOps.autocontrast(img, cutoff=0.5, preserve_tone=True)
        img = Image.blend(img, stretched, ENHANCE_STRENGTH)
    if logo_data is not None and variant != "thumb":
        img = _logo(img, logo_data)
    out = io.BytesIO()
    img.save(out, "JPEG", quality=90, optimize=True, progressive=True)  # no EXIF: no GPS leaks
    return out.getvalue()
