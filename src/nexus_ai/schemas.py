
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictStr, field_validator


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


class StructuredGenerateRequest(BaseModel):
    """Strict request contract for registry-backed structured generation."""

    model_config = ConfigDict(extra="forbid")

    schema_name: StrictStr = Field(min_length=1)
    prompt: StrictStr | None = Field(default=None, min_length=1)
    model: StrictStr | None = Field(default=None, min_length=1)

    @field_validator("schema_name")
    @classmethod
    def validate_schema_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Schema name cannot be blank.")
        return value

    @field_validator("prompt")
    @classmethod
    def validate_structured_prompt(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("Prompt cannot be blank.")
        return value

    @field_validator("model")
    @classmethod
    def validate_structured_model(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("Model cannot be blank.")
        return value


class StructuredGenerationAttemptMetricsResponse(BaseModel):
    """Public metric snapshot for one adapter attempt."""

    model: str | None
    duration_ms: float | None
    prompt_eval_count: int | None
    eval_count: int | None


class StructuredGenerationMetricsResponse(BaseModel):
    """Public aggregate metrics for one structured-generation request."""

    attempts: int
    per_attempt: list[StructuredGenerationAttemptMetricsResponse]
    model: str | None
    total_generation_duration_ms: float | None
    prompt_eval_count: int | None
    eval_count: int | None


class StructuredGenerateResponse(BaseModel):
    """Validated registry result and its measured generation metrics."""

    schema_name: str
    data: dict[str, object]
    metrics: StructuredGenerationMetricsResponse
