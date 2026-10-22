from pathlib import Path

import pytest

from nexus_ai.benchmark.cases import load_cases
from nexus_ai.benchmark.scoring import evaluate_case


CASES_PATH = (
    Path(__file__).resolve().parents[1] / "benchmarks" / "cases.json"
)


@pytest.fixture(scope="module")
def cases():
    return {
        case["id"]: case
        for case in load_cases(CASES_PATH).cases
    }


def test_cases_load_with_expected_version_and_ids(cases) -> None:
    assert set(cases) == {
        "rest_api_explanation",
        "structured_json",
        "http_status_bullets",
    }


def test_technical_explanation_passes_deterministic_checks(cases) -> None:
    response = (
        "REST API stands for Representational State Transfer Application "
        "Programming Interface. It is an architectural style for networked "
        "applications that uses HTTP methods to interact with resources. "
        "REST is stateless and separates the client from the server."
    )

    result = evaluate_case(cases["rest_api_explanation"], response)

    assert result.passed is True
    assert result.score == 1.0
    assert result.failure_reasons == ()
    assert result.manual_review_required is True
    assert result.manual_review_note


def test_technical_explanation_fails_without_required_expansions(
    cases,
) -> None:
    response = "REST is a useful API for servers and clients."

    result = evaluate_case(cases["rest_api_explanation"], response)

    assert result.passed is False
    assert result.score < 1.0
    assert any(
        "rest_expansion" in reason for reason in result.failure_reasons
    )
    assert any(
        "api_expansion" in reason for reason in result.failure_reasons
    )


def test_exact_json_object_passes(cases) -> None:
    result = evaluate_case(
        cases["structured_json"],
        '{"status": "ok", "model": "llama3.2"}',
    )

    assert result.passed is True
    assert result.score == 1.0
    assert result.manual_review_required is False


@pytest.mark.parametrize(
    "response",
    [
        '```json\n{"status": "ok", "model": "llama3.2"}\n```',
        'Here is the JSON: {"status": "ok", "model": "llama3.2"}',
        '{"status": "ok", "model": "llama3.2", "extra": true}',
        '{"status": "ok"}',
        '{"status": "failed", "model": "llama3.2"}',
        '{"status": "ok", "model": "llama3.1"}',
        '["ok", "llama3.2"]',
        "not json",
        "",
    ],
)
def test_exact_json_object_rejects_invalid_output(
    cases,
    response,
) -> None:
    result = evaluate_case(cases["structured_json"], response)

    assert result.passed is False
    assert result.failure_reasons


def test_exact_json_object_reports_field_failures(cases) -> None:
    result = evaluate_case(
        cases["structured_json"],
        '{"status": "ok", "model": "llama3.1"}',
    )

    assert result.passed is False
    assert any(
        reason.startswith("field:model:") for reason in result.failure_reasons
    )


def test_bullet_response_passes(cases) -> None:
    response = (
        "- HTTP 200 means the request succeeded.\n"
        "- HTTP 404 means the requested resource was not found.\n"
        "- HTTP 500 means the server encountered an internal error."
    )

    result = evaluate_case(cases["http_status_bullets"], response)

    assert result.passed is True
    assert result.score == 1.0
    assert result.manual_review_required is True


@pytest.mark.parametrize(
    "response",
    [
        (
            "The three codes are:\n"
            "- HTTP 200 means the request succeeded.\n"
            "- HTTP 404 means the requested resource was not found.\n"
            "- HTTP 500 means the server encountered an internal error."
        ),
        (
            "- HTTP 200 means the request succeeded.\n"
            "- HTTP 404 means the requested resource was not found."
        ),
        (
            "1. HTTP 200 means the request succeeded.\n"
            "2. HTTP 404 means the requested resource was not found.\n"
            "3. HTTP 500 means the server encountered an internal error."
        ),
        (
            "- HTTP 404 means the requested resource was not found.\n"
            "- HTTP 200 means the request succeeded.\n"
            "- HTTP 500 means the server encountered an internal error."
        ),
        (
            "- HTTP 200 means something happened here today.\n"
            "- HTTP 404 means something happened here today.\n"
            "- HTTP 500 means something happened here today."
        ),
        (
            "- HTTP 200\n"
            "- HTTP 404\n"
            "- HTTP 500"
        ),
        "",
    ],
)
def test_bullet_response_rejects_instruction_violations(
    cases,
    response,
) -> None:
    result = evaluate_case(cases["http_status_bullets"], response)

    assert result.passed is False
    assert result.failure_reasons


def test_bullet_response_accepts_common_404_synonyms(cases) -> None:
    response = (
        "- HTTP 200 means the request succeeded.\n"
        "- HTTP 404 means the requested resource cannot be found.\n"
        "- HTTP 500 means the server encountered an internal error."
    )

    result = evaluate_case(cases["http_status_bullets"], response)

    assert result.passed is True


def test_bullet_response_rejects_missing_status_keyword(cases) -> None:
    response = (
        "- HTTP 200 means the request succeeded.\n"
        "- HTTP 404 means the requested resource was not found.\n"
        "- HTTP 500 means something unexpected happened again."
    )

    result = evaluate_case(cases["http_status_bullets"], response)

    assert result.passed is False
    assert any(
        reason.startswith("meaning:500:") for reason in result.failure_reasons
    )
