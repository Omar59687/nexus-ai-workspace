"""Benchmark orchestration, scoring, summaries, and report writing."""

from __future__ import annotations

import json
import math
import platform
import re
import statistics
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from nexus_ai.benchmark.cases import BenchmarkCaseSet
from nexus_ai.benchmark.client import (
    BenchmarkClientError,
    GenerationResult,
    OllamaBenchmarkClient,
)
from nexus_ai.benchmark.metrics import (
    completion_failure_reasons,
    empty_generation_metrics,
)
from nexus_ai.benchmark.scoring import evaluate_case


WARMUP_PROMPT = "Reply with the single word: ready"
WARMUP_MAX_TOKENS = 16
PROJECT_ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class BenchmarkSettings:
    """Generation settings recorded with every benchmark run."""

    temperature: float = 0.0
    num_predict: int = 256
    seed: int = 42
    timeout_seconds: float = 120.0

    def __post_init__(self) -> None:
        if (
            isinstance(self.temperature, bool)
            or not isinstance(self.temperature, (int, float))
            or not math.isfinite(self.temperature)
            or self.temperature < 0
        ):
            raise ValueError(
                "temperature must be a finite non-negative number."
            )
        if (
            isinstance(self.num_predict, bool)
            or not isinstance(self.num_predict, int)
            or self.num_predict <= 0
        ):
            raise ValueError("num_predict must be a positive integer.")
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise ValueError("seed must be an integer.")
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or not math.isfinite(self.timeout_seconds)
            or self.timeout_seconds <= 0
        ):
            raise ValueError(
                "timeout_seconds must be a finite positive number."
            )

    def request_options(self) -> dict[str, Any]:
        """Return the exact options sent to Ollama."""
        return {
            "temperature": self.temperature,
            "num_predict": self.num_predict,
            "seed": self.seed,
        }

    def to_dict(self) -> dict[str, Any]:
        """Return serializable settings for the report."""
        return {
            **self.request_options(),
            "timeout_seconds": self.timeout_seconds,
        }


def run_benchmark(
    *,
    client: OllamaBenchmarkClient,
    case_set: BenchmarkCaseSet,
    model: str,
    repeats: int = 2,
    settings: BenchmarkSettings | None = None,
    run_id: str | None = None,
    warmup_enabled: bool = True,
    now: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    """Run warm-up and measured trials, returning a JSON-ready report."""
    if not isinstance(model, str) or not model.strip():
        raise ValueError("model must be a non-empty string.")
    if isinstance(repeats, bool) or not isinstance(repeats, int) or repeats < 1:
        raise ValueError("repeats must be a positive integer.")
    if not case_set.cases:
        raise ValueError("At least one benchmark case is required.")

    benchmark_settings = settings or BenchmarkSettings()
    clock = now or _utc_now
    started_at = _as_utc(clock())
    selected_run_id = run_id or _new_run_id(started_at)

    ollama_version: str | None = None
    version_error: str | None = None
    try:
        ollama_version = client.get_version()
    except BenchmarkClientError as exc:
        version_error = f"{type(exc).__name__}: {exc}"

    warmup = _run_warmup(
        client=client,
        model=model.strip(),
        settings=benchmark_settings,
        enabled=warmup_enabled,
        now=clock,
    )

    results: list[dict[str, Any]] = []
    for case in case_set.cases:
        trials = [
            _run_trial(
                client=client,
                case=case,
                model=model.strip(),
                settings=benchmark_settings,
                now=clock,
            )
            for _ in range(repeats)
        ]
        results.append(
            {
                "case_id": case["id"],
                "category": case["category"],
                "evaluation_type": case["evaluation"]["type"],
                "manual_review_required": bool(
                    case["evaluation"].get("manual_review_required", True)
                ),
                "trials": trials,
                "summary": _summarize_trials(trials),
            }
        )

    finished_at = _as_utc(clock())
    all_trials = [
        trial
        for result in results
        for trial in result["trials"]
    ]
    summary = _summarize_trials(all_trials)
    summary["all_passed"] = (
        summary["measured_trials"] > 0
        and summary["passed"] == summary["measured_trials"]
    )

    return {
        "schema_version": 1,
        "run_id": selected_run_id,
        "started_at_utc": _iso_utc(started_at),
        "finished_at_utc": _iso_utc(finished_at),
        "benchmark": {
            "schema_version": case_set.schema_version,
            "version": case_set.benchmark_version,
            "description": case_set.description,
            "cases_file": _display_path(case_set.source_path),
            "cases_sha256": case_set.sha256,
            "cases": list(case_set.cases),
        },
        "environment": {
            "python_version": platform.python_version(),
            "platform": platform.platform(),
        },
        "ollama": {
            "base_url": _redact_url_credentials(
                getattr(client, "base_url", "")
            ),
            "version": ollama_version,
            "version_error": version_error,
            "requested_model": model.strip(),
        },
        "settings": {
            **benchmark_settings.to_dict(),
            "repeats": repeats,
            "warmup_enabled": warmup_enabled,
            "stream": False,
        },
        "warmup": warmup,
        "results": results,
        "summary": summary,
    }


def write_report(
    report: Mapping[str, Any],
    output_dir: Path,
) -> Path:
    """Write one report without overwriting an existing artifact."""
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_run_id = str(report.get("run_id") or "benchmark")
    safe_run_id = (
        re.sub(r"[^A-Za-z0-9._-]+", "_", raw_run_id).strip("._-")
        or "benchmark"
    )
    report_path = output_dir / f"{safe_run_id}.json"
    serialized = json.dumps(report, indent=2, ensure_ascii=False) + "\n"

    with report_path.open("x", encoding="utf-8") as handle:
        handle.write(serialized)
    return report_path


def _run_warmup(
    *,
    client: OllamaBenchmarkClient,
    model: str,
    settings: BenchmarkSettings,
    enabled: bool,
    now: Callable[[], datetime],
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "enabled": enabled,
        "included_in_measurements": False,
        "trial": None,
    }
    if not enabled:
        return result

    warmup_options = {
        **settings.request_options(),
        "num_predict": min(settings.num_predict, WARMUP_MAX_TOKENS),
    }
    trial: dict[str, Any] = {
        "case_id": "warmup",
        "timestamp_utc": _iso_utc(_as_utc(now())),
        "request": {
            "model": model,
            "prompt": WARMUP_PROMPT,
            "options": warmup_options,
            "stream": False,
        },
        "response": None,
        "metrics": empty_generation_metrics(),
        "completion": {
            "ok": False,
            "failure_reasons": [],
        },
        "error": None,
    }

    try:
        generated = client.generate(
            WARMUP_PROMPT,
            model=model,
            options=warmup_options,
        )
    except BenchmarkClientError as exc:
        trial["error"] = {
            "type": type(exc).__name__,
            "message": str(exc),
        }
        trial["completion"]["failure_reasons"] = [
            f"request_error: {exc}"
        ]
        result["trial"] = trial
        return result

    _populate_generation(trial, generated)
    completion_reasons = completion_failure_reasons(
        generated.metrics,
        warmup_options["num_predict"],
    )
    trial["completion"] = {
        "ok": not completion_reasons,
        "failure_reasons": completion_reasons,
    }
    result["trial"] = trial
    return result


def _run_trial(
    *,
    client: OllamaBenchmarkClient,
    case: Mapping[str, Any],
    model: str,
    settings: BenchmarkSettings,
    now: Callable[[], datetime],
) -> dict[str, Any]:
    request_options = settings.request_options()
    trial: dict[str, Any] = {
        "case_id": case["id"],
        "timestamp_utc": _iso_utc(_as_utc(now())),
        "request": {
            "model": model,
            "prompt": case["prompt"],
            "options": request_options,
            "stream": False,
        },
        "response": None,
        "metrics": empty_generation_metrics(),
        "completion": {
            "ok": False,
            "failure_reasons": [],
        },
        "scoring": {
            "score": 0.0,
            "passed": False,
            "checks": [],
            "failure_reasons": [],
            "manual_review_required": bool(
                case["evaluation"].get("manual_review_required", True)
            ),
            "manual_review_note": _manual_review_note(case),
        },
        "passed": False,
        "failure_reasons": [],
        "error": None,
    }

    try:
        generated = client.generate(
            case["prompt"],
            model=model,
            options=request_options,
        )
    except BenchmarkClientError as exc:
        reasons = [f"request_error: {exc}"]
        trial["error"] = {
            "type": type(exc).__name__,
            "message": str(exc),
        }
        trial["completion"]["failure_reasons"] = reasons
        trial["scoring"]["failure_reasons"] = reasons
        trial["failure_reasons"] = reasons
        return trial

    _populate_generation(trial, generated)
    completion_reasons = completion_failure_reasons(
        generated.metrics,
        settings.num_predict,
    )
    trial["completion"] = {
        "ok": not completion_reasons,
        "failure_reasons": completion_reasons,
    }

    if completion_reasons:
        trial["scoring"] = {
            "score": 0.0,
            "passed": False,
            "checks": [
                {
                    "name": "completed_response",
                    "passed": False,
                    "detail": "; ".join(completion_reasons),
                }
            ],
            "failure_reasons": completion_reasons,
            "manual_review_required": bool(
                case["evaluation"].get("manual_review_required", True)
            ),
            "manual_review_note": _manual_review_note(case),
        }
        trial["failure_reasons"] = completion_reasons
        return trial

    evaluation = evaluate_case(case, generated.response)
    trial["scoring"] = evaluation.to_dict()
    trial["passed"] = evaluation.passed
    trial["failure_reasons"] = list(evaluation.failure_reasons)
    return trial


def _populate_generation(
    trial: dict[str, Any],
    generated: GenerationResult,
) -> None:
    trial["response"] = {
        "model": generated.model,
        "text": generated.response,
    }
    trial["metrics"] = dict(generated.metrics)


def _summarize_trials(
    trials: list[dict[str, Any]],
) -> dict[str, Any]:
    measured = len(trials)
    passed = sum(1 for trial in trials if trial["passed"])
    errors = sum(1 for trial in trials if trial["error"] is not None)
    completed = sum(
        1 for trial in trials if trial["completion"]["ok"]
    )
    incomplete = sum(
        1
        for trial in trials
        if not trial["completion"]["ok"] and trial["error"] is None
    )

    return {
        "measured_trials": measured,
        "passed": passed,
        "failed": measured - passed,
        "pass_rate": round(passed / measured, 4) if measured else 0.0,
        "completed": completed,
        "incomplete": incomplete,
        "errors": errors,
        "median_total_duration_ms": _median_metric(
            trials,
            "total_duration_ms",
        ),
        "median_load_duration_ms": _median_metric(
            trials,
            "load_duration_ms",
        ),
        "median_prompt_eval_duration_ms": _median_metric(
            trials,
            "prompt_eval_duration_ms",
        ),
        "median_eval_duration_ms": _median_metric(
            trials,
            "eval_duration_ms",
        ),
        "total_prompt_eval_count": _total_count(
            trials,
            "prompt_eval_count",
        ),
        "total_eval_count": _total_count(trials, "eval_count"),
    }


def _median_metric(
    trials: list[dict[str, Any]],
    metric_name: str,
) -> float | None:
    values: list[float] = []
    for trial in trials:
        value = trial.get("metrics", {}).get(metric_name)
        if (
            not isinstance(value, bool)
            and isinstance(value, (int, float))
            and math.isfinite(value)
        ):
            values.append(float(value))
    if not values:
        return None
    return round(statistics.median(values), 3)


def _total_count(
    trials: list[dict[str, Any]],
    metric_name: str,
) -> int:
    total = 0
    for trial in trials:
        value = trial.get("metrics", {}).get(metric_name)
        if isinstance(value, int) and not isinstance(value, bool):
            total += value
    return total


def _manual_review_note(
    case: Mapping[str, Any],
) -> str | None:
    note = case["evaluation"].get("manual_review_note")
    return note if isinstance(note, str) else None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso_utc(value: datetime) -> str:
    return (
        _as_utc(value)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _new_run_id(started_at: datetime) -> str:
    timestamp = started_at.strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-{uuid.uuid4().hex[:8]}"


def _display_path(path: Path) -> str:
    try:
        return path.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _redact_url_credentials(url: object) -> str | None:
    if not isinstance(url, str) or not url:
        return None
    parts = urlsplit(url)
    if parts.username is None and parts.password is None:
        return url
    host = parts.hostname or ""
    if parts.port is not None:
        host = f"{host}:{parts.port}"
    return urlunsplit(
        (parts.scheme, host, parts.path, parts.query, parts.fragment)
    )
