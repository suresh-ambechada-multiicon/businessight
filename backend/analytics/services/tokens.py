"""
Token counting and budget estimation.

Caches the tiktoken encoder to avoid expensive re-initialization on every call.
"""

import functools

import tiktoken

from analytics.services.llm import ModelConfig


@functools.lru_cache(maxsize=8)
def _get_encoder(model_suffix: str):
    """Cached tiktoken encoder lookup. LRU avoids repeated init cost."""
    try:
        return tiktoken.encoding_for_model(model_suffix)
    except Exception:
        return tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str, model: str = "gpt-4o") -> int:
    """Approximate token count using a cached encoder."""
    enc = _get_encoder(model.split(":")[-1])
    return len(enc.encode(str(text)))


def estimate_query_budget(
    model_config: ModelConfig, system_prompt: str, history: list[dict]
) -> dict:
    """Estimate token budget: how much room is left for tools and output."""
    system_tokens = count_tokens(system_prompt)
    history_tokens = sum(count_tokens(m.get("content", "")) for m in history)
    used = system_tokens + history_tokens
    available = model_config.context_window - used - model_config.max_output

    return {
        "system_tokens": system_tokens,
        "history_tokens": history_tokens,
        "total_used": used,
        "available_for_tools": max(0, available),
        "max_output": model_config.max_output,
        "context_window": model_config.context_window,
    }
