 
"""REST explanation schema and adapter to the generic structured-output engine."""

from collections.abc import Callable

from pydantic import BaseModel, ConfigDict, Field

from nexus_ai.structured_output_pipeline import (
    DEFAULT_MAX_ATTEMPTS,
    StructuredOutputRejectedError,
    build_correction_prompt,
    generate_with_validation,
)


class RESTExplanation(BaseModel):
    """Expected structure for a REST API explanation."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    rest_expansion: str = Field(
        min_length=1,
        description="The full expansion of REST",
    )
    api_expansion: str = Field(
        min_length=1,
        description="The full expansion of API",
    )
    purpose: str = Field(
        min_length=1,
        description="The purpose of a REST API",
    )


def validate_rest_explanation(result: RESTExplanation) -> None:
    """Validate known acronym expansions for this specific task."""

    expected_expansions = {
        "rest_expansion": "Representational State Transfer",
        "api_expansion": "Application Programming Interface",
    }

    for field_name, expected in expected_expansions.items():
        actual = getattr(result, field_name)

        if actual.casefold() != expected.casefold():
            raise ValueError(
                f"{field_name} must be '{expected}'."
            )


DEFAULT_REST_EXPLANATION_PROMPT = (
    "Explain REST APIs. Give the full expansions of REST "
    "and API, and briefly explain their purpose."
)

MAX_GENERATION_ATTEMPTS = DEFAULT_MAX_ATTEMPTS


def generate_rest_explanation_with_retry(
    generate: Callable[[str], RESTExplanation],
    prompt: str = DEFAULT_REST_EXPLANATION_PROMPT,
    max_attempts: int = MAX_GENERATION_ATTEMPTS,
) -> RESTExplanation:
    """Generate a validated ``RESTExplanation`` with at most one retry.

    REST adapter for
    :func:`nexus_ai.structured_output_pipeline.generate_with_validation`:
    the generate-and-validate loop, correction prompts, and rejection
    handling are delegated to the generic engine. ``generate`` receives
    the request prompt and must return a parsed ``RESTExplanation``.
    Only semantic validation failures raised by
    :func:`validate_rest_explanation` trigger a corrective retry; errors
    raised by ``generate`` itself (including Pydantic parsing errors and
    network failures) propagate unchanged. If the final attempt still
    fails validation, the result is rejected with
    :class:`StructuredOutputRejectedError` instead of being returned as
    a success.
    """

    return generate_with_validation(
        generate=generate,
        validator=validate_rest_explanation,
        prompt=prompt,
        max_attempts=max_attempts,
    )
