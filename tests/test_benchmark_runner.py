import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from nexus_ai.benchmark.cases import BenchmarkCaseSet, load_cases
from nexus_ai.benchmark.client import (
    BenchmarkResponseError,
    BenchmarkUnavailableError,
    GenerationResult,
)
from nexus_ai.benchmark.runner import (
    WARMUP_PROMPT,
    BenchmarkSettings,
    run_benchmark,
    write_report,
)


CASES_PATH = (
    Path(__file__).resolve().parents[1] / "benchmarks" / "cases.json"
)
FIXED_NOW = datetime(2026, 10, 21, 12, 0, 0, tzinfo=timezone.utc)


VALID_RESPONSES = {
    "rest_api_explanation": (
        "REST API stands for Representational State Transfer Application "
        "Programming Interface. It is an architectural style for networked "
        "applications that uses HTTP methods to interact with resources. "
        "REST is stateless and separates the client from the server."
    ),
    "structured_json": '{"status": "ok", "model": "llama3.2"}',
    "http_status_bullets": (
        "- HTTP 200 means the request succeeded.\n"
        "- HTTP 404 means the requested resource was not found.\n"
        "- HTTP 500 means the server encountered an internal error."
    ),
}


def make_metrics(
    *,
    total_duration_ms=1000.0,
    load_duration_ms=100.0,
    prompt_eval_duration_ms=50.0,
    eval_duration_ms=800.0,
    prompt_eval_count=10,
    eval_count=20,
    done=True,
    done_reason="stop",
):
    return {
        "total_duration_ms": total_duration_ms,
        "load_duration_ms": load_duration_ms,
        "prompt_eval_duration_ms": prompt_eval_duration_ms,
        "eval_duration_ms": eval_duration_ms,
        "prompt_eval_count": prompt_eval_count,
        "eval_count": eval_count,
        "done": done,
        "done_reason": done_reason,
    }


def make_result(
    text,
    *,
    total_duration_ms=1000.0,
    done=True,
    done_reason="stop",
    eval_count=20,
):
    return GenerationResult(
        model="llama3.2:latest",
        response=text,
        metrics=make_metrics(
            total_duration_ms=total_duration_ms,
            done=done,
            done_reason=done_reason,
            eval_count=eval_count,
        ),
    )


class FakeBenchmarkClient:
    base_url = "http://benchuser:benchpass@127.0.0.1:11434"

    def __init__(
        self,
        responder,
        *,
        version="0.40.5",
        version_error=None,
    ) -> None:
        self.responder = responder
        self.version = version
        self.version_error = version_error
        self.calls = []

    def get_version(self):
        if self.version_error is not None:
            raise self.version_error
        return self.version

    def generate(self, prompt, *, model, options):
        call_index = len(self.calls)
        self.calls.append(
            {
                "prompt": prompt,
                "model": model,
                "options": dict(options),
            }
        )
        return self.responder(prompt, options, call_index)


def subset_case_set(
    full_case_set: BenchmarkCaseSet,
    case_ids: set[str],
) -> BenchmarkCaseSet:
    return BenchmarkCaseSet(
        schema_version=full_case_set.schema_version,
        benchmark_version=full_case_set.benchmark_version,
        description=full_case_set.description,
        cases=tuple(
            case
            for case in full_case_set.cases
            if case["id"] in case_ids
        ),
        source_path=full_case_set.source_path,
        sha256=full_case_set.sha256,
    )


@pytest.fixture(scope="module")
def case_set():
    return load_cases(CASES_PATH)


def test_run_benchmark_records_warmup_measurements_and_summary(
    case_set,
) -> None:
    prompt_to_case = {
        case["prompt"]: case for case in case_set.cases
    }

    def responder(prompt, options, call_index):
        if prompt == WARMUP_PROMPT:
            return make_result(
                "ready",
                total_duration_ms=500.0,
                eval_count=1,
            )
        case = prompt_to_case[prompt]
        return make_result(
            VALID_RESPONSES[case["id"]],
            total_duration_ms=2000.0 + call_index * 100,
            eval_count=20,
        )

    client = FakeBenchmarkClient(responder)
    settings = BenchmarkSettings(
        temperature=0.0,
        num_predict=256,
        seed=42,
        timeout_seconds=30.0,
    )

    report = run_benchmark(
        client=client,
        case_set=case_set,
        model="llama3.2:latest",
        repeats=2,
        settings=settings,
        run_id="test-run",
        now=lambda: FIXED_NOW,
    )

    assert report["run_id"] == "test-run"
    assert report["started_at_utc"] == "2026-10-21T12:00:00.000Z"
    assert report["finished_at_utc"] == "2026-10-21T12:00:00.000Z"
    assert report["benchmark"]["version"] == "1.0.1"
    assert report["benchmark"]["cases_sha256"]
    assert len(report["benchmark"]["cases"]) == 3
    assert report["ollama"]["version"] == "0.40.5"
    assert report["ollama"]["requested_model"] == "llama3.2:latest"
    assert "benchuser" not in report["ollama"]["base_url"]
    assert "benchpass" not in report["ollama"]["base_url"]
    assert report["settings"] == {
        "temperature": 0.0,
        "num_predict": 256,
        "seed": 42,
        "timeout_seconds": 30.0,
        "repeats": 2,
        "warmup_enabled": True,
        "stream": False,
    }

    warmup_trial = report["warmup"]["trial"]
    assert report["warmup"]["included_in_measurements"] is False
    assert warmup_trial["completion"]["ok"] is True
    assert warmup_trial["metrics"]["total_duration_ms"] == 500.0
    assert warmup_trial["request"]["options"]["num_predict"] == 16

    assert len(client.calls) == 7
    assert client.calls[0]["prompt"] == WARMUP_PROMPT
    assert client.calls[1]["options"] == {
        "temperature": 0.0,
        "num_predict": 256,
        "seed": 42,
    }

    assert report["summary"]["measured_trials"] == 6
    assert report["summary"]["passed"] == 6
    assert report["summary"]["failed"] == 0
    assert report["summary"]["completed"] == 6
    assert report["summary"]["incomplete"] == 0
    assert report["summary"]["errors"] == 0
    assert report["summary"]["all_passed"] is True
    assert report["summary"]["median_total_duration_ms"] == 2350.0
    assert report["summary"]["total_prompt_eval_count"] == 60
    assert report["summary"]["total_eval_count"] == 120

    case_medians = {
        result["case_id"]: result["summary"]["median_total_duration_ms"]
        for result in report["results"]
    }
    assert case_medians == {
        "rest_api_explanation": 2150.0,
        "structured_json": 2350.0,
        "http_status_bullets": 2550.0,
    }

    results_by_id = {
        result["case_id"]: result for result in report["results"]
    }
    assert (
        results_by_id["rest_api_explanation"]["manual_review_required"]
        is True
    )
    assert (
        results_by_id["structured_json"]["manual_review_required"]
        is False
    )
    for result in report["results"]:
        for trial in result["trials"]:
            assert trial["completion"]["ok"] is True
            assert trial["passed"] is True
            assert trial["error"] is None
            assert trial["scoring"]["score"] == 1.0


def test_write_report_serializes_and_does_not_overwrite(
    case_set,
    tmp_path,
) -> None:
    def responder(prompt, options, call_index):
        if prompt == WARMUP_PROMPT:
            return make_result("ready")
        case = next(
            case for case in case_set.cases if case["prompt"] == prompt
        )
        return make_result(VALID_RESPONSES[case["id"]])

    report = run_benchmark(
        client=FakeBenchmarkClient(responder),
        case_set=case_set,
        model="llama3.2:latest",
        repeats=1,
        run_id="serialize-run",
        now=lambda: FIXED_NOW,
    )

    report_path = write_report(report, tmp_path)

    assert report_path.name == "serialize-run.json"
    loaded = json.loads(report_path.read_text(encoding="utf-8"))
    assert loaded == report

    with pytest.raises(FileExistsError):
        write_report(report, tmp_path)


@pytest.mark.parametrize(
    ("done", "done_reason", "eval_count", "expected_fragment"),
    [
        (False, None, 10, "did not complete"),
        (True, "length", 256, "num_predict"),
    ],
)
def test_incomplete_generation_cannot_pass(
    case_set,
    done,
    done_reason,
    eval_count,
    expected_fragment,
) -> None:
    single_case = subset_case_set(case_set, {"structured_json"})

    def responder(prompt, options, call_index):
        if prompt == WARMUP_PROMPT:
            return make_result("ready")
        return make_result(
            '{"status": "ok", "model": "llama3.2"}',
            done=done,
            done_reason=done_reason,
            eval_count=eval_count,
        )

    report = run_benchmark(
        client=FakeBenchmarkClient(responder),
        case_set=single_case,
        model="llama3.2:latest",
        repeats=1,
        settings=BenchmarkSettings(num_predict=256),
        run_id="incomplete-run",
        now=lambda: FIXED_NOW,
    )

    trial = report["results"][0]["trials"][0]
    assert trial["completion"]["ok"] is False
    assert trial["passed"] is False
    assert trial["scoring"]["score"] == 0.0
    assert trial["scoring"]["passed"] is False
    assert any(
        expected_fragment in reason
        for reason in trial["failure_reasons"]
    )
    assert report["summary"]["passed"] == 0
    assert report["summary"]["incomplete"] == 1
    assert report["summary"]["all_passed"] is False


def test_service_and_version_errors_are_recorded(case_set) -> None:
    single_case = subset_case_set(case_set, {"structured_json"})

    def responder(prompt, options, call_index):
        if prompt == WARMUP_PROMPT:
            return make_result("ready")
        raise BenchmarkUnavailableError("Ollama service is unavailable.")

    client = FakeBenchmarkClient(
        responder,
        version_error=BenchmarkResponseError(
            "Ollama returned an invalid version response."
        ),
    )

    report = run_benchmark(
        client=client,
        case_set=single_case,
        model="llama3.2:latest",
        repeats=1,
        run_id="error-run",
        now=lambda: FIXED_NOW,
    )

    trial = report["results"][0]["trials"][0]
    assert report["ollama"]["version"] is None
    assert "BenchmarkResponseError" in report["ollama"]["version_error"]
    assert trial["passed"] is False
    assert trial["error"] == {
        "type": "BenchmarkUnavailableError",
        "message": "Ollama service is unavailable.",
    }
    assert trial["scoring"]["score"] == 0.0
    assert trial["scoring"]["passed"] is False
    assert any(
        "request_error" in reason
        for reason in trial["failure_reasons"]
    )
    assert report["summary"]["errors"] == 1
    assert report["summary"]["incomplete"] == 0
    assert report["summary"]["all_passed"] is False
    json.dumps(report)


def test_warmup_error_is_kept_separate_from_measured_trials(
    case_set,
) -> None:
    single_case = subset_case_set(case_set, {"structured_json"})

    def responder(prompt, options, call_index):
        if prompt == WARMUP_PROMPT:
            raise BenchmarkUnavailableError("Ollama service is unavailable.")
        return make_result('{"status": "ok", "model": "llama3.2"}')

    report = run_benchmark(
        client=FakeBenchmarkClient(responder),
        case_set=single_case,
        model="llama3.2:latest",
        repeats=1,
        run_id="warmup-error-run",
        now=lambda: FIXED_NOW,
    )

    assert report["warmup"]["trial"]["error"]["type"] == (
        "BenchmarkUnavailableError"
    )
    assert report["warmup"]["included_in_measurements"] is False
    assert report["results"][0]["trials"][0]["passed"] is True
    assert report["summary"]["passed"] == 1
    assert report["summary"]["errors"] == 0


def test_benchmark_settings_reject_invalid_values() -> None:
    with pytest.raises(ValueError):
        BenchmarkSettings(temperature=-1)
    with pytest.raises(ValueError):
        BenchmarkSettings(num_predict=0)
    with pytest.raises(ValueError):
        BenchmarkSettings(timeout_seconds=0)


def test_run_benchmark_rejects_invalid_repeats(case_set) -> None:
    with pytest.raises(ValueError):
        run_benchmark(
            client=FakeBenchmarkClient(
                lambda prompt, options, index: make_result("ready")
            ),
            case_set=case_set,
            model="llama3.2:latest",
            repeats=0,
            now=lambda: FIXED_NOW,
        )
