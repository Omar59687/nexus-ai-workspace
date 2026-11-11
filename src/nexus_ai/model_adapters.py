"""LangChain ChatOllama adapter for validated structured generation.

The adapter enforces provider-reported completion before returning a parsed
result and treats unverifiable completion metadata as a failure. Schema
validation only proves that a response is structurally well-formed; it does
not imply that the content is factually correct, so callers must still apply
domain validation.
"""

import logging
import math
from dataclasses import dataclass
from typing import Protocol

import httpx
from langchain_core.messages import BaseMessage
from langchain_ollama import ChatOllama
from ollama import ResponseError
from pydantic import BaseModel

from nexus_ai.ollama import (
    DEFAULT_OLLAMA_BASE_URL,
    DEFAULT_OLLAMA_MODEL,
    OllamaError,
    OllamaResponseError,
    OllamaTimeoutError,
    OllamaUnavailableError,
)

_NANOSECONDS_PER_MILLISECOND = 1_000_000
_LENGTH_DONE_REASON = "length"
_LOGGER_NAME = "nexus_ai.model_adapters"

logger = logging.getLogger(_LOGGER_NAME)


class StructuredGenerationFailureError(OllamaError):
    """Provider returned malformed or unstructured output."""


class OllamaGenerationIncompleteError(StructuredGenerationFailureError):
    """Completion could not be verified (missing metadata, done False, or done_reason 'length')."""


@dataclass(frozen=True)
class StructuredGeneration:
    """A parsed structured result plus provider completion metadata."""

    result: BaseModel
    completion: bool
    model: str | None
    total_duration_ms: float | None
    prompt_eval_count: int | None
    eval_count: int | None


class StructuredModelAdapter(Protocol):
    """Protocol implemented by structured-output model adapters."""

    def generate_structured(
        self,
        prompt: str,
        model_class: type[BaseModel],
        *,
        model: str | None = None,
    ) -> StructuredGeneration: ...


class LangChainChatOllamaAdapter:
    """Generate Pydantic-validated responses through ``ChatOllama``."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        default_model: str | None = None,
        temperature: float = 0.0,
        num_predict: int = 256,
    ) -> None:
        configured_base_url = (
            base_url if base_url is not None else DEFAULT_OLLAMA_BASE_URL
        )
        self.base_url = (
            (configured_base_url or DEFAULT_OLLAMA_BASE_URL)
            .strip()
            .rstrip("/")
            or DEFAULT_OLLAMA_BASE_URL
        )

        configured_model = (
            default_model
            if default_model is not None
            else DEFAULT_OLLAMA_MODEL
        )
        self.default_model = (
            (configured_model or DEFAULT_OLLAMA_MODEL).strip()
            or DEFAULT_OLLAMA_MODEL
        )

        if (
            not isinstance(temperature, (int, float))
            or isinstance(temperature, bool)
            or not math.isfinite(temperature)
            or temperature < 0
        ):
            raise ValueError(
                "temperature must be a finite non-negative number."
            )
        self.temperature = float(temperature)

        if (
            not isinstance(num_predict, int)
            or isinstance(num_predict, bool)
            or num_predict <= 0
        ):
            raise ValueError(
                "num_predict must be a positive integer."
            )
        self.num_predict = num_predict

    def generate_structured(
        self,
        prompt: str,
        model_class: type[BaseModel],
        *,
        model: str | None = None,
    ) -> StructuredGeneration:
        """Generate and validate a structured response from Ollama."""

        selected_model = (model or self.default_model).strip()
        if not selected_model:
            selected_model = self.default_model

        try:
            # ChatOllama 1.1.0 has no timeout field and silently ignores
            # unknown kwargs, so no timeout is passed here.
            chat = ChatOllama(
                model=selected_model,
                base_url=self.base_url,
                temperature=self.temperature,
                num_predict=self.num_predict,
            )
            structured = chat.with_structured_output(
                model_class,
                include_raw=True,
            )
            payload = structured.invoke(prompt)
        except httpx.TimeoutException as exc:
            logger.warning(
                "Ollama structured request timed out for model %s (%s)",
                selected_model,
                type(exc).__name__,
            )
            raise OllamaTimeoutError(
                "Ollama request timed out."
            ) from exc
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            logger.warning(
                "Ollama returned HTTP %s for structured model %s",
                status_code,
                selected_model,
            )
            raise OllamaResponseError(
                f"Ollama returned HTTP {status_code}."
            ) from exc
        except ResponseError as exc:
            status_code = getattr(exc, "status_code", None)
            if (
                isinstance(status_code, int)
                and not isinstance(status_code, bool)
                and status_code > 0
            ):
                logger.warning(
                    "Ollama returned HTTP %s for structured model %s",
                    status_code,
                    selected_model,
                )
                raise OllamaResponseError(
                    f"Ollama returned HTTP {status_code}."
                ) from exc

            logger.warning(
                "Ollama returned an error response for structured model %s "
                "(%s)",
                selected_model,
                type(exc).__name__,
            )
            raise OllamaResponseError(
                "Ollama returned an invalid response."
            ) from exc
        except httpx.TransportError as exc:
            logger.warning(
                "Ollama transport failed for structured model %s (%s)",
                selected_model,
                type(exc).__name__,
            )
            raise OllamaUnavailableError(
                "Ollama service is unavailable."
            ) from exc
        except OSError as exc:
            logger.warning(
                "Ollama connection failed for structured model %s (%s)",
                selected_model,
                type(exc).__name__,
            )
            raise OllamaUnavailableError(
                "Ollama service is unavailable."
            ) from exc
        except Exception as exc:
            logger.warning(
                "Structured generation failed for model %s (%s)",
                selected_model,
                type(exc).__name__,
            )
            raise StructuredGenerationFailureError(
                "Structured generation failed."
            ) from exc

        generation = self._build_generation(
            payload,
            model_class,
            selected_model,
        )
        logger.info(
            "Structured generation succeeded for model %s",
            generation.model,
        )
        return generation

    def _build_generation(
        self,
        payload: object,
        model_class: type[BaseModel],
        requested_model: str,
    ) -> StructuredGeneration:
        if not isinstance(payload, dict) or not {
            "raw",
            "parsed",
            "parsing_error",
        }.issubset(payload):
            logger.warning(
                "Structured result was not a mapping for model %s",
                requested_model,
            )
            raise StructuredGenerationFailureError(
                "Model returned a malformed structured response."
            )

        raw = payload["raw"]
        parsed = payload["parsed"]
        parsing_error = payload["parsing_error"]

        if parsing_error is not None and not isinstance(
            parsing_error,
            BaseException,
        ):
            logger.warning(
                "Structured parsing error had an unexpected type for "
                "model %s (%s)",
                requested_model,
                type(parsing_error).__name__,
            )
            raise StructuredGenerationFailureError(
                "Model returned a malformed structured response."
            )

        if parsing_error is not None or parsed is None:
            logger.warning(
                "Structured parsing failed for model %s (%s)",
                requested_model,
                type(parsing_error).__name__,
            )
            raise StructuredGenerationFailureError(
                "Model returned a malformed structured response."
            ) from parsing_error

        if not isinstance(raw, BaseMessage):
            logger.warning(
                "Structured result lacked a raw message for model %s",
                requested_model,
            )
            raise StructuredGenerationFailureError(
                "Model returned a malformed structured response."
            )

        if not isinstance(parsed, BaseModel) or not isinstance(
            parsed,
            model_class,
        ):
            logger.warning(
                "Structured result had an unexpected parsed type for "
                "model %s (%s)",
                requested_model,
                type(parsed).__name__,
            )
            raise StructuredGenerationFailureError(
                "Model returned a malformed structured response."
            )

        metadata = raw.response_metadata
        if not isinstance(metadata, dict):
            logger.warning(
                "Structured completion metadata was missing for model %s",
                requested_model,
            )
            raise OllamaGenerationIncompleteError(
                "Generation completion could not be verified."
            )

        done = metadata.get("done")
        if done is not True:
            logger.warning(
                "Structured completion was not confirmed for model %s "
                "(done=%r)",
                requested_model,
                done,
            )
            raise OllamaGenerationIncompleteError(
                "Generation completion could not be verified."
            )

        done_reason = metadata.get("done_reason")
        if done_reason is not None and not isinstance(done_reason, str):
            logger.warning(
                "Structured completion reason had an unexpected type for "
                "model %s (%s)",
                requested_model,
                type(done_reason).__name__,
            )
            raise OllamaGenerationIncompleteError(
                "Generation completion could not be verified."
            )

        if done_reason == _LENGTH_DONE_REASON:
            logger.warning(
                "Structured completion reached the token limit for model %s",
                requested_model,
            )
            raise OllamaGenerationIncompleteError(
                "Generation completion could not be verified."
            )

        model_id = self._optional_str(metadata.get("model"))
        if model_id is None:
            model_id = requested_model

        total_duration_ns = self._optional_int(
            metadata.get("total_duration")
        )
        prompt_eval_count = self._optional_int(
            metadata.get("prompt_eval_count")
        )
        eval_count = self._optional_int(metadata.get("eval_count"))

        # ChatOllama 1.1.0 also mirrors token counts into usage_metadata;
        # use it only when the Ollama response metadata omits them.
        usage_metadata = getattr(raw, "usage_metadata", None)
        if isinstance(usage_metadata, dict):
            if prompt_eval_count is None:
                prompt_eval_count = self._optional_int(
                    usage_metadata.get("input_tokens")
                )
            if eval_count is None:
                eval_count = self._optional_int(
                    usage_metadata.get("output_tokens")
                )

        return StructuredGeneration(
            result=parsed,
            completion=True,
            model=model_id,
            total_duration_ms=(
                round(
                    total_duration_ns / _NANOSECONDS_PER_MILLISECOND,
                    3,
                )
                if total_duration_ns is not None
                else None
            ),
            prompt_eval_count=prompt_eval_count,
            eval_count=eval_count,
        )

    @staticmethod
    def _optional_int(value: object) -> int | None:
        if isinstance(value, bool):
            return None
        return value if isinstance(value, int) and value >= 0 else None

    @staticmethod
    def _optional_str(value: object) -> str | None:
        if not isinstance(value, str):
            return None
        stripped = value.strip()
        return stripped or None
