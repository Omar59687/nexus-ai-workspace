
import pytest
from pydantic import ValidationError

from nexus_ai.structured_outputs import (
    RESTExplanation,
    StructuredOutputRejectedError,
    build_correction_prompt,
    generate_rest_explanation_with_retry,
    validate_rest_explanation,
)


VALID_RESULT = RESTExplanation(
    rest_expansion="Representational State Transfer",
    api_expansion="Application Programming Interface",
    purpose="A standard way for systems to exchange data.",
)


def test_valid_rest_explanation_passes() -> None:
    result = RESTExplanation(
        rest_expansion="Representational State Transfer",
        api_expansion="Application Programming Interface",
        purpose="A standard way for systems to exchange data.",
    )

    validate_rest_explanation(result)


def test_wrong_rest_expansion_is_rejected() -> None:
    result = RESTExplanation(
        rest_expansion="Representational State of Resource",
        api_expansion="Application Programming Interface",
        purpose="A standard way for systems to exchange data.",
    )

    with pytest.raises(
        ValueError,
        match="rest_expansion must be",
    ):
        validate_rest_explanation(result)


def test_wrong_api_expansion_is_rejected() -> None:
    result = RESTExplanation(
        rest_expansion="Representational State Transfer",
        api_expansion="Application Programming Interface System",
        purpose="A standard way for systems to exchange data.",
    )

    with pytest.raises(
        ValueError,
        match="api_expansion must be",
    ):
        validate_rest_explanation(result)


def test_missing_required_field_is_rejected() -> None:
    with pytest.raises(ValidationError):
        RESTExplanation(
            rest_expansion="Representational State Transfer",
            api_expansion="Application Programming Interface",
        )


def test_unexpected_field_is_rejected() -> None:
    with pytest.raises(ValidationError):
        RESTExplanation(
            rest_expansion="Representational State Transfer",
            api_expansion="Application Programming Interface",
            purpose="A standard way to exchange data.",
            extra_field="unexpected",
        )


def test_correct_expansions_are_case_insensitive() -> None:
    result = RESTExplanation(
        rest_expansion="representational state transfer",
        api_expansion="application programming interface",
        purpose="A standard way for systems to exchange data.",
    )

    validate_rest_explanation(result)


class RecordingGenerator:
    """Fake injectable generator that records prompts and replays results."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.prompts = []

    def __call__(self, prompt: str) -> RESTExplanation:
        self.prompts.append(prompt)
        return self._responses.pop(0)


def test_first_response_passes_single_call() -> None:
    generate = RecordingGenerator([VALID_RESULT])

    result = generate_rest_explanation_with_retry(generate)

    assert result is VALID_RESULT
    assert len(generate.prompts) == 1


def test_first_fails_second_passes_two_calls_with_correction() -> None:
    invalid = VALID_RESULT.model_copy(
        update={"rest_expansion": "Representational State of Resource"}
    )
    generate = RecordingGenerator([invalid, VALID_RESULT])

    result = generate_rest_explanation_with_retry(generate)

    assert result is VALID_RESULT
    assert len(generate.prompts) == 2
    assert "rest_expansion must be 'Representational State Transfer'" in (
        generate.prompts[1]
    )


def test_both_responses_fail_is_rejected_after_two_calls() -> None:
    invalid = VALID_RESULT.model_copy(
        update={"rest_expansion": "Representational State of Resource"}
    )
    generate = RecordingGenerator([invalid, invalid])

    with pytest.raises(StructuredOutputRejectedError) as exc_info:
        generate_rest_explanation_with_retry(generate)

    assert len(generate.prompts) == 2
    assert exc_info.value.attempts == 2
    assert "rest_expansion must be" in str(exc_info.value)


def test_no_more_than_one_retry_is_performed() -> None:
    invalid = VALID_RESULT.model_copy(
        update={"rest_expansion": "Representational State of Resource"}
    )
    responses = [invalid] * 5
    generate = RecordingGenerator(responses)

    with pytest.raises(StructuredOutputRejectedError):
        generate_rest_explanation_with_retry(generate)

    assert len(generate.prompts) == 2
    assert len(generate._responses) == 3


def test_correction_prompt_contains_original_validation_error() -> None:
    invalid = VALID_RESULT.model_copy(
        update={"api_expansion": "Application Programming Interface System"}
    )
    generate = RecordingGenerator([invalid, VALID_RESULT])

    generate_rest_explanation_with_retry(generate)

    original_error = (
        "api_expansion must be 'Application Programming Interface'."
    )
    assert original_error in generate.prompts[1]
    assert generate.prompts[1].startswith(
        "Explain REST APIs."
    )


def test_network_errors_are_not_retried() -> None:
    def failing_generate(prompt: str) -> RESTExplanation:
        raise ConnectionError("Ollama is unreachable")

    with pytest.raises(ConnectionError):
        generate_rest_explanation_with_retry(failing_generate)


def test_invalid_max_attempts_is_rejected() -> None:
    with pytest.raises(ValueError, match="must be between 1 and 2"):
        generate_rest_explanation_with_retry(
            RecordingGenerator([VALID_RESULT]),
            max_attempts=0,
        )


def test_max_attempts_above_two_is_rejected() -> None:
    with pytest.raises(ValueError, match="must be between 1 and 2"):
        generate_rest_explanation_with_retry(
            RecordingGenerator([VALID_RESULT]),
            max_attempts=3,
        )


def test_single_attempt_mode_rejects_without_retry() -> None:
    invalid = VALID_RESULT.model_copy(
        update={"rest_expansion": "Representational State of Resource"}
    )
    generate = RecordingGenerator([invalid, invalid])

    with pytest.raises(StructuredOutputRejectedError) as exc_info:
        generate_rest_explanation_with_retry(
            generate,
            max_attempts=1,
        )

    assert len(generate.prompts) == 1
    assert exc_info.value.attempts == 1


def test_network_error_on_retry_is_not_classified_as_rejection() -> None:
    invalid = VALID_RESULT.model_copy(
        update={"rest_expansion": "Representational State of Resource"}
    )

    def generate(prompt: str) -> RESTExplanation:
        if not generate.prompts:
            generate.prompts.append(prompt)
            return invalid
        raise ConnectionError("Ollama is unreachable")

    generate.prompts = []

    with pytest.raises(ConnectionError):
        generate_rest_explanation_with_retry(generate)

    assert len(generate.prompts) == 1


def test_correction_prompt_includes_failure_and_reset_context() -> None:
    error = ValueError("rest_expansion must be 'Representational State Transfer'.")

    prompt = build_correction_prompt("Explain REST APIs.", error)

    assert prompt.startswith("Explain REST APIs.")
    assert "failed validation" in prompt
    assert str(error) in prompt


def _load_demo_script():
    import importlib.util
    import sys
    from pathlib import Path

    scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
    script_path = scripts_dir / "try_langchain_structured.py"

    if "try_langchain_structured" in sys.modules:
        return sys.modules["try_langchain_structured"]

    import sys as _sys
    _sys.path.insert(0, str(scripts_dir))
    spec = importlib.util.spec_from_file_location(
        "try_langchain_structured",
        script_path,
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["try_langchain_structured"] = module
    spec.loader.exec_module(module)
    return module


def test_final_rejection_produces_nonzero_cli_exit_status(capsys) -> None:
    demo = _load_demo_script()
    invalid = VALID_RESULT.model_copy(
        update={"rest_expansion": "Representational State of Resource"}
    )
    generate = RecordingGenerator([invalid, invalid])

    with pytest.raises(SystemExit) as exc_info:
        demo.main(generate=generate)

    assert exc_info.value.code == 1
    captured = capsys.readouterr().out
    assert "Rejected:" in captured
    assert "Generation attempts used: 2" in captured


def test_successful_cli_run_reports_attempt_count(capsys) -> None:
    demo = _load_demo_script()
    generate = RecordingGenerator([VALID_RESULT])

    demo.main(generate=generate)

    captured = capsys.readouterr().out
    assert "Generation attempts used: 1" in captured
    assert "Semantic validation: PASS" in captured
