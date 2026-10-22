"""Load and validate versioned benchmark case definitions."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SUPPORTED_SCHEMA_VERSION = 1
SUPPORTED_EVALUATION_TYPES = frozenset(
    {
        "technical_explanation",
        "exact_json_object",
        "bullet_list",
    }
)


class BenchmarkCaseError(ValueError):
    """Raised when benchmark case definitions are invalid."""


@dataclass(frozen=True)
class BenchmarkCaseSet:
    """A validated, versioned collection of benchmark cases."""

    schema_version: int
    benchmark_version: str
    description: str
    cases: tuple[dict[str, Any], ...]
    source_path: Path
    sha256: str


def load_cases(path: Path) -> BenchmarkCaseSet:
    """Read and validate a benchmark cases JSON document."""
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise BenchmarkCaseError(
            f"Could not read benchmark cases file: {path}"
        ) from exc

    try:
        document = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise BenchmarkCaseError(
            "Benchmark cases file is not valid JSON."
        ) from exc

    if not isinstance(document, dict):
        raise BenchmarkCaseError(
            "Benchmark cases file must contain a JSON object."
        )

    schema_version = document.get("schema_version")
    if schema_version != SUPPORTED_SCHEMA_VERSION:
        raise BenchmarkCaseError(
            "Unsupported benchmark cases schema_version: "
            f"{schema_version!r}."
        )

    benchmark_version = _non_empty_string(
        document,
        "benchmark_version",
        "benchmark document",
    )
    description = document.get("description", "")
    if not isinstance(description, str):
        raise BenchmarkCaseError(
            "Benchmark document 'description' must be a string."
        )

    raw_cases = document.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise BenchmarkCaseError(
            "Benchmark document must contain a non-empty 'cases' list."
        )

    cases: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, raw_case in enumerate(raw_cases):
        case = _validate_case(raw_case, index)
        case_id = case["id"]
        if case_id in seen_ids:
            raise BenchmarkCaseError(
                f"Duplicate benchmark case id: {case_id!r}."
            )
        seen_ids.add(case_id)
        cases.append(case)

    return BenchmarkCaseSet(
        schema_version=schema_version,
        benchmark_version=benchmark_version,
        description=description,
        cases=tuple(cases),
        source_path=path.resolve(),
        sha256=hashlib.sha256(raw).hexdigest(),
    )


def _validate_case(raw_case: object, index: int) -> dict[str, Any]:
    context = f"case at index {index}"
    if not isinstance(raw_case, dict):
        raise BenchmarkCaseError(f"{context} must be a JSON object.")

    case_id = _non_empty_string(raw_case, "id", context)
    _non_empty_string(raw_case, "category", f"case {case_id!r}")
    _non_empty_string(raw_case, "prompt", f"case {case_id!r}")

    evaluation = raw_case.get("evaluation")
    if not isinstance(evaluation, dict):
        raise BenchmarkCaseError(
            f"Case {case_id!r} must contain an 'evaluation' object."
        )

    evaluation_type = _non_empty_string(
        evaluation,
        "type",
        f"evaluation for case {case_id!r}",
    )
    if evaluation_type not in SUPPORTED_EVALUATION_TYPES:
        raise BenchmarkCaseError(
            f"Unsupported evaluation type for case {case_id!r}: "
            f"{evaluation_type!r}."
        )

    if evaluation_type == "technical_explanation":
        _validate_technical_evaluation(evaluation, case_id)
    elif evaluation_type == "exact_json_object":
        _validate_json_evaluation(evaluation, case_id)
    else:
        _validate_bullet_evaluation(evaluation, case_id)

    _validate_manual_review(evaluation, case_id)
    return raw_case


def _validate_technical_evaluation(
    evaluation: dict[str, Any],
    case_id: str,
) -> None:
    _positive_int(
        evaluation,
        "minimum_words",
        f"technical evaluation for case {case_id!r}",
    )

    patterns = evaluation.get("required_patterns")
    if not isinstance(patterns, list) or not patterns:
        raise BenchmarkCaseError(
            f"Case {case_id!r} requires non-empty 'required_patterns'."
        )
    pattern_names: set[str] = set()
    for spec in patterns:
        if not isinstance(spec, dict):
            raise BenchmarkCaseError(
                f"Case {case_id!r} has an invalid required pattern."
            )
        name = _non_empty_string(spec, "name", "required pattern")
        if name in pattern_names:
            raise BenchmarkCaseError(
                f"Case {case_id!r} has a duplicate pattern name: {name!r}."
            )
        pattern_names.add(name)
        pattern = _non_empty_string(spec, "pattern", f"pattern {name!r}")
        case_sensitive = spec.get("case_sensitive", False)
        if not isinstance(case_sensitive, bool):
            raise BenchmarkCaseError(
                f"Pattern {name!r} in case {case_id!r} has an invalid "
                "'case_sensitive' value."
            )
        try:
            re.compile(
                pattern,
                0 if case_sensitive else re.IGNORECASE,
            )
        except re.error as exc:
            raise BenchmarkCaseError(
                f"Pattern {name!r} in case {case_id!r} is invalid."
            ) from exc

    groups = evaluation.get("keyword_groups")
    if not isinstance(groups, list) or not groups:
        raise BenchmarkCaseError(
            f"Case {case_id!r} requires non-empty 'keyword_groups'."
        )
    _validate_keyword_groups(groups, case_id, "keyword_groups")

    minimum_groups = evaluation.get("minimum_keyword_groups")
    if (
        isinstance(minimum_groups, bool)
        or not isinstance(minimum_groups, int)
        or minimum_groups < 0
        or minimum_groups > len(groups)
    ):
        raise BenchmarkCaseError(
            f"Case {case_id!r} has an invalid 'minimum_keyword_groups'."
        )


def _validate_json_evaluation(
    evaluation: dict[str, Any],
    case_id: str,
) -> None:
    expected = evaluation.get("expected")
    if not isinstance(expected, dict) or not expected:
        raise BenchmarkCaseError(
            f"Case {case_id!r} requires a non-empty 'expected' object."
        )

    exact_keys = evaluation.get("exact_keys", True)
    if not isinstance(exact_keys, bool):
        raise BenchmarkCaseError(
            f"Case {case_id!r} has an invalid 'exact_keys' value."
        )


def _validate_bullet_evaluation(
    evaluation: dict[str, Any],
    case_id: str,
) -> None:
    marker = _non_empty_string(
        evaluation,
        "bullet_marker",
        f"bullet evaluation for case {case_id!r}",
    )
    if marker.strip() != marker or any(character.isspace() for character in marker):
        raise BenchmarkCaseError(
            f"Case {case_id!r} has an invalid 'bullet_marker'."
        )

    codes = evaluation.get("expected_status_codes")
    if (
        not isinstance(codes, list)
        or not codes
        or any(
            isinstance(code, bool) or not isinstance(code, int)
            for code in codes
        )
    ):
        raise BenchmarkCaseError(
            f"Case {case_id!r} has invalid 'expected_status_codes'."
        )

    _positive_int(
        evaluation,
        "minimum_words_per_bullet",
        f"bullet evaluation for case {case_id!r}",
    )

    keyword_groups = evaluation.get("status_keyword_groups")
    if not isinstance(keyword_groups, dict):
        raise BenchmarkCaseError(
            f"Case {case_id!r} has invalid 'status_keyword_groups'."
        )
    expected_keys = {str(code) for code in codes}
    if set(keyword_groups) != expected_keys:
        raise BenchmarkCaseError(
            f"Case {case_id!r} must define keyword groups for exactly "
            f"{sorted(expected_keys)}."
        )
    for code, phrases in keyword_groups.items():
        if (
            not isinstance(phrases, list)
            or not phrases
            or any(
                not isinstance(phrase, str) or not phrase.strip()
                for phrase in phrases
            )
        ):
            raise BenchmarkCaseError(
                f"Case {case_id!r} has invalid keywords for status {code}."
            )


def _validate_keyword_groups(
    groups: list[Any],
    case_id: str,
    field_name: str,
) -> None:
    seen_names: set[str] = set()
    for group in groups:
        if not isinstance(group, dict):
            raise BenchmarkCaseError(
                f"Case {case_id!r} has an invalid entry in "
                f"'{field_name}'."
            )
        name = _non_empty_string(
            group,
            "name",
            f"keyword group in case {case_id!r}",
        )
        if name in seen_names:
            raise BenchmarkCaseError(
                f"Case {case_id!r} has a duplicate keyword group: "
                f"{name!r}."
            )
        seen_names.add(name)
        phrases = group.get("any_of")
        if (
            not isinstance(phrases, list)
            or not phrases
            or any(
                not isinstance(phrase, str) or not phrase.strip()
                for phrase in phrases
            )
        ):
            raise BenchmarkCaseError(
                f"Keyword group {name!r} in case {case_id!r} must contain "
                "a non-empty string list in 'any_of'."
            )


def _validate_manual_review(
    evaluation: dict[str, Any],
    case_id: str,
) -> None:
    manual_review = evaluation.get("manual_review_required", True)
    if not isinstance(manual_review, bool):
        raise BenchmarkCaseError(
            f"Case {case_id!r} has an invalid "
            "'manual_review_required' value."
        )

    note = evaluation.get("manual_review_note")
    if note is not None and not isinstance(note, str):
        raise BenchmarkCaseError(
            f"Case {case_id!r} has an invalid 'manual_review_note'."
        )


def _non_empty_string(
    mapping: dict[str, Any],
    key: str,
    context: str,
) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise BenchmarkCaseError(
            f"{context} must contain a non-empty string '{key}'."
        )
    return value


def _positive_int(
    mapping: dict[str, Any],
    key: str,
    context: str,
) -> int:
    value = mapping.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise BenchmarkCaseError(
            f"{context} must contain a positive integer '{key}'."
        )
    return value
