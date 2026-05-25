"""LLM backend factory.

Reads settings and returns a configured backend. This is the only place that
maps a provider string to a concrete class — every other module depends on
the LLMBackend interface only.
"""

from __future__ import annotations

from functools import lru_cache

from app.core.config import LLMProvider, settings
from app.core.logging import get_logger
from app.llm.base import LLMBackend

log = get_logger(__name__)


@lru_cache(maxsize=1)
def get_llm() -> LLMBackend:
    provider = settings.llm_provider
    log.info("llm.factory.init", provider=provider.value)

    if provider == LLMProvider.OLLAMA:
        from app.llm.ollama_backend import OllamaBackend

        return OllamaBackend(host=settings.ollama_host, model=settings.llm_model_ollama)

    if provider == LLMProvider.GROQ:
        if settings.env.value == "production":
            raise RuntimeError(
                "Groq is a dev-only backend. Production must use ollama or another "
                "local backend. Set WEKAMS_LLM_PROVIDER=ollama for air-gap deployments."
            )
        from app.llm.groq_backend import GroqBackend

        return GroqBackend(
            api_key=settings.groq_api_key or "",
            model=settings.llm_model_groq,
        )

    raise NotImplementedError(
        f"LLM provider {provider.value!r} is not implemented yet. "
        "Implement a class extending LLMBackend and wire it here."
    )
