"""Deterministic tests for the structured-output schema registry.

Covers the frozen contract of ``nexus_ai.structured_schemas``: valid
construction and lookup, deterministic rejection of invalid specs and
unknown names, registry/naming invariants, frozen-dataclass
immutability, and lookup identity. No network, database, or live
model service is required.
"""

import dataclasses
import inspect

import pytest
from pydantic import BaseModel

from nexus_ai.structured_schemas import (
    SCHEMA_NAMES,
    SCHEMA_REGISTRY,
    StructuredSchemaNotFoundError,
    StructuredSchemaSpec,
    get_schema_spec,
)
from nexus_ai.structured_outputs import (
    DEFAULT_REST_EXPLANATION_PROMPT,
    RESTExplanation,
    StructuredOutputRejectedError,
    generate_rest_explanation_with_retry,
    validate_rest_explanation,
)


def _valid_spec_kwargs() -> dict:
    return {
        "schema_name": "rest_explanation",
        "model_class": RESTExplanation,
        "validator": validate_rest_explanation,
        "default_prompt": DEFAULT_REST_EXPLANATION_PROMPT,
    }


def _kwarg_overrides(**overrides) -> dict:
    kwargs = _valid_spec_kwargs()
    kwargs.update(overrides)
    return kwargs


class Answer(BaseModel):
    """A minimal BaseModel subclass different from RESTExplanation."""

    value: str


def accept_answer(result: Answer) -> None:
    return None


class RecordingGenerator:
    """Fake injectable generator that records prompts and replays results."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.prompts = []

    def __call__(self, prompt: str) -> RESTExplanation:
        self.prompts.append(prompt)
        return self._responses.pop(0)


def test_rest_explanation_registry_entry_has_expected_members() -> None:
    spec = SCHEMA_REGISTRY["rest_explanation"]

    assert spec.schema_name == "rest_explanation"
    assert spec.model_class is RESTExplanation
    assert spec.validator is validate_rest_explanation
    assert spec.default_prompt == DEFAULT_REST_EXPLANATION_PROMPT


def test_registry_contains_exactly_one_entry_named_rest_explanation() -> None:
    assert list(SCHEMA_REGISTRY) == ["rest_explanation"]


def test_default_prompt_is_a_non_blank_usable_instruction() -> None:
    spec = SCHEMA_REGISTRY["rest_explanation"]

    assert isinstance(spec.default_prompt, str)
    assert spec.default_prompt.strip() == spec.default_prompt
    assert spec.default_prompt.startswith("Explain REST APIs.")


def test_schema_names_is_a_sorted_tuple_matching_registry_keys() -> None:
    assert isinstance(SCHEMA_NAMES, tuple)
    assert SCHEMA_NAMES == tuple(sorted(SCHEMA_REGISTRY))
    assert SCHEMA_NAMES == ("rest_explanation",)


def test_every_schema_name_resolves_to_its_registered_spec() -> None:
    for name in SCHEMA_NAMES:
        spec = get_schema_spec(name)
        assert spec.schema_name == name
        assert spec is SCHEMA_REGISTRY[name]
        assert isinstance(spec.model_class, type)
        assert issubclass(spec.model_class, BaseModel)
        assert callable(spec.validator)


def test_get_schema_spec_returns_the_same_registered_object() -> None:
    first = get_schema_spec("rest_explanation")
    second = get_schema_spec("rest_explanation")

    assert first is second
    assert first is SCHEMA_REGISTRY["rest_explanation"]


def test_unknown_name_raises_lookup_error_with_name_and_repr() -> None:
    with pytest.raises(StructuredSchemaNotFoundError) as exc_info:
        get_schema_spec("nonexistent_schema")

    error = exc_info.value
    assert isinstance(error, LookupError)
    assert error.schema_name == "nonexistent_schema"
    assert str(error) == "Unknown structured schema: 'nonexistent_schema'."


@pytest.mark.parametrize(
    "unknown_name",
    ["", "   ", "rest explanation", "rest_explanations",
     "REST_EXPLANATION", "Rest_Explanation"],
)
def test_near_miss_and_blank_names_are_not_matched(unknown_name: str) -> None:
    with pytest.raises(StructuredSchemaNotFoundError) as exc_info:
        get_schema_spec(unknown_name)

    assert exc_info.value.schema_name == unknown_name
    assert repr(unknown_name) in str(exc_info.value)


@pytest.mark.parametrize(
    "non_string_name",
    [42, None, True, 3.14],
)
def test_non_string_hashable_names_raise_not_found_carrying_name(
    non_string_name: object,
) -> None:
    """Current implementation: any hashable unknown key maps to the
    lookup error, and ``.schema_name`` carries the exact value."""

    with pytest.raises(StructuredSchemaNotFoundError) as exc_info:
        get_schema_spec(non_string_name)

    assert exc_info.value.schema_name == non_string_name


def test_unhashable_name_raises_type_error_unchanged() -> None:
    """Current implementation: the dict lookup itself rejects
    unhashable keys before the registry error can be produced."""

    with pytest.raises(TypeError):
        get_schema_spec(["rest_explanation"])


def test_valid_spec_constructs_and_lookup_returns_it() -> None:
    spec = StructuredSchemaSpec(**_valid_spec_kwargs())

    assert spec == get_schema_spec("rest_explanation")


def test_valid_spec_with_independent_members_constructs() -> None:
    spec = StructuredSchemaSpec(
        schema_name="answer",
        model_class=Answer,
        validator=accept_answer,
        default_prompt="Answer the question.",
    )

    assert spec.schema_name == "answer"
    assert spec.model_class is Answer
    assert spec.validator is accept_answer
    assert spec.default_prompt == "Answer the question."


@pytest.mark.parametrize(
    "overrides",
    [
        {"schema_name": ""},
        {"schema_name": "   "},
        {"schema_name": " x "},
        {"schema_name": 42},
        {"schema_name": None},
        {"model_class": 42},
        {"model_class": "RESTExplanation"},
        {"model_class": None},
        {"validator": None},
        {"validator": 42},
        {"default_prompt": None},
        {"default_prompt": 42},
        {"default_prompt": ""},
        {"default_prompt": "   "},
    ],
)
def test_invalid_spec_inputs_raise_value_error(overrides: dict) -> None:
    with pytest.raises(ValueError):
        StructuredSchemaSpec(**_kwarg_overrides(**overrides))


def test_model_class_outside_base_model_hierarchy_is_rejected() -> None:
    class NotBaseModel:
        pass

    with pytest.raises(ValueError):
        StructuredSchemaSpec(
            schema_name="answer",
            model_class=NotBaseModel,
            validator=accept_answer,
            default_prompt="Answer the question.",
        )


def test_frozen_spec_rejects_attribute_assignment() -> None:
    spec = get_schema_spec("rest_explanation")

    with pytest.raises(dataclasses.FrozenInstanceError):
        spec.schema_name = "other"


def test_registry_spec_drives_engine_end_to_end() -> None:
    spec = get_schema_spec("rest_explanation")
    valid = RESTExplanation(
        rest_expansion="Representational State Transfer",
        api_expansion="Application Programming Interface",
        purpose="A standard way for systems to exchange data.",
    )
    generate = RecordingGenerator([valid])

    result = generate_rest_explanation_with_retry(
        generate, prompt=spec.default_prompt
    )

    assert result is valid
    assert generate.prompts == [spec.default_prompt]
    spec.validator(result)


def test_registered_validator_drives_correction_and_rejection() -> None:
    spec = get_schema_spec("rest_explanation")
    valid = RESTExplanation(
        rest_expansion="Representational State Transfer",
        api_expansion="Application Programming Interface",
        purpose="A standard way for systems to exchange data.",
    )
    invalid = valid.model_copy(
        update={"rest_expansion": "Representational State of Resource"}
    )

    recovered = generate_rest_explanation_with_retry(
        RecordingGenerator([invalid, valid]), prompt=spec.default_prompt
    )
    assert recovered is valid

    rejected_generate = RecordingGenerator([invalid, invalid])
    with pytest.raises(StructuredOutputRejectedError):
        generate_rest_explanation_with_retry(
            rejected_generate, prompt=spec.default_prompt
        )
    assert len(rejected_generate.prompts) == 2


def test_module_logs_nothing() -> None:
    import nexus_ai.structured_schemas as module

    source = inspect.getsource(module)

    assert "import logging" not in source
    assert "getLogger" not in source
    assert "print(" not in source
