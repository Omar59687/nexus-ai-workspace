
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


TaskStatus = Literal["pending", "in_progress", "completed", "failed"]


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Title cannot be blank.")
        return value


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    status: TaskStatus | None = None


class TaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    status: TaskStatus
    created_at: datetime


class LLMGenerateRequest(BaseModel):
    prompt: str = Field(min_length=1)
    model: str | None = Field(default=None, min_length=1)

    @field_validator("prompt")
    @classmethod
    def validate_prompt(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Prompt cannot be blank.")
        return value

    @field_validator("model")
    @classmethod
    def validate_model(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("Model cannot be blank.")
        return value


class LLMGenerateResponse(BaseModel):
    model: str
    response: str
    done: bool | None = None
    total_duration_ms: float | None = None
    prompt_eval_count: int | None = None
    eval_count: int | None = None
