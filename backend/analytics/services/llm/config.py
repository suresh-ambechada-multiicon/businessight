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

    # Fallback pricing is intentionally conservative. Exact prices vary by
    # concrete model/version; add models to MODEL_REGISTRY for precise billing.
    provider = "openai"
    input_cost = 2.00
    output_cost = 8.00
    if model.lower().startswith("runware:") or "runware" in model.lower():
        provider = "runware"
        input_cost = 0.50
        output_cost = 3.00
    elif "claude" in model.lower() or "anthropic" in model.lower():
        provider = "anthropic"
        input_cost = 3.00
        output_cost = 15.00
    elif "gemini" in model.lower() or "google" in model.lower():
        provider = "google_genai"
        input_cost = 0.50
        output_cost = 3.00

    return ModelConfig(provider, 128_000, 8_192, input_cost, output_cost)
