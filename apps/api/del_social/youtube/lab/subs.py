"""Subtitles from a transcript, by code: line breaking, timing, re-timing after cuts, SRT and styled ASS.

Transcript segments are {"start", "end", "text"} in seconds of the source video. After a cut the
same words sit at other times: retime() maps them through the kept ranges.
"""
from typing import Any, Literal

from pydantic import BaseModel, Field

from del_social.youtube.render import upper

MAX_CHARS = 42  # per line (YouTube and broadcast practice)
MAX_LINES = 2
MAX_SECONDS = 6.0
FONT_FAMILY = {"bold": "Montserrat", "condensed": "Oswald", "wide": "Unbounded", "tech": "Exo 2", "elegant": "Playfair Display",
               "rounded": "Comfortaa"}

Seg = dict[str, Any]


class SubStyle(BaseModel):
    font: Literal["bold", "condensed", "wide", "tech", "elegant", "rounded"] = "bold"
    size: Literal["s", "m", "l"] = "m"
    color: str = Field(default="#FFFFFF", pattern="^#[0-9A-Fa-f]{6}$")
    outline: str = Field(default="#000000", pattern="^#[0-9A-Fa-f]{6}$")
    box: bool = False  # a dark box behind the text instead of an outline
    position: Literal["bottom", "middle", "top"] = "bottom"
    uppercase: bool = False
    language: Literal["az", "ru", "en", "tr"] = "az"


def from_chunks(chunks: list[dict[str, Any]]) -> list[Seg]:
    """Whisper chunks ({"timestamp": [start, end], "text"}) → clean segments."""
    out: list[Seg] = []
    for c in chunks:
        ts = c.get("timestamp") or [None, None]
        start, end = ts[0], ts[1]
        text = " ".join((c.get("text") or "").split())
        if start is None or not text:
            continue
        end = end if end is not None and end > start else start + 2.0
        out.append({"start": round(float(start), 2), "end": round(float(end), 2), "text": text})
    return out


def wrap(text: str) -> list[str]:
    lines: list[str] = [""]
    for w in text.split():
        if lines[-1] and len(lines[-1]) + 1 + len(w) > MAX_CHARS:
            lines.append(w)
        else:
            lines[-1] = f"{lines[-1]} {w}".strip()
    return lines


def cues(segs: list[Seg]) -> list[Seg]:
    """Segments → subtitle cues of at most 2 lines and 6 seconds, time split by length of text."""
    out: list[Seg] = []
    for s in segs:
        lines = wrap(s["text"])
        groups = [lines[i:i + MAX_LINES] for i in range(0, len(lines), MAX_LINES)]
        dur = s["end"] - s["start"]
        chars = sum(len(" ".join(g)) for g in groups) or 1
        t = s["start"]
        for g in groups:
            share = dur * len(" ".join(g)) / chars
            end = min(t + max(share, 0.8), s["end"]) if len(groups) > 1 else s["end"]
            start = t
            while end - start > MAX_SECONDS:  # very long cue: keep it on screen at most 6 s at a time
                out.append({"start": round(start, 2), "end": round(start + MAX_SECONDS, 2), "lines": g})
                start += MAX_SECONDS
            out.append({"start": round(start, 2), "end": round(end, 2), "lines": g})
            t = end
    return out


def retime(segs: list[Seg], ranges: list[tuple[float, float]], speed: float = 1.0) -> list[Seg]:
    """Map source times to the output timeline of kept ranges; parts inside cut-out silences disappear."""
    out: list[Seg] = []
    offset = 0.0
    for rs, re_ in ranges:
        for s in segs:
            a, b = max(s["start"], rs), min(s["end"], re_)
            if b - a >= 0.2:
                out.append({"start": round((offset + a - rs) / speed, 2), "end": round((offset + b - rs) / speed, 2), "text": s["text"]})
        offset += re_ - rs
    out.sort(key=lambda x: x["start"])
    return out


def _t(sec: float, sep: str = ",") -> str:
    ms = int(round(sec * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def srt(segs: list[Seg]) -> str:
    return "\n".join(f"{i}\n{_t(c['start'])} --> {_t(c['end'])}\n" + "\n".join(c["lines"]) + "\n"
                     for i, c in enumerate(cues(segs), 1))


def _ass_color(hex_: str, alpha: int = 0) -> str:
    r, g, b = hex_[1:3], hex_[3:5], hex_[5:7]
    return f"&H{alpha:02X}{b}{g}{r}".upper()


def _ass_t(sec: float) -> str:
    cs = int(round(sec * 100))
    h, cs = divmod(cs, 360_000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _esc(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "(").replace("}", ")")


def ass(segs: list[Seg], style: SubStyle, width: int, height: int, hook: str | None = None) -> str:
    """Styled subtitles (and an optional headline at the top) for burning in with FFmpeg."""
    base = min(width, height)
    size = int(base * {"s": 0.045, "m": 0.06, "l": 0.075}[style.size])
    align = {"bottom": 2, "middle": 5, "top": 8}[style.position]
    margin = int(height * (0.12 if width < height else 0.07))
    border = 3 if style.box else 1
    back = _ass_color("#000000", 0x60)
    outline_w = max(2, size // 12) if not style.box else max(4, size // 6)
    header = (
        "[Script Info]\nScriptType: v4.00+\nWrapStyle: 2\nScaledBorderAndShadow: yes\n"
        f"PlayResX: {width}\nPlayResY: {height}\n\n[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, "
        "StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Sub,{FONT_FAMILY[style.font]},{size},{_ass_color(style.color)},{_ass_color(style.color)},"
        f"{_ass_color(style.outline if not style.box else '#000000', 0x60 if style.box else 0)},{back},-1,0,0,0,100,100,0,0,"
        f"{border},{outline_w},0,{align},60,60,{margin},1\n"
        f"Style: Hook,{FONT_FAMILY[style.font]},{int(size * 1.25)},{_ass_color('#FFD400')},{_ass_color('#FFD400')},"
        f"{_ass_color('#000000')},{back},-1,0,0,0,100,100,0,0,1,{outline_w + 2},0,8,60,60,{int(height * 0.08)},1\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    lines = []
    end_all = 0.0
    for c in cues(segs):
        text = "\\N".join(c["lines"])
        if style.uppercase:
            text = upper(text, style.language)
        lines.append(f"Dialogue: 0,{_ass_t(c['start'])},{_ass_t(c['end'])},Sub,,0,0,0,,{_esc(text)}")
        end_all = max(end_all, c["end"])
    if hook:
        lines.append(f"Dialogue: 1,{_ass_t(0)},{_ass_t(max(end_all, 3.0))},Hook,,0,0,0,,{_esc(upper(hook, style.language))}")
    return header + "\n".join(lines) + "\n"
