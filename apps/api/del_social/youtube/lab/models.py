"""The AI video models a creator can choose from, and what each costs in credits.

Models are configuration, not code (CLAUDE.md, fal.ai row): ids and request shapes can be replaced
with VIDEO_MODELS_JSON without a release. Credits per second are proposals (ADR 012). The payload
template's {prompt}, {duration}, {aspect} and {image_url} are filled in by code.
"""
import json
import math
from typing import Any

from pydantic import BaseModel

from del_social.core.config import get_settings


class VideoModel(BaseModel):
    key: str
    name: str  # shown in the panel
    tier: str  # fast | standard | premium
    text_model: str
    image_model: str | None = None  # image-to-video version, when the model has one
    durations: list[int]
    aspects: list[str]
    credits_per_second: int
    audio: bool = False
    payload: dict[str, Any]
    duration_format: str = "{n}"  # how the model wants the number: "{n}", "{n}s"


DEFAULT = [
    VideoModel(key="fast", name="Fast (Wan)", tier="fast", text_model="fal-ai/wan/v2.2-a14b/text-to-video",
               image_model="fal-ai/wan/v2.2-a14b/image-to-video", durations=[5], aspects=["16:9", "9:16", "1:1"], credits_per_second=2,
               payload={"prompt": "{prompt}", "aspect_ratio": "{aspect}"}),
    VideoModel(key="standard", name="Standard (Kling)", tier="standard", text_model="fal-ai/kling-video/v2.1/standard/text-to-video",
               image_model="fal-ai/kling-video/v2.1/standard/image-to-video", durations=[5, 10], aspects=["16:9", "9:16", "1:1"],
               credits_per_second=4, payload={"prompt": "{prompt}", "duration": "{duration}", "aspect_ratio": "{aspect}"}),
    VideoModel(key="premium", name="Premium with sound (Veo)", tier="premium", text_model="fal-ai/veo3/fast",
               image_model="fal-ai/veo3/fast/image-to-video", durations=[8], aspects=["16:9", "9:16"], credits_per_second=9, audio=True,
               payload={"prompt": "{prompt}", "duration": "{duration}", "aspect_ratio": "{aspect}", "generate_audio": True},
               duration_format="{n}s"),
]


def catalog() -> list[VideoModel]:
    raw = get_settings().video_models_json.strip()
    if raw:
        return [VideoModel.model_validate(m) for m in json.loads(raw)]
    return DEFAULT


def get(key: str) -> VideoModel:
    for m in catalog():
        if m.key == key:
            return m
    raise KeyError(key)


def credits_for(model: VideoModel, seconds: int, clips: int = 1) -> int:
    return model.credits_per_second * seconds * clips


def payload(model: VideoModel, prompt: str, seconds: int, aspect: str, image_url: str | None) -> dict[str, Any]:
    values = {"prompt": prompt, "duration": model.duration_format.format(n=seconds), "aspect": aspect}

    def fill(v: Any) -> Any:
        if isinstance(v, str) and v.startswith("{") and v.endswith("}"):
            return values.get(v[1:-1], v)
        return v

    out = {k: fill(v) for k, v in model.payload.items()}
    if image_url:
        out["image_url"] = image_url
    return out


def minutes_credits(seconds: float, per_minute: int) -> int:
    """Rendering: per started minute of output."""
    return max(1, math.ceil(seconds / 60)) * per_minute
