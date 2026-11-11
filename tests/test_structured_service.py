"""Deterministic tests for the schema-driven structured-output service.

All adapters in this module are in-process fakes implementing the
``StructuredModelAdapter`` protocol. No network, Ollama, LangChain model,
or database is used.
"""

from __future__ import annotations

import logging
from dataclasses import FrozenInstanceError

import pytest
from pydantic import ValidationError

from nexus_ai.model_adapters import (
    OllamaGenerationIncompleteError,
    StructuredGeneration,
    StructuredGenerationFailureError,
)
from nexus_ai.ollama import (
    OllamaResponseError,
    OllamaTimeoutError,
    OllamaUnavailableError,
)
from nexus_ai.structured_outputs import (
    DEFAULT_REST_EXPLANATION_PROMPT,
    RESTExplanation,
)
from nexus_ai.structured_schemas import (
    StructuredSchemaNotFoundError,
    get_schema_spec,
)
from nexus_ai.structured_service import (
    GenerationAttemptMetrics,
    GenerationMetrics,
    StructuredGenerationResult,
    StructuredOutputService,
    StructuredRetryPolicy,
    StructuredServiceRejectedError,
)

SCHEMA_NAME = "rest_explanation"

VALID_DATA = RESTExplanation(
    rest_expansion="Representational State Transfer",
    api_expansion="Application Programming Interface",
    purpose="A standard way for systems to exchange data.",
)

INVALID_DATA = VALID_DATA.model_copy(
    update={"rest_expansion": "Representational State of Resource"}
)

VALIDATION_ERROR_TEXT = (
    "rest_expansion must be 'Representational State Transfer'."
)


def make_generation(
    result=VALID_DATA,
    *,
    completion=True,
    model="fake-model",
    duration_ms=10.0,
    prompt_eval_count=3,
    eval_count=5,
):
    """Build adapter metadata for one deterministic fake response."""

    return StructuredGeneration(
        result=result,
        completion=completion,
        model=model,
        total_duration_ms=duration_ms,
        prompt_eval_count=prompt_eval_count,
        eval_count=eval_count,
    )


class FakeAdapter:
    """In-process adapter that records calls and replays scripted outcomes."""

    def __init__(self, outcomes):
        self._outcomes = list(outcomes)
        self.calls = []

    def generate_structured(self, prompt, model_class, *, model=None):
        self.calls.append(
            {"prompt": prompt, "model_class": model_class, "model": model}
        )
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    @property
    def call_count(self):
        return len(self.calls)


def make_service(adapter, *, default_model="default-model", max_attempts=None):
    policy = (
        StructuredRetryPolicy(max_attempts=max_attempts)
        if max_attempts is not None
        else None
    )
    return StructuredOutputService(
        adapter,
        default_model=default_model,
        retry_policy=policy,
    )


# ---------------------------------------------------------------------------
# Success path
# ---------------------------------------------------------------------------


def test_successful_first_attempt_returns_result_and_forwards_inputs():
    adapter = FakeAdapter([make_generation(VALID_DATA)])
    service = make_service(adapter)

    result = service.generate(
        SCHEMA_NAME,
        "Explain REST APIs precisely.",
        model="explicit-model",
    )

    assert isinstance(result, StructuredGenerationResult)
    assert result.schema_name == SCHEMA_NAME
    assert result.data is VALID_DATA
    assert adapter.call_count == 1
    assert adapter.calls[0]["prompt"] == "Explain REST APIs precisely."
    assert adapter.calls[0]["model_class"] is RESTExplanation
    assert adapter.calls[0]["model"] == "explicit-model"

    metrics = result.metrics
    assert metrics.attempts == 1
    assert metrics.per_attempt == (
        GenerationAttemptMetrics(
            model="fake-model",
            duration_ms=10.0,
            prompt_eval_count=3,
            eval_count=5,
        ),
    )
    assert metrics.model == "fake-model"
    assert metrics.total_generation_duration_ms == 10.0
    assert metrics.prompt_eval_count == 3
    assert metrics.eval_count == 5


def test_none_prompt_uses_registry_default_prompt():
    adapter = FakeAdapter([make_generation(VALID_DATA)])
    service = make_service(adapter)

    service.generate(SCHEMA_NAME)

    default_prompt = get_schema_spec(SCHEMA_NAME).default_prompt
    assert default_prompt == DEFAULT_REST_EXPLANATION_PROMPT
    assert adapter.call_count == 1
    assert adapter.calls[0]["prompt"] == default_prompt


def test_explicit_model_wins_and_default_is_used_when_missing_or_blank():
    explicit_adapter = FakeAdapter([make_generation(VALID_DATA)])
    make_service(explicit_adapter).generate(
        SCHEMA_NAME, "prompt", model="other-model"
    )
    assert explicit_adapter.calls[0]["model"] == "other-model"

    omitted_adapter = FakeAdapter([make_generation(VALID_DATA)])
    make_service(omitted_adapter).generate(SCHEMA_NAME, "prompt")
    assert omitted_adapter.calls[0]["model"] == "default-model"

    blank_adapter = FakeAdapter([make_generation(VALID_DATA)])
    make_service(blank_adapter).generate(
        SCHEMA_NAME, "prompt", model="   "
    )
    assert blank_adapter.calls[0]["model"] == "default-model"


# ---------------------------------------------------------------------------
# Pre-adapter validation
# ---------------------------------------------------------------------------


def test_unknown_schema_raises_before_adapter_is_called():
    adapter = FakeAdapter([])
    service = make_service(adapter)

    with pytest.raises(StructuredSchemaNotFoundError):
        service.generate("not-a-real-schema", "prompt")

    assert adapter.call_count == 0


@pytest.mark.parametrize("invalid_prompt", [123, "", "   ", "\t\n"])
def test_invalid_prompt_is_rejected_before_adapter_is_called(invalid_prompt):
    adapter = FakeAdapter([])
    service = make_service(adapter)

    with pytest.raises(ValueError):
        service.generate(SCHEMA_NAME, invalid_prompt)

    assert adapter.call_count == 0


# ---------------------------------------------------------------------------
# Retry policy
# ---------------------------------------------------------------------------


def test_retry_policy_accepts_only_one_or_two_attempts():
    assert StructuredRetryPolicy().max_attempts == 2
    assert StructuredRetryPolicy(max_attempts=1).max_attempts == 1
    assert StructuredRetryPolicy(max_attempts=2).max_attempts == 2


@pytest.mark.parametrize(
    "invalid_max_attempts",
    [0, 3, -1, True, 2.0, "2", None],
)
def test_retry_policy_rejects_invalid_values(invalid_max_attempts):
    with pytest.raises(ValueError):
        StructuredRetryPolicy(max_attempts=invalid_max_attempts)


# ---------------------------------------------------------------------------
# Bounded semantic retry and final rejection
# ---------------------------------------------------------------------------


def test_semantic_failure_then_success_retries_with_correction_prompt():
    first = make_generation(
        INVALID_DATA,
        model="first-model",
        duration_ms=10.0,
        prompt_eval_count=3,
        eval_count=4,
    )
    second = make_generation(
        VALID_DATA,
        model="second-model",
        duration_ms=25.5,
        prompt_eval_count=7,
        eval_count=9,
    )
    adapter = FakeAdapter([first, second])
    service = make_service(adapter)

    result = service.generate(SCHEMA_NAME, "Original prompt.")

    assert result.data is VALID_DATA
    assert adapter.call_count == 2
    assert adapter.calls[0]["prompt"] == "Original prompt."
    correction_prompt = adapter.calls[1]["prompt"]
    assert correction_prompt != adapter.calls[0]["prompt"]
    assert "Original prompt." in correction_prompt
    assert VALIDATION_ERROR_TEXT in correction_prompt

    metrics = result.metrics
    assert metrics.attempts == 2
    assert metrics.per_attempt == (
        GenerationAttemptMetrics(
            model="first-model",
            duration_ms=10.0,
            prompt_eval_count=3,
            eval_count=4,
        ),
        GenerationAttemptMetrics(
            model="second-model",
            duration_ms=25.5,
            prompt_eval_count=7,
            eval_count=9,
        ),
    )
    assert metrics.model == "second-model"
    assert metrics.total_generation_duration_ms == 35.5
    assert metrics.prompt_eval_count == 10
    assert metrics.eval_count == 13


def test_all_attempts_failing_raises_generic_service_rejection():
    adapter = FakeAdapter(
        [make_generation(INVALID_DATA), make_generation(INVALID_DATA)]
    )
    service = make_service(adapter)

    with pytest.raises(StructuredServiceRejectedError) as exc_info:
        service.generate(SCHEMA_NAME, "Original prompt.")

    rejection = exc_info.value
    assert rejection.attempts == 2
    assert isinstance(rejection.last_error, ValueError)
    assert str(rejection.last_error) == VALIDATION_ERROR_TEXT
    assert VALIDATION_ERROR_TEXT not in str(rejection)
    assert "rejected after 2 attempt" in str(rejection)
    assert adapter.call_count == 2
    assert rejection.metrics.attempts == 2
    assert len(rejection.metrics.per_attempt) == 2


def test_single_attempt_policy_rejects_after_one_adapter_call():
    adapter = FakeAdapter(
        [make_generation(INVALID_DATA), make_generation(VALID_DATA)]
    )
    service = make_service(adapter, max_attempts=1)

    with pytest.raises(StructuredServiceRejectedError) as exc_info:
        service.generate(SCHEMA_NAME, "Original prompt.")

    assert exc_info.value.attempts == 1
    assert exc_info.value.metrics.attempts == 1
    assert adapter.call_count == 1


# ---------------------------------------------------------------------------
# Provider failures and completion enforcement
# ---------------------------------------------------------------------------

PROVIDER_ERROR_TYPES = (
    OllamaTimeoutError,
    OllamaUnavailableError,
    OllamaResponseError,
    OllamaGenerationIncompleteError,
    StructuredGenerationFailureError,
)


@pytest.mark.parametrize("error_type", PROVIDER_ERROR_TYPES)
def test_provider_error_mid_run_propagates_unchanged_with_metrics(error_type):
    provider_error = error_type("provider detail that must not leak")
    first = make_generation(
        INVALID_DATA,
        model="first-model",
        duration_ms=10.0,
        prompt_eval_count=3,
        eval_count=4,
    )
    adapter = FakeAdapter(
        [first, provider_error, make_generation(VALID_DATA)]
    )
    service = make_service(adapter)

    with pytest.raises(error_type) as exc_info:
        service.generate(SCHEMA_NAME, "Original prompt.")

    assert exc_info.value is provider_error
    assert adapter.call_count == 2

    metrics = provider_error.generation_metrics
    assert isinstance(metrics, GenerationMetrics)
    assert metrics.attempts == 2
    assert metrics.per_attempt == (
        GenerationAttemptMetrics(
            model="first-model",
            duration_ms=10.0,
            prompt_eval_count=3,
            eval_count=4,
        ),
    )
    assert metrics.model == "first-model"
    assert metrics.total_generation_duration_ms is None
    assert metrics.prompt_eval_count is None
    assert metrics.eval_count is None


@pytest.mark.parametrize("error_type", PROVIDER_ERROR_TYPES)
def test_provider_error_on_first_attempt_counts_call_without_metadata(
    error_type,
):
    provider_error = error_type("provider detail")
    adapter = FakeAdapter([provider_error])
    service = make_service(adapter)

    with pytest.raises(error_type) as exc_info:
        service.generate(SCHEMA_NAME, "Original prompt.")

    assert exc_info.value is provider_error
    assert adapter.call_count == 1

    metrics = provider_error.generation_metrics
    assert metrics.attempts == 1
    assert metrics.per_attempt == ()
    assert metrics.model is None
    assert metrics.total_generation_duration_ms is None
    assert metrics.prompt_eval_count is None
    assert metrics.eval_count is None


def test_incomplete_generation_is_rejected_with_metrics_no_success_path():
    incomplete = make_generation(
        VALID_DATA,
        completion=False,
        model="incomplete-model",
        duration_ms=7.5,
        prompt_eval_count=2,
        eval_count=4,
    )
    adapter = FakeAdapter([incomplete, make_generation(VALID_DATA)])
    service = make_service(adapter)

    with pytest.raises(OllamaGenerationIncompleteError) as exc_info:
        service.generate(SCHEMA_NAME, "Original prompt.")

    assert adapter.call_count == 1
    metrics = exc_info.value.generation_metrics
    assert metrics.attempts == 1
    assert metrics.per_attempt == (
        GenerationAttemptMetrics(
            model="incomplete-model",
            duration_ms=7.5,
            prompt_eval_count=2,
            eval_count=4,
        ),
    )
    assert metrics.total_generation_duration_ms == 7.5
    assert metrics.prompt_eval_count == 2
    assert metrics.eval_count == 4


# ---------------------------------------------------------------------------
# Metrics aggregation and absent values
# ---------------------------------------------------------------------------


def test_metrics_do_not_report_partial_values_as_aggregates():
    first = make_generation(
        INVALID_DATA,
        duration_ms=10.0,
        prompt_eval_count=3,
        eval_count=4,
    )
    second = make_generation(
        VALID_DATA,
        duration_ms=None,
        prompt_eval_count=None,
        eval_count=None,
    )
    adapter = FakeAdapter([first, second])
    service = make_service(adapter)

    result = service.generate(SCHEMA_NAME, "prompt")

    assert result.metrics.attempts == 2
    assert len(result.metrics.per_attempt) == 2
    assert result.metrics.total_generation_duration_ms is None
    assert result.metrics.prompt_eval_count is None
    assert result.metrics.eval_count is None
    assert result.metrics.per_attempt[0].duration_ms == 10.0
    assert result.metrics.per_attempt[0].prompt_eval_count == 3
    assert result.metrics.per_attempt[0].eval_count == 4


def test_metrics_missing_for_every_attempt_stay_none_not_zero():
    first = make_generation(
        INVALID_DATA,
        model=None,
        duration_ms=None,
        prompt_eval_count=None,
        eval_count=None,
    )
    second = make_generation(
        VALID_DATA,
        model=None,
        duration_ms=None,
        prompt_eval_count=None,
        eval_count=None,
    )
    adapter = FakeAdapter([first, second])
    service = make_service(adapter)

    result = service.generate(SCHEMA_NAME, "prompt")

    metrics = result.metrics
    assert metrics.attempts == 2
    assert len(metrics.per_attempt) == 2
    assert metrics.model is None
    assert metrics.total_generation_duration_ms is None
    assert metrics.prompt_eval_count is None
    assert metrics.eval_count is None


# ---------------------------------------------------------------------------
# Safe logging
# ---------------------------------------------------------------------------

SERVICE_LOGGER = "nexus_ai.structured_service"


def _assert_no_secret_in_logs(caplog, secrets):
    log_text = caplog.text
    for secret in secrets:
        assert secret not in log_text


def test_success_logging_does_not_leak_prompt_or_generated_data(caplog):
    caplog.set_level(logging.DEBUG, logger=SERVICE_LOGGER)
    prompt_marker = "UNIQUE_PROMPT_SUCCESS_MARKER_9001"
    purpose_marker = "UNIQUE_GENERATED_SUCCESS_MARKER_9002"
    generated = VALID_DATA.model_copy(update={"purpose": purpose_marker})
    adapter = FakeAdapter([make_generation(generated)])
    service = make_service(adapter)

    caplog.clear()
    service.generate(SCHEMA_NAME, prompt_marker)

    assert "Structured generation accepted" in caplog.text
    _assert_no_secret_in_logs(
        caplog, [prompt_marker, purpose_marker, VALIDATION_ERROR_TEXT]
    )


def test_rejection_logging_does_not_leak_prompt_data_or_validation_text(
    caplog,
):
    caplog.set_level(logging.DEBUG, logger=SERVICE_LOGGER)
    prompt_marker = "UNIQUE_PROMPT_REJECTION_MARKER_9003"
    purpose_marker = "UNIQUE_GENERATED_REJECTION_MARKER_9004"
    invalid = INVALID_DATA.model_copy(update={"purpose": purpose_marker})
    adapter = FakeAdapter([make_generation(invalid), make_generation(invalid)])
    service = make_service(adapter)

    caplog.clear()
    with pytest.raises(StructuredServiceRejectedError):
        service.generate(SCHEMA_NAME, prompt_marker)

    assert "rejected" in caplog.text
    _assert_no_secret_in_logs(
        caplog,
        [
            prompt_marker,
            purpose_marker,
            VALIDATION_ERROR_TEXT,
            "Representational State of Resource",
        ],
    )


def test_provider_failure_logging_does_not_leak_prompt_data_or_error(
    caplog,
):
    caplog.set_level(logging.DEBUG, logger=SERVICE_LOGGER)
    prompt_marker = "UNIQUE_PROMPT_PROVIDER_MARKER_9005"
    purpose_marker = "UNIQUE_GENERATED_PROVIDER_MARKER_9006"
    error_marker = "UNIQUE_PROVIDER_ERROR_MARKER_9007"
    invalid = INVALID_DATA.model_copy(update={"purpose": purpose_marker})
    provider_error = OllamaTimeoutError(error_marker)
    adapter = FakeAdapter(
        [make_generation(invalid), provider_error]
    )
    service = make_service(adapter)

    caplog.clear()
    with pytest.raises(OllamaTimeoutError):
        service.generate(SCHEMA_NAME, prompt_marker)

    assert "provider failure" in caplog.text
    _assert_no_secret_in_logs(
        caplog,
        [prompt_marker, purpose_marker, error_marker, VALIDATION_ERROR_TEXT],
    )


# ---------------------------------------------------------------------------
# Non-provider errors, frozen contract, and taxonomy
# ---------------------------------------------------------------------------


def test_parsing_error_from_adapter_propagates_unchanged_without_retry():
    try:
        RESTExplanation.model_validate({})
    except ValidationError as err:
        parsing_error = err
    else:  # pragma: no cover - guards the test setup itself
        raise AssertionError("expected RESTExplanation validation to fail")

    adapter = FakeAdapter(
        [parsing_error, make_generation(VALID_DATA)]
    )
    service = make_service(adapter)

    with pytest.raises(ValidationError) as exc_info:
        service.generate(SCHEMA_NAME, "Original prompt.")

    assert exc_info.value is parsing_error
    assert adapter.call_count == 1


def test_metrics_dataclasses_are_frozen_and_attempt_type_is_preserved():
    attempt = GenerationAttemptMetrics(
        model="fake-model",
        duration_ms=10.0,
        prompt_eval_count=3,
        eval_count=5,
    )
    metrics = GenerationMetrics(
        attempts=1,
        per_attempt=(attempt,),
        model="fake-model",
        total_generation_duration_ms=10.0,
        prompt_eval_count=3,
        eval_count=5,
    )

    with pytest.raises(FrozenInstanceError):
        attempt.model = "mutated"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        metrics.attempts = 2  # type: ignore[misc]

    adapter = FakeAdapter([make_generation(VALID_DATA)])
    result = make_service(adapter).generate(SCHEMA_NAME, "prompt")

    assert isinstance(result.metrics, GenerationMetrics)
    assert isinstance(result.metrics.per_attempt[0], GenerationAttemptMetrics)


def test_provider_error_taxonomy_relationships_are_preserved():
    assert issubclass(OllamaTimeoutError, OllamaUnavailableError)
    assert issubclass(
        OllamaGenerationIncompleteError, StructuredGenerationFailureError
    )
    assert not issubclass(OllamaResponseError, OllamaUnavailableError)
    assert not issubclass(
        StructuredGenerationFailureError, OllamaUnavailableError
    )
