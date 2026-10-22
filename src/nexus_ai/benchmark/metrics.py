"""Metric extraction and completion validation for Ollama responses."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any


NANOSECONDS_PER_MILLISECOND = 1_000_000
DURATION_FIELDS = (
    "total_duration",
    "load_duration",
    "prompt_eval_duration",
    "eval_duration",
)
COUNT_FIELDS = (
    "prompt_eval_count",
    "eval_count",
)
METRIC_FIELDS = DURATION_FIELDS + COUNT_FIELDS


def nanoseconds_to_milliseconds(value: object) -> float | None:
    """Convert an Ollama nanosecond duration to milliseconds."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or value < 0:
        return None
    return round(value / NANOSECONDS_PER_MILLISECOND, 3)


def extract_generation_metrics(
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Extract optional metrics without failing on missing or invalid data."""
    metrics: dict[str, Any] = {}
    for field_name in DURATION_FIELDS:
        metrics[f"{field_name}_ms"] = nanoseconds_to_milliseconds(
            payload.get(field_name)
        )
    for field_name in COUNT_FIELDS:
        metrics[field_name] = _non_negative_int(payload.get(field_name))

    done = payload.get("done")
    metrics["done"] = done if isinstance(done, bool) else None

    done_reason = payload.get("done_reason")
    metrics["done_reason"] = (
        done_reason
        if isinstance(done_reason, str) and done_reason.strip()
        else None
    )
    return metrics


def empty_generation_metrics() -> dict[str, Any]:
    """Return a metrics object with every value marked unavailable."""
    metrics: dict[str, Any] = {
        f"{field_name}_ms": None for field_name in DURATION_FIELDS
    }
    metrics.update({field_name: None for field_name in COUNT_FIELDS})
    metrics["done"] = None
    metrics["done_reason"] = None
    return metrics


def completion_failure_reasons(
    metrics: Mapping[str, Any],
    num_predict: int | None,
) -> list[str]:
    """Return reasons why an Ollama response is not a complete generation."""
    reasons: list[str] = []

    done = metrics.get("done")
    if done is not True:
        reasons.append(f"generation did not complete (done={done!r})")

    done_reason = metrics.get("done_reason")
    if done_reason == "length":
        reasons.append(
            "generation stopped at the num_predict token limit "
            "(done_reason='length')"
        )
    else:
        eval_count = metrics.get("eval_count")
        if (
            isinstance(eval_count, int)
            and not isinstance(eval_count, bool)
            and isinstance(num_predict, int)
            and not isinstance(num_predict, bool)
            and num_predict > 0
            and eval_count >= num_predict
        ):
            reasons.append(
                "generation reached the num_predict token limit "
                f"(eval_count={eval_count}, num_predict={num_predict})"
            )

    return reasons


def _non_negative_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value
