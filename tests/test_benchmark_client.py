import io
import json
from urllib.error import HTTPError, URLError

import pytest

from nexus_ai.benchmark import client as benchmark_client
from nexus_ai.benchmark.client import (
    BenchmarkResponseError,
    BenchmarkTimeoutError,
    BenchmarkUnavailableError,
    OllamaBenchmarkClient,
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


def test_generate_sends_explicit_options_and_maps_metrics(
    monkeypatch,
) -> None:
    payload = {
        "model": "llama3.2:latest",
        "response": "Benchmark response.",
        "done": True,
        "done_reason": "stop",
        "total_duration": 2_500_000_000,
        "load_duration": 400_000_000,
        "prompt_eval_duration": 200_000_000,
        "eval_duration": 1_800_000_000,
        "prompt_eval_count": 12,
        "eval_count": 34,
    }
    calls = []

    def fake_urlopen(request, timeout):
        calls.append((request, timeout))
        return FakeResponse(json.dumps(payload).encode("utf-8"))

    monkeypatch.setattr(benchmark_client, "urlopen", fake_urlopen)

    client = OllamaBenchmarkClient(
        base_url="http://127.0.0.1:11434/",
        timeout_seconds=15,
    )
    result = client.generate(
        "Benchmark prompt",
        model="llama3.2:latest",
        options={
            "temperature": 0.0,
            "num_predict": 256,
            "seed": 42,
        },
    )

    assert result.model == "llama3.2:latest"
    assert result.response == "Benchmark response."
    assert result.metrics["total_duration_ms"] == 2500.0
    assert result.metrics["load_duration_ms"] == 400.0
    assert result.metrics["prompt_eval_duration_ms"] == 200.0
    assert result.metrics["eval_duration_ms"] == 1800.0
    assert result.metrics["prompt_eval_count"] == 12
    assert result.metrics["eval_count"] == 34
    assert result.metrics["done"] is True
    assert result.metrics["done_reason"] == "stop"

    request, timeout = calls[0]
    assert request.full_url == "http://127.0.0.1:11434/api/generate"
    assert timeout == 15.0
    assert json.loads(request.data) == {
        "model": "llama3.2:latest",
        "prompt": "Benchmark prompt",
        "stream": False,
        "options": {
            "temperature": 0.0,
            "num_predict": 256,
            "seed": 42,
        },
    }


def test_generate_records_missing_optional_metrics(monkeypatch) -> None:
    def fake_urlopen(request, timeout):
        return FakeResponse(
            json.dumps(
                {
                    "model": "llama3.2:latest",
                    "response": "Minimal response.",
                    "done": True,
                }
            ).encode("utf-8")
        )

    monkeypatch.setattr(benchmark_client, "urlopen", fake_urlopen)

    result = OllamaBenchmarkClient(timeout_seconds=5).generate(
        "Hello",
        model="llama3.2:latest",
        options={},
    )

    assert result.metrics["total_duration_ms"] is None
    assert result.metrics["load_duration_ms"] is None
    assert result.metrics["prompt_eval_duration_ms"] is None
    assert result.metrics["eval_duration_ms"] is None
    assert result.metrics["prompt_eval_count"] is None
    assert result.metrics["eval_count"] is None
    assert result.metrics["done"] is True
    assert result.metrics["done_reason"] is None


def test_generate_records_invalid_optional_metrics(monkeypatch) -> None:
    def fake_urlopen(request, timeout):
        return FakeResponse(
            json.dumps(
                {
                    "model": "llama3.2:latest",
                    "response": "Response.",
                    "done": True,
                    "total_duration": "fast",
                    "load_duration": -1,
                    "prompt_eval_count": True,
                    "eval_count": -10,
                    "done_reason": 123,
                }
            ).encode("utf-8")
        )

    monkeypatch.setattr(benchmark_client, "urlopen", fake_urlopen)

    result = OllamaBenchmarkClient(timeout_seconds=5).generate(
        "Hello",
        model="llama3.2:latest",
        options={},
    )

    assert result.metrics["total_duration_ms"] is None
    assert result.metrics["load_duration_ms"] is None
    assert result.metrics["prompt_eval_count"] is None
    assert result.metrics["eval_count"] is None
    assert result.metrics["done_reason"] is None


def test_generate_records_done_false_without_raising(monkeypatch) -> None:
    def fake_urlopen(request, timeout):
        return FakeResponse(
            json.dumps(
                {
                    "model": "llama3.2:latest",
                    "response": "Partial response.",
                    "done": False,
                    "done_reason": "length",
                }
            ).encode("utf-8")
        )

    monkeypatch.setattr(benchmark_client, "urlopen", fake_urlopen)

    result = OllamaBenchmarkClient(timeout_seconds=5).generate(
        "Hello",
        model="llama3.2:latest",
        options={"num_predict": 8},
    )

    assert result.metrics["done"] is False
    assert result.metrics["done_reason"] == "length"


@pytest.mark.parametrize(
    "body",
    [
        b"not json",
        b"[]",
        b'{"error": "model not found"}',
        b'{"model": "llama3.2:latest", "done": true}',
    ],
)
def test_generate_rejects_malformed_responses(monkeypatch, body) -> None:
    def fake_urlopen(request, timeout):
        return FakeResponse(body)

    monkeypatch.setattr(benchmark_client, "urlopen", fake_urlopen)

    client = OllamaBenchmarkClient(timeout_seconds=5)

    with pytest.raises(BenchmarkResponseError):
        client.generate(
            "private prompt content",
            model="llama3.2:latest",
            options={},
        )


def test_generate_hides_prompt_in_error_message(monkeypatch) -> None:
    prompt = "private-prompt-content"

    def fake_urlopen(request, timeout):
        raise URLError(ConnectionRefusedError(10061, "Connection refused"))

    monkeypatch.setattr(benchmark_client, "urlopen", fake_urlopen)

    client = OllamaBenchmarkClient(timeout_seconds=5)

    with pytest.raises(BenchmarkUnavailableError) as exc_info:
        client.generate(
            prompt,
            model="llama3.2:latest",
            options={},
        )

    assert prompt not in str(exc_info.value)


def test_generate_raises_response_error_for_http_error(monkeypatch) -> None:
    def fake_urlopen(request, timeout):
        raise HTTPError(
            request.full_url,
            500,
            "Internal Server Error",
            None,
            io.BytesIO(b'{"error": "sensitive detail"}'),
        )

    monkeypatch.setattr(benchmark_client, "urlopen", fake_urlopen)

    client = OllamaBenchmarkClient(timeout_seconds=5)

    with pytest.raises(BenchmarkResponseError) as exc_info:
        client.generate(
            "Hello",
            model="llama3.2:latest",
            options={},
        )

    assert "500" in str(exc_info.value)
    assert "sensitive detail" not in str(exc_info.value)


def test_generate_raises_response_error_for_non_200_status(
    monkeypatch,
) -> None:
    def fake_urlopen(request, timeout):
        return FakeResponse(b"{}", status=502)

    monkeypatch.setattr(benchmark_client, "urlopen", fake_urlopen)

    client = OllamaBenchmarkClient(timeout_seconds=5)

    with pytest.raises(BenchmarkResponseError):
        client.generate(
            "Hello",
            model="llama3.2:latest",
            options={},
        )


def test_generate_raises_timeout_error(monkeypatch) -> None:
    def fake_urlopen(request, timeout):
        raise TimeoutError("timed out")

    monkeypatch.setattr(benchmark_client, "urlopen", fake_urlopen)

    client = OllamaBenchmarkClient(timeout_seconds=5)

    with pytest.raises(BenchmarkTimeoutError):
        client.generate(
            "Hello",
            model="llama3.2:latest",
            options={},
        )


def test_generate_raises_unavailable_error(monkeypatch) -> None:
    def fake_urlopen(request, timeout):
        raise URLError(ConnectionRefusedError(10061, "Connection refused"))

    monkeypatch.setattr(benchmark_client, "urlopen", fake_urlopen)

    client = OllamaBenchmarkClient(timeout_seconds=5)

    with pytest.raises(BenchmarkUnavailableError):
        client.generate(
            "Hello",
            model="llama3.2:latest",
            options={},
        )


def test_get_version_returns_server_version(monkeypatch) -> None:
    calls = []

    def fake_urlopen(request, timeout):
        calls.append(request)
        return FakeResponse(b'{"version": "0.40.5"}')

    monkeypatch.setattr(benchmark_client, "urlopen", fake_urlopen)

    client = OllamaBenchmarkClient(timeout_seconds=5)

    assert client.get_version() == "0.40.5"
    assert calls[0].full_url == "http://127.0.0.1:11434/api/version"
    assert calls[0].get_method() == "GET"


@pytest.mark.parametrize(
    "body",
    [
        b"not json",
        b"[]",
        b"{}",
        b'{"version": ""}',
        b'{"version": 5}',
    ],
)
def test_get_version_rejects_invalid_responses(monkeypatch, body) -> None:
    def fake_urlopen(request, timeout):
        return FakeResponse(body)

    monkeypatch.setattr(benchmark_client, "urlopen", fake_urlopen)

    client = OllamaBenchmarkClient(timeout_seconds=5)

    with pytest.raises(BenchmarkResponseError):
        client.get_version()


def test_client_rejects_invalid_timeout() -> None:
    with pytest.raises(ValueError):
        OllamaBenchmarkClient(timeout_seconds=0)


def test_client_rejects_blank_model(monkeypatch) -> None:
    client = OllamaBenchmarkClient(timeout_seconds=5)

    with pytest.raises(ValueError):
        client.generate("Hello", model="   ", options={})
