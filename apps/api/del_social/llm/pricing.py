"""What an LLM call costs, computed by code from the token counts the API returns.

USD per million tokens, from platform.claude.com/docs/en/about-claude/pricing (checked
2026-09-26). Update this table when prices change; an unknown model records cost as
NULL and logs a warning instead of guessing.
"""
from dataclasses import dataclass
from decimal import Decimal

MILLION = Decimal(1_000_000)


@dataclass(frozen=True)
class Price:
    input: Decimal
    cache_write: Decimal  # 5-minute cache writes
    cache_read: Decimal
    output: Decimal


def _p(input: str, cache_write: str, cache_read: str, output: str) -> Price:
    return Price(Decimal(input), Decimal(cache_write), Decimal(cache_read), Decimal(output))


PRICES: dict[str, Price] = {
    "claude-opus-5-5": _p("4", "5", "0.20", "20"),
    "claude-sonnet-5": _p("2", "2.50", "0.20", "10"),
    "claude-haiku-4-5-20251001": _p("1", "1.25", "0.10", "5"),
    "claude-haiku-4-5": _p("1", "1.25", "0.10", "5"),
}


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0  # not counting cache reads/writes
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


def cost_usd(model: str, usage: Usage) -> Decimal | None:
    price = PRICES.get(model)
    if price is None:
        return None
    total = (
        usage.input_tokens * price.input
        + usage.cache_write_tokens * price.cache_write
        + usage.cache_read_tokens * price.cache_read
        + usage.output_tokens * price.output
    ) / MILLION
    return total.quantize(Decimal("0.000001"))
