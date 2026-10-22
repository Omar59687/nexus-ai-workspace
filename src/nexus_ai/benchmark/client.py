"""Minimal Ollama HTTP client used by the local benchmark runner."""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from http.client import HTTPException as HTTPClientException
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from nexus_ai.benchmark.metrics import extract_generation_metrics
from nexus_ai.ollama import DEFAULT_OLLAMA_BASE_URL


DEFAULT_BENCHMARK_TIMEOUT_SECONDS = 120.0


class BenchmarkClientError(Exception):
    """Base class for benchmark client failures."""


class BenchmarkUnavailableError(BenchmarkClientError):
    """Raised when the local Ollama service cannot be reached."""


class BenchmarkTimeoutError(BenchmarkUnavailableError):
    """Raised when an Ollama benchmark request times out."""


class BenchmarkResponseError(BenchmarkClientError):
    """Raised when Ollama returns an invalid or unsuccessful response."""


@dataclass(frozen=True)
class GenerationResult:
    """A generated response plus the metrics reported by Ollama."""

    model: str
    response: str
    metrics: dict[str, Any]


class OllamaBenchmarkClient:
    """Call the Ollama HTTP API with explicit generation options."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        timeout_seconds: float = DEFAULT_BENCHMARK_TIMEOUT_SECONDS,
    ) -> None:
        configured_base_url = (
            base_url if base_url is not None else os.getenv("OLLAMA_BASE_URL")
        )
        self.base_url = (
            (configured_base_url or DEFAULT_OLLAMA_BASE_URL)
            .strip()
            .rstrip("/")
            or DEFAULT_OLLAMA_BASE_URL
        )

        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(timeout_seconds)
            or timeout_seconds <= 0
        ):
            raise ValueError(
                "timeout_seconds must be a finite positive number."
            )
        self.timeout_seconds = float(timeout_seconds)

    def get_version(self) -> str:
        """Return the Ollama server version."""
        request = Request(
            url=f"{self.base_url}/api/version",
            headers={"Accept": "application/json"},
            method="GET",
        )
        payload = self._request_json(request)

        if not isinstance(payload, dict):
            raise BenchmarkResponseError(
                "Ollama returned an invalid version response."
            )

        version = payload.get("version")
        if not isinstance(version, str) or not version.strip():
            raise BenchmarkResponseError(
                "Ollama returned an invalid version response."
            )
        return version.strip()

    def generate(
        self,
        prompt: str,
        *,
        model: str,
        options: dict[str, Any],
    ) -> GenerationResult:
        """Generate a non-streaming completion with explicit options."""
        selected_model = model.strip()
        if not selected_model:
            raise ValueError("model must be a non-empty string.")

        payload = json.dumps(
            {
                "model": selected_model,
                "prompt": prompt,
                "stream": False,
                "options": dict(options),
            }
        ).encode("utf-8")

        request = Request(
            url=f"{self.base_url}/api/generate",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )

        response_payload = self._request_json(request)
        return self._parse_generation(response_payload, selected_model)

    def _request_json(self, request: Request) -> object:
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                status_code = getattr(response, "status", 200)
                body = response.read()
        except HTTPError as exc:
            raise BenchmarkResponseError(
                f"Ollama returned HTTP {exc.code}."
            ) from exc
        except URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                raise BenchmarkTimeoutError(
                    "Ollama request timed out."
                ) from exc
            raise BenchmarkUnavailableError(
                "Ollama service is unavailable."
            ) from exc
        except TimeoutError as exc:
            raise BenchmarkTimeoutError(
                "Ollama request timed out."
            ) from exc
        except HTTPClientException as exc:
            raise BenchmarkResponseError(
                "Ollama returned an invalid response."
            ) from exc
        except OSError as exc:
            raise BenchmarkUnavailableError(
                "Ollama service is unavailable."
            ) from exc

        if status_code != 200:
            raise BenchmarkResponseError(
                f"Ollama returned HTTP {status_code}."
            )

        try:
            return json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise BenchmarkResponseError(
                "Ollama returned an invalid response."
            ) from exc

    @staticmethod
    def _parse_generation(
        payload: object,
        requested_model: str,
    ) -> GenerationResult:
        if not isinstance(payload, dict) or "error" in payload:
            raise BenchmarkResponseError(
                "Ollama returned an invalid response."
            )

        generated_text = payload.get("response")
        if not isinstance(generated_text, str):
            raise BenchmarkResponseError(
                "Ollama returned an invalid response."
            )

        response_model = payload.get("model")
        if not isinstance(response_model, str) or not response_model:
            response_model = requested_model

        return GenerationResult(
            model=response_model,
            response=generated_text,
            metrics=extract_generation_metrics(payload),
        )
