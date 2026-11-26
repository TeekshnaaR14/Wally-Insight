from typing import Literal
from pydantic import BaseModel, Field, field_validator

MODEL_NAME_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$"


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=4000)


class AssistantQuestion(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    # Earlier messages of the conversation, so follow-up questions make sense
    history: list[ChatMessage] = Field(default_factory=list, max_length=10)

    @field_validator("question")
    @classmethod
    def strip_question(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("question must not be empty")
        return value


class AssistantAnswer(BaseModel):
    answer: str
    provider: str
    model: str


class AssistantSettingsPublic(BaseModel):
    provider: Literal["ollama", "api"]
    ollama_url: str
    ollama_model: str
    api_url: str
    api_model: str
    # The API key itself is never sent back to the browser
    api_key_set: bool


class AssistantSettingsUpdate(BaseModel):
    provider: Literal["ollama", "api"] | None = None
    ollama_url: str | None = Field(default=None, max_length=300)
    ollama_model: str | None = Field(default=None, pattern=MODEL_NAME_PATTERN)
    api_url: str | None = Field(default=None, max_length=300)
    api_model: str | None = Field(default=None, max_length=128)
    # None keeps the saved key, "" removes it
    api_key: str | None = Field(default=None, max_length=500)

    @field_validator("ollama_url", "api_url")
    @classmethod
    def check_url(cls, value):
        if value is None:
            return value
        value = value.strip()
        if value and not value.startswith(("http://", "https://")):
            raise ValueError("URL must start with http:// or https://")
        return value.rstrip("/")

    @field_validator("api_model", "api_key")
    @classmethod
    def strip_value(cls, value):
        return value.strip() if value is not None else value


class OllamaPullRequest(BaseModel):
    model: str = Field(pattern=MODEL_NAME_PATTERN)
