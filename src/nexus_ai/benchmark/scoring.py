"""Deterministic scoring for benchmark cases."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any
from collections.abc import Mapping


WORD_PATTERN = re.compile(r"[A-Za-z0-9]+(?:['-][A-Za-z0-9]+)*")


@dataclass(frozen=True)
class EvaluationResult:
    """Automated evaluation of one model response."""

    score: float
    passed: bool
    checks: tuple[dict[str, Any], ...]
    failure_reasons: tuple[str, ...]
    manual_review_required: bool
    manual_review_note: str | None

    def to_dict(self) -> dict[str, Any]:
        """Convert the result into JSON-serializable report data."""
        return {
            "score": self.score,
            "passed": self.passed,
            "checks": [dict(check) for check in self.checks],
            "failure_reasons": list(self.failure_reasons),
            "manual_review_required": self.manual_review_required,
            "manual_review_note": self.manual_review_note,
        }


def evaluate_case(
    case: Mapping[str, Any],
    response_text: str,
) -> EvaluationResult:
    """Evaluate a generated response against a validated case definition."""
    evaluation = case["evaluation"]
    evaluation_type = evaluation["type"]

    if evaluation_type == "technical_explanation":
        checks = _evaluate_technical(evaluation, response_text)
    elif evaluation_type == "exact_json_object":
        checks = _evaluate_exact_json(evaluation, response_text)
    elif evaluation_type == "bullet_list":
        checks = _evaluate_bullets(evaluation, response_text)
    else:
        raise ValueError(
            f"Unsupported evaluation type: {evaluation_type!r}."
        )

    return _finish(evaluation, checks)


def _evaluate_technical(
    evaluation: Mapping[str, Any],
    response_text: str,
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    text = response_text.strip()

    checks.append(
        _check(
            "non_empty_response",
            bool(text),
            "response is empty" if not text else "response is not empty",
        )
    )

    word_count = len(WORD_PATTERN.findall(text))
    minimum_words = evaluation["minimum_words"]
    checks.append(
        _check(
            "minimum_words",
            word_count >= minimum_words,
            f"expected at least {minimum_words} words, found {word_count}",
        )
    )

    for spec in evaluation["required_patterns"]:
        flags = 0 if spec.get("case_sensitive", False) else re.IGNORECASE
        matched = re.search(spec["pattern"], text, flags=flags) is not None
        checks.append(
            _check(
                spec["name"],
                matched,
                (
                    f"matched required pattern {spec['pattern']!r}"
                    if matched
                    else f"missing required pattern {spec['pattern']!r}"
                ),
            )
        )

    matched_groups: list[str] = []
    missing_groups: list[str] = []
    folded_text = text.casefold()
    for group in evaluation["keyword_groups"]:
        if any(
            phrase.casefold() in folded_text
            for phrase in group["any_of"]
        ):
            matched_groups.append(group["name"])
        else:
            missing_groups.append(group["name"])

    minimum_groups = evaluation["minimum_keyword_groups"]
    coverage_ok = len(matched_groups) >= minimum_groups
    checks.append(
        _check(
            "keyword_coverage",
            coverage_ok,
            (
                f"matched {len(matched_groups)} of {len(evaluation['keyword_groups'])} "
                f"groups; required at least {minimum_groups}"
                + (
                    f"; missing: {', '.join(missing_groups)}"
                    if missing_groups
                    else ""
                )
            ),
        )
    )
    return checks


def _evaluate_exact_json(
    evaluation: Mapping[str, Any],
    response_text: str,
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    expected = evaluation["expected"]
    expected_keys = set(expected)

    parsed: object = None
    parse_error: str | None = None
    try:
        parsed = json.loads(
            response_text.strip(),
            object_pairs_hook=_unique_object,
        )
    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        parse_error = str(exc)

    parse_ok = parse_error is None
    checks.append(
        _check(
            "valid_json",
            parse_ok,
            (
                "response is valid JSON"
                if parse_ok
                else f"response is not valid JSON ({parse_error})"
            ),
        )
    )

    object_ok = isinstance(parsed, dict)
    checks.append(
        _check(
            "json_object",
            object_ok,
            (
                "response is a JSON object"
                if object_ok
                else "response is not a JSON object"
            ),
        )
    )

    if object_ok:
        actual_keys = set(parsed)
        if evaluation.get("exact_keys", True):
            keys_ok = actual_keys == expected_keys
            key_detail = (
                f"expected keys {sorted(expected_keys)}, "
                f"found {sorted(actual_keys)}"
            )
        else:
            keys_ok = expected_keys.issubset(actual_keys)
            key_detail = (
                f"expected at least keys {sorted(expected_keys)}, "
                f"found {sorted(actual_keys)}"
            )
    else:
        keys_ok = False
        key_detail = f"expected keys {sorted(expected_keys)} in a JSON object"

    checks.append(_check("keys", keys_ok, key_detail))

    for key in expected:
        expected_value = expected[key]
        if object_ok and key in parsed:
            actual_value = parsed[key]
            value_ok = _is_exact_value(actual_value, expected_value)
            value_detail = (
                f"expected {key}={expected_value!r}, "
                f"found {actual_value!r}"
            )
        else:
            value_ok = False
            value_detail = f"missing field {key!r}"
        checks.append(_check(f"field:{key}", value_ok, value_detail))

    return checks


def _evaluate_bullets(
    evaluation: Mapping[str, Any],
    response_text: str,
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    lines = [
        line.strip()
        for line in response_text.splitlines()
        if line.strip()
    ]
    codes = evaluation["expected_status_codes"]
    marker = evaluation["bullet_marker"]
    bullet_pattern = re.compile(rf"^{re.escape(marker)}\s+\S")
    minimum_words = evaluation["minimum_words_per_bullet"]

    checks.append(
        _check(
            "line_count",
            len(lines) == len(codes),
            (
                f"expected exactly {len(codes)} non-empty lines, "
                f"found {len(lines)}"
            ),
        )
    )

    all_bullets = bool(lines) and all(
        bullet_pattern.match(line) is not None for line in lines
    )
    checks.append(
        _check(
            "hyphen_bullets",
            all_bullets,
            (
                "every non-empty line uses the requested bullet marker"
                if all_bullets
                else "at least one non-empty line is not a valid bullet"
            ),
        )
    )

    keyword_groups = evaluation["status_keyword_groups"]
    for index, code in enumerate(codes):
        line = lines[index] if index < len(lines) else ""
        status_pattern = re.compile(rf"\b{code}\b")
        status_ok = status_pattern.search(line) is not None
        checks.append(
            _check(
                f"status:{code}",
                status_ok,
                (
                    f"line {index + 1} contains status {code}"
                    if status_ok
                    else f"line {index + 1} does not contain status {code}"
                ),
            )
        )

        word_content = _bullet_explanation_word_content(
            line,
            marker,
            code,
        )
        word_count = len(WORD_PATTERN.findall(word_content))
        checks.append(
            _check(
                f"words:{code}",
                word_count >= minimum_words,
                (
                    f"expected at least {minimum_words} explanation words "
                    f"for status {code}, found {word_count}"
                ),
            )
        )

        phrases = keyword_groups[str(code)]
        keyword_ok = any(
            phrase.casefold() in line.casefold() for phrase in phrases
        )
        checks.append(
            _check(
                f"meaning:{code}",
                keyword_ok,
                (
                    f"line {index + 1} explains status {code}"
                    if keyword_ok
                    else f"line {index + 1} is missing an expected "
                    f"concept for status {code}"
                ),
            )
        )

    return checks


def _bullet_explanation_word_content(
    line: str,
    marker: str,
    code: int,
) -> str:
    content = line
    if content.startswith(marker):
        content = content[len(marker):].strip()
    content = re.sub(rf"\b{code}\b", " ", content)
    content = re.sub(r"\bHTTP\b", " ", content, flags=re.IGNORECASE)
    return content


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _is_exact_value(actual: object, expected: object) -> bool:
    return type(actual) is type(expected) and actual == expected


def _check(name: str, passed: bool, detail: str) -> dict[str, Any]:
    return {
        "name": name,
        "passed": passed,
        "detail": detail,
    }


def _finish(
    evaluation: Mapping[str, Any],
    checks: list[dict[str, Any]],
) -> EvaluationResult:
    failed_checks = [check for check in checks if not check["passed"]]
    score = (
        round(
            sum(1 for check in checks if check["passed"]) / len(checks),
            4,
        )
        if checks
        else 0.0
    )
    manual_review_required = bool(
        evaluation.get("manual_review_required", True)
    )
    note = evaluation.get("manual_review_note")
    manual_review_note = note if isinstance(note, str) else None

    return EvaluationResult(
        score=score,
        passed=bool(checks) and not failed_checks,
        checks=tuple(checks),
        failure_reasons=tuple(
            f"{check['name']}: {check['detail']}"
            for check in failed_checks
        ),
        manual_review_required=manual_review_required,
        manual_review_note=manual_review_note,
    )
