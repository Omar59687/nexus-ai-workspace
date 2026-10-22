import math

import pytest

from nexus_ai.benchmark.metrics import (
    completion_failure_reasons,
    empty_generation_metrics,
    extract_generation_metrics,
    nanoseconds_to_milliseconds,
)


@pytest.mark.parametrize(
    ("raw_value", "expected"),
    [
        (1_500_000_000, 1500.0),
        (123_456_789, 123.457),
        (1_000_000, 1.0),
        (0, 0.0),
        (999, 0.001),
    ],
)
def test_nanoseconds_to_milliseconds(raw_value, expected) -> None:
    assert nanoseconds_to_milliseconds(raw_value) == expected


@pytest.mark.parametrize(
    "raw_value",
    [
        None,
        "1000000",
        True,
        -1,
        float("nan"),
        float("inf"),
        float("-inf"),
    ],
)
def test_nanoseconds_to_milliseconds_rejects_invalid_values(
    raw_value,
) -> None:
    assert nanoseconds_to_milliseconds(raw_value) is None


def test_extract_generation_metrics_maps_all_available_fields() -> None:
    metrics = extract_generation_metrics(
        {
            "total_duration": 2_000_000_000,
            "load_duration": 500_000_000,
            "prompt_eval_duration": 100_000_000,
            "eval_duration": 1_400_000_000,
            "prompt_eval_count": 11,
            "eval_count": 22,
            "done": True,
            "done_reason": "stop",
        }
    )

    assert metrics == {
        "total_duration_ms": 2000.0,
        "load_duration_ms": 500.0,
        "prompt_eval_duration_ms": 100.0,
        "eval_duration_ms": 1400.0,
        "prompt_eval_count": 11,
        "eval_count": 22,
        "done": True,
        "done_reason": "stop",
    }


def test_extract_generation_metrics_handles_missing_and_invalid_values() -> None:
    metrics = extract_generation_metrics(
        {
            "total_duration": "slow",
            "load_duration": -5,
            "eval_duration": math.inf,
            "prompt_eval_count": True,
            "eval_count": -2,
            "done": "yes",
            "done_reason": "",
        }
    )

    assert metrics == {
        "total_duration_ms": None,
        "load_duration_ms": None,
        "prompt_eval_duration_ms": None,
        "eval_duration_ms": None,
        "prompt_eval_count": None,
        "eval_count": None,
        "done": None,
        "done_reason": None,
    }


def test_empty_generation_metrics_has_all_fields_missing() -> None:
    metrics = empty_generation_metrics()

    assert metrics["total_duration_ms"] is None
    assert metrics["load_duration_ms"] is None
    assert metrics["prompt_eval_duration_ms"] is None
    assert metrics["eval_duration_ms"] is None
    assert metrics["prompt_eval_count"] is None
    assert metrics["eval_count"] is None
    assert metrics["done"] is None
    assert metrics["done_reason"] is None


@pytest.mark.parametrize(
    ("done", "done_reason", "eval_count", "num_predict", "expected_fragment"),
    [
        (False, None, 10, 256, "did not complete"),
        (None, None, 10, 256, "did not complete"),
        (True, "length", 256, 256, "num_predict"),
        (True, "stop", 256, 256, "num_predict"),
        (True, None, 256, 256, "num_predict"),
    ],
)
def test_completion_failure_reasons_detect_incomplete_generations(
    done,
    done_reason,
    eval_count,
    num_predict,
    expected_fragment,
) -> None:
    metrics = {
        "done": done,
        "done_reason": done_reason,
        "eval_count": eval_count,
    }

    reasons = completion_failure_reasons(metrics, num_predict)

    assert reasons
    assert expected_fragment in " ".join(reasons)


def test_complete_generation_has_no_failure_reasons() -> None:
    metrics = {
        "done": True,
        "done_reason": "stop",
        "eval_count": 20,
    }

    assert completion_failure_reasons(metrics, 256) == []


def test_missing_num_predict_skips_count_based_limit_check() -> None:
    metrics = {
        "done": True,
        "done_reason": "stop",
        "eval_count": 500,
    }

    assert completion_failure_reasons(metrics, None) == []
