"""Run the reproducible local Ollama benchmark and save a JSON report."""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from nexus_ai.benchmark.cases import (
    BenchmarkCaseError,
    load_cases,
)
from nexus_ai.benchmark.client import (
    DEFAULT_BENCHMARK_TIMEOUT_SECONDS,
    OllamaBenchmarkClient,
)
from nexus_ai.benchmark.runner import (
    BenchmarkSettings,
    run_benchmark,
    write_report,
)


DEFAULT_MODEL = "llama3.2:latest"
DEFAULT_REPEATS = 2
DEFAULT_NUM_PREDICT = 256
DEFAULT_SEED = 42
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "local_data" / "llm_benchmarks"
DEFAULT_CASES_PATH = PROJECT_ROOT / "benchmarks" / "cases.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run deterministic benchmark cases against a local Ollama model."
        )
    )
    parser.add_argument(
        "--cases",
        type=Path,
        default=DEFAULT_CASES_PATH,
        help="Path to the benchmark cases JSON file.",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Ollama model name (default: {DEFAULT_MODEL}).",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help=(
            "Ollama base URL. Defaults to OLLAMA_BASE_URL or "
            "http://127.0.0.1:11434."
        ),
    )
    parser.add_argument(
        "--repeats",
        type=_positive_int,
        default=DEFAULT_REPEATS,
        help=f"Measured repeats per case (default: {DEFAULT_REPEATS}).",
    )
    parser.add_argument(
        "--temperature",
        type=_non_negative_float,
        default=0.0,
        help="Sampling temperature (default: 0.0).",
    )
    parser.add_argument(
        "--num-predict",
        type=_positive_int,
        default=DEFAULT_NUM_PREDICT,
        help=f"Maximum generated tokens (default: {DEFAULT_NUM_PREDICT}).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SEED,
        help=f"Generation seed (default: {DEFAULT_SEED}).",
    )
    parser.add_argument(
        "--timeout",
        type=_positive_float,
        default=DEFAULT_BENCHMARK_TIMEOUT_SECONDS,
        help=(
            "Per-request timeout in seconds "
            f"(default: {DEFAULT_BENCHMARK_TIMEOUT_SECONDS:.0f})."
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Local report directory (default: local_data/llm_benchmarks).",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="Optional explicit run identifier; defaults to a timestamped ID.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        case_set = load_cases(args.cases)
        settings = BenchmarkSettings(
            temperature=args.temperature,
            num_predict=args.num_predict,
            seed=args.seed,
            timeout_seconds=args.timeout,
        )
    except (BenchmarkCaseError, ValueError) as exc:
        print(f"Benchmark configuration error: {exc}", file=sys.stderr)
        return 2

    client = OllamaBenchmarkClient(
        base_url=args.base_url,
        timeout_seconds=settings.timeout_seconds,
    )
    report = run_benchmark(
        client=client,
        case_set=case_set,
        model=args.model,
        repeats=args.repeats,
        settings=settings,
        run_id=args.run_id,
    )

    try:
        report_path = write_report(report, args.output_dir)
    except OSError as exc:
        print(f"Could not write benchmark report: {exc}", file=sys.stderr)
        return 2

    _print_summary(report, report_path)
    return 0 if report["summary"]["all_passed"] else 1


def _print_summary(
    report: dict[str, Any],
    report_path: Path,
) -> None:
    ollama = report["ollama"]
    settings = report["settings"]
    summary = report["summary"]
    version = ollama["version"] or "unavailable"

    print(f"Run ID: {report['run_id']}")
    print(
        f"Model: {ollama['requested_model']} | Ollama version: {version}"
    )
    print(
        "Settings: "
        f"repeats={settings['repeats']} "
        f"temperature={settings['temperature']} "
        f"num_predict={settings['num_predict']} "
        f"seed={settings['seed']}"
    )

    warmup_trial = report["warmup"]["trial"]
    if warmup_trial is None:
        print("Warm-up: disabled (results are not steady-state)")
    else:
        total_ms = warmup_trial["metrics"].get("total_duration_ms")
        total_text = (
            f"{total_ms:.3f} ms" if isinstance(total_ms, (int, float)) else "n/a"
        )
        state = "complete" if warmup_trial["completion"]["ok"] else "incomplete"
        error = warmup_trial["error"]
        if error is not None:
            state = f"error: {error['type']}"
        print(
            f"Warm-up: {state} | total={total_text} "
            "(excluded from measured results)"
        )

    print("Cases:")
    for result in report["results"]:
        case_summary = result["summary"]
        measured = case_summary["measured_trials"]
        median_ms = case_summary["median_total_duration_ms"]
        median_text = (
            f"{median_ms:.3f} ms"
            if isinstance(median_ms, (int, float))
            else "n/a"
        )
        state = "PASS" if case_summary["passed"] == measured else "FAIL"
        print(
            f"- {result['case_id']}: {state} "
            f"{case_summary['passed']}/{measured} | "
            f"median total={median_text} | "
            f"prompt tokens={case_summary['total_prompt_eval_count']} | "
            f"generated tokens={case_summary['total_eval_count']} | "
            f"completed={case_summary['completed']}/{measured} | "
            f"incomplete={case_summary['incomplete']} | "
            f"errors={case_summary['errors']}"
        )

    overall_state = "PASS" if summary["all_passed"] else "FAIL"
    overall_median = summary["median_total_duration_ms"]
    overall_median_text = (
        f"{overall_median:.3f} ms"
        if isinstance(overall_median, (int, float))
        else "n/a"
    )
    print(
        f"Overall: {overall_state} "
        f"{summary['passed']}/{summary['measured_trials']} | "
        f"median total={overall_median_text} | "
        f"completed={summary['completed']} | "
        f"incomplete={summary['incomplete']} | "
        f"errors={summary['errors']}"
    )
    print(f"Report: {report_path}")


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
        raise argparse.ArgumentTypeError(
            "must be a non-negative finite number"
        )
    return parsed


if __name__ == "__main__":
    raise SystemExit(main())
