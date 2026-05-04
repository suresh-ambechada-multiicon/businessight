import tiktoken
from analytics.services.llm_config import ModelConfig

def count_tokens(text: str, model: str = "gpt-4o") -> int:
    """Approximate token count."""
    try:
        enc = tiktoken.encoding_for_model(model.split(":")[-1])
    except Exception:
        enc = tiktoken.get_encoding("cl100k_base")
    return len(enc.encode(str(text)))

def estimate_query_budget(model_config: ModelConfig, system_prompt: str, history: list[dict]) -> dict:
    system_tokens = count_tokens(system_prompt)
    history_tokens = sum(count_tokens(m.get("content", "")) for m in history)
    used = system_tokens + history_tokens
    available = model_config.context_window - used - model_config.max_output

    return {
        "system_tokens": system_tokens,
        "history_tokens": history_tokens,
        "total_used": used,
        "available_for_tools": available,
        "max_output": model_config.max_output,
        "context_window": model_config.context_window,
    }
