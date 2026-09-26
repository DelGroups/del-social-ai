"""Deterministic Brand Guardian checks: rules that code can decide with certainty, no LLM.

Each finding has a severity: "block" (must never be published) or "fix" (send back to the
Copywriter). The LLM review adds judgement-based findings on top (spelling, tone, claims).
"""
import re
from dataclasses import dataclass
from typing import Literal

from del_social.agents.common import Brief
from del_social.knowledge.brand_profile import BrandProfile

Severity = Literal["fix", "block"]

INSTAGRAM_CAPTION_LIMIT = 2200
INSTAGRAM_HASHTAG_LIMIT = 30

HASHTAG_RE = re.compile(r"^#[\w]+$", re.UNICODE)
CYRILLIC_RE = re.compile(r"[Ѐ-ӿ]")
AZ_SPECIFIC_RE = re.compile(r"[əğıöüşçƏĞİÖÜŞÇ]")
# Letters Azerbaijani doesn't use; a common sign of Turkic-language mix-ups
FOREIGN_LETTERS_RE = re.compile(r"[äÄñÑßéèêàáíóúâ]")
PHONE_RE = re.compile(r"(\+?\d[\d\s\-()]{7,}\d)")
URL_RE = re.compile(r"(https?://|www\.)\S+|\b[\w-]+\.(com|az|ru|net|org)\b", re.IGNORECASE)
PRICE_RE = re.compile(
    r"(\d[\d\s.,]*\s*(azn|₼|manat\w*|man\.?|\$|usd|eur|€|руб\w*|ман|манат\w*)(?!\w))"
    r"|((azn|₼|\$|€)\s*\d)"
    r"|(\d+\s*%)|(%\s*\d+)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Finding:
    code: str
    severity: Severity
    message: str  # English, for the Copywriter and the reviewer


def az_lower(text: str) -> str:
    """Lowercase with Azerbaijani/Turkish dotted and dotless i handled correctly."""
    return text.replace("I", "ı").replace("İ", "i").lower()


def _word_hits(text: str, words: list[str]) -> list[str]:
    """Words or phrases that occur as whole words (any case, also as a word prefix: 'ucuzluq' hits 'ucuz')."""
    haystack = az_lower(text)
    hits = []
    for w in words:
        needle = az_lower(w.strip())
        if needle and re.search(rf"(?<!\w){re.escape(needle)}", haystack):
            hits.append(w.strip())
    return hits


def check_option(
    profile: BrandProfile,
    brief: Brief,
    caption_az: str,
    caption_ru: str,
    hashtags: list[str],
    full_caption: str,
) -> list[Finding]:
    f: list[Finding] = []
    body = f"{caption_az}\n{caption_ru}"
    uses_az = profile.languages.mode.value in ("az_ru_same_caption", "az", "alternate")
    uses_ru = profile.languages.mode.value in ("az_ru_same_caption", "ru")

    if uses_az and not caption_az.strip():
        f.append(Finding("missing_az", "fix", "The Azerbaijani part is empty."))
    if uses_ru and not caption_ru.strip():
        f.append(Finding("missing_ru", "fix", "The Russian part is empty."))
    if CYRILLIC_RE.search(caption_az):
        f.append(Finding("az_has_cyrillic", "fix", "The Azerbaijani part contains Cyrillic letters."))
    if caption_az.strip() and len(caption_az) > 40 and not AZ_SPECIFIC_RE.search(caption_az):
        f.append(Finding("az_not_azerbaijani", "fix", "The Azerbaijani part has none of ə ğ ı ö ü ş ç; it may not be Azerbaijani."))
    if m := FOREIGN_LETTERS_RE.search(caption_az):
        f.append(Finding("az_foreign_letter", "fix", f"The Azerbaijani part uses '{m.group()}', which Azerbaijani does not have."))
    if caption_ru.strip() and not CYRILLIC_RE.search(caption_ru):
        f.append(Finding("ru_not_russian", "fix", "The Russian part contains no Cyrillic text."))

    if len(full_caption) > INSTAGRAM_CAPTION_LIMIT:
        f.append(Finding("too_long", "fix", f"The caption is {len(full_caption)} characters; Instagram allows {INSTAGRAM_CAPTION_LIMIT}."))
    limit = min(profile.hashtags.max_per_post, INSTAGRAM_HASHTAG_LIMIT)
    if len(hashtags) > limit:
        f.append(Finding("too_many_hashtags", "fix", f"{len(hashtags)} hashtags; the maximum is {limit}."))
    bad_tags = [h for h in hashtags if not HASHTAG_RE.match(h)]
    if bad_tags:
        f.append(Finding("bad_hashtag", "fix", f"Malformed hashtags: {', '.join(bad_tags)}."))
    if len({az_lower(h) for h in hashtags}) != len(hashtags):
        f.append(Finding("duplicate_hashtag", "fix", "A hashtag is repeated."))
    if "#" in body:
        f.append(Finding("hashtag_in_text", "fix", "Hashtags belong in the hashtag list, not in the caption text."))

    if hits := _word_hits(body, profile.never.words):
        f.append(Finding("never_word", "fix", f"Uses words the brand never uses: {', '.join(hits)}."))
    if hits := _word_hits(body + " " + " ".join(hashtags), profile.never.competitors):
        f.append(Finding("competitor", "block", f"Mentions a competitor: {', '.join(hits)}."))

    if PHONE_RE.search(body):
        f.append(Finding("phone_in_text", "fix", "Remove phone numbers; contact details are added by the system."))
    if URL_RE.search(body):
        f.append(Finding("link_in_text", "fix", "Remove links and web addresses; they are added by the system."))
    if not profile.mention_prices:
        price_ok = brief.price_text and brief.price_text in body
        if (m := PRICE_RE.search(body)) and not price_ok:
            f.append(Finding("price", "fix", f"Mentions a price, amount or percentage ('{m.group().strip()}'); prices are not allowed."))
    return f
