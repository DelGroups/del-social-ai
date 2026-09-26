"""The brand profile: what every agent reads about a tenant (docs/phase-1-plan.md §2).

Stored as versioned JSON (brand_profiles). This schema is the contract: agents get it
as structured data, the panel edits it, and new fields get defaults so old versions
still load.
"""
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Short = Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)]
Long = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)]
Item = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]


def items(max_items: int = 40):
    return Field(default_factory=list, max_length=max_items)


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Basics(_Section):
    company_name: Short = ""
    description: Long = ""  # what the company sells, in a few sentences
    cities: list[Item] = items()
    showroom_address: Short = ""
    working_hours: Short = ""
    website: Short = ""
    phone: Short = ""
    whatsapp: Short = ""


class Audience(_Section):
    description: Long = ""
    segments: list[Item] = items()


class Products(_Section):
    categories: list[Item] = items()
    materials: list[Item] = items()
    usps: list[Item] = items()  # what makes the products different


class Formality(StrEnum):
    FORMAL = "formal"  # siz / вы
    FRIENDLY = "friendly"  # sən / ты


class EmojiUse(StrEnum):
    NONE = "none"
    FEW = "few"
    MANY = "many"


class CaptionLength(StrEnum):
    SHORT = "short"
    MEDIUM = "medium"
    LONG = "long"


class Voice(_Section):
    tone_words: list[Item] = items(12)
    formality: Formality = Formality.FORMAL
    emoji: EmojiUse = EmojiUse.FEW
    caption_length: CaptionLength = CaptionLength.MEDIUM
    notes: Long = ""


class LanguageMode(StrEnum):
    AZ_RU_SAME_CAPTION = "az_ru_same_caption"  # Azerbaijani first, then Russian
    AZ = "az"
    RU = "ru"
    ALTERNATE = "alternate"


class Languages(_Section):
    mode: LanguageMode = LanguageMode.AZ_RU_SAME_CAPTION


class NeverList(_Section):
    words: list[Item] = items(100)
    topics: list[Item] = items()
    competitors: list[Item] = items()


class Hashtags(_Section):
    branded: list[Item] = items(10)
    pool: list[Item] = items(100)
    max_per_post: int = Field(default=10, ge=0, le=30)  # Instagram allows 30


class Examples(_Section):
    good: list[Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2200)]] = items(10)
    bad: list[Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2200)]] = items(10)


DEFAULT_OCCASIONS = [
    "Yeni il — 31 dekabr / 1 yanvar",
    "8 Mart — Beynəlxalq Qadınlar Günü",
    "Novruz bayramı — 20-21 mart",
    "Ramazan bayramı (tarix hər il dəyişir)",
    "Qurban bayramı (tarix hər il dəyişir)",
    "Müstəqillik Günü — 28 may",
    "Məktəb mövsümü — sentyabr",
    "Black Friday — noyabrın son cüməsi",
]


class ImageEditing(_Section):
    """Unused since edits are configured per photo (ADR 005, revised). Kept so saved versions load."""

    background: bool = False  # replace the product's surroundings
    remove_objects: bool = False  # remove items from the photo
    enhance: bool = False  # upscale, denoise, sharpen
    recolor: bool = False  # change the product's colour/finish, keep its design
    swap_product: bool = False  # replace the product with a similar one


class BrandProfile(_Section):
    basics: Basics = Field(default_factory=Basics)
    audience: Audience = Field(default_factory=Audience)
    products: Products = Field(default_factory=Products)
    voice: Voice = Field(default_factory=Voice)
    languages: Languages = Field(default_factory=Languages)
    never: NeverList = Field(default_factory=NeverList)
    claims: list[Item] = items()  # only claims that are true and can be proven
    # The company's own vocabulary, one line each, e.g. "handleless door: qulpsuz qapı (not dəstəksiz)"
    terminology: list[Item] = items(80)
    ctas: list[Item] = items(20)
    hashtags: Hashtags = Field(default_factory=Hashtags)
    examples: Examples = Field(default_factory=Examples)
    occasions: list[Item] = Field(default_factory=lambda: list(DEFAULT_OCCASIONS), max_length=40)
    image_editing: ImageEditing = Field(default_factory=ImageEditing)
    # Phase 1 rule (plan §2): posts never mention prices or discounts unless a human writes them in the brief
    mention_prices: bool = False
