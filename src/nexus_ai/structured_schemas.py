"""Registry of schema specifications for structured-output generation.

A :class:`StructuredSchemaSpec` couples a Pydantic model class with a
semantic validator and a default prompt so that services can generate
schema-conformant data by name. Schema validity does not imply factual
correctness: passing the validator proves only the declared structure
and validation rules, never the truth of the generated content.
"""

from collections.abc import Callable
from dataclasses import dataclass

from pydantic import BaseModel

from nexus_ai.structured_outputs import (
    DEFAULT_REST_EXPLANATION_PROMPT,
    RESTExplanation,
    validate_rest_explanation,
)


@dataclass(frozen=True)
class StructuredSchemaSpec:
    """Immutable description of one structured-output schema."""

    schema_name: str
    model_class: type[BaseModel]
    validator: Callable[[BaseModel], None]
    default_prompt: str

    def __post_init__(self) -> None:
        if not isinstance(self.schema_name, str) or (
            not self.schema_name.strip()
            or self.schema_name != self.schema_name.strip()
        ):
            raise ValueError("schema_name must be a non-blank string.")

        if not isinstance(self.model_class, type) or not issubclass(
            self.model_class, BaseModel
        ):
            raise ValueError("model_class must be a BaseModel subclass.")

        if not callable(self.validator):
            raise ValueError("validator must be callable.")

        if not isinstance(self.default_prompt, str) or not (
            self.default_prompt.strip()
        ):
            raise ValueError("default_prompt must be a non-empty string.")


class StructuredSchemaNotFoundError(LookupError):
    """Raised when a schema name is not in the registry."""

    def __init__(self, schema_name: str) -> None:
        super().__init__(f"Unknown structured schema: {schema_name!r}.")
        self.schema_name = schema_name


SCHEMA_REGISTRY: dict[str, StructuredSchemaSpec] = {
    "rest_explanation": StructuredSchemaSpec(
        schema_name="rest_explanation",
        model_class=RESTExplanation,
        validator=validate_rest_explanation,
        default_prompt=DEFAULT_REST_EXPLANATION_PROMPT,
    ),
}

SCHEMA_NAMES: tuple[str, ...] = tuple(sorted(SCHEMA_REGISTRY))


def get_schema_spec(schema_name: str) -> StructuredSchemaSpec:
    """Return the registered spec for ``schema_name``.

    Raises :class:`StructuredSchemaNotFoundError` when the name is not
    registered.
    """

    try:
        return SCHEMA_REGISTRY[schema_name]
    except KeyError as exc:
        raise StructuredSchemaNotFoundError(schema_name) from exc
