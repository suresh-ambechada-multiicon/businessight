from dataclasses import dataclass


@dataclass
class ModelConfig:
    provider: str
    context_window: int
    max_output: int
    cost_per_1m_input: float
    cost_per_1m_output: float
    supports_streaming: bool = True
    supports_tools: bool = True


MODEL_REGISTRY = {
    # OpenAI (GPT-5 series)
    "openai:gpt-5.5": ModelConfig("openai", 1_000_000, 100_000, 5.00, 30.00),
    "openai:gpt-5.4": ModelConfig("openai", 1_000_000, 100_000, 2.50, 15.00),
    # Anthropic (Claude 4 series)
    "anthropic:claude-opus-4.7": ModelConfig(
        "anthropic", 1_000_000, 100_000, 5.00, 25.00
    ),
    "anthropic:claude-sonnet-4.6": ModelConfig(
        "anthropic", 1_000_000, 100_000, 3.00, 15.00
    ),
    "anthropic:claude-haiku-4.5": ModelConfig(
        "anthropic", 1_000_000, 100_000, 1.00, 5.00
    ),
    # Google (Gemini 3 series)
    "google_genai:gemini-3.1-pro-preview": ModelConfig(
        "google_genai", 1_000_000, 65_536, 2.00, 12.00
    ),
    "google_genai:gemini-3-flash-preview": ModelConfig(
        "google_genai", 1_000_000, 65_536, 0.50, 3.00
    ),
    "google_genai:gemini-3.1-flash-lite-preview": ModelConfig(
        "google_genai", 1_000_000, 65_536, 0.25, 1.50
    ),
    "google_genai:gemini-2.5-pro": ModelConfig(
        "google_genai", 1_000_000, 65_536, 0.25, 1.50
    ),
    "google_genai:gemini-2.5-flash": ModelConfig(
        "google_genai", 1_000_000, 65_536, 0.25, 1.50
    ),
}


def get_model_config(model: str) -> ModelConfig:
    if model in MODEL_REGISTRY:
        return MODEL_REGISTRY[model]

    # Fallback
    provider = "openai"
    if "claude" in model.lower() or "anthropic" in model.lower():
        provider = "anthropic"
    elif "gemini" in model.lower() or "google" in model.lower():
        provider = "google_genai"

    return ModelConfig(provider, 128_000, 8_192, 0.005, 0.015)
