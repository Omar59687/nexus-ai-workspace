"""Schema-driven structured-output generation service.

Wraps the frozen generate-and-validate engine with the schema registry
and an Ollama model adapter, adding per-attempt metrics and bounded
semantic retries. Schema validity does not imply factual correctness: a
result accepted by the validator satisfies the schema contract only,
never the truth of the underlying content.
"""

import logging
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict

from nexus_ai.model_adapters import (
    OllamaGenerationIncompleteError,
    StructuredGeneration,
    StructuredGenerationFailureError,
    StructuredModelAdapter,
)
from nexus_ai.ollama import (
    OllamaResponseError,
    OllamaTimeoutError,
    OllamaUnavailableError,
)
from nexus_ai.structured_output_pipeline import (
    DEFAULT_MAX_ATTEMPTS,
    MAX_ATTEMPTS_LIMIT,
    StructuredOutputRejectedError,
    generate_with_validation,
)
from nexus_ai.structured_schemas import get_schema_spec


logger = logging.getLogger("nexus_ai.structured_service")

_PROVIDER_FAILURE_ERRORS: tuple[type[BaseException], ...] = (
    OllamaGenerationIncompleteError,
    StructuredGenerationFailureError,
    OllamaUnavailableError,
    OllamaTimeoutError,
    OllamaResponseError,
)


@dataclass(frozen=True)
class StructuredRetryPolicy:
    """Bounded retry configuration for structured generation."""

    max_attempts: int = DEFAULT_MAX_ATTEMPTS

    def __post_init__(self) -> None:
        if (
            not isinstance(self.max_attempts, int)
            or isinstance(self.max_attempts, bool)
            or not 1 <= self.max_attempts <= MAX_ATTEMPTS_LIMIT
        ):
            raise ValueError(
                "max_attempts must be between 1 and "
                f"{MAX_ATTEMPTS_LIMIT}"
            )


@dataclass(frozen=True)
class GenerationAttemptMetrics:
    """Provider metrics from one adapter call that returned metadata."""

    model: str | None
    duration_ms: float | None
    prompt_eval_count: int | None
    eval_count: int | None


@dataclass(frozen=True)
class GenerationMetrics:
    """Aggregate generation metrics; absent values are never fabricated."""

    attempts: int
    per_attempt: tuple[GenerationAttemptMetrics, ...]
    model: str | None
    total_generation_duration_ms: float | None
    prompt_eval_count: int | None
    eval_count: int | None


def _aggregate_metrics(
    attempts: int,
    per_attempt: tuple[GenerationAttemptMetrics, ...],
) -> GenerationMetrics:
    """Aggregate per-attempt adapter metrics into a single snapshot."""

    model: str | None = None
    for attempt in per_attempt:
        if attempt.model is not None:
            model = attempt.model

    durations = [
        attempt.duration_ms
        for attempt in per_attempt
        if attempt.duration_ms is not None
    ]
    prompt_eval_counts = [
        attempt.prompt_eval_count
        for attempt in per_attempt
        if attempt.prompt_eval_count is not None
    ]
    eval_counts = [
        attempt.eval_count
        for attempt in per_attempt
        if attempt.eval_count is not None
    ]

    return GenerationMetrics(
        attempts=attempts,
        per_attempt=per_attempt,
        model=model,
        total_generation_duration_ms=(
            round(sum(durations), 3) if durations else None
        ),
        prompt_eval_count=(
            sum(prompt_eval_counts) if prompt_eval_counts else None
        ),
        eval_count=sum(eval_counts) if eval_counts else None,
    )


class StructuredServiceRejectedError(RuntimeError):
    """Raised when semantic validation rejected every bounded attempt.

    The public message is intentionally generic; the original validation
    failure stays available on ``last_error`` and is never embedded in
    ``str`` or log output.
    """

    def __init__(
        self,
        attempts: int,
        last_error: ValueError,
        metrics: GenerationMetrics,
    ) -> None:
        super().__init__(
            f"Structured output rejected after {attempts} attempt(s)."
        )
        self.attempts = attempts
        self.last_error = last_error
        self.metrics = metrics


class StructuredGenerationResult(BaseModel):
    """Validated structured result with aggregate generation metrics."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    schema_name: str
    data: BaseModel
    metrics: GenerationMetrics


class StructuredOutputService:
    """Generate schema-validated structured outputs via an adapter."""

    def __init__(
        self,
        adapter: StructuredModelAdapter,
        *,
        default_model: str,
        retry_policy: StructuredRetryPolicy | None = None,
    ) -> None:
        if not isinstance(default_model, str) or not default_model.strip():
            raise ValueError("default_model must be a non-empty string.")
        self.adapter = adapter
        self.default_model = default_model
        self.retry_policy = (
            retry_policy
            if retry_policy is not None
            else StructuredRetryPolicy()
        )

    def generate(
        self,
        schema_name: str,
        prompt: str | None = None,
        *,
        model: str | None = None,
    ) -> StructuredGenerationResult:
        """Generate and validate one structured result by schema name.

        Semantic retries are bounded by the configured retry policy.
        Provider-category failures propagate unchanged with the metrics
        gathered so far attached; rejection after every attempt raises
        :class:`StructuredServiceRejectedError` with a generic message.
        """

        spec = get_schema_spec(schema_name)

        if prompt is None:
            resolved_prompt = spec.default_prompt
        elif isinstance(prompt, str) and prompt.strip():
            resolved_prompt = prompt
        else:
            raise ValueError("Prompt cannot be blank.")

        selected_model = (
            (model or self.default_model).strip() or self.default_model
        )

        attempts = 0
        per_attempt: list[GenerationAttemptMetrics] = []

        def generate_once(request_prompt: str) -> BaseModel:
            """Call the adapter once with completion enforcement."""

            nonlocal attempts
            attempts += 1
            generation: StructuredGeneration = (
                self.adapter.generate_structured(
                    request_prompt,
                    spec.model_class,
                    model=selected_model,
                )
            )
            # Record metadata for every adapter call that returned a
            # StructuredGeneration, including calls rejected below for
            # unverified completion. ``attempts`` already counts this call;
            # ``per_attempt`` must not silently drop its metrics.
            per_attempt.append(
                GenerationAttemptMetrics(
                    model=generation.model,
                    duration_ms=generation.total_duration_ms,
                    prompt_eval_count=generation.prompt_eval_count,
                    eval_count=generation.eval_count,
                )
            )
            # Defense in depth: never accept output whose completion the
            # provider metadata could not prove.
            if generation.completion is not True:
                raise OllamaGenerationIncompleteError(
                    "Generation completion could not be verified."
                )
            return generation.result

        try:
            result = generate_with_validation(
                generate=generate_once,
                validator=spec.validator,
                prompt=resolved_prompt,
                max_attempts=self.retry_policy.max_attempts,
            )
        except StructuredOutputRejectedError as exc:
            metrics = _aggregate_metrics(attempts, tuple(per_attempt))
            logger.warning(
                "Structured generation rejected for schema %s after %d "
                "attempt(s): %s",
                schema_name,
                attempts,
                type(exc).__name__,
            )
            raise StructuredServiceRejectedError(
                attempts, exc.last_error, metrics
            ) from exc
        except _PROVIDER_FAILURE_ERRORS as exc:
            exc.generation_metrics = _aggregate_metrics(
                attempts, tuple(per_attempt)
            )
            logger.warning(
                "Structured generation provider failure for schema %s: %s",
                schema_name,
                type(exc).__name__,
            )
            raise

        metrics = _aggregate_metrics(attempts, tuple(per_attempt))
        logger.info(
            "Structured generation accepted (schema=%r, model=%r, "
            "attempts=%d)",
            schema_name,
            selected_model,
            attempts,
        )
        return StructuredGenerationResult(
            schema_name=schema_name,
            data=result,
            metrics=metrics,
        )
