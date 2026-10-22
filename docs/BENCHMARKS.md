# Local LLM Benchmarks

This benchmark subsystem measures the locally installed Ollama model
`llama3.2:latest`. It is intentionally small, deterministic, and
reproducible. It does not call cloud APIs or download models.

## Benchmark cases

Case definitions and deterministic evaluation rules live in
`benchmarks/cases.json`. The current cases version is `1.0.1`.

| Case ID | Category | Requirement |
| --- | --- | --- |
| `rest_api_explanation` | Technical accuracy | Expand REST and API and explain the purpose of a REST API in 3-5 sentences. |
| `structured_json` | Structured output | Return exactly one JSON object with exactly `status="ok"` and `model="llama3.2"`. |
| `http_status_bullets` | Instruction following | Return exactly three hyphen bullets in order for HTTP 200, 404, and 500, with no introduction or conclusion. |

### Evaluation rules

- **REST explanation:** the response must have at least 25 words, contain
  both "Representational State Transfer" and "Application Programming
  Interface", and cover at least three of five keyword groups: HTTP,
  resources, statelessness, architecture, and client/server. The automated
  score is the fraction of checks that pass; all checks must pass. A human
  must still review factual accuracy, completeness, and clarity.
- **JSON object:** the entire response must parse as a JSON object with
  exactly two keys (`status` and `model`) and exact string values. Code
  fences, surrounding commentary, extra keys, missing keys, or wrong values
  fail the case. No manual review is required.
- **HTTP bullets:** the response must contain exactly three non-empty lines.
  Every line must start with `- `, line 1 must contain 200, line 2 must
  contain 404, line 3 must contain 500, and each line must have at least four
  explanation words and a required concept (for example "not found" or
  "cannot be found" for 404, or "internal error" for 500). A human should
  confirm technical accuracy.

The numeric score is the fraction of deterministic checks that pass. A case
passes only when every check passes. Manual review requirements are recorded
in each report.

## Measurements

The runner calls the Ollama HTTP API (`/api/generate` and `/api/version`)
directly with:

- `temperature`, `num_predict`, and `seed` sent as Ollama options
- `stream=false`
- an explicit warm-up request before any measured request

Ollama reports durations in nanoseconds. The runner converts them to
milliseconds by dividing by 1,000,000 and records:

- total duration
- model load duration
- prompt evaluation duration
- generation/evaluation duration
- prompt token count and generated token count
- `done` and `done_reason`
- the generated response and its automated checks

Missing or invalid metric fields are recorded as `null` and do not crash the
run. A response is considered incomplete if `done` is not `true`, if Ollama
reports `done_reason="length"`, or if the generated token count reaches
`num_predict`. Incomplete responses receive a score of `0.0` and cannot pass.

The first warm-up request is never included in measured results and must not
be treated as steady-state performance. Warm-up data is stored separately in
the report.

## Reproducibility

Each report records the exact model name, Ollama version when available,
request options, case definitions and version, cases file SHA-256, run ID,
timestamps, environment details, and individual measurements. The default
seed is `42` and the default temperature is `0.0`. Sampling is not guaranteed
to be bit-for-bit deterministic on every backend, so reports describe the
actual measured run rather than an assumed result.

## Observed model behavior and prompt experiments

Historical local runs of `rest_api_explanation` recorded `llama3.2:latest`
expanding REST as "Representational State of Resource" rather than
"Representational State Transfer" in all recorded original-prompt trials.
The deterministic evaluator correctly failed those responses; this is a model
factual error, not a scoring defect. The original case and its criteria remain
unchanged as the baseline.

Diagnostic prompts are kept separate under `benchmarks/experiments/` and are
run with `scripts/rest_api_prompt_experiment.py`. A two-trial experiment with
a four-sentence prompt produced the correct REST and API expansions, exactly
four sentences, and a passing score under the unchanged
`rest_api_explanation` evaluator in both trials. This is limited evidence about
one prompt and one case; it does not establish general technical reliability.
Experimental reports are local artifacts under `local_data/llm_benchmarks/`
and are not committed.

## Run the benchmark (PowerShell)

From the repository root:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
ollama list
python scripts\run_llm_benchmark.py
```

The default run uses one warm-up request and two measured repeats per case
(seven requests total) against `llama3.2:latest`. Useful options:

```powershell
# Quick single-repeat run
python scripts\run_llm_benchmark.py --repeats 1

# Explicit model, seed, and report location
python scripts\run_llm_benchmark.py `
  --model llama3.2:latest `
  --seed 42 `
  --output-dir local_data\llm_benchmarks
```

Reports are written to `local_data/llm_benchmarks/<run-id>.json`. The
`local_data/` directory is Git-ignored, so generated reports are not
committed. Reports are local evaluation artifacts and include prompts and
model responses; they are not written to application logs. Do not add
credentials or `.env` contents to benchmark cases or reports.

The command exits with code `0` only when every measured trial passes. It
exits with code `1` when any measured trial fails or errors, and code `2` for
configuration or report-writing failures. A missing Ollama service or a real
generation failure is recorded honestly in the report.

## Tests

The benchmark tests use mocked Ollama responses and do not require a running
server:

```powershell
python -m pytest tests\test_benchmark_metrics.py tests\test_benchmark_scoring.py tests\test_benchmark_client.py tests\test_benchmark_runner.py -v
```

Run the full regression suite with:

```powershell
python -m pytest -v
```
