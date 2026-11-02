
import pytest
from pydantic import BaseModel, ValidationError

from nexus_ai.structured_output_pipeline import generate_with_validation


class RecordingGenerator:
    """Fake injectable generator that records prompts and replays results."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.prompts = []

    def __call__(self, prompt: str):
        self.prompts.append(prompt)
        return self._responses.pop(0)

    @property
    def call_count(self) -> int:
        return len(self.prompts)


class RecordingFailer:
    """Fake injectable generator that records prompts and always raises."""

    def __init__(self, error: Exception) -> None:
        self._error = error
        self.prompts = []

    def __call__(self, prompt: str):
        self.prompts.append(prompt)
        raise self._error

    @property
    def call_count(self) -> int:
        return len(self.prompts)


class PydanticJsonGenerator:
    """Fake generator that parses payload JSON into a Pydantic model."""

    def __init__(self, model: type[BaseModel], payload_jsons: list[str]) -> None:
        self._model = model
        self._payload_jsons = list(payload_jsons)
        self.prompts = []

    def __call__(self, prompt: str):
        self.prompts.append(prompt)
        return self._model.model_validate_json(self._payload_jsons.pop(0))

    @property
    def call_count(self) -> int:
        return len(self.prompts)


def accept_anything(value) -> None:
    return None


class CapitalAnswer(BaseModel):
    country: str
    capital: str


class WordCountAnswer(BaseModel):
    word_count: int


def validate_capital_answer(value: CapitalAnswer) -> None:
    if value.capital != "Lisbon":
        raise ValueError("capital must be 'Lisbon'.")


def validate_word_count(value: WordCountAnswer) -> None:
    if value.word_count != 4:
        raise ValueError("word_count must be 4.")


@pytest.fixture(scope="module")
def final_rejection_type() -> type[Exception]:
    """The module's final rejection exception class, resolved by a probe.

    The contract counts attempts used and the last validation error as
    part of the final rejection behavior, the class name is left to the
    implementation, so the class is discovered from the module's behavior
    rather than guessed.
    """

    def generate(prompt: str) -> str:
        return "invalid output"

    def validator(value: str) -> None:
        raise ValueError("validation never passes.")

    with pytest.raises(Exception) as exc_info:
        generate_with_validation(generate, validator, "probe prompt")

    rejection = exc_info.value

    assert rejection.attempts == 2
    assert isinstance(rejection.last_error, ValueError)
    assert "validation never passes." in str(rejection)

    return type(rejection)


def test_valid_first_attempt_returns_result_with_single_call() -> None:
    result: object = object()
    generate = RecordingGenerator([result])

    returned = generate_with_validation(
        generate, accept_anything, "original prompt"
    )

    assert returned is result
    assert generate.call_count == 1
    assert generate.prompts == ["original prompt"]


def test_validator_valueerror_triggers_exactly_one_correction_retry() -> None:
    invalid = "invalid answer"
    valid = "valid answer"
    generate = RecordingGenerator([invalid, valid])

    def validator(value: str) -> None:
        if value is invalid:
            raise ValueError("capital must be 'Lisbon'.")

    result = generate_with_validation(
        generate, validator, "Explain REST APIs."
    )

    assert result is valid
    assert generate.call_count == 2
    assert generate.prompts[0] == "Explain REST APIs."
    corrective = generate.prompts[1]
    assert "Explain REST APIs." in corrective
    assert "capital must be 'Lisbon'." in corrective
    assert corrective != generate.prompts[0]


def test_corrective_prompt_contains_exact_validator_message() -> None:
    failure = ValueError("capital must be 'Lisbon'.")
    generate = RecordingGenerator(["bad", "good"])

    def validator(value: str) -> None:
        if value == "bad":
            raise failure

    generate_with_validation(generate, validator, "original prompt")

    assert str(failure) in generate.prompts[1]


def test_first_pydantic_model_validates_through_pipeline() -> None:
    generate = PydanticJsonGenerator(
        CapitalAnswer,
        ['{"country": "Portugal", "capital": "Lisbon"}'],
    )

    result = generate_with_validation(
        generate, validate_capital_answer, "Name the capital of Portugal."
    )

    assert isinstance(result, CapitalAnswer)
    assert result.capital == "Lisbon"
    assert result.country == "Portugal"
    assert generate.call_count == 1


def test_second_pydantic_model_retries_through_pipeline() -> None:
    generate = PydanticJsonGenerator(
        WordCountAnswer,
        ['{"word_count": 3}', '{"word_count": 4}'],
    )

    result = generate_with_validation(
        generate, validate_word_count, "Count the words."
    )

    assert result.word_count == 4
    assert generate.call_count == 2
    assert "word_count must be 4." in generate.prompts[1]


def test_all_attempts_failing_raises_final_rejection(
    final_rejection_type: type[Exception],
) -> None:
    generate = RecordingGenerator(["bad"] * 5)

    def validator(value: str) -> None:
        raise ValueError("bad value.")

    with pytest.raises(final_rejection_type) as exc_info:
        generate_with_validation(generate, validator, "prompt.")

    rejection = exc_info.value
    assert rejection.attempts == 2
    assert isinstance(rejection.last_error, ValueError)
    assert str(rejection.last_error) == "bad value."
    assert "bad value." in str(rejection)
    assert generate.call_count == 2


def test_retry_prompt_uses_first_error_and_rejection_keeps_last_error(
    final_rejection_type: type[Exception],
) -> None:
    first_error = ValueError("first failure")
    last_error = ValueError("last failure")
    errors = iter([first_error, last_error])
    generate = RecordingGenerator(["first candidate", "second candidate"])

    def validator(value: str) -> None:
        raise next(errors)

    with pytest.raises(final_rejection_type) as exc_info:
        generate_with_validation(generate, validator, "original prompt")

    rejection = exc_info.value
    assert rejection.last_error is last_error
    assert generate.call_count == 2
    assert "first failure" in generate.prompts[1]


def test_no_infinite_retries_when_every_attempt_fails(
    final_rejection_type: type[Exception],
) -> None:
    generate = RecordingGenerator(["bad"] * 10)

    def validator(value: str) -> None:
        raise ValueError("invalid.")

    with pytest.raises(final_rejection_type):
        generate_with_validation(generate, validator, "prompt.")

    assert generate.call_count == 2


def test_max_attempts_boundary_one_succeeds_on_first_call() -> None:
    result: object = object()
    generate = RecordingGenerator([result, result])

    returned = generate_with_validation(
        generate, accept_anything, "prompt", max_attempts=1
    )

    assert returned is result
    assert generate.call_count == 1


def test_max_attempts_boundary_two_succeeds_on_second_call() -> None:
    generate = RecordingGenerator(["invalid", "valid"])

    def validator(value: str) -> None:
        if value == "invalid":
            raise ValueError("capital must be 'Lisbon'.")

    result = generate_with_validation(
        generate, validator, "prompt", max_attempts=2
    )

    assert result == "valid"
    assert generate.call_count == 2


def test_max_attempts_boundary_one_rejects_after_single_call(
    final_rejection_type: type[Exception],
) -> None:
    generate = RecordingGenerator(["bad"] * 5)

    def validator(value: str) -> None:
        raise ValueError("invalid.")

    with pytest.raises(final_rejection_type) as exc_info:
        generate_with_validation(generate, validator, "prompt", max_attempts=1)

    assert exc_info.value.attempts == 1
    assert generate.call_count == 1


@pytest.mark.parametrize("bad_max_attempts", [0, -1, 3, 10])
def test_max_attempts_outside_allowed_range_is_rejected(
    bad_max_attempts: int,
) -> None:
    generate = RecordingGenerator(["ok"] * 3)

    with pytest.raises(ValueError):
        generate_with_validation(
            generate, accept_anything, "prompt", max_attempts=bad_max_attempts
        )

    assert generate.call_count == 0


@pytest.mark.parametrize("bad_max_attempts", [1.5, 2.0, None, "2", True])
def test_non_int_max_attempts_is_rejected_before_generate(
    bad_max_attempts: object,
) -> None:
    generate = RecordingGenerator(["ok"] * 3)

    with pytest.raises(ValueError):
        generate_with_validation(
            generate, accept_anything, "prompt", max_attempts=bad_max_attempts
        )

    assert generate.call_count == 0


def test_connection_error_from_generate_propagates_unchanged() -> None:
    network_error = ConnectionError("Ollama is unreachable")
    generate = RecordingFailer(network_error)

    with pytest.raises(ConnectionError) as exc_info:
        generate_with_validation(generate, accept_anything, "prompt")

    assert exc_info.value is network_error
    assert generate.call_count == 1


def test_connection_error_on_retry_path_propagates_unchanged() -> None:
    network_error = ConnectionError("Ollama is unreachable during retry")
    prompts: list[str] = []
    candidates = iter(["invalid candidate"])

    def generate(prompt: str) -> str:
        prompts.append(prompt)
        try:
            return next(candidates)
        except StopIteration:
            raise network_error

    def validator(value: str) -> None:
        raise ValueError("invalid candidate.")

    with pytest.raises(ConnectionError) as exc_info:
        generate_with_validation(generate, validator, "prompt.")

    assert exc_info.value is network_error
    assert len(prompts) == 2


def test_pydantic_validation_error_from_generate_propagates_unchanged() -> None:
    try:
        CapitalAnswer.model_validate({"country": "Portugal"})
    except ValidationError as err:
        expected_error = err
    else:  # pragma: no cover - guards the test setup itself
        raise AssertionError("expected CapitalAnswer validation to fail")

    generate = RecordingFailer(expected_error)

    with pytest.raises(ValidationError) as exc_info:
        generate_with_validation(generate, validate_capital_answer, "prompt.")

    assert exc_info.value is expected_error
    assert generate.call_count == 1


def test_typeerror_from_validator_propagates_not_retried() -> None:
    expected_error = TypeError("value is not an int.")
    generate = RecordingGenerator(list(range(3)))

    def validator(value: str) -> None:
        raise expected_error

    with pytest.raises(TypeError) as exc_info:
        generate_with_validation(generate, validator, "prompt.")

    assert generate.call_count == 1
    assert exc_info.value is expected_error


def test_generate_returning_none_is_rejected_not_returned_as_success(
    final_rejection_type: type[Exception],
) -> None:
    generate = RecordingGenerator([None, None])

    def validator(value: None) -> None:
        raise ValueError("result is None.")

    with pytest.raises(final_rejection_type) as exc_info:
        generate_with_validation(generate, validator, "prompt.")

    assert exc_info.value.last_error is not None
    assert generate.call_count == 2


def test_none_is_returned_when_validator_accepts_it() -> None:
    generate = RecordingGenerator([None])
    received: list[object] = []

    def validator(value: object) -> None:
        received.append(value)

    result = generate_with_validation(generate, validator, "prompt.")

    assert result is None
    assert len(received) == 1
    assert received[0] is None
    assert generate.call_count == 1


def test_empty_prompt_is_passed_to_generate() -> None:
    result: object = object()
    generate = RecordingGenerator([result])

    returned = generate_with_validation(
        generate, accept_anything, ""
    )

    assert returned is result
    assert generate.call_count == 1
    assert generate.prompts == [""]
