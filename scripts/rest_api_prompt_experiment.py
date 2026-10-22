"""Controlled prompt experiment for the rest_api_explanation benchmark case."""

from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from nexus_ai.benchmark.cases import BenchmarkCaseError, load_cases
from nexus_ai.benchmark.client import (
    BenchmarkClientError,
    OllamaBenchmarkClient,
)
from nexus_ai.benchmark.metrics import completion_failure_reasons
from nexus_ai.benchmark.runner import (
    BenchmarkSettings,
    WARMUP_MAX_TOKENS,
    WARMUP_PROMPT,
)
from nexus_ai.benchmark.scoring import evaluate_case
from nexus_ai.ollama import DEFAULT_OLLAMA_BASE_URL


DEFAULT_MODEL = "llama3.2:latest"
DEFAULT_CASES_PATH = PROJECT_ROOT / "benchmarks" / "cases.json"
DEFAULT_PROMPT_PATH = (
    PROJECT_ROOT / "benchmarks" / "experiments" / "rest_api_improved_prompt.json"
)
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "local_data" / "llm_benchmarks"
DEFAULT_CASE_ID = "rest_api_explanation"
EXPERIMENT_TAG = "rest-api-prompt-experiment"

REST_EXPANSION = re.compile(r"representational\s+state\s+transfer", re.IGNORECASE)
API_EXPANSION = re.compile(r"application\s+programming\s+interface", re.IGNORECASE)
REST_INCORRECT = re.compile(
    r"representational\s+state\s+of\s+resource",
    re.IGNORECASE,
)
SENTENCE_BOUNDARY = re.compile(r"[.!?]+(?=\s|$)")
TARGET_SENTENCE_COUNT = 4


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Compare the original rest_api_explanation prompt with a clearer "
            "experimental prompt using identical generation settings."
        )
    )
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--prompt-file", type=Path, default=DEFAULT_PROMPT_PATH)
    parser.add_argument("--case-id", default=DEFAULT_CASE_ID)
    parser.add_argument(
        "--experiment-id",
        default="rest_api_prompt_clarity_v1",
        help="Experiment identifier recorded in the report.",
    )
    parser.add_argument(
        "--conditions",
        nargs="+",
        choices=("original", "experimental"),
        default=("original", "experimental"),
        help="Prompt conditions to measure (default: both).",
    )
    parser.add_argument("--base-url", default=DEFAULT_OLLAMA_BASE_URL)
    parser.add_argument("--repeats", type=_positive_int, default=2)
    parser.add_argument("--temperature", type=_non_negative_float, default=0.0)
    parser.add_argument("--num-predict", type=_positive_int, default=256)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--timeout", type=_positive_float, default=120.0)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--run-id", default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        case_set = load_cases(args.cases)
        original_case = _find_case(case_set.cases, args.case_id)
        experimental_prompt = _load_experimental_prompt(args.prompt_file)
        settings = BenchmarkSettings(
            temperature=args.temperature,
            num_predict=args.num_predict,
            seed=args.seed,
            timeout_seconds=args.timeout,
        )
    except (BenchmarkCaseError, ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"Experiment configuration error: {exc}", file=sys.stderr)
        return 2

    client = OllamaBenchmarkClient(
        base_url=args.base_url,
        timeout_seconds=settings.timeout_seconds,
    )
    started_at = _utc_now()
    run_id = args.run_id or (
        f"{started_at.strftime('%Y%m%dT%H%M%SZ')}-"
        f"{uuid.uuid4().hex[:8]}-{EXPERIMENT_TAG}"
    )

    ollama_version: str | None = None
    version_error: str | None = None
    try:
        ollama_version = client.get_version()
    except BenchmarkClientError as exc:
        version_error = f"{type(exc).__name__}: {exc}"

    warmup = _run_warmup(client, args.model, settings)
    prompt_by_condition = {
        "original": original_case["prompt"],
        "experimental": experimental_prompt,
    }
    conditions = [
        (condition, prompt_by_condition[condition])
        for condition in dict.fromkeys(args.conditions)
    ]
    trials: list[dict[str, Any]] = []
    counters = {condition: 0 for condition, _ in conditions}
    for round_number in range(1, args.repeats + 1):
        for prompt_version, prompt in conditions:
            counters[prompt_version] += 1
            trials.append(
                _run_trial(
                    client=client,
                    model=args.model,
                    prompt_version=prompt_version,
                    prompt=prompt,
                    trial_number=counters[prompt_version],
                    round_number=round_number,
                    settings=settings,
                    original_case=original_case,
                )
            )

    finished_at = _utc_now()
    report = {
        "schema_version": 1,
        "experiment_id": args.experiment_id,
        "run_id": run_id,
        "started_at_utc": _iso_utc(started_at),
        "finished_at_utc": _iso_utc(finished_at),
        "purpose": (
            "Diagnose the original rest_api_explanation failures and test "
            "whether a clearer prompt mitigates them without changing the "
            "original benchmark case or scoring rules."
        ),
        "benchmark_reference": {
            "cases_file": _display_path(case_set.source_path),
            "cases_sha256": case_set.sha256,
            "benchmark_version": case_set.benchmark_version,
            "case": original_case,
            "evaluation_unchanged": True,
        },
        "experimental_input": {
            "prompt_file": _display_path(args.prompt_file),
            "prompt": experimental_prompt,
            "replaces_original_case": False,
        },
        "ollama": {
            "base_url": args.base_url,
            "version": ollama_version,
            "version_error": version_error,
            "requested_model": args.model,
        },
        "settings": {
            **settings.to_dict(),
            "repeats_per_prompt": args.repeats,
            "conditions": [condition for condition, _ in conditions],
            "stream": False,
        },
        "warmup": warmup,
        "trials": trials,
        "summary": _summarize(
            trials,
            args.repeats,
            [condition for condition, _ in conditions],
        ),
        "manual_review": {
            "required": True,
            "note": (
                "Automated factual flags verify only the two acronym "
                "expansions. A human must still review completeness, "
                "clarity, and technical accuracy. Two trials per prompt do "
                "not establish general model reliability."
            ),
        },
    }

    try:
        report_path = _write_report(report, args.output_dir)
    except OSError as exc:
        print(f"Could not write experiment report: {exc}", file=sys.stderr)
        return 2

    _print_summary(report, report_path)
    return 0


def _find_case(cases: tuple[dict[str, Any], ...], case_id: str) -> dict[str, Any]:
    for case in cases:
        if case["id"] == case_id:
            return case
    raise ValueError(f"Benchmark case {case_id!r} was not found.")


def _load_experimental_prompt(path: Path) -> str:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("Experimental prompt file must contain a JSON object.")
    prompt = document.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("Experimental prompt file must contain a non-empty prompt.")
    return prompt


def _run_warmup(
    client: OllamaBenchmarkClient,
    model: str,
    settings: BenchmarkSettings,
) -> dict[str, Any]:
    options = {
        **settings.request_options(),
        "num_predict": min(settings.num_predict, WARMUP_MAX_TOKENS),
    }
    trial: dict[str, Any] = {
        "enabled": True,
        "included_in_measurements": False,
        "timestamp_utc": _iso_utc(_utc_now()),
        "request": {
            "model": model,
            "prompt": WARMUP_PROMPT,
            "options": options,
            "stream": False,
        },
        "response": None,
        "metrics": None,
        "completion": {"ok": False, "failure_reasons": []},
        "error": None,
    }
    try:
        generated = client.generate(WARMUP_PROMPT, model=model, options=options)
    except BenchmarkClientError as exc:
        trial["error"] = {"type": type(exc).__name__, "message": str(exc)}
        trial["completion"]["failure_reasons"] = [f"request_error: {exc}"]
        return trial

    trial["response"] = {"model": generated.model, "text": generated.response}
    trial["metrics"] = dict(generated.metrics)
    reasons = completion_failure_reasons(generated.metrics, options["num_predict"])
    trial["completion"] = {"ok": not reasons, "failure_reasons": reasons}
    return trial


def _run_trial(
    *,
    client: OllamaBenchmarkClient,
    model: str,
    prompt_version: str,
    prompt: str,
    trial_number: int,
    round_number: int,
    settings: BenchmarkSettings,
    original_case: dict[str, Any],
) -> dict[str, Any]:
    options = settings.request_options()
    trial: dict[str, Any] = {
        "prompt_version": prompt_version,
        "trial_number": trial_number,
        "round_number": round_number,
        "timestamp_utc": _iso_utc(_utc_now()),
        "request": {
            "model": model,
            "prompt": prompt,
            "options": options,
            "stream": False,
        },
        "response": None,
        "metrics": None,
        "completion": {"ok": False, "failure_reasons": []},
        "original_evaluator": None,
        "factual_check": None,
        "error": None,
    }

    try:
        generated = client.generate(prompt, model=model, options=options)
    except BenchmarkClientError as exc:
        reasons = [f"request_error: {exc}"]
        trial["error"] = {"type": type(exc).__name__, "message": str(exc)}
        trial["completion"]["failure_reasons"] = reasons
        trial["original_evaluator"] = {
            "passed": False,
            "score": 0.0,
            "failure_reasons": reasons,
            "skipped_due_to_request_error": True,
        }
        return trial

    trial["response"] = {"model": generated.model, "text": generated.response}
    trial["metrics"] = dict(generated.metrics)
    completion_reasons = completion_failure_reasons(
        generated.metrics,
        settings.num_predict,
    )
    trial["completion"] = {
        "ok": not completion_reasons,
        "failure_reasons": completion_reasons,
    }
    trial["factual_check"] = _factual_check(generated.response)

    if completion_reasons:
        trial["original_evaluator"] = {
            "passed": False,
            "score": 0.0,
            "failure_reasons": completion_reasons,
            "skipped_due_to_incomplete_response": True,
        }
        return trial

    evaluation = evaluate_case(original_case, generated.response)
    trial["original_evaluator"] = evaluation.to_dict()
    return trial


def _factual_check(text: str) -> dict[str, Any]:
    sentence_count = _count_sentences(text)
    rest_correct = REST_EXPANSION.search(text) is not None
    api_correct = API_EXPANSION.search(text) is not None
    return {
        "rest_expansion_correct": rest_correct,
        "api_expansion_correct": api_correct,
        "both_expansions_correct": rest_correct and api_correct,
        "incorrect_rest_expansion_detected": REST_INCORRECT.search(text) is not None,
        "sentence_count": sentence_count,
        "target_sentence_count": TARGET_SENTENCE_COUNT,
        "exactly_four_sentences": sentence_count == TARGET_SENTENCE_COUNT,
        "sentence_count_method": (
            "Counted terminal punctuation (. ! ?) followed by whitespace or "
            "end of text; abbreviations are not specially handled."
        ),
        "scope_note": (
            "These flags check only the two acronym expansions and sentence "
            "count; they are not a complete factual review."
        ),
    }


def _count_sentences(text: str) -> int:
    return len(SENTENCE_BOUNDARY.findall(text.strip()))


def _summarize(
    trials: list[dict[str, Any]],
    repeats: int,
    conditions: list[str],
) -> dict[str, Any]:
    by_prompt: dict[str, Any] = {}
    for prompt_version in conditions:
        subset = [t for t in trials if t["prompt_version"] == prompt_version]
        by_prompt[prompt_version] = {
            "measured_trials": len(subset),
            "passed": sum(
                1
                for t in subset
                if (t["original_evaluator"] or {}).get("passed") is True
            ),
            "completed": sum(1 for t in subset if t["completion"]["ok"]),
            "errors": sum(1 for t in subset if t["error"] is not None),
            "factually_correct_expansions": sum(
                1
                for t in subset
                if (t["factual_check"] or {}).get("both_expansions_correct")
            ),
            "exactly_four_sentences": sum(
                1
                for t in subset
                if (t["factual_check"] or {}).get("exactly_four_sentences")
            ),
            "sentence_counts": [
                (t.get("factual_check") or {}).get("sentence_count")
                for t in subset
            ],
            "median_total_duration_ms": _median_metric(subset, "total_duration_ms"),
            "median_load_duration_ms": _median_metric(subset, "load_duration_ms"),
            "median_eval_duration_ms": _median_metric(subset, "eval_duration_ms"),
            "eval_counts": [
                (t.get("metrics") or {}).get("eval_count") for t in subset
            ],
        }
    return {
        "repeats_per_prompt": repeats,
        "by_prompt": by_prompt,
        "comparison_complete": len(conditions) > 1
        and all(
            by_prompt[name]["measured_trials"] == repeats
            for name in conditions
        ),
    }


def _median_metric(trials: list[dict[str, Any]], metric_name: str) -> float | None:
    values: list[float] = []
    for trial in trials:
        value = (trial.get("metrics") or {}).get(metric_name)
        if (
            not isinstance(value, bool)
            and isinstance(value, (int, float))
            and math.isfinite(value)
        ):
            values.append(float(value))
    if not values:
        return None
    return round(statistics.median(values), 3)


def _write_report(report: dict[str, Any], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_run_id = (
        re.sub(r"[^A-Za-z0-9._-]+", "_", report["run_id"]).strip("._-")
        or EXPERIMENT_TAG
    )
    path = output_dir / f"{safe_run_id}.json"
    serialized = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    with path.open("x", encoding="utf-8") as handle:
        handle.write(serialized)
    return path


def _print_summary(report: dict[str, Any], report_path: Path) -> None:
    print(f"Run ID: {report['run_id']}")
    print(
        f"Model: {report['ollama']['requested_model']} | "
        f"Ollama version: {report['ollama']['version'] or 'unavailable'}"
    )
    settings = report["settings"]
    print(
        "Settings: "
        f"temperature={settings['temperature']} "
        f"num_predict={settings['num_predict']} "
        f"seed={settings['seed']} "
        f"repeats_per_prompt={settings['repeats_per_prompt']}"
    )
    warmup = report["warmup"]
    warmup_total = (warmup.get("metrics") or {}).get("total_duration_ms")
    print(
        "Warm-up: "
        f"{'complete' if warmup['completion']['ok'] else 'incomplete'} | "
        f"total={warmup_total} ms | excluded from measurements"
    )
    for name, summary in report["summary"]["by_prompt"].items():
        print(
            f"- {name}: passed={summary['passed']}/"
            f"{summary['measured_trials']} | "
            f"completed={summary['completed']} | "
            f"correct_expansions={summary['factually_correct_expansions']} | "
            f"exactly_four_sentences={summary['exactly_four_sentences']} | "
            f"median_total={summary['median_total_duration_ms']} ms"
        )
    print(f"Report: {report_path}")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def _display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def _positive_float(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a number") from exc
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive finite number")
    return parsed


def _non_negative_float(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a number") from exc
    if not math.isfinite(parsed) or parsed < 0:
        raise argparse.ArgumentTypeError("must be a non-negative finite number")
    return parsed


if __name__ == "__main__":
    raise SystemExit(main())
