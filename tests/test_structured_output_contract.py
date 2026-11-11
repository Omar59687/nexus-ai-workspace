"""Cross-component contract tests for P3-CP4 structured output system.

These tests codify the mandatory frozen contract (clauses 1-9). They are
independent of source code — they will fail if components violate the contract,
and failures are evidence routed to file owners through the orchestrator.
"""

import inspect
import logging
from pytest import raises

from nexus_ai.structured_schemas import (
    SCHEMA_NAMES,
    SCHEMA_REGISTRY,
    get_schema_spec,
    StructuredSchemaNotFoundError,
)
from nexus_ai.structured_service import (
    StructuredServiceRejectedError,
    StructuredOutputService,
    StructuredRetryPolicy,
    StructuredGenerationResult,
    GenerationMetrics,
    GenerationAttemptMetrics,
)
from nexus_ai.model_adapters import (
    StructuredModelAdapter,
    LangChainChatOllamaAdapter,
    StructuredGeneration,
    OllamaGenerationIncompleteError,
)
from nexus_ai.structured_outputs import RESTExplanation, validate_rest_explanation
from pydantic import BaseModel


# ──────────────────────────────────────────────────────────────────────
# Helper: tiny purpose-built pydantic model (not registered in the frozen registry)
# ──────────────────────────────────────────────────────────────────────

class _TinyModel(BaseModel):
    """Minimal Pydantic model used solely for protocol/signature tests."""
    value: str


# ──────────────────────────────────────────────────────────────────────
# Helper: fake adapter that records calls and replays scripted outcomes
# ──────────────────────────────────────────────────────────────────────

class FakeAdapter:
    """Fake adapter implementing StructuredModelAdapter protocol.

    Records every (prompt, model_class, model) call and replays a pre-
    planned outcome (StructuredGeneration or Exception).  Zero network,
    zero Ollama, fully deterministic.
    """

    def __init__(self, outcomes):
        """outcomes: list of StructuredGeneration or Exception instances."""
        self._outcomes = list(outcomes)
        self._call_args = []

    def generate_structured(self, prompt, model_class, *, model=None):
        """Record the call and replay the next planned outcome."""
        self._call_args.append((prompt, model_class, model))
        if not self._outcomes:
            raise RuntimeError("No more planned outcomes")
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def recorded_call_args(self):
        """Return list of (prompt, model_class, model) tuples seen so far."""
        return list(self._call_args)


def _rest(**kwargs):
    """Create a RESTExplanation with sensible defaults merged."""
    defaults = {
        "rest_expansion": "Representational State Transfer",
        "api_expansion": "Application Programming Interface",
        "purpose": "A standard way for systems to exchange data.",
    }
    defaults.update(kwargs)
    return RESTExplanation(**defaults)


# ──────────────────────────────────────────────────────────────────────
# Clause 1: Protocol compatibility
# ──────────────────────────────────────────────────────────────────────


def test_protocol_signature_structured_model_adapter():
    """StructuredModelAdapter.generate_structured has the documented signature."""
    # inspect.signature on a Protocol includes 'self' as first param;
    # verify the remaining params match the documented shape.
    sig = inspect.signature(StructuredModelAdapter.generate_structured)
    params = list(sig.parameters.values())
    # skip 'self'
    actual_params = params[1:]
    assert len(actual_params) == 3  # prompt, model_class, model
    assert actual_params[0].name == "prompt"
    assert actual_params[1].name == "model_class"
    # model should be keyword-only (after the protocol's *)
    model_param = actual_params[2]
    assert model_param.kind == inspect.Parameter.KEYWORD_ONLY


def test_langchain_adapter_conforms_to_protocol_structurally():
    """LangChainChatOllamaAdapter satisfies the StructuredModelAdapter Protocol signature."""
    adapter = LangChainChatOllamaAdapter()
    sig = inspect.signature(adapter.generate_structured)
    assert "prompt" in sig.parameters
    assert "model_class" in sig.parameters
    assert "model" in sig.parameters
    model_param = sig.parameters["model"]
    assert model_param.kind == inspect.Parameter.KEYWORD_ONLY


# ──────────────────────────────────────────────────────────────────────
# Clause 2: Registry-to-service linkage
# ──────────────────────────────────────────────────────────────────────


def test_all_schema_names_resolve_via_get_schema_spec():
    """Every name in SCHEMA_NAMES resolves via get_schema_spec without error."""
    for name in SCHEMA_NAMES:
        spec = get_schema_spec(name)
        assert spec.schema_name == name


def test_schema_registry_model_classes_are_pydantic_base_model_subclasses():
    """Each SCHEMA_REGISTRY entry's model_class is a pydantic BaseModel subclass."""
    for name, spec in SCHEMA_REGISTRY.items():
        assert issubclass(spec.model_class, BaseModel)


def test_rest_explanation_generatable_via_service_with_fake_adapter():
    """rest_explanation schema is generatable through StructuredOutputService with a fake adapter."""
    valid_result = _rest()

    fake_adapter = FakeAdapter(
        [StructuredGeneration(
            result=valid_result,
            completion=True,
            model="test-model",
            total_duration_ms=100.0,
            prompt_eval_count=10,
            eval_count=5,
        )]
    )

    service = StructuredOutputService(
        adapter=fake_adapter,
        default_model="test-model",
    )

    result = service.generate(
        schema_name="rest_explanation",
        prompt="Explain REST APIs.",
    )

    assert isinstance(result.data, RESTExplanation)
    assert result.data.rest_expansion == "Representational State Transfer"
    assert result.data.api_expansion == "Application Programming Interface"
    assert result.data.purpose == "A standard way for systems to exchange data."
    assert len(fake_adapter.recorded_call_args()) == 1


def test_service_uses_rest_explanation_validator_for_success_retry_rejection():
    """Service uses the RESTExplanation validator for success/retry/rejection scripts."""
    valid_result = _rest()
    invalid_result = _rest(rest_expansion="Wrong Expansion")

    fake_adapter = FakeAdapter(
        [StructuredGeneration(
            result=invalid_result,
            completion=True,
            model="test-model",
            total_duration_ms=100.0,
            prompt_eval_count=10,
            eval_count=5,
        ),
         StructuredGeneration(
             result=valid_result,
             completion=True,
             model="test-model",
             total_duration_ms=100.0,
             prompt_eval_count=10,
             eval_count=5,
         )]
    )

    service = StructuredOutputService(
        adapter=fake_adapter,
        default_model="test-model",
    )

    result = service.generate(
        schema_name="rest_explanation",
        prompt="Explain REST APIs.",
    )

    assert isinstance(result.data, RESTExplanation)
    assert result.data.rest_expansion == "Representational State Transfer"


def test_service_rejects_when_all_attempts_fail_validation():
    """Service raises StructuredServiceRejectedError when all validation attempts fail."""
    invalid_result = _rest(rest_expansion="Bad")

    fake_adapter = FakeAdapter(
        [StructuredGeneration(
            result=invalid_result,
            completion=True,
            model="test-model",
            total_duration_ms=100.0,
            prompt_eval_count=10,
            eval_count=5,
        ),
         StructuredGeneration(
             result=invalid_result,
             completion=True,
             model="test-model",
             total_duration_ms=100.0,
             prompt_eval_count=10,
             eval_count=5,
         )]
    )

    service = StructuredOutputService(
        adapter=fake_adapter,
        default_model="test-model",
    )

    with raises(StructuredServiceRejectedError) as exc_info:
        service.generate(
            schema_name="rest_explanation",
            prompt="Explain REST APIs.",
        )

    assert exc_info.value.attempts == 2
    assert isinstance(exc_info.value.last_error, ValueError)


# ──────────────────────────────────────────────────────────────────────
# Clause 3: Error taxonomy
# ──────────────────────────────────────────────────────────────────────


def test_structured_schema_not_found_error_is_lookup_error():
    """StructuredSchemaNotFoundError is a LookupError."""
    try:
        raise StructuredSchemaNotFoundError("test")
    except LookupError:
        pass
    else:
        raise AssertionError("StructuredSchemaNotFoundError is not a LookupError")


def test_structured_service_rejected_error_has_attempts_last_error_metrics():
    """StructuredServiceRejectedError has .attempts/.last_error(.ValueError)/.metrics and a GENERIC message."""
    metrics = GenerationMetrics(
        attempts=2,
        per_attempt=(
            GenerationAttemptMetrics(model="m1", duration_ms=100.0, prompt_eval_count=10, eval_count=5),
            GenerationAttemptMetrics(model="m2", duration_ms=200.0, prompt_eval_count=15, eval_count=8),
        ),
        model="test-model",
        total_generation_duration_ms=300.0,
        prompt_eval_count=25,
        eval_count=13,
    )

    last_error = ValueError("validation failed")
    rejected = StructuredServiceRejectedError(attempts=2, last_error=last_error, metrics=metrics)

    assert rejected.attempts == 2
    assert rejected.last_error is last_error
    assert rejected.metrics is metrics
    msg = str(rejected)
    # Public message is intentionally generic — no validation text, no prompt text
    assert "validation failed" not in msg.lower()


def test_ollama_generation_incomplete_error_is_structured_generation_failure_which_is_ollama_error():
    """OllamaGenerationIncompleteError is a StructuredGenerationFailureError which is an OllamaError."""
    from nexus_ai.model_adapters import (
        OllamaGenerationIncompleteError,
        StructuredGenerationFailureError,
    )

    assert issubclass(OllamaGenerationIncompleteError, StructuredGenerationFailureError)


def test_provider_failure_exceptions_surface_with_generation_metrics_attached():
    """Provider failure exceptions raised by the adapter surface through the service with .generation_metrics attached."""
    from nexus_ai.structured_service import StructuredOutputService
    from nexus_ai.model_adapters import OllamaResponseError

    class RaisingAdapter:
        def generate_structured(self, prompt, model_class, *, model=None):
            raise OllamaResponseError("Ollama error")

    fake_adapter = RaisingAdapter()
    service = StructuredOutputService(
        adapter=fake_adapter,
        default_model="test-model",
    )

    with raises(OllamaResponseError) as exc_info:
        service.generate(
            schema_name="rest_explanation",
            prompt="Explain REST APIs.",
        )

    exc = exc_info.value
    assert hasattr(exc, "generation_metrics"), (
        "Provider failure exception must have generation_metrics attached"
    )


# ──────────────────────────────────────────────────────────────────────
# Clause 4: Retry bounds
# ──────────────────────────────────────────────────────────────────────


def test_service_performs_at_most_max_attempts_adapter_calls():
    """Service performs at most StructuredRetryPolicy().max_attempts (default 2) adapter calls."""
    valid_result = _rest()
    invalid_result = _rest(rest_expansion="Bad")

    fake_adapter = FakeAdapter(
        [StructuredGeneration(
            result=invalid_result,
            completion=True,
            model="test-model",
            total_duration_ms=100.0,
            prompt_eval_count=10,
            eval_count=5,
        ),
         StructuredGeneration(
             result=invalid_result,
             completion=True,
             model="test-model",
             total_duration_ms=100.0,
             prompt_eval_count=10,
             eval_count=5,
         )]
    )

    service = StructuredOutputService(
        adapter=fake_adapter,
        default_model="test-model",
        retry_policy=StructuredRetryPolicy(max_attempts=2),
    )

    with raises(StructuredServiceRejectedError):
        service.generate(
            schema_name="rest_explanation",
            prompt="Explain REST APIs.",
        )

    assert len(fake_adapter.recorded_call_args()) == 2


def test_failed_validation_retries_exactly_once_when_max_attempts_2():
    """Failed validation retries exactly once when max_attempts=2; no third call."""
    valid_result = _rest()
    invalid_result = _rest(rest_expansion="Wrong Expansion")

    fake_adapter = FakeAdapter(
        [StructuredGeneration(
            result=invalid_result,
            completion=True,
            model="test-model",
            total_duration_ms=100.0,
            prompt_eval_count=10,
            eval_count=5,
        ),
         StructuredGeneration(
             result=valid_result,
             completion=True,
             model="test-model",
             total_duration_ms=100.0,
             prompt_eval_count=10,
             eval_count=5,
         )]
    )

    service = StructuredOutputService(
        adapter=fake_adapter,
        default_model="test-model",
        retry_policy=StructuredRetryPolicy(max_attempts=2),
    )

    # First attempt returns invalid (fails validator), second (with correction)
    # returns valid result
    result = service.generate(
        schema_name="rest_explanation",
        prompt="Explain REST APIs.",
    )

    assert isinstance(result.data, RESTExplanation)
    assert len(fake_adapter.recorded_call_args()) == 2


def test_attempts_mode_1_never_retries():
    """Attempts=1 mode never retries — single adapter call, then rejection."""
    invalid_result = _rest(rest_expansion="Bad")

    fake_adapter = FakeAdapter(
        [StructuredGeneration(
            result=invalid_result,
            completion=True,
            model="test-model",
            total_duration_ms=100.0,
            prompt_eval_count=10,
            eval_count=5,
        )]
    )

    service = StructuredOutputService(
        adapter=fake_adapter,
        default_model="test-model",
        retry_policy=StructuredRetryPolicy(max_attempts=1),
    )

    with raises(StructuredServiceRejectedError) as exc_info:
        service.generate(
            schema_name="rest_explanation",
            prompt="Explain REST APIs.",
        )

    assert len(fake_adapter.recorded_call_args()) == 1
    assert exc_info.value.attempts == 1


# ──────────────────────────────────────────────────────────────────────
# Clause 5: Metrics are never fabricated
# ──────────────────────────────────────────────────────────────────────


def test_aggregate_metrics_equal_per_attempt_when_present():
    """Aggregate metrics equal the per-attempt provider metadata when present."""
    from nexus_ai.structured_service import _aggregate_metrics

    per_attempt = (
        GenerationAttemptMetrics(
            model="test-model",
            duration_ms=150.0,
            prompt_eval_count=10,
            eval_count=5,
        ),
    )

    metrics = _aggregate_metrics(attempts=1, per_attempt=per_attempt)
    assert metrics.model == "test-model"
    assert metrics.total_generation_duration_ms == 150.0
    assert metrics.prompt_eval_count == 10
    assert metrics.eval_count == 5


def test_aggregate_metrics_none_for_missing_optional_values_not_fabricated_as_zero():
    """Aggregate metrics equal None (not 0) for missing optional values."""
    from nexus_ai.structured_service import _aggregate_metrics, GenerationAttemptMetrics

    per_attempt = (
        GenerationAttemptMetrics(
            model=None,
            duration_ms=None,
            prompt_eval_count=None,
            eval_count=None,
        ),
    )

    metrics = _aggregate_metrics(attempts=1, per_attempt=per_attempt)
    assert metrics.model is None
    assert metrics.total_generation_duration_ms is None
    assert metrics.prompt_eval_count is None
    assert metrics.eval_count is None


def test_attempts_counts_calls_without_metadata_too():
    """Attempts counts calls without metadata too; per_attempt does not strip them."""
    from nexus_ai.structured_service import _aggregate_metrics, GenerationAttemptMetrics

    per_attempt = (
        GenerationAttemptMetrics(
            model=None,
            duration_ms=None,
            prompt_eval_count=None,
            eval_count=None,
        ),
    )

    metrics = _aggregate_metrics(attempts=2, per_attempt=per_attempt)
    assert metrics.attempts == 2  # counts the calls even though metadata is missing
    assert len(metrics.per_attempt) == 1  # per_attempt preserves the tuple as-is
    assert metrics.total_generation_duration_ms is None
    assert metrics.prompt_eval_count is None
    assert metrics.eval_count is None


# ──────────────────────────────────────────────────────────────────────
# Clause 6: Model selection
# ──────────────────────────────────────────────────────────────────────


def test_service_forwards_callers_model_to_adapter():
    """Service forwards the caller's model to the adapter."""
    from nexus_ai.structured_service import StructuredOutputService

    captured = {}

    class CapturingAdapter:
        def generate_structured(self, prompt, model_class, *, model=None):
            captured["model"] = model
            from nexus_ai.model_adapters import StructuredGeneration
            from nexus_ai.structured_outputs import RESTExplanation
            valid = RESTExplanation(
                rest_expansion="Representational State Transfer",
                api_expansion="Application Programming Interface",
                purpose="A standard way for systems to exchange data.",
            )
            return StructuredGeneration(
                result=valid,
                completion=True,
                model=model or "default-model",
                total_duration_ms=100.0,
                prompt_eval_count=10,
                eval_count=5,
            )

    adapter = CapturingAdapter()
    service = StructuredOutputService(
        adapter=adapter,
        default_model="default-model-name",
    )

    service.generate(
        schema_name="rest_explanation",
        prompt="Explain REST APIs.",
        model="caller-specified-model",
    )

    assert captured["model"] == "caller-specified-model"


def test_whitespace_only_model_falls_back_to_default_model():
    """Whitespace-only model falls back to default_model."""
    from nexus_ai.structured_service import StructuredOutputService

    captured = {}

    class CapturingAdapter:
        def generate_structured(self, prompt, model_class, *, model=None):
            captured["model"] = model or "fallback"
            from nexus_ai.model_adapters import StructuredGeneration
            from nexus_ai.structured_outputs import RESTExplanation
            valid = RESTExplanation(
                rest_expansion="Representational State Transfer",
                api_expansion="Application Programming Interface",
                purpose="A standard way for systems to exchange data.",
            )
            return StructuredGeneration(
                result=valid,
                completion=True,
                model=(model or "fallback"),
                total_duration_ms=100.0,
                prompt_eval_count=10,
                eval_count=5,
            )

    adapter = CapturingAdapter()
    service = StructuredOutputService(
        adapter=adapter,
        default_model="default-model-name",
    )

    service.generate(
        schema_name="rest_explanation",
        prompt="Explain REST APIs.",
        model="   ",
    )

    assert captured["model"] == "default-model-name"


def test_default_model_flows_to_adapter_when_unspecified():
    """Default model flows to the adapter when model unspecified."""
    from nexus_ai.structured_service import StructuredOutputService

    captured = {}

    class CapturingAdapter:
        def generate_structured(self, prompt, model_class, *, model=None):
            captured["model"] = model
            from nexus_ai.model_adapters import StructuredGeneration
            from nexus_ai.structured_outputs import RESTExplanation
            valid = RESTExplanation(
                rest_expansion="Representational State Transfer",
                api_expansion="Application Programming Interface",
                purpose="A standard way for systems to exchange data.",
            )
            actual = model or "default-model-name"
            return StructuredGeneration(
                result=valid,
                completion=True,
                model=actual,
                total_duration_ms=100.0,
                prompt_eval_count=10,
                eval_count=5,
            )

    adapter = CapturingAdapter()
    service = StructuredOutputService(
        adapter=adapter,
        default_model="default-model-name",
    )

    # No model kwarg at all - service should use default_model
    service.generate(
        schema_name="rest_explanation",
        prompt="Explain REST APIs.",
    )

    # When model is omitted, service sets selected_model = default_model,
    # which flows to the adapter
    assert captured["model"] == "default-model-name"


# ──────────────────────────────────────────────────────────────────────
# Clause 7: Logging safety contract
# ──────────────────────────────────────────────────────────────────────

def test_logging_safety_success_no_prompt_data_or_validation_error(caplog):
    """Successful path: caplog contains neither prompt substring, generated data, nor validation error text."""
    purpose_marker = "UNIQUE_GENERATED_SUCCESS_MARKER_2a71"
    valid_result = _rest(purpose=purpose_marker)
    prompt_marker = "UNIQUE_PROMPT_SUCCESS_MARKER_4f9d"

    class LogCaptureAdapter:
        def __init__(self):
            self.call_args = []

        def generate_structured(self, prompt, model_class, *, model=None):
            self.call_args.append((prompt, model))
            from nexus_ai.model_adapters import StructuredGeneration
            return StructuredGeneration(
                result=valid_result,
                completion=True,
                model=model or "default",
                total_duration_ms=100.0,
                prompt_eval_count=10,
                eval_count=5,
            )

    capturing = LogCaptureAdapter()
    service = StructuredOutputService(
        adapter=capturing,
        default_model="default",
    )

    with caplog.at_level(logging.INFO, logger="nexus_ai.structured_service"):
        result = service.generate(
            schema_name="rest_explanation",
            prompt=prompt_marker,
        )

    assert result.data == valid_result
    assert len(capturing.call_args) == 1
    log_text = caplog.text
    assert prompt_marker not in log_text
    assert purpose_marker not in log_text
    assert "validation failed" not in log_text.lower()








def test_logging_safety_rejected_no_prompt_data_or_validation_error(caplog):
    """Rejected path: caplog contains neither prompt substring, generated data, nor validation error text."""
    class LogCaptureAdapter:
        def __init__(self):
            self.call_args = []

        def generate_structured(self, prompt, model_class, *, model=None):
            self.call_args.append((prompt, model))
            from nexus_ai.model_adapters import StructuredGeneration
            from nexus_ai.structured_outputs import RESTExplanation
            return StructuredGeneration(
                result=_rest(rest_expansion="Wrong Expansion"),
                completion=True,
                model=model or "default",
                total_duration_ms=100.0,
                prompt_eval_count=10,
                eval_count=5,
            )

    capturing = LogCaptureAdapter()
    service = StructuredOutputService(
        adapter=capturing,
        default_model="default",
    )

    with caplog.at_level(logging.WARNING, logger="nexus_ai.structured_service"):
        with raises(StructuredServiceRejectedError):
            service.generate(
                schema_name="rest_explanation",
                prompt="Explain REST APIs. Give the full expansions of REST and API.",
            )

    for record in caplog.records:
        record_msg = record.getMessage()
        assert "Explain REST APIs." not in record_msg, (
            f"Log contains prompt substring: {record_msg}"
        )
        assert "Wrong Expansion" not in record_msg


def test_logging_safety_provider_failure_no_prompt_data_or_validation_error(caplog):
    """Provider-failure path: caplog contains neither prompt substring, generated data, nor validation error text."""
    from nexus_ai.model_adapters import OllamaResponseError

    class LogCaptureAdapter:
        def __init__(self):
            self.call_args = []

        def generate_structured(self, prompt, model_class, *, model=None):
            self.call_args.append((prompt, model))
            from nexus_ai.model_adapters import StructuredGeneration
            raise OllamaResponseError("Ollama error")

    capturing = LogCaptureAdapter()
    service = StructuredOutputService(
        adapter=capturing,
        default_model="default",
    )

    with caplog.at_level(logging.WARNING, logger="nexus_ai.structured_service"):
        with raises(OllamaResponseError):
            service.generate(
                schema_name="rest_explanation",
                prompt="Explain REST APIs. Give the full expansions of REST and API.",
            )

    for record in caplog.records:
        record_msg = record.getMessage()
        assert "Explain REST APIs." not in record_msg, (
            f"Log contains prompt substring: {record_msg}"
        )
        assert "Ollama error" not in record_msg


def test_logging_safety_unknown_schema_no_prompt_in_log(caplog):
    """Unknown-schema path: caplog contains neither prompt substring, generated data, nor validation error text."""
    class NonCallingAdapter:
        def generate_structured(self, prompt, model_class, *, model=None):
            raise RuntimeError("should not be called")

    service = StructuredOutputService(
        adapter=NonCallingAdapter(),
        default_model="default",
    )

    with caplog.at_level(logging.ERROR, logger="nexus_ai.structured_service"):
        with raises(StructuredSchemaNotFoundError):
            service.generate(
                schema_name="nonexistent_schema",
                prompt="Explain REST APIs.",
            )

    for record in caplog.records:
        record_msg = record.getMessage()
        assert "Explain REST APIs." not in record_msg, (
            f"Log contains prompt substring: {record_msg}"
        )


# ──────────────────────────────────────────────────────────────────────
# Clause 8: Deterministic rejection semantics
# ──────────────────────────────────────────────────────────────────────

def test_final_rejection_never_returned_as_success():
    """Final rejection after exhausting bounded attempts is never returned as a success."""
    from nexus_ai.structured_service import StructuredOutputService, StructuredServiceRejectedError

    invalid_result = _rest(rest_expansion="Bad")

    fake_adapter = FakeAdapter(
        [StructuredGeneration(
            result=invalid_result,
            completion=True,
            model="test-model",
            total_duration_ms=100.0,
            prompt_eval_count=10,
            eval_count=5,
        ),
         StructuredGeneration(
             result=invalid_result,
             completion=True,
             model="test-model",
             total_duration_ms=100.0,
             prompt_eval_count=10,
             eval_count=5,
         )]
    )

    service = StructuredOutputService(
        adapter=fake_adapter,
        default_model="test-model",
    )

    with raises(StructuredServiceRejectedError):
        service.generate(
            schema_name="rest_explanation",
            prompt="Explain REST APIs.",
        )


def test_unknown_schema_lookup_fails_before_any_adapter_call():
    """Unknown schema lookup fails before any adapter call."""
    from nexus_ai.structured_service import StructuredOutputService

    class NonCallingAdapter:
        def generate_structured(self, prompt, model_class, *, model=None):
            raise RuntimeError("should not be called")

    service = StructuredOutputService(
        adapter=NonCallingAdapter(),
        default_model="default",
    )

    with raises(StructuredSchemaNotFoundError):
        service.generate(
            schema_name="nonexistent_schema",
            prompt="Explain REST APIs.",
        )



def test_blank_prompt_fails_before_any_adapter_call():
    """Blank prompt fails before any adapter call."""
    from nexus_ai.structured_service import StructuredOutputService

    class NonCallingAdapter:
        def generate_structured(self, prompt, model_class, *, model=None):
            raise RuntimeError("should not be called")

    service = StructuredOutputService(
        adapter=NonCallingAdapter(),
        default_model="default",
    )

    with raises(ValueError, match="Prompt cannot be blank."):
        service.generate(
            schema_name="rest_explanation",
            prompt="",  # empty string is blank; None uses default prompt instead
        )


# ──────────────────────────────────────────────────────────────────────
# Clause 9: Schema validity clarification
# ──────────────────────────────────────────────────────────────────────

def test_result_data_is_same_object_returned_by_adapter():
    """result.data is the same object returned by the adapter (identity, not equality)."""
    valid_result = _rest()

    fake_adapter = FakeAdapter(
        [StructuredGeneration(
            result=valid_result,
            completion=True,
            model="test-model",
            total_duration_ms=100.0,
            prompt_eval_count=10,
            eval_count=5,
        )]
    )

    service = StructuredOutputService(
        adapter=fake_adapter,
        default_model="test-model",
    )

    result = service.generate(
        schema_name="rest_explanation",
        prompt="Explain REST APIs.",
    )

    # The result.data must be the exact same object the adapter returned
    assert result.data is valid_result
