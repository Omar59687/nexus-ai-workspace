"""Generic generate-and-validate pipeline for structured LLM outputs."""

from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")

DEFAULT_MAX_ATTEMPTS = 2
MAX_ATTEMPTS_LIMIT = 2


class StructuredOutputRejectedError(RuntimeError):
    """Raised when a structured response fails validation on every attempt."""

    def __init__(self, attempts: int, last_error: ValueError) -> None:
        super().__init__(
            f"Structured output rejected after {attempts} attempt(s). "
            f"Last validation error: {last_error}"
        )
        self.attempts = attempts
        self.last_error = last_error


def build_correction_prompt(prompt: str, validation_error: ValueError) -> str:
    """Append the previous validation failure to the prompt as feedback."""

    return (
        f"{prompt}\n\n"
        "Your previous answer was rejected because it failed validation:\n"
        f"{validation_error}\n"
        "Return a corrected answer that satisfies every requirement above."
    )


def generate_with_validation(
    generate: Callable[[str], T],
    validator: Callable[[T], None],
    prompt: str,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> T:
    """Generate a result of type ``T`` and validate it with retry.

    ``generate`` receives the request prompt and may be any callable that
    produces a candidate result. ``validator`` receives the candidate and
    raises ``ValueError`` to reject it. Only ``ValueError`` raised by the
    validator triggers a corrective retry whose prompt includes the
    original prompt and the validation failure text; exceptions raised by
    ``generate`` itself (network, parsing, Pydantic errors) propagate
    unchanged and are never retried. If every attempt fails validation,
    the result is rejected with :class:`StructuredOutputRejectedError`
    instead of being returned; the total number of generate calls never
    exceeds ``max_attempts``.
    """

    if (
        not isinstance(max_attempts, int)
        or isinstance(max_attempts, bool)
        or not 1 <= max_attempts <= MAX_ATTEMPTS_LIMIT
    ):
        raise ValueError(
            "max_attempts must be between 1 and "
            f"{MAX_ATTEMPTS_LIMIT}"
        )

    request = prompt
    last_error: ValueError | None = None

    for attempt in range(1, max_attempts + 1):
        result = generate(request)

        try:
            validator(result)
        except ValueError as exc:
            last_error = exc
            if attempt == max_attempts:
                break
            request = build_correction_prompt(prompt, exc)
        else:
            return result

    assert last_error is not None
    raise StructuredOutputRejectedError(max_attempts, last_error)
