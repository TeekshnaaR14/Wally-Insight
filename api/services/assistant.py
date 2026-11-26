"""AI assistant: settings, prompt and calls to the chosen model.

By default the model runs locally in Ollama. Users can also point Wally at
an OpenAI-compatible API in Settings; that is opt-in and never the default.
"""
import json
import os
import threading
from dataclasses import dataclass

import httpx
from sqlmodel import Session

from ..models.app import AppConfig

PROVIDER_OLLAMA = "ollama"
PROVIDER_API = "api"

DEFAULT_OLLAMA_URL = "http://localhost:11434"
DEFAULT_OLLAMA_MODEL = "llama3.2:3b"

SETTING_KEYS = {
    "provider": "ASSISTANT_PROVIDER",
    "ollama_url": "ASSISTANT_OLLAMA_URL",
    "ollama_model": "ASSISTANT_OLLAMA_MODEL",
    "api_url": "ASSISTANT_API_URL",
    "api_model": "ASSISTANT_API_MODEL",
    "api_key": "ASSISTANT_API_KEY",
}

# Models suggested in Settings, with roughly how much memory they need.
RECOMMENDED_OLLAMA_MODELS = [
    {"name": "llama3.2:1b", "label": "Fastest, basic answers", "download_gb": 1.3, "min_ram_gb": 4},
    {"name": "llama3.2:3b", "label": "Recommended balance of speed and quality", "download_gb": 2.0, "min_ram_gb": 8},
    {"name": "qwen2.5:3b", "label": "Alternative small model", "download_gb": 1.9, "min_ram_gb": 8},
    {"name": "llama3.1:8b", "label": "Best answers, needs a strong computer", "download_gb": 4.9, "min_ram_gb": 16},
    {"name": "qwen2.5:7b", "label": "Alternative large model", "download_gb": 4.7, "min_ram_gb": 16},
]

SYSTEM_PROMPT = """You are Wally's assistant. You answer questions about the user's personal finances.

Rules:
- Use ONLY the information in the WALLY DATA section below. It is the user's real data.
- Copy amounts exactly as they appear in the data, with the same currency symbol.
- If the data does not contain the answer, say that Wally does not have that information. Never guess or invent numbers, dates or names.
- You can only read this summary. You cannot add, change or delete anything in Wally; if asked to, say so.
- Answer in plain text without markdown, in at most three short sentences.

WALLY DATA:
{context}"""

CONNECT_TIMEOUT = 5.0
ANSWER_TIMEOUT = 240.0

# Tests replace this with httpx.MockTransport so no real service is called.
http_transport: httpx.BaseTransport | None = None


class AssistantUnavailable(Exception):
    """The model could not be reached or did not give an answer."""


@dataclass
class AssistantSettings:
    provider: str
    ollama_url: str
    ollama_model: str
    api_url: str
    api_model: str
    api_key: str

    @property
    def model(self) -> str:
        return self.api_model if self.provider == PROVIDER_API else self.ollama_model


def _client(timeout: float = ANSWER_TIMEOUT) -> httpx.Client:
    return httpx.Client(transport=http_transport, timeout=httpx.Timeout(timeout, connect=CONNECT_TIMEOUT))


def load_settings(db: Session) -> AssistantSettings:
    def value(field, default=""):
        config = db.get(AppConfig, SETTING_KEYS[field])
        return str(config.value) if config and config.value not in (None, "") else default

    provider = value("provider", PROVIDER_OLLAMA)
    return AssistantSettings(
        provider=provider if provider in (PROVIDER_OLLAMA, PROVIDER_API) else PROVIDER_OLLAMA,
        ollama_url=value("ollama_url", os.getenv("OLLAMA_URL", DEFAULT_OLLAMA_URL)),
        ollama_model=value("ollama_model", os.getenv("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL)),
        api_url=value("api_url"),
        api_model=value("api_model"),
        api_key=value("api_key"),
    )


def save_settings(db: Session, changes: dict) -> AssistantSettings:
    for field, new_value in changes.items():
        key = SETTING_KEYS[field]
        config = db.get(AppConfig, key) or AppConfig(key=key, value="")
        config.value = new_value
        db.add(config)
    db.commit()
    return load_settings(db)


def build_messages(question: str, context_text: str, history: list[dict] | None = None) -> list[dict]:
    messages = [{"role": "system", "content": SYSTEM_PROMPT.format(context=context_text)}]
    messages += [{"role": item["role"], "content": item["content"]} for item in (history or [])]
    messages.append({"role": "user", "content": question})
    return messages


def _error_detail(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:200]
    error = body.get("error") if isinstance(body, dict) else None
    if isinstance(error, dict):
        return str(error.get("message", ""))[:200]
    return str(error or body)[:200]


def _ask_ollama(settings: AssistantSettings, messages: list[dict]) -> str:
    url = settings.ollama_url.rstrip("/")
    try:
        with _client() as client:
            response = client.post(f"{url}/api/chat", json={
                "model": settings.ollama_model,
                "messages": messages,
                "stream": False,
                "options": {"temperature": 0},
            })
    except httpx.TimeoutException:
        raise AssistantUnavailable("The local AI model took too long to answer. Try again or choose a smaller model in Settings.")
    except httpx.HTTPError:
        raise AssistantUnavailable(f"The AI assistant is not available: Ollama is not running at {url}. Start Ollama and try again.")

    if response.status_code == 404:
        raise AssistantUnavailable(
            f"The model '{settings.ollama_model}' is not installed in Ollama. Download it in Settings → AI Assistant."
        )
    if response.status_code != 200:
        raise AssistantUnavailable(f"Ollama returned an error: {_error_detail(response)}")

    try:
        return response.json()["message"]["content"].strip()
    except (ValueError, KeyError, TypeError):
        raise AssistantUnavailable("Ollama returned an answer Wally could not read.")


def _ask_api(settings: AssistantSettings, messages: list[dict]) -> str:
    if not settings.api_url or not settings.api_model:
        raise AssistantUnavailable("The external API is not configured. Enter its URL and model in Settings → AI Assistant.")

    url = settings.api_url.rstrip("/")
    headers = {"Authorization": f"Bearer {settings.api_key}"} if settings.api_key else {}
    try:
        with _client() as client:
            response = client.post(f"{url}/chat/completions", headers=headers, json={
                "model": settings.api_model,
                "messages": messages,
                "temperature": 0,
            })
    except httpx.TimeoutException:
        raise AssistantUnavailable("The AI service took too long to answer. Try again later.")
    except httpx.HTTPError:
        raise AssistantUnavailable(f"The AI assistant is not available: could not connect to {url}.")

    if response.status_code in (401, 403):
        raise AssistantUnavailable("The AI service rejected the API key. Check it in Settings → AI Assistant.")
    if response.status_code != 200:
        raise AssistantUnavailable(f"The AI service returned an error ({response.status_code}): {_error_detail(response)}")

    try:
        return response.json()["choices"][0]["message"]["content"].strip()
    except (ValueError, KeyError, IndexError, TypeError):
        raise AssistantUnavailable("The AI service returned an answer Wally could not read.")


def ask_model(settings: AssistantSettings, messages: list[dict]) -> str:
    if settings.provider == PROVIDER_API:
        return _ask_api(settings, messages)
    return _ask_ollama(settings, messages)


# ---------------------------------------------------------------------------
# Ollama model management (list installed models, download new ones)
# ---------------------------------------------------------------------------

def system_memory_gb() -> float | None:
    """Memory of the computer running Wally, used to suggest models that fit."""
    try:
        return round(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1024 ** 3, 1)
    except (AttributeError, ValueError, OSError):
        return None


def list_ollama_models(url: str) -> list[dict]:
    """Installed models; raises AssistantUnavailable if Ollama cannot be reached."""
    url = url.rstrip("/")
    try:
        with _client(timeout=10.0) as client:
            response = client.get(f"{url}/api/tags")
        response.raise_for_status()
        models = response.json().get("models", [])
    except (httpx.HTTPError, ValueError, AttributeError):
        raise AssistantUnavailable(f"Ollama is not running at {url}.")

    return sorted(
        (
            {
                "name": model.get("name", ""),
                "size_gb": round(model.get("size", 0) / 1024 ** 3, 1),
                "parameter_size": (model.get("details") or {}).get("parameter_size", ""),
            }
            for model in models
        ),
        key=lambda model: model["name"],
    )


_pull_lock = threading.Lock()
_pull_status: dict = {"model": None, "running": False, "status": "", "completed": 0, "total": 0, "error": None, "done": False}
_pull_thread: threading.Thread | None = None


def pull_status() -> dict:
    with _pull_lock:
        return dict(_pull_status)


def _update_pull(**changes) -> None:
    with _pull_lock:
        _pull_status.update(changes)


def _run_pull(url: str, model: str) -> None:
    try:
        with _client(timeout=None) as client:
            with client.stream("POST", f"{url.rstrip('/')}/api/pull", json={"model": model, "stream": True}) as response:
                if response.status_code != 200:
                    response.read()
                    raise AssistantUnavailable(_error_detail(response) or f"Ollama returned {response.status_code}")
                for line in response.iter_lines():
                    if not line:
                        continue
                    event = json.loads(line)
                    if event.get("error"):
                        raise AssistantUnavailable(event["error"])
                    _update_pull(
                        status=event.get("status", ""),
                        completed=event.get("completed", 0),
                        total=event.get("total", 0),
                    )
        _update_pull(running=False, done=True, status="success")
    except AssistantUnavailable as error:
        _update_pull(running=False, done=True, error=str(error))
    except (httpx.HTTPError, ValueError):
        _update_pull(running=False, done=True, error=f"Could not download {model}: Ollama is not reachable at {url}.")


def start_pull(url: str, model: str) -> bool:
    """Start downloading a model in the background. Returns False if a download is already running."""
    global _pull_thread
    with _pull_lock:
        if _pull_status["running"]:
            return False
        _pull_status.update(model=model, running=True, status="starting", completed=0, total=0, error=None, done=False)

    _pull_thread = threading.Thread(target=_run_pull, args=(url, model), daemon=True)
    _pull_thread.start()
    return True
