from ninja import Router

from analytics.services.llm import MODEL_REGISTRY

router = Router()


@router.get("/")
def list_models(request):
    return [
        {
            "id": model_id,
            "provider": config.provider,
            "name": model_id.split(":")[-1].replace("-", " ").title(),
        }
        for model_id, config in MODEL_REGISTRY.items()
    ]