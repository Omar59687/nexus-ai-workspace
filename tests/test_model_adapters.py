"""Deterministic tests for the ChatOllama structured model adapter.

No live Ollama service and no network access: the ChatOllama layer is
replaced at the module seam (``nexus_ai.model_adapters.ChatOllama``) with
a fake that replays crafted payloads and exceptions. The tests codify the
frozen P3-CP4 adapter contract for ``LangChainChatOllamaAdapter``.
"""

import dataclasses
import inspect
import logging

import httpx
import ollama
import pytest
from langchain_core.messages import AIMessage
from pydantic import BaseModel

import nexus_ai.model_adapters as model_adapters
from nexus_ai.model_adapters import (
    LangChainChatOllamaAdapter,
    OllamaGenerationIncompleteError,
    StructuredGeneration,
    StructuredGenerationFailureError,
    StructuredModelAdapter,
)
from nexus_ai.ollama import (
    DEFAULT_OLLAMA_BASE_URL,
    DEFAULT_OLLAMA_MODEL,
    DEFAULT_OLLAMA_TIMEOUT_SECONDS,
    OllamaError,
    OllamaResponseError,
    OllamaTimeoutError,
    OllamaUnavailableError,
)


class Answer(BaseModel):
    """Schema class used as the ``model_class`` argument."""

    text: str


class OtherAnswer(BaseModel):
    """Sibling schema used to demonstrate parsed-type mismatches."""

    text: str


PROMPT_MARKER = "SECRET_PROMPT_MARKER_3f9c21"
GENERATED_MARKER = "SECRET_GENERATED_MARKER_8a1d07"
DEFAULT_PROMPT = "Explain structured output."

# Independent worked example: 1_234_567_891 ns = 1234.567891 ms,
# rounded to 3 decimal places.
TOTAL_DURATION_NS = 1_234_567_891
TOTAL_DURATION_MS = 1234.568


def _complete_metadata(**overrides: object) -> dict:
    """Provider-style response metadata with all common fields present."""

    metadata: dict = {
        "model": "llama3.2:latest",
        "created_at": "2026-11-10T00:00:00.000Z",
        "done": True,
        "done_reason": "stop",
        "total_duration": TOTAL_DURATION_NS,
        "prompt_eval_count": 42,
        "eval_count": 17,
        "load_duration": 1_000_000,
    }
    metadata.update(overrides)
    return metadata


def _raw(
    content: str = "generated-content",
    response_metadata: dict | None = None,
    usage_metadata: dict | None = None,
) -> AIMessage:
    """Build a real AIMessage; ``None`` keeps the library default."""

    kwargs: dict = {"content": content}
    if response_metadata is not None:
        kwargs["response_metadata"] = response_metadata
    if usage_metadata is not None:
        kwargs["usage_metadata"] = usage_metadata
    return AIMessage(**kwargs)


def _payload(raw, parsed, parsing_error=None) -> dict:
    return {"raw": raw, "parsed": parsed, "parsing_error": parsing_error}


class _FakeControl:
    """Mutable harness state shared by the fake ChatOllama layer."""

    def __init__(self) -> None:
        self.payload = None
        self.error: BaseException | None = None
        self.constructions: list[dict] = []
        self.structured_calls: list[dict] = []
        self.invoke_calls: list[str] = []


class FakeStructured:
    """Stand-in for the Runnable returned by ``with_structured_output``."""

    def __init__(self, control: _FakeControl) -> None:
        self._control = control

    def invoke(self, prompt: str):
        self._control.invoke_calls.append(prompt)
        if self._control.error is not None:
            raise self._control.error
        return self._control.payload


class FakeChat:
    """Stand-in for ``langchain_ollama.ChatOllama``."""

    def __init__(self, control: _FakeControl, **kwargs) -> None:
        self._control = control
        self.kwargs = kwargs
        control.constructions.append(kwargs)

    def with_structured_output(
        self,
        model_class,
        *,
        method: str = "json_schema",
        include_raw: bool = False,
        **kwargs,
    ):
        self._control.structured_calls.append(
            {
                "model_class": model_class,
                "method": method,
                "include_raw": include_raw,
                "extra_kwargs": kwargs,
                "chat_kwargs": dict(self.kwargs),
            }
        )
        return FakeStructured(self._control)


@pytest.fixture
def fake_chat(monkeypatch):
    """Replace the module-level ChatOllama with a controllable fake."""

    control = _FakeControl()

    def _factory(**kwargs):
        return FakeChat(control, **kwargs)

    monkeypatch.setattr(model_adapters, "ChatOllama", _factory)
    return control


def _generate(
    control: _FakeControl,
    payload,
    *,
    prompt: str = DEFAULT_PROMPT,
    model_class=Answer,
    model: str | None = None,
    adapter: LangChainChatOllamaAdapter | None = None,
) -> StructuredGeneration:
    control.payload = payload
    if adapter is None:
        adapter = LangChainChatOllamaAdapter()
    return adapter.generate_structured(prompt, model_class, model=model)


def _success_payload(**metadata_overrides) -> dict:
    return _payload(
        _raw(response_metadata=_complete_metadata(**metadata_overrides)),
        Answer(text="structured answer"),
    )


# ---------------------------------------------------------------------------
# Slice 1: success path, single invocation, constructor/argument forwarding
# ---------------------------------------------------------------------------


def test_successful_generation_returns_parsed_result_with_metrics(fake_chat):
    parsed = Answer(text="structured answer")
    payload = _payload(
        _raw(response_metadata=_complete_metadata()),
        parsed,
    )

    generation = _generate(fake_chat, payload)

    assert isinstance(generation, StructuredGeneration)
    assert generation.result is parsed
    assert generation.completion is True
    assert generation.model == "llama3.2:latest"
    assert generation.total_duration_ms == TOTAL_DURATION_MS
    assert generation.prompt_eval_count == 42
    assert generation.eval_count == 17


def test_single_model_invocation_per_generate_structured_call(fake_chat):
    prompt = DEFAULT_PROMPT

    _generate(fake_chat, _success_payload(), prompt=prompt)

    assert fake_chat.invoke_calls == [prompt]
    assert len(fake_chat.constructions) == 1
    assert len(fake_chat.structured_calls) == 1


def test_with_structured_output_uses_include_raw_and_model_class(fake_chat):
    _generate(fake_chat, _success_payload(), model_class=Answer)

    call = fake_chat.structured_calls[0]
    assert call["model_class"] is Answer
    assert call["include_raw"] is True
    assert call["method"] == "json_schema"


def test_constructor_kwargs_forward_default_timeout_through_client_kwargs(
    fake_chat,
):
    adapter = LangChainChatOllamaAdapter(
        base_url="http://host:11434",
        default_model="default-model",
        temperature=0.5,
        num_predict=64,
    )

    _generate(
        fake_chat,
        _success_payload(model="default-model"),
        adapter=adapter,
    )

    chat_kwargs = fake_chat.constructions[0]
    assert set(chat_kwargs) == {
        "model",
        "base_url",
        "temperature",
        "num_predict",
        "client_kwargs",
    }
    assert chat_kwargs["base_url"] == "http://host:11434"
    assert chat_kwargs["temperature"] == 0.5
    assert chat_kwargs["num_predict"] == 64
    assert chat_kwargs["client_kwargs"] == {
        "timeout": DEFAULT_OLLAMA_TIMEOUT_SECONDS,
    }


def test_explicit_timeout_is_forwarded_through_client_kwargs(fake_chat):
    adapter = LangChainChatOllamaAdapter(timeout_seconds=17.5)

    _generate(
        fake_chat,
        _success_payload(),
        adapter=adapter,
    )

    assert fake_chat.constructions[0]["client_kwargs"] == {
        "timeout": 17.5,
    }


@pytest.mark.parametrize(
    "timeout_seconds",
    [0.0, -1.0, float("inf"), float("nan"), 10**1000],
)
def test_invalid_timeout_is_rejected(timeout_seconds):
    with pytest.raises(ValueError, match="timeout_seconds"):
        LangChainChatOllamaAdapter(timeout_seconds=timeout_seconds)


def test_model_override_forwarded_and_used_as_metadata_fallback(fake_chat):
    adapter = LangChainChatOllamaAdapter(default_model="default-model")
    metadata = _complete_metadata()
    metadata.pop("model")

    generation = _generate(
        fake_chat,
        _payload(_raw(response_metadata=metadata), Answer(text="ok")),
        model="override-model",
        adapter=adapter,
    )

    assert fake_chat.constructions[0]["model"] == "override-model"
    assert generation.model == "override-model"


def test_blank_model_override_falls_back_to_default_model(fake_chat):
    adapter = LangChainChatOllamaAdapter(default_model="default-model")

    _generate(fake_chat, _success_payload(), model="   ", adapter=adapter)

    assert fake_chat.constructions[0]["model"] == "default-model"


# ---------------------------------------------------------------------------
# Slice 2: constructor validation and frozen signatures
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "temperature",
    [-1, -0.0001, float("nan"), float("inf"), float("-inf"), True, False, "0.5"],
)
def test_invalid_temperature_is_rejected(temperature):
    with pytest.raises(ValueError, match="finite non-negative number"):
        LangChainChatOllamaAdapter(temperature=temperature)


@pytest.mark.parametrize("temperature", [0.0, 0, 7])
def test_valid_temperature_is_accepted_as_float(temperature):
    adapter = LangChainChatOllamaAdapter(temperature=temperature)

    assert isinstance(adapter.temperature, float)
    assert adapter.temperature == float(temperature)


@pytest.mark.parametrize("num_predict", [0, -1, True, False, 1.5, 256.0, "256"])
def test_invalid_num_predict_is_rejected(num_predict):
    with pytest.raises(ValueError, match="positive integer"):
        LangChainChatOllamaAdapter(num_predict=num_predict)


@pytest.mark.parametrize("num_predict", [1, 7, 256])
def test_valid_num_predict_is_accepted_as_int(num_predict):
    adapter = LangChainChatOllamaAdapter(num_predict=num_predict)

    assert isinstance(adapter.num_predict, int)
    assert not isinstance(adapter.num_predict, bool)
    assert adapter.num_predict == num_predict


@pytest.mark.parametrize("base_url", [None, "", "   "])
def test_blank_base_url_falls_back_to_default(base_url):
    adapter = LangChainChatOllamaAdapter(base_url=base_url)

    assert adapter.base_url == DEFAULT_OLLAMA_BASE_URL
    assert adapter.base_url == "http://127.0.0.1:11434"


def test_base_url_trailing_slash_is_stripped():
    adapter = LangChainChatOllamaAdapter(base_url="http://host:11434/")

    assert adapter.base_url == "http://host:11434"


@pytest.mark.parametrize("default_model", [None, "", "   "])
def test_blank_default_model_falls_back_to_default_model(default_model):
    adapter = LangChainChatOllamaAdapter(default_model=default_model)

    # The default model must not change: it is the ollama.py constant.
    assert adapter.default_model == DEFAULT_OLLAMA_MODEL
    assert adapter.default_model == "llama3.2:latest"


def test_explicit_default_model_is_stripped():
    adapter = LangChainChatOllamaAdapter(default_model="  custom-model  ")

    assert adapter.default_model == "custom-model"


def test_constructor_signature_is_frozen_keyword_only_with_defaults():
    signature = inspect.signature(LangChainChatOllamaAdapter.__init__)
    parameters = [
        parameter
        for name, parameter in signature.parameters.items()
        if name != "self"
    ]

    assert [parameter.name for parameter in parameters] == [
        "base_url",
        "default_model",
        "temperature",
        "num_predict",
        "timeout_seconds",
    ]
    assert all(
        parameter.kind is inspect.Parameter.KEYWORD_ONLY
        for parameter in parameters
    )
    assert [parameter.default for parameter in parameters] == [
        None,
        None,
        0.0,
        256,
        None,
    ]


def test_structured_model_adapter_protocol_signature_is_frozen():
    # typing.Protocol marks protocol classes with _is_protocol = True
    # (Python 3.12 has no public typing.is_protocol helper).
    assert getattr(StructuredModelAdapter, "_is_protocol", False) is True
    assert "__protocol_attrs__" in dir(StructuredModelAdapter)

    signature = inspect.signature(StructuredModelAdapter.generate_structured)
    parameters = [
        parameter
        for name, parameter in signature.parameters.items()
        if name != "self"
    ]

    assert [parameter.name for parameter in parameters] == [
        "prompt",
        "model_class",
        "model",
    ]
    assert parameters[0].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    assert parameters[1].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    assert parameters[2].kind is inspect.Parameter.KEYWORD_ONLY
    assert parameters[2].default is None
    assert signature.return_annotation is StructuredGeneration


def test_adapter_generate_structured_matches_protocol_signature():
    def _spec(func):
        signature = inspect.signature(func)
        return [
            (name, parameter.kind, parameter.default)
            for name, parameter in signature.parameters.items()
            if name != "self"
        ]

    adapter_method = LangChainChatOllamaAdapter.generate_structured
    protocol_method = StructuredModelAdapter.generate_structured

    assert _spec(adapter_method) == _spec(protocol_method)
    assert (
        inspect.signature(adapter_method).return_annotation
        is StructuredGeneration
    )


def test_structured_generation_is_frozen_with_exact_fields():
    assert dataclasses.is_dataclass(StructuredGeneration)
    assert StructuredGeneration.__dataclass_params__.frozen is True

    fields = dataclasses.fields(StructuredGeneration)
    assert [field.name for field in fields] == [
        "result",
        "completion",
        "model",
        "total_duration_ms",
        "prompt_eval_count",
        "eval_count",
    ]
    assert all(field.default is dataclasses.MISSING for field in fields)

    generation = StructuredGeneration(
        result=Answer(text="x"),
        completion=True,
        model=None,
        total_duration_ms=None,
        prompt_eval_count=None,
        eval_count=None,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        generation.completion = False


# ---------------------------------------------------------------------------
# Slice 3: completion enforcement (done, done_reason, metadata shape)
# ---------------------------------------------------------------------------


def test_done_false_raises_generation_incomplete(fake_chat):
    payload = _success_payload(done=False)

    with pytest.raises(OllamaGenerationIncompleteError) as exc_info:
        _generate(fake_chat, payload)

    assert isinstance(exc_info.value, StructuredGenerationFailureError)
    assert not isinstance(exc_info.value, OllamaResponseError)
    assert fake_chat.invoke_calls == [DEFAULT_PROMPT]


@pytest.mark.parametrize("done", [None, 1, "true", False])
def test_done_not_exactly_true_raises_generation_incomplete(fake_chat, done):
    metadata = _complete_metadata()
    if done is None:
        metadata.pop("done")
    else:
        metadata["done"] = done

    with pytest.raises(OllamaGenerationIncompleteError):
        _generate(
            fake_chat,
            _payload(_raw(response_metadata=metadata), Answer(text="ok")),
        )


def test_done_reason_length_raises_generation_incomplete(fake_chat):
    payload = _success_payload(done_reason="length")

    with pytest.raises(OllamaGenerationIncompleteError) as exc_info:
        _generate(fake_chat, payload)

    assert isinstance(exc_info.value, StructuredGenerationFailureError)


def test_done_reason_stop_is_accepted(fake_chat):
    generation = _generate(fake_chat, _success_payload(done_reason="stop"))

    assert generation.completion is True


@pytest.mark.parametrize("done_reason", [None, ""])
def test_falsy_or_absent_done_reason_is_accepted(fake_chat, done_reason):
    metadata = _complete_metadata()
    if done_reason is None:
        metadata.pop("done_reason")
    else:
        metadata["done_reason"] = done_reason

    generation = _generate(
        fake_chat,
        _payload(_raw(response_metadata=metadata), Answer(text="ok")),
    )

    assert generation.completion is True


@pytest.mark.parametrize("done_reason", [0, False, 1, 3.5, object()])
def test_non_string_done_reason_raises_generation_incomplete(
    fake_chat,
    done_reason,
):
    payload = _success_payload(done_reason=done_reason)

    with pytest.raises(OllamaGenerationIncompleteError):
        _generate(fake_chat, payload)


def test_empty_response_metadata_raises_generation_incomplete(fake_chat):
    # AIMessage defaults response_metadata to {}; with no done key the
    # completion cannot be proven.
    payload = _payload(_raw(), Answer(text="ok"))

    with pytest.raises(OllamaGenerationIncompleteError):
        _generate(fake_chat, payload)


def test_non_dict_response_metadata_raises_generation_incomplete(fake_chat):
    raw = _raw(response_metadata=_complete_metadata())
    raw.response_metadata = "not-a-dict"

    with pytest.raises(OllamaGenerationIncompleteError):
        _generate(fake_chat, _payload(raw, Answer(text="ok")))


# ---------------------------------------------------------------------------
# Slice 4: malformed payloads -> StructuredGenerationFailureError
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("payload", [None, "not-a-dict", ["raw"], 42])
def test_payload_not_a_dict_raises_structured_failure(fake_chat, payload):
    with pytest.raises(StructuredGenerationFailureError) as exc_info:
        _generate(fake_chat, payload)

    assert not isinstance(exc_info.value, OllamaGenerationIncompleteError)
    # Malformed payloads are never retried.
    assert fake_chat.invoke_calls == [DEFAULT_PROMPT]


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"raw": None, "parsed": None},
        {"parsed": None, "parsing_error": None},
        {"raw": None, "parsing_error": None},
        {"unexpected": 1},
    ],
)
def test_payload_missing_required_keys_raises_structured_failure(
    fake_chat,
    payload,
):
    with pytest.raises(StructuredGenerationFailureError):
        _generate(fake_chat, payload)

    assert fake_chat.invoke_calls == [DEFAULT_PROMPT]


def test_parsing_error_set_raises_structured_failure_with_cause(fake_chat):
    parsing_error = ValueError("invalid json")
    payload = _payload(_raw(), None, parsing_error)

    with pytest.raises(StructuredGenerationFailureError) as exc_info:
        _generate(fake_chat, payload)

    assert exc_info.value.__cause__ is parsing_error
    assert not isinstance(exc_info.value, OllamaGenerationIncompleteError)


def test_parsing_error_with_parsed_value_still_raises_structured_failure(
    fake_chat,
):
    payload = _payload(
        _raw(),
        Answer(text="ok"),
        ValueError("invalid json"),
    )

    with pytest.raises(StructuredGenerationFailureError):
        _generate(fake_chat, payload)


def test_parsing_error_of_unexpected_type_raises_structured_failure(
    fake_chat,
):
    payload = _payload(_raw(), Answer(text="ok"), "not-an-exception")

    with pytest.raises(StructuredGenerationFailureError):
        _generate(fake_chat, payload)


def test_parsed_none_raises_structured_failure(fake_chat):
    payload = _payload(_raw(), None, None)

    with pytest.raises(StructuredGenerationFailureError) as exc_info:
        _generate(fake_chat, payload)

    assert exc_info.value.__cause__ is None


@pytest.mark.parametrize(
    "parsed",
    [
        OtherAnswer(text="wrong schema"),
        {"text": "not a model"},
        "text",
        None,
    ],
)
def test_parsed_wrong_type_raises_structured_failure(fake_chat, parsed):
    payload = _payload(_raw(), parsed, None)

    with pytest.raises(StructuredGenerationFailureError):
        _generate(fake_chat, payload, model_class=Answer)


@pytest.mark.parametrize("raw", ["raw-text", {"content": "x"}, None, 7])
def test_raw_not_base_message_raises_structured_failure(fake_chat, raw):
    payload = _payload(raw, Answer(text="ok"), None)

    with pytest.raises(StructuredGenerationFailureError):
        _generate(fake_chat, payload)


def test_malformed_payload_never_reinvokes_model(fake_chat):
    fake_chat.payload = "not-a-dict"

    adapter = LangChainChatOllamaAdapter()
    with pytest.raises(StructuredGenerationFailureError):
        adapter.generate_structured(DEFAULT_PROMPT, Answer)

    assert len(fake_chat.invoke_calls) == 1
    assert len(fake_chat.constructions) == 1


# ---------------------------------------------------------------------------
# Slice 5: provider exception taxonomy raised by the invoke seam
# ---------------------------------------------------------------------------


def test_timeout_exception_maps_to_ollama_timeout_error(fake_chat):
    fake_chat.error = httpx.TimeoutException("read timed out")

    with pytest.raises(OllamaTimeoutError) as exc_info:
        _generate(fake_chat, None)

    assert isinstance(exc_info.value, OllamaUnavailableError)
    assert not isinstance(exc_info.value, StructuredGenerationFailureError)
    assert isinstance(exc_info.value.__cause__, httpx.TimeoutException)
    assert fake_chat.invoke_calls == [DEFAULT_PROMPT]


def test_http_status_error_maps_to_ollama_response_error(fake_chat):
    request = httpx.Request("POST", "http://127.0.0.1:11434/api/chat")
    response = httpx.Response(503, request=request)
    fake_chat.error = httpx.HTTPStatusError(
        "service unavailable",
        request=request,
        response=response,
    )

    with pytest.raises(OllamaResponseError) as exc_info:
        _generate(fake_chat, None)

    assert isinstance(exc_info.value, OllamaError)
    assert not isinstance(exc_info.value, StructuredGenerationFailureError)
    assert "503" in str(exc_info.value)


@pytest.mark.parametrize("status_code", [400, 404, 500])
def test_response_error_with_status_code_maps_to_response_error(
    fake_chat,
    status_code,
):
    fake_chat.error = ollama.ResponseError("provider error", status_code)

    with pytest.raises(OllamaResponseError) as exc_info:
        _generate(fake_chat, None)

    assert not isinstance(exc_info.value, StructuredGenerationFailureError)
    assert str(status_code) in str(exc_info.value)
    assert "HTTP" in str(exc_info.value)


@pytest.mark.parametrize("status_code", [-1, 0, "500", None, True])
def test_response_error_without_usable_status_maps_to_generic_response_error(
    fake_chat,
    status_code,
):
    # ollama.ResponseError defaults status_code to -1; anything that is not
    # a positive int maps to the generic invalid-response message.
    fake_chat.error = ollama.ResponseError("provider error", status_code)

    with pytest.raises(OllamaResponseError) as exc_info:
        _generate(fake_chat, None)

    assert "invalid response" in str(exc_info.value)
    assert "HTTP" not in str(exc_info.value)


@pytest.mark.parametrize(
    "error",
    [
        httpx.ConnectError("connection refused"),
        httpx.ReadError("read failed"),
        httpx.TransportError("transport broken"),
    ],
)
def test_transport_errors_map_to_ollama_unavailable_error(fake_chat, error):
    fake_chat.error = error

    with pytest.raises(OllamaUnavailableError) as exc_info:
        _generate(fake_chat, None)

    assert not isinstance(exc_info.value, StructuredGenerationFailureError)
    assert not isinstance(exc_info.value, OllamaResponseError)
    assert isinstance(exc_info.value.__cause__, httpx.TransportError)


@pytest.mark.parametrize(
    "error",
    [
        ConnectionError("refused"),
        OSError("socket closed"),
        TimeoutError("timed out"),  # builtin TimeoutError is an OSError
    ],
)
def test_os_error_subclasses_map_to_ollama_unavailable_error(
    fake_chat,
    error,
):
    fake_chat.error = error

    with pytest.raises(OllamaUnavailableError) as exc_info:
        _generate(fake_chat, None)

    assert not isinstance(exc_info.value, StructuredGenerationFailureError)
    assert isinstance(exc_info.value.__cause__, OSError)


def test_unexpected_exception_maps_to_structured_generation_failure(
    fake_chat,
):
    fake_chat.error = ValueError("unexpected boom")

    with pytest.raises(StructuredGenerationFailureError) as exc_info:
        _generate(fake_chat, None)

    assert not isinstance(exc_info.value, OllamaGenerationIncompleteError)
    assert not isinstance(exc_info.value, OllamaResponseError)
    assert not isinstance(exc_info.value, OllamaUnavailableError)
    assert isinstance(exc_info.value.__cause__, ValueError)
    # Exactly one invocation attempt, even on failure.
    assert fake_chat.invoke_calls == [DEFAULT_PROMPT]


def test_exception_taxonomy_isinstance_relations():
    # Adapter-defined hierarchy.
    assert issubclass(OllamaGenerationIncompleteError, OllamaError)
    assert issubclass(StructuredGenerationFailureError, OllamaError)
    assert issubclass(
        OllamaGenerationIncompleteError,
        StructuredGenerationFailureError,
    )
    assert not issubclass(
        StructuredGenerationFailureError,
        OllamaGenerationIncompleteError,
    )

    # Provider hierarchy from ollama.py.
    assert issubclass(OllamaTimeoutError, OllamaUnavailableError)
    assert issubclass(OllamaUnavailableError, OllamaError)
    assert issubclass(OllamaResponseError, OllamaError)

    # The two hierarchies stay disjoint in both directions.
    assert not issubclass(
        StructuredGenerationFailureError,
        OllamaUnavailableError,
    )
    assert not issubclass(StructuredGenerationFailureError, OllamaResponseError)
    assert not issubclass(OllamaResponseError, StructuredGenerationFailureError)
    assert not issubclass(OllamaUnavailableError, StructuredGenerationFailureError)
    assert not issubclass(
        OllamaGenerationIncompleteError,
        OllamaTimeoutError,
    )


# ---------------------------------------------------------------------------
# Slice 6: metrics extraction, usage fallback, model fallback
# ---------------------------------------------------------------------------


def test_total_duration_converted_from_nanoseconds_to_milliseconds(fake_chat):
    generation = _generate(
        fake_chat,
        _success_payload(total_duration=2_500_000),
    )

    assert generation.total_duration_ms == 2.5


@pytest.mark.parametrize(
    ("total_duration", "expected_ms"),
    [
        (1_234_567, 1.235),  # 1.234567 ms rounded to 3 decimals
        (1_000_000, 1.0),
        (999_999, 1.0),  # 0.999999 ms rounds up
        (500_000, 0.5),
    ],
)
def test_total_duration_rounding_is_three_decimals(
    fake_chat,
    total_duration,
    expected_ms,
):
    generation = _generate(
        fake_chat,
        _success_payload(total_duration=total_duration),
    )

    assert generation.total_duration_ms == expected_ms


@pytest.mark.parametrize("value", [None, True, False, "42", 1.5, -1_000_000])
def test_invalid_total_duration_yields_none_not_zero(fake_chat, value):
    metadata = _complete_metadata()
    if value is None:
        metadata.pop("total_duration")
    else:
        metadata["total_duration"] = value

    generation = _generate(
        fake_chat,
        _payload(_raw(response_metadata=metadata), Answer(text="ok")),
    )

    assert generation.total_duration_ms is None


@pytest.mark.parametrize("value", [True, False, "42", 4.2, None, -1])
def test_invalid_token_counts_yield_none_not_zero(fake_chat, value):
    metadata = _complete_metadata()
    if value is None:
        metadata.pop("prompt_eval_count")
        metadata.pop("eval_count")
    else:
        metadata["prompt_eval_count"] = value
        metadata["eval_count"] = value

    generation = _generate(
        fake_chat,
        _payload(_raw(response_metadata=metadata), Answer(text="ok")),
    )

    assert generation.prompt_eval_count is None
    assert generation.eval_count is None


def test_missing_optional_metrics_are_none_not_zero(fake_chat):
    metadata = _complete_metadata()
    metadata.pop("total_duration")
    metadata.pop("prompt_eval_count")
    metadata.pop("eval_count")

    generation = _generate(
        fake_chat,
        _payload(_raw(response_metadata=metadata), Answer(text="ok")),
    )

    assert generation.total_duration_ms is None
    assert generation.prompt_eval_count is None
    assert generation.eval_count is None
    # None, never a fabricated zero.
    assert generation.total_duration_ms != 0
    assert generation.prompt_eval_count != 0
    assert generation.eval_count != 0


def test_usage_metadata_fills_counts_omitted_from_response_metadata(
    fake_chat,
):
    metadata = _complete_metadata()
    metadata.pop("prompt_eval_count")
    metadata.pop("eval_count")

    generation = _generate(
        fake_chat,
        _payload(
            _raw(
                response_metadata=metadata,
                usage_metadata={
                    "input_tokens": 13,
                    "output_tokens": 7,
                    "total_tokens": 20,
                },
            ),
            Answer(text="ok"),
        ),
    )

    assert generation.prompt_eval_count == 13
    assert generation.eval_count == 7


def test_negative_usage_metadata_counts_are_ignored(fake_chat):
    metadata = _complete_metadata()
    metadata.pop("prompt_eval_count")
    metadata.pop("eval_count")

    raw = _raw(response_metadata=metadata)
    raw.usage_metadata = {
        "input_tokens": -3,
        "output_tokens": -2,
        "total_tokens": -5,
    }
    generation = _generate(fake_chat, _payload(raw, Answer(text="ok")))

    assert generation.prompt_eval_count is None
    assert generation.eval_count is None


def test_response_metadata_counts_take_precedence_over_usage_metadata(
    fake_chat,
):
    generation = _generate(
        fake_chat,
        _success_payload(),
        # complete metadata already has 42/17
    )
    raw_usage_first = _raw(
        response_metadata=_complete_metadata(),
        usage_metadata={
            "input_tokens": 99,
            "output_tokens": 88,
            "total_tokens": 187,
        },
    )
    generation_with_usage = _generate(
        fake_chat,
        _payload(raw_usage_first, Answer(text="ok")),
    )

    assert generation.prompt_eval_count == 42
    assert generation.eval_count == 17
    assert generation_with_usage.prompt_eval_count == 42
    assert generation_with_usage.eval_count == 17


def test_usage_metadata_only_fills_the_missing_count(fake_chat):
    metadata = _complete_metadata()
    metadata.pop("eval_count")

    generation = _generate(
        fake_chat,
        _payload(
            _raw(
                response_metadata=metadata,
                usage_metadata={
                    "input_tokens": 99,
                    "output_tokens": 7,
                    "total_tokens": 106,
                },
            ),
            Answer(text="ok"),
        ),
    )

    assert generation.prompt_eval_count == 42  # kept from metadata
    assert generation.eval_count == 7  # filled from usage


@pytest.mark.parametrize("usage_metadata", [None, "not-a-dict", 5])
def test_usage_metadata_ignored_unless_it_is_a_dict(
    fake_chat,
    usage_metadata,
):
    metadata = _complete_metadata()
    metadata.pop("prompt_eval_count")
    metadata.pop("eval_count")
    raw = _raw(response_metadata=metadata)
    if usage_metadata is not None:
        raw.usage_metadata = usage_metadata

    generation = _generate(fake_chat, _payload(raw, Answer(text="ok")))

    assert generation.prompt_eval_count is None
    assert generation.eval_count is None


@pytest.mark.parametrize(
    ("metadata_model", "expected_model"),
    [
        ("llama3.2:latest", "llama3.2:latest"),
        ("  stripped-model  ", "stripped-model"),
        ("", "override-model"),
        ("   ", "override-model"),
        (5, "override-model"),
    ],
)
def test_model_metadata_falls_back_to_requested_model(
    fake_chat,
    metadata_model,
    expected_model,
):
    metadata = _complete_metadata()
    metadata["model"] = metadata_model

    generation = _generate(
        fake_chat,
        _payload(_raw(response_metadata=metadata), Answer(text="ok")),
        model="override-model",
    )

    assert generation.model == expected_model


def test_model_metadata_absent_falls_back_to_requested_model(fake_chat):
    metadata = _complete_metadata()
    metadata.pop("model")

    generation = _generate(
        fake_chat,
        _payload(_raw(response_metadata=metadata), Answer(text="ok")),
        model="override-model",
    )

    assert generation.model == "override-model"


# ---------------------------------------------------------------------------
# Slice 7: logging safety - no prompt or generated content in log records
# ---------------------------------------------------------------------------


def test_success_log_records_contain_no_prompt_or_generated_content(
    fake_chat,
    caplog,
):
    payload = _payload(
        _raw(content=GENERATED_MARKER, response_metadata=_complete_metadata()),
        Answer(text=GENERATED_MARKER),
    )

    with caplog.at_level(logging.INFO, logger="nexus_ai.model_adapters"):
        _generate(fake_chat, payload, prompt=PROMPT_MARKER)

    assert any(
        record.levelno == logging.INFO for record in caplog.records
    ), "expected the success path to emit a log record"
    assert PROMPT_MARKER not in caplog.text
    assert GENERATED_MARKER not in caplog.text


@pytest.mark.parametrize(
    "scenario",
    ["incomplete", "malformed", "provider_error"],
)
def test_failure_log_records_contain_no_prompt_or_generated_content(
    fake_chat,
    caplog,
    scenario,
):
    if scenario == "incomplete":
        payload = _success_payload(done=False)
        expected = OllamaGenerationIncompleteError
    elif scenario == "malformed":
        payload = _payload(
            _raw(content=GENERATED_MARKER),
            Answer(text=GENERATED_MARKER),
            ValueError("bad json"),
        )
        expected = StructuredGenerationFailureError
    else:
        payload = None
        fake_chat.error = httpx.TimeoutException("timed out")
        expected = OllamaTimeoutError

    with caplog.at_level(logging.WARNING, logger="nexus_ai.model_adapters"):
        with pytest.raises(expected):
            _generate(fake_chat, payload, prompt=PROMPT_MARKER)

    assert any(
        record.levelno == logging.WARNING for record in caplog.records
    ), "expected the failure path to emit a log record"
    assert PROMPT_MARKER not in caplog.text
    assert GENERATED_MARKER not in caplog.text
    assert "bad json" not in caplog.text


def test_exception_messages_carry_no_prompt_or_generated_content(fake_chat):
    payload = _payload(
        _raw(content=GENERATED_MARKER),
        Answer(text=GENERATED_MARKER),
        ValueError("bad json"),
    )

    with pytest.raises(StructuredGenerationFailureError) as exc_info:
        _generate(fake_chat, payload, prompt=PROMPT_MARKER)

    message = str(exc_info.value)
    assert PROMPT_MARKER not in message
    assert GENERATED_MARKER not in message
    assert "bad json" not in message
