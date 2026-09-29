"""FFmpeg for the video lab: probing, silence detection, cutting, reframing, subtitles, loudness.

Every time and range is computed here by code (CLAUDE.md principle 2): a model may choose *which*
transcript segments make a Short, never the seconds. FFmpeg runs niced, one job at a time for the
whole server (a small VPS also serves the API), with a hard timeout.
"""
import asyncio
import json
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

log = logging.getLogger(__name__)

ONE_AT_A_TIME = asyncio.Semaphore(1)
TIMEOUT_S = 3 * 3600
ENCODE = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p", "-threads", "2",
          "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart"]
LOUDNESS = "loudnorm=I=-14:TP=-1.5:LRA=11"  # YouTube plays at about -14 LUFS
SILENCE = {"gentle": (-38, 1.2, 0.35), "normal": (-34, 0.7, 0.25), "tight": (-30, 0.45, 0.15)}  # dB, min seconds, padding
MAX_RANGES = 400

Progress = Callable[[int], Awaitable[None]]
Range = tuple[float, float]


class FFmpegError(RuntimeError):
    """Safe to show (no paths of other companies)."""


@dataclass(frozen=True)
class Probe:
    duration: float
    width: int | None
    height: int | None
    has_audio: bool


async def _exec(*args: str, timeout: float = 120) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout)
    except TimeoutError:
        proc.kill()
        raise FFmpegError("The video took too long to process") from None
    return proc.returncode or 0, out.decode(errors="replace"), err.decode(errors="replace")


async def probe(path: Path) -> Probe:
    code, out, _ = await _exec("ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path))
    if code != 0:
        raise FFmpegError("This file is not a readable video")
    data = json.loads(out or "{}")
    streams = data.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video is None:
        raise FFmpegError("This file has no video")
    duration = float((data.get("format") or {}).get("duration") or video.get("duration") or 0)
    return Probe(duration=duration, width=video.get("width"), height=video.get("height"),
                 has_audio=any(s.get("codec_type") == "audio" for s in streams))


async def run(args: list[str], duration: float, progress: Progress | None = None) -> None:
    """ffmpeg with progress (0–100) reported from its -progress output."""
    cmd = ["nice", "-n", "10", "ffmpeg", "-y", "-hide_banner", "-nostdin", "-loglevel", "error", "-progress", "pipe:1", *args]
    async with ONE_AT_A_TIME:
        proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        last = -1

        async def read() -> None:
            nonlocal last
            assert proc.stdout
            async for raw in proc.stdout:
                line = raw.decode(errors="replace").strip()
                if line.startswith("out_time_us=") and duration > 0 and progress:
                    try:
                        pct = min(99, int(int(line.split("=")[1]) / 1_000_000 / duration * 100))
                    except ValueError:
                        continue
                    if pct >= last + 5:
                        last = pct
                        await progress(pct)

        try:
            await asyncio.wait_for(asyncio.gather(read(), proc.wait()), TIMEOUT_S)
        except TimeoutError:
            proc.kill()
            raise FFmpegError("The video took too long to process") from None
        err = (await proc.stderr.read()).decode(errors="replace") if proc.stderr else ""
        if proc.returncode != 0:
            log.warning("ffmpeg failed: %s", err[-800:])
            raise FFmpegError("The video could not be processed")


# --- silence ---

_START = re.compile(r"silence_start: (-?[\d.]+)")
_END = re.compile(r"silence_end: ([\d.]+)")


def parse_silences(stderr: str) -> list[Range]:
    out: list[Range] = []
    start: float | None = None
    for line in stderr.splitlines():
        if m := _START.search(line):
            start = max(0.0, float(m.group(1)))
        elif (m := _END.search(line)) and start is not None:
            out.append((start, float(m.group(1))))
            start = None
    return out


async def silences(path: Path, level: str) -> list[Range]:
    db, min_s, _ = SILENCE[level]
    async with ONE_AT_A_TIME:
        code, _, err = await _exec("nice", "-n", "10", "ffmpeg", "-hide_banner", "-nostdin", "-i", str(path),
                                   "-af", f"silencedetect=noise={db}dB:d={min_s}", "-vn", "-f", "null", "-", timeout=TIMEOUT_S)
    if code != 0:
        raise FFmpegError("The sound of this video could not be read")
    return parse_silences(err)


def keep_ranges(duration: float, quiet: list[Range], pad: float) -> list[Range]:
    """The parts to keep: everything except the silences, each silence shortened by `pad` on both sides."""
    keep: list[Range] = []
    cursor = 0.0
    for s, e in sorted(quiet):
        cut_s, cut_e = s + pad, e - pad
        if cut_e - cut_s <= 0.05:
            continue
        if cut_s > cursor:
            keep.append((round(cursor, 3), round(cut_s, 3)))
        cursor = max(cursor, cut_e)
    if duration - cursor > 0.05:
        keep.append((round(cursor, 3), round(duration, 3)))
    return merge_close(keep)


def merge_close(ranges: list[Range], gap: float = 0.08) -> list[Range]:
    """Join ranges separated by tiny gaps and cap how many there are (FFmpeg's filter stays small)."""
    out: list[Range] = []
    for s, e in sorted(ranges):
        if out and s - out[-1][1] <= gap:
            out[-1] = (out[-1][0], max(out[-1][1], e))
        else:
            out.append((s, e))
    while len(out) > MAX_RANGES:  # join the pair with the smallest gap
        i = min(range(len(out) - 1), key=lambda k: out[k + 1][0] - out[k][1])
        out[i:i + 2] = [(out[i][0], out[i + 1][1])]
    return out


def total(ranges: list[Range]) -> float:
    return round(sum(e - s for s, e in ranges), 3)


# --- filters ---

Frame = Literal["original", "vertical_center", "vertical_blur", "square", "landscape"]
SIZES = {"vertical_center": (1080, 1920), "vertical_blur": (1080, 1920), "square": (1080, 1080), "landscape": (1920, 1080)}


def graph(ranges: list[Range] | None, has_audio: bool, *, frame: Frame = "original", speed: float = 1.0,
          loudness: bool = False, subtitles: Path | None = None, fonts: Path | None = None, crop_x: float = 0.5) -> tuple[str, list[str]]:
    """One -filter_complex for: keep ranges → speed → reframe → burned subtitles → loudness. Returns (graph, maps)."""
    parts: list[str] = []
    v, a = "0:v", "0:a" if has_audio else None
    if ranges:
        for i, (s, e) in enumerate(ranges):
            parts.append(f"[0:v]trim=start={s}:end={e},setpts=PTS-STARTPTS[v{i}]")
            if has_audio:
                parts.append(f"[0:a]atrim=start={s}:end={e},asetpts=PTS-STARTPTS[a{i}]")
        n = len(ranges)
        ins = "".join(f"[v{i}]" + (f"[a{i}]" if has_audio else "") for i in range(n))
        parts.append(f"{ins}concat=n={n}:v=1:a={1 if has_audio else 0}[vc]" + ("[ac]" if has_audio else ""))
        v, a = "vc", "ac" if has_audio else None
    if speed != 1.0:
        parts.append(f"[{v}]setpts=PTS/{speed}[vs]")
        v = "vs"
        if a:
            parts.append(f"[{a}]atempo={speed}[as]")
            a = "as"
    if frame != "original":
        w, h = SIZES[frame]
        if frame == "vertical_blur":
            parts.append(f"[{v}]split[bg0][fg0];[bg0]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},boxblur=24:2[bg];"
                         f"[fg0]scale={w}:-2[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1[vf]")
        else:
            parts.append(f"[{v}]scale={w}:{h}:force_original_aspect_ratio=increase,"
                         f"crop={w}:{h}:(iw-ow)*{min(1.0, max(0.0, crop_x))}:(ih-oh)/2,setsar=1[vf]")
        v = "vf"
    if subtitles is not None:
        fontsdir = f":fontsdir='{fonts}'" if fonts else ""
        parts.append(f"[{v}]subtitles='{subtitles}'{fontsdir}[vt]")
        v = "vt"
    if a and loudness:
        parts.append(f"[{a}]{LOUDNESS}[al]")
        a = "al"
    maps = ["-map", f"[{v}]" if parts and v not in ("0:v",) else "0:v"]
    if a:
        maps += ["-map", f"[{a}]" if a != "0:a" else "0:a"]
    return ";".join(parts), maps


async def render(src: Path, dst: Path, duration_out: float, has_audio: bool, progress: Progress | None = None, **kw) -> None:
    g, maps = graph(kw.pop("ranges", None), has_audio, **kw)
    args = ["-i", str(src)]
    if g:
        args += ["-filter_complex", g]
    await run([*args, *maps, *ENCODE, str(dst)], duration_out, progress)


async def audio_for_transcription(src: Path, dst: Path) -> None:
    """Mono 16 kHz MP3 at 48 kb/s: small enough to send, clear enough for speech recognition."""
    await run(["-i", str(src), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "libmp3lame", "-b:a", "48k", str(dst)], 0)


async def concat(clips: list[Path], dst: Path, duration_out: float, progress: Progress | None = None) -> None:
    """Join generated clips (same size) end to end."""
    inputs: list[str] = []
    for c in clips:
        inputs += ["-i", str(c)]
    ins = "".join(f"[{i}:v]" for i in range(len(clips)))
    g = f"{ins}concat=n={len(clips)}:v=1:a=0[v]"
    await run([*inputs, "-filter_complex", g, "-map", "[v]", "-an", *ENCODE[:10], "-movflags", "+faststart", str(dst)], duration_out, progress)
