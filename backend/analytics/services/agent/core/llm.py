"""LLM initialization and message-history helpers."""

from langchain.chat_models import init_chat_model

from analytics.models import QueryHistory
from analytics.services.logger import get_logger

logger = get_logger("agent")


def _detect_provider(model: str) -> str:
    """
    Detect the LLM provider from the model string.
    Supports both explicit format (e.g., 'openai:gpt-4o') and
    bare model names (e.g., 'gemini-2.0-flash').
    """
    if ":" in model:
        return model.split(":")[0]

    model_lower = model.lower()
    if "runware" in model_lower:
        return "runware"
    if any(k in model_lower for k in ("gemini", "gemma", "palm")):
        return "google_genai"
    if any(k in model_lower for k in ("claude", "anthropic")):
        return "anthropic"
    return "openai"


def init_llm(model: str, api_key: str, llm_config, ctx=None):
    """
    Initialize the LLM passing the API key and dynamic configs.
    """
    provider = _detect_provider(model)
    if provider == "runware":
        raise ValueError(
            "Runware models use the schema-to-SQL Runware execution path, not LangChain init_chat_model."
        )

    _ctx = ctx.to_dict() if ctx else {}
    logger.info(
        "LLM initialized",
        extra={
            "data": {
                **_ctx,
                "provider": provider,
                "model": model,
            }
        },
    )

    model_kwargs = {
        "api_key": api_key,
        "temperature": getattr(llm_config, "temperature", 0.1),
    }

    max_tokens = getattr(llm_config, "max_tokens", None)
    if max_tokens:
        model_kwargs["max_tokens"] = max_tokens

    top_p = getattr(llm_config, "top_p", 1.0)
    if top_p != 1.0:
        model_kwargs["top_p"] = top_p

    # Disable SDK retries so we fail fast on 429 rate limits
    model_kwargs["max_retries"] = 0

    if provider == "google_genai":
        model_kwargs["google_api_key"] = api_key
        model_provider = "google_genai"
    elif provider == "anthropic":
        model_kwargs["api_key"] = api_key
        model_provider = "anthropic"
    else:
        model_provider = provider

    # Explicitly pass model_provider to avoid LangChain defaulting Google models to vertexai
    if ":" in model:
        model_name = model.split(":", 1)[1]
    else:
        model_name = model

    llm = init_chat_model(
        model=model_name, model_provider=model_provider, **model_kwargs
    )
    return llm


# ── Message History Builder ─────────────────────────────────────────────


def build_messages(session_id: str, query: str) -> list[dict]:
    """
    Build the message history for the agent, including the last 3 session
    interactions as context. Excludes in-flight queries (report='Analyzing...')
    and failed fallback reports.
    """
    past_interactions = list(
        QueryHistory.objects.filter(session_id=session_id)
        .exclude(report="Analyzing...")  # Exclude current in-flight query
        .order_by("-created_at")[:3]
    )
    past_interactions.reverse()

    messages = []
    for interaction in past_interactions:
        # Avoid feeding bad fallback reports back into history
        if "couldn't generate a verbal summary" in (interaction.report or ""):
            continue
        messages.append({"role": "user", "content": interaction.query})
        messages.append({"role": "assistant", "content": interaction.report})

    messages.append({"role": "user", "content": query})

    logger.debug(
        "Messages built",
        extra={
            "data": {
                "session_id": session_id,
                "history_count": len(past_interactions),
                "total_messages": len(messages),
            }
        },
    )

    return messages
