"""Reports and ideas in the reader's language: translated on first view, then cached on the row.

A report is written once, in the channel's report language. When someone reads it in another panel
language, its text fields are translated (fast model) and kept in output["_i18n"][lang], so the
next reader gets it at once. Code decides what is text: numbers, ids, names of grades and formats
(shown through the panel's own translations), video titles, hooks and keywords are never sent.
"""
import asyncio
import copy
import logging
import uuid
from typing import Any

from del_social.agents import youtube as agents
from del_social.llm import LLM, LLMError
from del_social.team import texts

log = logging.getLogger(__name__)

LANGS = ("az", "ru", "en", "fa")
# Keys whose values are not prose for the reader: enums the panel translates itself, ids, the
# creator's own material (titles, hooks, keywords stay in the video's language) and references.
KEEP = {"lang", "_i18n", "video_id", "area", "grade", "effort", "impact", "format", "difficulty", "style",
        "title_video", "hook", "keywords", "evidence", "url", "time", "seconds"}


def source_lang(output: dict[str, Any]) -> str:
    if output.get("lang") in LANGS:
        return output["lang"]
    sample = " ".join(str(output.get(k) or "") for k in ("headline", "summary", "angle", "why"))
    return texts.detect(sample) or texts.DEFAULT


def _leaves(obj: Any, path: tuple = ()) -> list[tuple[tuple, str]]:
    out: list[tuple[tuple, str]] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k not in KEEP:
                out += _leaves(v, (*path, k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out += _leaves(v, (*path, i))
    elif isinstance(obj, str) and any(ch.isalpha() for ch in obj):
        out.append((path, obj))
    return out


def _put(obj: Any, path: tuple, value: str) -> None:
    for p in path[:-1]:
        obj = obj[p]
    obj[path[-1]] = value


async def translate(llm: LLM, tenant_id: uuid.UUID, obj: dict[str, Any], lang: str) -> dict[str, Any] | None:
    """A translated copy of `obj` (same shape; untranslated leaves keep the original), or None on failure."""
    body = {k: v for k, v in obj.items() if k not in ("_i18n",)}
    leaves = _leaves(body)
    if not leaves:
        return body
    listing = "\n".join(f"{i}: {text}" for i, (_, text) in enumerate(leaves))
    try:
        out = (await agents.translate_segments(llm, tenant_id, f"<language>{lang}</language>\n<segments>\n{listing}\n</segments>",
                                               prompt="yt_translate")).output
    except LLMError as e:
        log.warning("report translation failed: %s", e)
        return None
    result = copy.deepcopy(body)
    by_index = {s.index: s.text for s in out.segments}
    for i, (path, _) in enumerate(leaves):
        if by_index.get(i, "").strip():
            _put(result, path, by_index[i])
    result["lang"] = lang
    return result


async def localized(llm: LLM | None, tenant_id: uuid.UUID, output: dict[str, Any] | None, lang: str | None) -> tuple[dict[str, Any] | None, bool]:
    """(what to show, whether `output` gained a cached translation and should be saved)."""
    if not output or not lang or lang not in LANGS or source_lang(output) == lang:
        return output, False
    cached = (output.get("_i18n") or {}).get(lang)
    if cached:
        return cached, False
    if llm is None:
        return output, False
    done = await translate(llm, tenant_id, output, lang)
    if done is None:
        return output, False
    output.setdefault("_i18n", {})[lang] = done
    return done, True


async def localize_many(llm: LLM | None, tenant_id: uuid.UUID, outputs: list[dict[str, Any] | None], lang: str | None
                        ) -> list[tuple[dict[str, Any] | None, bool]]:
    return list(await asyncio.gather(*(localized(llm, tenant_id, o, lang) for o in outputs)))
