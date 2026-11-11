"""Deterministic HTTP contract tests for structured generation.

All model calls are replaced with an in-process adapter. These tests exercise
the FastAPI dependency boundary and never contact Ollama or PostgreSQL.
"""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

from nexus_ai import main as main_module
from nexus_ai.main import app, get_structured_output_service
from nexus_ai.model_adapters import (
    OllamaGenerationIncompleteError,
    StructuredGeneration,
    StructuredGenerationFailureError,
)
from nexus_ai.ollama import (
    DEFAULT_OLLAMA_MODEL,
    OllamaResponseError,
    OllamaTimeoutError,
    OllamaUnavailableError,
)
from nexus_ai.structured_outputs import (
    DEFAULT_REST_EXPLANATION_PROMPT,
    RESTExplanation,
)
from nexus_ai.structured_service import (
    StructuredOutputService,
    StructuredRetryPolicy,
)


SCHEMA_NAME = "rest_explanation"
PROMPT_SECRET = "STRUCTURED_API_PROMPT_SECRET_7d19"
OUTPUT_SECRET = "STRUCTURED_API_OUTPUT_SECRET_81b2"
ERROR_SECRET = "STRUCTURED_API_ERROR_SECRET_a551"
SERVICE_LOGGER = "nexus_ai.structured_service"

VALID_DATA = RESTExplanation(
    rest_expansion="Representational State Transfer",
    api_expansion="Application Programming Interface",
    purpose="A standard way for systems to exchange data.",
)
INVALID_DATA = VALID_DATA.model_copy(
    update={"rest_expansion": "Representational State of Resource"}
)


def make_generation(
    result: RESTExplanation = VALID_DATA,
    *,
    completion: bool = True,
    model: str | None = "test-model",
    duration_ms: float | None = 12.5,
    prompt_eval_count: int | None = 7,
    eval_count: int | None = 4,
) -> StructuredGeneration:
    return StructuredGeneration(
        result=result,
        completion=completion,
        model=model,
        total_duration_ms=duration_ms,
        prompt_eval_count=prompt_eval_count,
        eval_count=eval_count,
    )


class FakeAdapter:
    """In-process adapter that records requests and replays outcomes."""

    def __init__(self, outcomes: list[StructuredGeneration | BaseException]):
        self.outcomes = list(outcomes)
        self.calls: list[dict[str, object]] = []

    def generate_structured(self, prompt, model_class, *, model=None):
        self.calls.append(
            {"prompt": prompt, "model_class": model_class, "model": model}
        )
        if not self.outcomes:
            raise AssertionError("Unexpected extra structured-generation call")
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def make_service(
    adapter: FakeAdapter,
    *,
    max_attempts: int = 2,
) -> StructuredOutputService:
    return StructuredOutputService(
        adapter,
        default_model="configured-default-model",
        retry_policy=StructuredRetryPolicy(max_attempts=max_attempts),
    )


@pytest.fixture
def structured_api():
    """Override only the structured service and always clear shared app state."""
    services: dict[str, StructuredOutputService] = {}

    def override_service() -> StructuredOutputService:
        return services["service"]

    previous_override = app.dependency_overrides.get(
        get_structured_output_service
    )
    app.dependency_overrides[get_structured_output_service] = override_service
    try:
        with TestClient(app) as client:
            yield client, services
    finally:
        if previous_override is None:
            app.dependency_overrides.pop(get_structured_output_service, None)
        else:
            app.dependency_overrides[get_structured_output_service] = (
                previous_override
            )


def test_valid_request_returns_structured_data_and_all_metrics(structured_api):
    client, services = structured_api
    adapter = FakeAdapter([make_generation()])
    services["service"] = make_service(adapter)

    response = client.post(
        "/structured/generate",
        json={"schema_name": SCHEMA_NAME, "prompt": PROMPT_SECRET},
    )

    assert response.status_code == 200
    assert response.json() == {
        "schema_name": SCHEMA_NAME,
        "data": VALID_DATA.model_dump(),
        "metrics": {
            "attempts": 1,
            "per_attempt": [
                {
                    "model": "test-model",
                    "duration_ms": 12.5,
                    "prompt_eval_count": 7,
                    "eval_count": 4,
                }
            ],
            "model": "test-model",
            "total_generation_duration_ms": 12.5,
            "prompt_eval_count": 7,
            "eval_count": 4,
        },
    }
    assert adapter.calls == [
        {
            "prompt": PROMPT_SECRET,
            "model_class": RESTExplanation,
            "model": "configured-default-model",
        }
    ]


def test_omitted_prompt_uses_registry_default_and_model_override_is_trimmed(
    structured_api,
):
    client, services = structured_api
    adapter = FakeAdapter([make_generation()])
    services["service"] = make_service(adapter)

    response = client.post(
        "/structured/generate",
        json={"schema_name": SCHEMA_NAME, "model": "  custom-model  "},
    )

    assert response.status_code == 200
    assert adapter.calls[0]["prompt"] == DEFAULT_REST_EXPLANATION_PROMPT
    assert adapter.calls[0]["model"] == "custom-model"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"prompt": "a prompt"},
        {"schema_name": "", "prompt": "a prompt"},
        {"schema_name": "   ", "prompt": "a prompt"},
        {"schema_name": SCHEMA_NAME, "prompt": "   "},
        {"schema_name": SCHEMA_NAME, "prompt": 9},
        {"schema_name": SCHEMA_NAME, "model": "   "},
        {"schema_name": SCHEMA_NAME, "model": ["MODEL_INPUT_SECRET_6e22"]},
        {"schema_name": SCHEMA_NAME, "unexpected": PROMPT_SECRET},
    ],
)
def test_invalid_request_is_generic_422_without_echoing_input(
    structured_api, payload
):
    client, services = structured_api
    # Validation must happen before dependency execution/model invocation.
    services["service"] = make_service(FakeAdapter([]))

    response = client.post("/structured/generate", json=payload)

    assert response.status_code == 422
    assert PROMPT_SECRET not in response.text
    assert "MODEL_INPUT_SECRET_6e22" not in response.text
    assert "Input should" not in response.text
    assert "input" not in response.json().get("detail", "").lower()


def test_unknown_schema_returns_generic_404_without_calling_adapter(
    structured_api,
):
    client, services = structured_api
    adapter = FakeAdapter([])
    services["service"] = make_service(adapter)

    response = client.post(
        "/structured/generate",
        json={"schema_name": "UNKNOWN_SCHEMA_SECRET_2c90", "prompt": PROMPT_SECRET},
    )

    assert response.status_code == 404
    assert "UNKNOWN_SCHEMA_SECRET_2c90" not in response.text
    assert PROMPT_SECRET not in response.text
    assert adapter.calls == []


def test_semantic_retry_then_success_returns_aggregate_attempt_metrics(
    structured_api,
):
    client, services = structured_api
    adapter = FakeAdapter(
        [
            make_generation(INVALID_DATA),
            make_generation(VALID_DATA, duration_ms=20.0),
        ]
    )
    services["service"] = make_service(adapter)

    response = client.post(
        "/structured/generate",
        json={"schema_name": SCHEMA_NAME, "prompt": PROMPT_SECRET},
    )

    assert response.status_code == 200
    metrics = response.json()["metrics"]
    assert response.json()["data"] == VALID_DATA.model_dump()
    assert metrics["attempts"] == 2
    assert [attempt["duration_ms"] for attempt in metrics["per_attempt"]] == [
        12.5,
        20.0,
    ]
    assert metrics["total_generation_duration_ms"] == 32.5
    assert metrics["prompt_eval_count"] == 14
    assert metrics["eval_count"] == 8
    assert len(adapter.calls) == 2


def test_final_semantic_rejection_is_422_without_validation_details(
    structured_api,
):
    client, services = structured_api
    invalid = INVALID_DATA.model_copy(update={"purpose": OUTPUT_SECRET})
    adapter = FakeAdapter(
        [make_generation(invalid), make_generation(invalid)]
    )
    services["service"] = make_service(adapter)

    response = client.post(
        "/structured/generate",
        json={"schema_name": SCHEMA_NAME, "prompt": PROMPT_SECRET},
    )

    assert response.status_code == 422
    assert response.json().get("detail")
    assert PROMPT_SECRET not in response.text
    assert OUTPUT_SECRET not in response.text
    assert "Representational State Transfer" not in response.text
    assert "must be" not in response.text
    assert len(adapter.calls) == 2


@pytest.mark.parametrize(
    ("error", "status_code"),
    [
        (OllamaTimeoutError(ERROR_SECRET), 503),
        (OllamaUnavailableError(ERROR_SECRET), 503),
        (OllamaResponseError(ERROR_SECRET), 502),
        (StructuredGenerationFailureError(ERROR_SECRET), 502),
        (OllamaGenerationIncompleteError(ERROR_SECRET), 502),
    ],
)
def test_provider_failure_statuses_are_sanitized(
    structured_api, error, status_code
):
    client, services = structured_api
    services["service"] = make_service(FakeAdapter([error]))

    response = client.post(
        "/structured/generate",
        json={"schema_name": SCHEMA_NAME, "prompt": PROMPT_SECRET},
    )

    assert response.status_code == status_code
    assert ERROR_SECRET not in response.text
    assert PROMPT_SECRET not in response.text


@pytest.mark.parametrize(
    "completion",
    [False, None],
)
def test_unverified_completion_never_returns_success(
    structured_api, completion
):
    client, services = structured_api
    services["service"] = make_service(
        FakeAdapter([make_generation(completion=completion)])
    )

    response = client.post(
        "/structured/generate",
        json={"schema_name": SCHEMA_NAME},
    )

    assert response.status_code == 502
    assert "success" not in response.json().get("detail", "").lower()
    assert PROMPT_SECRET not in response.text


def test_missing_provider_metrics_remain_null_in_response(structured_api):
    client, services = structured_api
    adapter = FakeAdapter(
        [
            make_generation(
                duration_ms=None,
                prompt_eval_count=None,
                eval_count=None,
            )
        ]
    )
    services["service"] = make_service(adapter)

    response = client.post(
        "/structured/generate",
        json={"schema_name": SCHEMA_NAME},
    )

    assert response.status_code == 200
    metrics = response.json()["metrics"]
    assert metrics["total_generation_duration_ms"] is None
    assert metrics["prompt_eval_count"] is None
    assert metrics["eval_count"] is None
    assert metrics["per_attempt"] == [
        {
            "model": "test-model",
            "duration_ms": None,
            "prompt_eval_count": None,
            "eval_count": None,
        }
    ]


def test_logging_excludes_prompt_generated_content_and_provider_detail(
    structured_api, caplog
):
    client, services = structured_api
    adapter = FakeAdapter([OllamaTimeoutError(ERROR_SECRET)])
    services["service"] = make_service(adapter)
    caplog.set_level(logging.DEBUG, logger=SERVICE_LOGGER)

    response = client.post(
        "/structured/generate",
        json={"schema_name": SCHEMA_NAME, "prompt": PROMPT_SECRET},
    )

    assert response.status_code == 503
    log_text = caplog.text
    assert PROMPT_SECRET not in log_text
    assert OUTPUT_SECRET not in log_text
    assert ERROR_SECRET not in log_text


def test_openapi_documents_structured_generation_contract(structured_api):
    client, services = structured_api
    services["service"] = make_service(FakeAdapter([]))

    response = client.get("/openapi.json")

    assert response.status_code == 200
    schema = response.json()
    operation = schema["paths"]["/structured/generate"]["post"]
    request_ref = operation["requestBody"]["content"]["application/json"]
    response_ref = operation["responses"]["200"]["content"]["application/json"]
    assert request_ref["schema"]["$ref"].endswith("StructuredGenerateRequest")
    assert response_ref["schema"]["$ref"].endswith("StructuredGenerateResponse")
    assert "422" in operation["responses"]


def test_dependency_override_is_used_without_constructing_live_adapter(
    structured_api, monkeypatch
):
    client, services = structured_api
    adapter = FakeAdapter([make_generation()])
    services["service"] = make_service(adapter)

    def fail_if_live_adapter_is_constructed(*args, **kwargs):
        raise AssertionError("dependency override constructed the live adapter")

    monkeypatch.setattr(
        "nexus_ai.main.LangChainChatOllamaAdapter",
        fail_if_live_adapter_is_constructed,
    )

    response = client.post(
        "/structured/generate",
        json={"schema_name": SCHEMA_NAME},
    )

    assert response.status_code == 200
    assert adapter.calls


def test_service_factory_forwards_configured_ollama_timeout(monkeypatch):
    captured: dict[str, object] = {}
    expected_adapter = object()
    expected_service = object()

    class FakeOllamaClient:
        base_url = "http://ollama.test:11434"
        default_model = "test-model"
        timeout_seconds = 37.5

    class FakeStructuredOutputService:
        def __init__(self, *, adapter, default_model):
            captured["service_adapter"] = adapter
            captured["service_default_model"] = default_model

    def make_adapter(**kwargs):
        captured["adapter_kwargs"] = kwargs
        return expected_adapter

    def make_service(*, adapter, default_model):
        FakeStructuredOutputService(
            adapter=adapter,
            default_model=default_model,
        )
        return expected_service

    monkeypatch.setattr(main_module, "OllamaClient", FakeOllamaClient)
    monkeypatch.setattr(main_module, "LangChainChatOllamaAdapter", make_adapter)
    monkeypatch.setattr(
        main_module,
        "StructuredOutputService",
        make_service,
    )

    service = main_module.get_structured_output_service()

    assert service is expected_service
    assert captured["adapter_kwargs"] == {
        "base_url": FakeOllamaClient.base_url,
        "default_model": FakeOllamaClient.default_model,
        "timeout_seconds": FakeOllamaClient.timeout_seconds,
    }
    assert captured["service_adapter"] is expected_adapter
    assert captured["service_default_model"] == FakeOllamaClient.default_model
