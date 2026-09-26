"""Versioned prompt files (CLAUDE.md: every agent has a versioned prompt file).

Layout: del_social/agents/<agent>/prompt.v<N>.md. A prompt is never edited in place once
it has produced output; a change is a new file with the next version number, so every
llm_calls row says exactly which text produced it. The short hash catches accidental edits.
"""
import hashlib
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

AGENTS_DIR = Path(__file__).resolve().parents[1] / "agents"
_NAME = re.compile(r"^[a-z][a-z0-9_]*$")


class PromptNotFound(LookupError):
    pass


@dataclass(frozen=True)
class Prompt:
    agent: str
    version: int
    text: str
    sha: str  # first 12 hex chars of sha256(text)

    @property
    def ref(self) -> str:
        """Recorded with every call, e.g. 'copywriter@v1#3fa2b9c01d2e'."""
        return f"{self.agent}@v{self.version}#{self.sha}"


def _versions(agent: str, base: Path) -> dict[int, Path]:
    found = {}
    for path in (base / agent).glob("prompt.v*.md"):
        m = re.fullmatch(r"prompt\.v(\d+)\.md", path.name)
        if m:
            found[int(m.group(1))] = path
    return found


@lru_cache
def load_prompt(agent: str, version: int | None = None, base: Path = AGENTS_DIR) -> Prompt:
    """The given version, or the newest one when version is None."""
    if not _NAME.match(agent):
        raise PromptNotFound(f"Invalid agent name {agent!r}")
    versions = _versions(agent, base)
    if not versions:
        raise PromptNotFound(f"No prompt files for agent {agent!r}")
    chosen = max(versions) if version is None else version
    if chosen not in versions:
        raise PromptNotFound(f"{agent} has no prompt version {chosen}")
    text = versions[chosen].read_text(encoding="utf-8").strip()
    return Prompt(agent, chosen, text, hashlib.sha256(text.encode()).hexdigest()[:12])
