from analytics.services.llm.config import ModelConfig, get_model_config

__all__ = ["MODEL_REGISTRY", "get_model_config", "ModelConfig"]


def __getattr__(name: str):
    if name == "MODEL_REGISTRY":
        from analytics.constants import MODEL_REGISTRY

        return MODEL_REGISTRY
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
