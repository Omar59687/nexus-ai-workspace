import io
import json
from urllib.error import HTTPError, URLError

import pytest
from fastapi.testclient import TestClient

from nexus_ai import ollama
from nexus_ai.main import app


client = TestClient(app)


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


@pytest.fixture(autouse=True)
def deterministic_ollama_environment(monkeypatch) -> None:
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    monkeypatch.setenv("OLLAMA_MODEL", "llama3.2:latest")
    monkeypatch.setenv("OLLAMA_TIMEOUT_SECONDS", "10")


def test_generate_returns_generated_text(monkeypatch) -> None:
    calls = []
    payload = {
        "model": "llama3.2:latest",
        "response": "Mocked generation output.",
        "done": True,
        "total_duration": 2_000_000_000,
        "prompt_eval_count": 5,
        "eval_count": 9,
    }

    def fake_urlopen(request, timeout):
        calls.append((request, timeout))
        return FakeResponse(json.dumps(payload).encode("utf-8"))

    monkeypatch.setattr(ollama, "urlopen", fake_urlopen)

    response = client.post(
        "/llm/generate",
        json={"prompt": "  Explain local-first AI.  "},
    )

    assert response.status_code == 200
    assert response.json() == {
        "model": "llama3.2:latest",
        "response": "Mocked generation output.",
        "done": True,
        "total_duration_ms": 2000.0,
        "prompt_eval_count": 5,
        "eval_count": 9,
    }

    request, timeout = calls[0]
    assert json.loads(request.data) == {
        "model": "llama3.2:latest",
        "prompt": "Explain local-first AI.",
        "stream": False,
    }
    assert timeout is not None
    assert timeout > 0


def test_generate_uses_requested_model(monkeypatch) -> None:
    calls = []

    def fake_urlopen(request, timeout):
        calls.append(request)
        return FakeResponse(
            json.dumps(
                {
                    "model": "custom-model:latest",
                    "response": "Custom model output.",
                    "done": True,
                }
            ).encode("utf-8")
        )

    monkeypatch.setattr(ollama, "urlopen", fake_urlopen)

    response = client.post(
        "/llm/generate",
        json={"prompt": "Hello", "model": "  custom-model:latest  "},
    )

    assert response.status_code == 200
    assert response.json()["model"] == "custom-model:latest"
    assert json.loads(calls[0].data)["model"] == "custom-model:latest"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"prompt": ""},
        {"prompt": "   "},
        {"prompt": None},
        {"prompt": 123},
        {"prompt": "Hello", "model": "   "},
        {"prompt": "Hello", "model": ""},
    ],
)
def test_generate_rejects_invalid_prompts(payload) -> None:
    response = client.post("/llm/generate", json=payload)

    assert response.status_code == 422


def test_generate_returns_503_when_ollama_is_unavailable(monkeypatch) -> None:
    def fake_urlopen(request, timeout):
        raise URLError(ConnectionRefusedError(10061, "Connection refused"))

    monkeypatch.setattr(ollama, "urlopen", fake_urlopen)

    response = client.post(
        "/llm/generate",
        json={"prompt": "Hello"},
    )

    assert response.status_code == 503
    assert response.json() == {
        "detail": "Ollama service is unavailable"
    }
    assert "Connection refused" not in response.text


def test_generate_returns_503_on_timeout(monkeypatch) -> None:
    def fake_urlopen(request, timeout):
        raise TimeoutError("internal timeout detail")

    monkeypatch.setattr(ollama, "urlopen", fake_urlopen)

    response = client.post(
        "/llm/generate",
        json={"prompt": "Hello"},
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "Ollama request timed out"}
    assert "internal timeout detail" not in response.text


def test_generate_returns_502_on_unsuccessful_response(monkeypatch) -> None:
    def fake_urlopen(request, timeout):
        raise HTTPError(
            request.full_url,
            500,
            "Internal Server Error",
            None,
            io.BytesIO(b'{"error": "internal detail"}'),
        )

    monkeypatch.setattr(ollama, "urlopen", fake_urlopen)

    response = client.post(
        "/llm/generate",
        json={"prompt": "Hello"},
    )

    assert response.status_code == 502
    assert response.json() == {
        "detail": "Ollama returned an invalid response"
    }
    assert "internal detail" not in response.text


@pytest.mark.parametrize(
    "body",
    [
        b"not valid json",
        b"[]",
        b'{"model": "llama3.2:latest"}',
        b'{"error": "model not found"}',
    ],
)
def test_generate_returns_502_on_malformed_response(monkeypatch, body) -> None:
    def fake_urlopen(request, timeout):
        return FakeResponse(body)

    monkeypatch.setattr(ollama, "urlopen", fake_urlopen)

    response = client.post(
        "/llm/generate",
        json={"prompt": "Hello"},
    )

    assert response.status_code == 502
    assert response.json() == {
        "detail": "Ollama returned an invalid response"
    }
    assert "model not found" not in response.text
