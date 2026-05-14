from dataclasses import dataclass
from typing import Dict

@dataclass
class ModelConfig:
    provider: str
    context_window: int
    max_output: int
    cost_per_1m_input: float
    cost_per_1m_output: float
    supports_streaming: bool = True
    supports_tools: bool = True

def get_model_config(model: str) -> ModelConfig:
    from analytics.constants import MODEL_REGISTRY
    
    if model in MODEL_REGISTRY:
        return MODEL_REGISTRY[model]

    # Fallback
    provider = "openai"
    if model.lower().startswith("runware:") or "runware" in model.lower():
        provider = "runware"
    elif "claude" in model.lower() or "anthropic" in model.lower():
        provider = "anthropic"
    elif "gemini" in model.lower() or "google" in model.lower():
        provider = "google_genai"

    return ModelConfig(provider, 128_000, 8_192, 0.005, 0.015)
