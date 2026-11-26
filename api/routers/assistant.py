from fastapi import APIRouter, Depends, HTTPException
from typing import Annotated
from sqlmodel import Session

from ..database import get_session
from ..models.assistant import (
    AssistantAnswer,
    AssistantQuestion,
    AssistantSettingsPublic,
    AssistantSettingsUpdate,
    OllamaPullRequest,
)
from ..services import assistant
from ..services.assistant_context import build_context, render_context
from .auth import check_login


router = APIRouter(tags=["Assistant"], dependencies=[Depends(check_login)])


def settings_public(settings: assistant.AssistantSettings) -> AssistantSettingsPublic:
    return AssistantSettingsPublic(
        provider=settings.provider,
        ollama_url=settings.ollama_url,
        ollama_model=settings.ollama_model,
        api_url=settings.api_url,
        api_model=settings.api_model,
        api_key_set=bool(settings.api_key),
    )


@router.post("/assistant", response_model=AssistantAnswer)
def ask_assistant(
    question: AssistantQuestion,
    db: Annotated[Session, Depends(get_session)],
):
    settings = assistant.load_settings(db)

    # The model only receives this read-only text summary, never database access.
    context_text = render_context(build_context(db))
    messages = assistant.build_messages(
        question.question,
        context_text,
        [message.model_dump() for message in question.history],
    )

    try:
        answer = assistant.ask_model(settings, messages)
    except assistant.AssistantUnavailable as error:
        raise HTTPException(status_code=503, detail=str(error))

    return AssistantAnswer(answer=answer, provider=settings.provider, model=settings.model)


@router.get("/assistant/settings", response_model=AssistantSettingsPublic)
def read_assistant_settings(db: Annotated[Session, Depends(get_session)]):
    return settings_public(assistant.load_settings(db))


@router.put("/assistant/settings", response_model=AssistantSettingsPublic)
def update_assistant_settings(
    update: AssistantSettingsUpdate,
    db: Annotated[Session, Depends(get_session)],
):
    changes = update.model_dump(exclude_none=True)
    current = assistant.load_settings(db)

    provider = changes.get("provider", current.provider)
    api_url = changes.get("api_url", current.api_url)
    api_model = changes.get("api_model", current.api_model)
    if provider == assistant.PROVIDER_API and not (api_url and api_model):
        raise HTTPException(status_code=400, detail="Enter the API URL and model before using an external API.")
    if "ollama_url" in changes and not changes["ollama_url"]:
        raise HTTPException(status_code=400, detail="Enter the Ollama URL.")

    return settings_public(assistant.save_settings(db, changes))


@router.post("/assistant/test", response_model=AssistantAnswer)
def test_assistant(db: Annotated[Session, Depends(get_session)]):
    # Checks the saved settings with a tiny question; no user data is sent.
    settings = assistant.load_settings(db)
    try:
        answer = assistant.ask_model(settings, [{"role": "user", "content": "Reply with the single word OK."}])
    except assistant.AssistantUnavailable as error:
        raise HTTPException(status_code=503, detail=str(error))
    return AssistantAnswer(answer=answer, provider=settings.provider, model=settings.model)


@router.get("/assistant/ollama/models")
def read_ollama_models(db: Annotated[Session, Depends(get_session)]):
    settings = assistant.load_settings(db)
    memory = assistant.system_memory_gb()

    try:
        installed = assistant.list_ollama_models(settings.ollama_url)
        error = None
    except assistant.AssistantUnavailable as unavailable:
        installed, error = [], str(unavailable)

    installed_names = {model["name"] for model in installed}
    recommended = [
        {
            **model,
            "fits": memory is None or memory >= model["min_ram_gb"],
            "installed": model["name"] in installed_names,
        }
        for model in assistant.RECOMMENDED_OLLAMA_MODELS
    ]

    return {
        "url": settings.ollama_url,
        "reachable": error is None,
        "error": error,
        "installed": installed,
        "recommended": recommended,
        "system_memory_gb": memory,
    }


@router.post("/assistant/ollama/pull", status_code=202)
def pull_ollama_model(
    pull: OllamaPullRequest,
    db: Annotated[Session, Depends(get_session)],
):
    settings = assistant.load_settings(db)
    if not assistant.start_pull(settings.ollama_url, pull.model):
        raise HTTPException(status_code=409, detail="Another model is already downloading. Wait for it to finish.")
    return assistant.pull_status()


@router.get("/assistant/ollama/pull")
def read_ollama_pull_status():
    return assistant.pull_status()
