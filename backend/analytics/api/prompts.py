from django.shortcuts import get_object_or_404
from ninja import Router
from ninja.errors import HttpError

from analytics.models import SavedPrompt
from analytics.schemas import SavedPromptCreate, SavedPromptUpdate

router = Router()


@router.get("/prompts/")
def list_saved_prompts(request):
    prompts = SavedPrompt.objects.all()
    return [
        {
            "id": p.id,
            "name": p.name,
            "query": p.query,
            "sql_command": p.sql_command,
            "created_at": p.created_at.isoformat(),
        }
        for p in prompts
    ]


@router.post("/prompts/")
def create_saved_prompt(request, payload: SavedPromptCreate):
    if SavedPrompt.objects.filter(sql_command=payload.sql_command).exists():
        raise HttpError(
            400, "A saved prompt with this exact SQL command already exists."
        )
    if SavedPrompt.objects.filter(name=payload.name).exists():
        raise HttpError(
            400,
            "A saved prompt with this name already exists. Please choose a different name.",
        )

    p = SavedPrompt.objects.create(
        name=payload.name,
        query=payload.query,
        sql_command=payload.sql_command,
    )
    return {
        "id": p.id,
        "name": p.name,
        "query": p.query,
        "sql_command": p.sql_command,
        "created_at": p.created_at.isoformat(),
    }


@router.put("/prompts/{prompt_id}/")
def rename_saved_prompt(request, prompt_id: int, payload: SavedPromptUpdate):
    p = get_object_or_404(SavedPrompt, id=prompt_id)
    p.name = payload.name
    p.save()
    return {"status": "success", "id": p.id, "name": p.name}


@router.delete("/prompts/{prompt_id}/")
def delete_saved_prompt(request, prompt_id: int):
    SavedPrompt.objects.filter(id=prompt_id).delete()
    return {"status": "deleted"}
