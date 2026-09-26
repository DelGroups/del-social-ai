"""LLM access for agents: one client, versioned prompts, cost + tracing per tenant."""
import anthropic
import httpx
from sqlalchemy.ext.asyncio import AsyncEngine

from del_social.core.config import Settings
from del_social.llm.client import LLM, Effort, LLMError, LLMResult, Tier
from del_social.llm.prompts import Prompt, load_prompt
from del_social.llm.tracing import Tracer

__all__ = ["LLM", "Effort", "LLMError", "LLMResult", "Prompt", "Tier", "build_llm", "load_prompt"]


class LLMNotConfigured(RuntimeError):
    pass


def build_llm(settings: Settings, engine: AsyncEngine | None, http: httpx.AsyncClient) -> LLM:
    if not settings.anthropic_api_key:
        raise LLMNotConfigured("ANTHROPIC_API_KEY is not set")
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key, max_retries=2, timeout=120.0)
    tracer = (
        Tracer(http, settings.langfuse_host, settings.langfuse_public_key, settings.langfuse_secret_key)
        if settings.langfuse_configured
        else None
    )
    return LLM(client, settings, engine, tracer)
