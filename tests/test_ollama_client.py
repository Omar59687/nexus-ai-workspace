import io
import json
import logging
from urllib.error import HTTPError, URLError

import pytest

from nexus_ai import ollama
from nexus_ai.ollama import (
    DEFAULT_OLLAMA_BASE_URL,
    DEFAULT_OLLAMA_MODEL,
    DEFAULT_OLLAMA_TIMEOUT_SECONDS,
    OllamaClient,
    OllamaResponseError,
    OllamaTimeoutError,
    OllamaUnavailableError,
)


class FakeResponse:
    def __init__(self, body: bytes, status: int = 200) -> None:
        self._body = body
        self.status = status

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def test_generate_maps_response_and_request_payload(monkeypatch) -> None:
    payload = {
        "model": "llama3.2:latest",
        "response": "Hello from the model.",
        "done": True,
        "total_duration": 1_500_000_000,
        "prompt_eval_count": 12,
        "eval_count": 34,
    }
    calls = []

    def fake_urlopen(request, timeout):
        calls.append((request, timeout))
        return FakeResponse(json.dumps(payload).encode("utf-8"))

    monkeypatch.setattr(ollama, "urlopen", fake_urlopen)

    client = OllamaClient(
        base_url="http://127.0.0.1:11434",
        default_model="llama3.2:latest",
        timeout_seconds=7,
    )
    result = client.generate("Say hello")

    assert result.model == "llama3.2:latest"
    assert result.response == "Hello from the model."
    assert result.done is True
    assert result.total_duration_ms == 1500.0
    assert result.prompt_eval_count == 12
    assert result.eval_count == 34

    request, timeout = calls[0]
    assert request.full_url == "http://127.0.0.1:11434/api/generate"
    assert timeout == 7
    assert json.loads(request.data) == {
        "model": "llama3.2:latest",
        "prompt": "Say hello",
        "stream": False,
    }


def test_generate_uses_model_override(monkeypatch) -> None:
    calls = []

    def fake_urlopen(request, timeout):
        calls.append(request)
        return FakeResponse(
            json.dumps(
                {
                    "model": "qwen3-coder:30b",
                    "response": "Override response.",
                    "done": True,
                }
            ).encode("utf-8")
        )

    monkeypatch.setattr(ollama, "urlopen", fake_urlopen)

    client = OllamaClient(
        default_model="llama3.2:latest",
        timeout_seconds=5,
    )
    result = client.generate("Hello", model="qwen3-coder:30b")

    assert json.loads(calls[0].data)["model"] == "qwen3-coder:30b"
    assert result.model == "qwen3-coder:30b"


def test_client_uses_environment_defaults(monkeypatch) -> None:
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:9999/")
    monkeypatch.setenv("OLLAMA_MODEL", "environment-model")
    monkeypatch.setenv("OLLAMA_TIMEOUT_SECONDS", "30")

    client = OllamaClient()

    assert client.base_url == "http://127.0.0.1:9999"
    assert client.default_model == "environment-model"
    assert client.timeout_seconds == 30


def test_client_falls_back_to_safe_defaults(monkeypatch) -> None:
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    monkeypatch.delenv("OLLAMA_TIMEOUT_SECONDS", raising=False)

    client = OllamaClient()

    assert client.base_url == DEFAULT_OLLAMA_BASE_URL
    assert client.default_model == DEFAULT_OLLAMA_MODEL
    assert client.timeout_seconds == DEFAULT_OLLAMA_TIMEOUT_SECONDS


def test_client_rejects_non_finite_timeout() -> None:
    with pytest.raises(ValueError):
        OllamaClient(timeout_seconds=float("inf"))


def test_generate_raises_timeout_error(monkeypatch) -> None:
    def fake_urlopen(request, timeout):
        raise TimeoutError("timed out")

    monkeypatch.setattr(ollama, "urlopen", fake_urlopen)

    client = OllamaClient(timeout_seconds=1)

    with pytest.raises(OllamaTimeoutError):
        client.generate("Hello")


def test_generate_raises_timeout_error_from_url_error(monkeypatch) -> None:
    def fake_urlopen(request, timeout):
        raise URLError(TimeoutError("timed out"))

    monkeypatch.setattr(ollama, "urlopen", fake_urlopen)

    client = OllamaClient(timeout_seconds=1)

    with pytest.raises(OllamaTimeoutError):
        client.generate("Hello")


def test_generate_raises_unavailable_error(monkeypatch) -> None:
    def fake_urlopen(request, timeout):
        raise URLError(ConnectionRefusedError(10061, "Connection refused"))

    monkeypatch.setattr(ollama, "urlopen", fake_urlopen)

    client = OllamaClient(timeout_seconds=1)

    with pytest.raises(OllamaUnavailableError):
        client.generate("Hello")


def test_generate_raises_response_error_for_http_error(monkeypatch) -> None:
    def fake_urlopen(request, timeout):
        raise HTTPError(
            request.full_url,
            500,
            "Internal Server Error",
            None,
            io.BytesIO(b'{"error": "internal detail"}'),
        )

    monkeypatch.setattr(ollama, "urlopen", fake_urlopen)

    client = OllamaClient(timeout_seconds=1)

    with pytest.raises(OllamaResponseError):
        client.generate("Hello")


def test_generate_raises_response_error_for_unsuccessful_status(
    monkeypatch,
) -> None:
    def fake_urlopen(request, timeout):
        return FakeResponse(b"{}", status=500)

    monkeypatch.setattr(ollama, "urlopen", fake_urlopen)

    client = OllamaClient(timeout_seconds=1)

    with pytest.raises(OllamaResponseError):
        client.generate("Hello")


def test_generate_raises_response_error_for_malformed_json(monkeypatch) -> None:
    def fake_urlopen(request, timeout):
        return FakeResponse(b"not valid json")

    monkeypatch.setattr(ollama, "urlopen", fake_urlopen)

    client = OllamaClient(timeout_seconds=1)

    with pytest.raises(OllamaResponseError):
        client.generate("Hello")


def test_generate_raises_response_error_for_missing_text(monkeypatch) -> None:
    def fake_urlopen(request, timeout):
        return FakeResponse(
            json.dumps({"model": "llama3.2:latest"}).encode("utf-8")
        )

    monkeypatch.setattr(ollama, "urlopen", fake_urlopen)

    client = OllamaClient(timeout_seconds=1)

    with pytest.raises(OllamaResponseError):
        client.generate("Hello")


def test_generate_raises_response_error_for_error_payload(monkeypatch) -> None:
    def fake_urlopen(request, timeout):
        return FakeResponse(
            json.dumps({"error": "model not found"}).encode("utf-8")
        )

    monkeypatch.setattr(ollama, "urlopen", fake_urlopen)

    client = OllamaClient(timeout_seconds=1)

    with pytest.raises(OllamaResponseError):
        client.generate("Hello")


def test_error_logging_does_not_include_prompt(monkeypatch, caplog) -> None:
    prompt = "private-prompt-content-should-not-be-logged"

    def fake_urlopen(request, timeout):
        raise URLError(ConnectionRefusedError(10061, "Connection refused"))

    monkeypatch.setattr(ollama, "urlopen", fake_urlopen)

    client = OllamaClient(timeout_seconds=1)

    with caplog.at_level(logging.WARNING, logger="nexus_ai.ollama"):
        with pytest.raises(OllamaUnavailableError):
            client.generate(prompt)

    assert prompt not in caplog.text
