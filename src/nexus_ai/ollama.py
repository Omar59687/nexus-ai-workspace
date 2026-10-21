"""HTTP client for the locally running Ollama service."""

import json
import logging
import math
import os
from http.client import HTTPException as HTTPClientException
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from dotenv import load_dotenv

from nexus_ai.schemas import LLMGenerateResponse


PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

DEFAULT_OLLAMA_BASE_URL = "http://127.0.0.1:11434"
DEFAULT_OLLAMA_MODEL = "llama3.2:latest"
DEFAULT_OLLAMA_TIMEOUT_SECONDS = 120.0

logger = logging.getLogger("nexus_ai.ollama")


class OllamaError(Exception):
    """Base class for categorized Ollama integration failures."""


class OllamaUnavailableError(OllamaError):
    """Raised when Ollama cannot be reached."""


class OllamaTimeoutError(OllamaUnavailableError):
    """Raised when an Ollama request exceeds the configured timeout."""


class OllamaResponseError(OllamaError):
    """Raised when Ollama returns an unsuccessful or malformed response."""


def _configured_timeout_seconds() -> float:
    raw_value = os.getenv("OLLAMA_TIMEOUT_SECONDS")
    if raw_value is None or not raw_value.strip():
        return DEFAULT_OLLAMA_TIMEOUT_SECONDS

    try:
        timeout_seconds = float(raw_value)
    except ValueError:
        logger.warning(
            "Ignoring invalid OLLAMA_TIMEOUT_SECONDS; using %.0f seconds",
            DEFAULT_OLLAMA_TIMEOUT_SECONDS,
        )
        return DEFAULT_OLLAMA_TIMEOUT_SECONDS

    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        logger.warning(
            "Ignoring invalid OLLAMA_TIMEOUT_SECONDS; using %.0f seconds",
            DEFAULT_OLLAMA_TIMEOUT_SECONDS,
        )
        return DEFAULT_OLLAMA_TIMEOUT_SECONDS

    return timeout_seconds


class OllamaClient:
    """Send generation requests to the local Ollama HTTP API."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        default_model: str | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        configured_base_url = (
            base_url if base_url is not None else os.getenv("OLLAMA_BASE_URL")
        )
        self.base_url = (
            (configured_base_url or DEFAULT_OLLAMA_BASE_URL).strip().rstrip("/")
            or DEFAULT_OLLAMA_BASE_URL
        )

        configured_model = (
            default_model
            if default_model is not None
            else os.getenv("OLLAMA_MODEL")
        )
        self.default_model = (
            (configured_model or DEFAULT_OLLAMA_MODEL).strip()
            or DEFAULT_OLLAMA_MODEL
        )

        if timeout_seconds is None:
            self.timeout_seconds = _configured_timeout_seconds()
        elif not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError(
                "timeout_seconds must be a finite positive number."
            )
        else:
            self.timeout_seconds = timeout_seconds

    def generate(
        self,
        prompt: str,
        model: str | None = None,
    ) -> LLMGenerateResponse:
        selected_model = (model or self.default_model).strip()
        if not selected_model:
            selected_model = self.default_model

        payload = json.dumps(
            {
                "model": selected_model,
                "prompt": prompt,
                "stream": False,
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

        body = self._post(request, selected_model)
        return self._parse_response(body, selected_model)

    def _post(self, request: Request, model: str) -> bytes:
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                status_code = getattr(response, "status", 200)
                body = response.read()
        except HTTPError as exc:
            logger.warning(
                "Ollama returned HTTP %s for model %s",
                exc.code,
                model,
            )
            raise OllamaResponseError(
                f"Ollama returned HTTP {exc.code}."
            ) from exc
        except URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                logger.warning(
                    "Ollama request timed out for model %s",
                    model,
                )
                raise OllamaTimeoutError(
                    "Ollama request timed out."
                ) from exc

            logger.warning(
                "Ollama connection failed for model %s: %s",
                model,
                type(exc.reason).__name__,
            )
            raise OllamaUnavailableError(
                "Ollama service is unavailable."
            ) from exc
        except TimeoutError as exc:
            logger.warning(
                "Ollama request timed out for model %s",
                model,
            )
            raise OllamaTimeoutError(
                "Ollama request timed out."
            ) from exc
        except HTTPClientException as exc:
            logger.warning(
                "Ollama returned an incomplete response for model %s: %s",
                model,
                type(exc).__name__,
            )
            raise OllamaResponseError(
                "Ollama returned an invalid response."
            ) from exc
        except OSError as exc:
            logger.warning(
                "Ollama connection failed for model %s: %s",
                model,
                type(exc).__name__,
            )
            raise OllamaUnavailableError(
                "Ollama service is unavailable."
            ) from exc

        if status_code != 200:
            logger.warning(
                "Ollama returned HTTP %s for model %s",
                status_code,
                model,
            )
            raise OllamaResponseError(
                f"Ollama returned HTTP {status_code}."
            )

        return body

    def _parse_response(
        self,
        body: bytes,
        requested_model: str,
    ) -> LLMGenerateResponse:
        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            logger.warning(
                "Ollama returned invalid JSON for model %s",
                requested_model,
            )
            raise OllamaResponseError(
                "Ollama returned an invalid response."
            ) from exc

        if not isinstance(payload, dict) or "error" in payload:
            logger.warning(
                "Ollama returned an error payload for model %s",
                requested_model,
            )
            raise OllamaResponseError(
                "Ollama returned an invalid response."
            )

        generated_text = payload.get("response")
        if not isinstance(generated_text, str):
            logger.warning(
                "Ollama response did not include generated text for model %s",
                requested_model,
            )
            raise OllamaResponseError(
                "Ollama returned an invalid response."
            )

        response_model = payload.get("model")
        if not isinstance(response_model, str) or not response_model:
            response_model = requested_model

        done = payload.get("done")
        if not isinstance(done, bool):
            done = None

        total_duration = self._optional_int(payload, "total_duration")
        prompt_eval_count = self._optional_int(
            payload,
            "prompt_eval_count",
        )
        eval_count = self._optional_int(payload, "eval_count")

        logger.info(
            "Ollama generation succeeded for model %s (eval_count=%s)",
            response_model,
            eval_count,
        )

        return LLMGenerateResponse(
            model=response_model,
            response=generated_text,
            done=done,
            total_duration_ms=(
                round(total_duration / 1_000_000, 3)
                if total_duration is not None
                else None
            ),
            prompt_eval_count=prompt_eval_count,
            eval_count=eval_count,
        )

    @staticmethod
    def _optional_int(payload: dict[str, object], key: str) -> int | None:
        value = payload.get(key)
        if isinstance(value, bool):
            return None
        return value if isinstance(value, int) else None
