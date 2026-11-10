# Nexus AI Project Checkpoints

**Document role:** Living progress tracker and acceptance ledger.

**Repository identity at last verification:** branch `phase-1/foundation`, HEAD `e200aad34646f7b58cdd94db26ba735b2834aac5`, last verified 2026-11-10.

**Rule:** Implementation does not equal acceptance. A checkpoint must not be marked `ACCEPTED` without the required tests, recorded evidence, and a recorded review disposition. A file existing is not evidence that its task is complete.

## Status vocabulary

| Status | Meaning |
| --- | --- |
| `NOT_STARTED` | No work has begun, or no work is recorded. |
| `READY` | Dependencies are satisfied; work may start. |
| `IN_PROGRESS` | Work is actively underway. |
| `IMPLEMENTED` | Code or documentation exists, but verification and/or review is incomplete. |
| `REVIEW_PENDING` | Implementation is reported complete; independent review is not confirmed. |
| `CHANGES_REQUESTED` | Review found defects that must be fixed. |
| `VERIFIED` | Required tests and checks passed with recorded evidence; review disposition may still be pending. |
| `ACCEPTED` | Evidence, review, and owner acceptance are all recorded. |
| `BLOCKED` | A dependency, decision, or environment issue prevents progress. |
| `DEFERRED` | Deliberately postponed by an owner decision. |

## Evidence rules

1. Record the exact command, environment, date, and result. Do not summarize an unrun test as passing.
2. Historical results stay historical. The 162-pass and 116-pass results below were not rerun during the documentation session.
3. `pytest` cache files are collection metadata, not proof of a passing run.
4. Review evidence must identify the reviewer, the diff or files inspected, and the disposition.
5. Acceptance requires a named owner or delegated reviewer. An agent report is not acceptance.
6. Never read or print `.env` contents while gathering evidence.

## Summary

| ID | Phase | Objective | Status | Commit |
| --- | --- | --- | --- | --- |
| P0-CP1 | Planning | Project blueprint and phase-gate policy | `IMPLEMENTED` | `8344955` |
| DOC-001 | Documentation | Documentation foundation and onboarding | `REVIEW_PENDING` | none |
| P1-CP1 | 1 | Python project scaffold and tooling | `IMPLEMENTED` | `57af43f` |
| P1-CP2 | 1 | FastAPI foundation, health endpoint, API tests | `IMPLEMENTED` | `98cdb77` |
| P1-QG | 1 | Phase 1 quality gate | `NOT_STARTED` | n/a |
| P2-CP1 | 2 | PostgreSQL persistence and task CRUD | `IMPLEMENTED` | `50663ad` |
| P2-QG | 2 | Phase 2 quality gate | `NOT_STARTED` | n/a |
| P3-CP1 | 3 | Local Ollama integration | `IMPLEMENTED` | `9b8227e` |
| P3-CP2 | 3 | Reproducible local benchmark suite | `IMPLEMENTED` | `17eb240` |
| P3-CP3 | 3 | Generic structured-output engine | `IMPLEMENTED` | `328c823` |
| P3-CP4 | 3 | Schema registry, structured service, model adapter | `REVIEW_PENDING` | uncommitted |
| P3-CP5 | 3 | FastAPI structured-output integration | `NOT_STARTED` | none |
| P3-CP6 | 3 | Dedicated production service, adapter, and API tests | `NOT_STARTED` | none |
| P3-DEC1 | 3 | LangChain necessity decision | `NOT_STARTED` | none |
| P3-QG | 3 | Phase 3 quality gate | `BLOCKED` | n/a |
| FACTORY-001 | Supporting | Software Factory V2 configuration | `IMPLEMENTED` | `38a2813` |

## P0-CP1 — Project blueprint and phase-gate policy

- **Phase:** Planning
- **Objective:** Record the product blueprint, 12-phase roadmap, non-negotiable engineering principles, and mandatory phase quality gate.
- **Status:** `IMPLEMENTED`
- **Dependencies:** None
- **Files affected:** `docs/PROJECT_BLUEPRINT.md`, `README.md`, `.gitignore`
- **Commit:** `8344955af53d67636bcb22a9425bee0eee2d500a`
- **Tasks:**
  - [x] Product goals and engineering principles recorded.
  - [x] 12-phase roadmap recorded.
  - [x] Mandatory phase quality gate recorded.
  - [ ] Owner approval of this documentation baseline is recorded.
- **Acceptance criteria:**
  - [ ] The blueprint is reviewed by the owner against the current product direction.
  - [ ] Stale statements (for example, the Current status section) are corrected without rewriting history.
- **Required test commands:** None; documentation review only.
- **Actual verification evidence:** Commit `8344955` exists and contains `docs/PROJECT_BLUEPRINT.md`. File was read during this documentation session (2026-11-10). No approval record exists.
- **Review status:** Not recorded.
- **Remaining blockers:** The blueprint's Current status section is stale; the owner has not recorded approval of the plan.
- **Next action:** Keep `docs/PROJECT_BLUEPRINT.md` as the historical official roadmap and use `docs/ROADMAP.md` for reconciled status. Do not edit the blueprint under this documentation-only task.

## DOC-001 — Documentation foundation and onboarding

- **Phase:** Documentation
- **Objective:** Create a permanent documentation system so a future AI session can identify the repository state, approved decisions, implemented capabilities, open questions, and next checkpoint without reconstructing chat history.
- **Status:** `REVIEW_PENDING`
- **Dependencies:** P0-CP1; repository preflight
- **Files affected:** `docs/PROJECT_PLAN.md`, `docs/PROJECT_CHECKPOINTS.md`, `docs/AI_ONBOARDING.md`, `docs/ARCHITECTURE.md`, `docs/ROADMAP.md`, `GLOSSARY.md`, `docs/adr/`
- **Commit:** None; owner has not authorized a commit.
- **Tasks:**
  - [x] Verify branch, HEAD, and working-tree state.
  - [x] Inspect existing documentation, source, tests, benchmarks, skills, and agent profiles without reading `.env`.
  - [x] Create the master project plan with the 37-entry owner-approved decision register.
  - [x] Create this checkpoint tracker with historical and current evidence separated.
  - [x] Create the AI onboarding entry point.
  - [x] Create the current-versus-target architecture document.
  - [x] Create the glossary using the domain-modeling format.
  - [x] Create the roadmap reconciliation without adding phases.
  - [x] Create ADRs for accepted decisions and proposed technical choices.
  - [x] Internal Markdown links verify cleanly.
  - [x] `git diff --check` verifies cleanly for tracked changes.
  - [ ] Owner review of the documentation baseline.
- **Acceptance criteria:**
  - [x] Every required document exists and is internally consistent.
  - [x] No document claims that a planned or untracked capability is accepted or verified.
  - [x] All internal relative links resolve.
  - [x] The 37 decisions and the open technical questions are separated.
  - [x] Phase 3 is recorded as blocked pending reviews, tests, integration, and decisions.
- **Required test commands:**
  - Markdown link/path check across all repository Markdown files.
  - `git diff --check`
  - `git status --short --branch`
- **Actual verification evidence:** Run 2026-11-10 during this documentation session. The local Markdown link/path check scanned 88 repository Markdown files and found no broken relative links. `git diff --check` exited 0 with no tracked changes. A supplementary `git diff --no-index --check` against an empty file found no whitespace errors in `docs/` or the root glossary. The decision register has 37 unique `D-` IDs and 24 unique `TQ-` IDs. Final `git status` shows the documentation baseline untracked, with no staged changes. See the verification record below.
- **Review status:** Owner review pending.
- **Remaining blockers:** No owner review or acceptance; no commit authorization; no independent review of the documentation baseline.
- **Next action:** Request owner review of the documentation baseline. Preserve the untracked files and do not commit until the owner authorizes it.

### DOC-001 verification record

- **Date:** 2026-11-10
- **Markdown links/paths:** `PASS` — 88 Markdown files scanned, excluding `.git`, `.venv`, `node_modules`, `local_data`, and `.pytest_cache`; all local relative links resolve.
- **`git diff --check`:** `PASS` — exit 0; no tracked changes, so no diff output.
- **Untracked whitespace:** `PASS` — `git diff --no-index --check` against an empty file over `docs/**/*.md` and `GLOSSARY.md` found no trailing whitespace, space-before-tab, or blank-line-at-EOF errors.
- **Decision/question counts:** 37 unique `D-` IDs and 24 unique `TQ-` IDs in `docs/PROJECT_PLAN.md`.
- **Contradiction review:** `PASS` after one correction. The false description of `POST /llm/generate` as an "OpenAI-compatible endpoint" was changed to "model-generation endpoint." Planned and untracked capabilities remain labeled as such; no checkpoint is `ACCEPTED`.
- **Final `git status --short --branch`:**

```text
## phase-1/foundation
?? .agents/
?? GLOSSARY.md
?? docs/AI_ONBOARDING.md
?? docs/ARCHITECTURE.md
?? docs/PROJECT_CHECKPOINTS.md
?? docs/PROJECT_PLAN.md
?? docs/ROADMAP.md
?? docs/adr/
?? skills-lock.json
?? src/nexus_ai/model_adapters.py
?? src/nexus_ai/structured_schemas.py
?? src/nexus_ai/structured_service.py
```

- **Result:** All automated documentation checks passed. The checkpoint remains `REVIEW_PENDING` until the owner reviews and accepts it.

## P1-CP1 — Python project scaffold and tooling

- **Phase:** 1
- **Objective:** Establish the Python project structure, packaging metadata, and test package.
- **Status:** `IMPLEMENTED`
- **Dependencies:** None
- **Files affected:** `pyproject.toml`, `src/nexus_ai/__init__.py`, `tests/__init__.py`, `.gitignore`
- **Commit:** `57af43f09caa3fb79ec06d957bc82618c9d00fef`
- **Tasks:**
  - [x] Create the `src`-layout package and test package.
  - [x] Declare Python and project metadata.
  - [x] Add Python and local-data ignores.
  - [ ] Record environment verification for the target machine.
- **Acceptance criteria:**
  - [ ] A clean environment can install the project and run `pytest` collection.
  - [ ] The virtual environment procedure is documented and reproducible.
- **Required test commands:** `python -m pytest --collect-only -q`
- **Actual verification evidence:** Commit `57af43f` contains the scaffold. No installation or collection output was recorded at that commit. Not rerun during this documentation session.
- **Review status:** Not recorded.
- **Remaining blockers:** No environment evidence.
- **Next action:** Include environment setup evidence in the Phase 1 gate package.

## P1-CP2 — FastAPI foundation, health endpoint, and API tests

- **Phase:** 1
- **Objective:** Provide the initial FastAPI application, root and health endpoints, Pydantic response model, generic error handling, logging, and API tests.
- **Status:** `IMPLEMENTED`
- **Dependencies:** P1-CP1
- **Files affected:** `src/nexus_ai/main.py`, `tests/test_api.py`, `pyproject.toml`
- **Commit:** `98cdb772170ed8084651f495344b323449376b6a`
- **Tasks:**
  - [x] Create the FastAPI app.
  - [x] Add `/` and `/health`.
  - [x] Add a Pydantic health response model.
  - [x] Add a generic exception handler and baseline logging.
  - [x] Add API tests.
  - [ ] Record a passing test run at this checkpoint.
- **Acceptance criteria:**
  - [ ] All Task 1.1-1.7 acceptance criteria have explicit evidence.
  - [ ] API tests pass with exact totals recorded.
  - [ ] Review of the phase deliverables is recorded.
- **Required test commands:** `python -m pytest tests/test_api.py -v`
- **Actual verification evidence:** Commit `98cdb77` contains the app and `tests/test_api.py`. The test file defines five tests. No command output at this checkpoint is recorded.
- **Review status:** Not recorded.
- **Remaining blockers:** No test-run evidence and no formal Phase 1 gate decision.
- **Next action:** Assemble the Phase 1 evidence package before starting Phase 2 work, or record the phase as not formally gated.

## P1-QG — Phase 1 quality gate

- **Phase:** 1
- **Objective:** Verify every Phase 1 acceptance criterion, phase test, regression test, cross-phase check, quality check, review, and evidence record.
- **Status:** `NOT_STARTED`
- **Dependencies:** P1-CP1, P1-CP2
- **Files affected:** None yet
- **Commit:** Not applicable
- **Tasks:**
  - [ ] Map the seven Phase 1 tasks to evidence.
  - [ ] Run the Phase 1 tests.
  - [ ] Run the full regression suite.
  - [ ] Record commands, environment, and totals.
  - [ ] Record review disposition and gate decision.
- **Acceptance criteria:** All eight Mandatory Phase Quality Gate criteria in `docs/PROJECT_BLUEPRINT.md`.
- **Required test commands:** `python -m pytest -v`
- **Actual verification evidence:** None recorded.
- **Review status:** Not started.
- **Remaining blockers:** No gate evidence package.
- **Next action:** Create the Phase 1 gate evidence before relying on Phase 1 as complete.

## P2-CP1 — PostgreSQL persistence and task CRUD

- **Phase:** 2
- **Objective:** Add PostgreSQL persistence, SQLAlchemy models, Alembic migration, and task CRUD API endpoints with validation.
- **Status:** `IMPLEMENTED`
- **Dependencies:** P1-CP2
- **Files affected:** `src/nexus_ai/database.py`, `src/nexus_ai/models.py`, `src/nexus_ai/schemas.py`, `src/nexus_ai/main.py`, `alembic/`, `compose.yaml`, `tests/test_database.py`, `tests/test_tasks_crud.py`, `tests/test_tasks_api.py`
- **Commit:** `50663ade9b1e941c3af19c2338933478119de155`
- **Tasks:**
  - [x] Add SQLAlchemy engine, session factory, and database dependency.
  - [x] Add the `workspace_tasks` model and status constraint.
  - [x] Add the Alembic migration.
  - [x] Add task create, list, read, update, and delete endpoints.
  - [x] Add validation for blank titles, null fields, and invalid statuses.
  - [x] Add database, CRUD, and API tests.
  - [ ] Record a passing test run at this checkpoint.
- **Acceptance criteria:**
  - [ ] CRUD lifecycle passes against PostgreSQL.
  - [ ] Negative paths return documented errors.
  - [ ] Migration and dependency checks pass.
  - [ ] Review of the phase deliverables is recorded.
- **Required test commands:**
  - `python -m pytest tests/test_database.py tests/test_tasks_crud.py tests/test_tasks_api.py -v`
  - `alembic check`
  - `python -m pip check`
- **Actual verification evidence:** Commit `50663ad` contains the implementation and tests. During the documentation session, `docker compose ps` reported `nexus-ai-postgres` healthy at `127.0.0.1:5433`; this is environment status, not a test run. The Phase 3 draft recorded a historical 116-pass suite after PostgreSQL was restored. The owner brief reports a later 162-pass suite. Neither was rerun in this documentation session.
- **Review status:** Not recorded.
- **Remaining blockers:** No per-checkpoint test output or formal Phase 2 gate decision.
- **Next action:** Assemble the Phase 2 gate evidence or record the phase as not formally gated.

## P2-QG — Phase 2 quality gate

- **Phase:** 2
- **Objective:** Verify Phase 2 acceptance criteria, phase tests, Phase 1 regression, cross-phase integration, quality checks, review, evidence, and gate decision.
- **Status:** `NOT_STARTED`
- **Dependencies:** P2-CP1, P1-QG
- **Files affected:** None yet
- **Commit:** Not applicable
- **Tasks:**
  - [ ] Run Phase 2 tests and full regression.
  - [ ] Run `pip check` and `alembic check`.
  - [ ] Record PostgreSQL and environment details.
  - [ ] Record review disposition and gate decision.
- **Acceptance criteria:** All eight Mandatory Phase Quality Gate criteria.
- **Required test commands:** `python -m pytest -v`, `python -m pip check`, `alembic check`
- **Actual verification evidence:** None recorded.
- **Review status:** Not started.
- **Remaining blockers:** No gate evidence package.
- **Next action:** Do not claim Phase 2 is accepted until the gate is recorded.

## P3-CP1 — Local Ollama integration

- **Phase:** 3
- **Objective:** Integrate the local Ollama service with the FastAPI backend and expose controlled text generation with categorized failures.
- **Status:** `IMPLEMENTED`
- **Dependencies:** P1-CP2, P2-CP1
- **Files affected:** `src/nexus_ai/ollama.py`, `src/nexus_ai/main.py`, `src/nexus_ai/schemas.py`, `.env.example`, `tests/test_ollama_client.py`, `tests/test_llm_api.py`
- **Commit:** `9b8227e28648b7d13e2d383c8e28b4ae7a74b651`
- **Tasks:**
  - [x] Add an Ollama HTTP client using `/api/generate` with `stream: false`.
  - [x] Add environment defaults for base URL, model, and timeout.
  - [x] Categorize timeout, unavailable-service, and invalid-response failures.
  - [x] Add `POST /llm/generate` with 503/502 error mapping.
  - [x] Add client and API tests.
  - [ ] Record a passing test run at this checkpoint.
- **Acceptance criteria:**
  - [ ] Valid requests return model, text, completion status, and available metrics.
  - [ ] Timeout, unavailable service, HTTP error, and malformed response are mapped deterministically.
  - [ ] Error responses do not leak prompts or internal details.
  - [ ] Review of the phase deliverables is recorded.
- **Required test commands:** `python -m pytest tests/test_ollama_client.py tests/test_llm_api.py -v`
- **Actual verification evidence:** Commit `9b8227e` contains the implementation and tests. No per-checkpoint test output is recorded. The Phase 3 draft calls this "Checkpoint 1" and records the commit, not a verification result.
- **Review status:** Not recorded.
- **Remaining blockers:** No test-run evidence and no independent review record.
- **Next action:** Record the Phase 3 checkpoint evidence package.

## P3-CP2 — Reproducible local benchmark suite

- **Phase:** 3
- **Objective:** Provide versioned benchmark cases, deterministic scoring, Ollama metrics capture, warm-up handling, completion rejection, and non-overwriting reports.
- **Status:** `IMPLEMENTED`
- **Dependencies:** P3-CP1
- **Files affected:** `src/nexus_ai/benchmark/`, `benchmarks/`, `scripts/run_llm_benchmark.py`, `scripts/rest_api_prompt_experiment.py`, `tests/test_benchmark_*.py`, `docs/BENCHMARKS.md`, `README.md`
- **Commit:** `17eb240472d94986ca4c50c5117cd41c2fb403db`
- **Tasks:**
  - [x] Add versioned benchmark cases at version `1.0.1`.
  - [x] Add case validation and deterministic scoring.
  - [x] Add warm-up separation and completion validation.
  - [x] Add JSON report writing without overwriting.
  - [x] Add benchmark tests with mocked Ollama responses.
  - [x] Record model evidence in local reports and `docs/BENCHMARKS.md`.
  - [ ] Record a passing test run at this checkpoint.
- **Acceptance criteria:**
  - [ ] Incomplete generations cannot pass.
  - [ ] Historical reports are never overwritten.
  - [ ] Scoring remains unchanged and versioned.
  - [ ] Benchmark tests pass with exact totals.
  - [ ] Review of the phase deliverables is recorded.
- **Required test commands:**
  - `python -m pytest tests/test_benchmark_metrics.py tests/test_benchmark_scoring.py tests/test_benchmark_client.py tests/test_benchmark_runner.py -v`
  - `python scripts/run_llm_benchmark.py --repeats 1`
- **Actual verification evidence:** Commit `17eb240` contains the benchmark subsystem. `docs/BENCHMARKS.md` records the observed model behavior: `llama3.2:latest` 4/6, `qwen3:4b` 0/6, `gemma3:4b` 2/6, and the two-trial concise REST experiment 2/2. Local reports exist under Git-ignored `local_data/llm_benchmarks/`. No per-checkpoint test output is recorded.
- **Review status:** Not recorded.
- **Remaining blockers:** No test-run evidence or formal review disposition.
- **Next action:** Record the benchmark test output and review before Phase 3 closure.

## P3-CP3 — Generic structured-output engine

- **Phase:** 3
- **Objective:** Provide a reusable generate-and-validate pipeline with bounded correction retries and a REST-explanation adapter.
- **Status:** `IMPLEMENTED`
- **Dependencies:** P3-CP2
- **Files affected:** `src/nexus_ai/structured_output_pipeline.py`, `src/nexus_ai/structured_outputs.py`, `scripts/try_langchain_structured.py`, `tests/test_structured_output_pipeline.py`, `tests/test_langchain_structured.py`, `pyproject.toml`
- **Commit:** `328c8236e8d63f051e943aad0fdaf377fc9709ad`
- **Tasks:**
  - [x] Add a generic generate/validate/retry engine.
  - [x] Add correction prompts containing the validation error.
  - [x] Bound retries to a maximum of two attempts.
  - [x] Add a Pydantic REST-explanation schema and semantic validator.
  - [x] Add a demo script with injectable generation for tests.
  - [x] Add historical regression tests for the engine and adapter.
  - [ ] Record a passing test run at this checkpoint.
- **Acceptance criteria:**
  - [ ] A valid first response is returned without mutation.
  - [ ] A semantic validation failure triggers at most one correction retry.
  - [ ] Final rejection is never returned as success.
  - [ ] Network and parsing errors are not misclassified as validation rejections.
  - [ ] Tests pass with exact totals.
  - [ ] Review of the phase deliverables is recorded.
- **Required test commands:** `python -m pytest tests/test_structured_output_pipeline.py tests/test_langchain_structured.py -v`
- **Actual verification evidence:** Commit `328c823` contains the engine, adapter, demo, and tests. `tests/test_structured_output_pipeline.py` and `tests/test_langchain_structured.py` are tracked. The owner brief reports a historical full-suite result of 162 passed after PostgreSQL was restored; per-checkpoint output is not recorded and was not rerun in this documentation session.
- **Review status:** Not recorded.
- **Remaining blockers:** No per-checkpoint test output; no formal review record.
- **Next action:** Use this committed engine as the baseline for `P3-CP4`; do not modify it without review.

## P3-CP4 — Schema registry, structured service, and model adapter

- **Phase:** 3
- **Objective:** Add a named schema registry, a service that coordinates schema-driven generation with bounded retries and metrics, and a ChatOllama adapter that verifies provider completion.
- **Status:** `REVIEW_PENDING`
- **Dependencies:** P3-CP3
- **Files affected:** `src/nexus_ai/structured_schemas.py`, `src/nexus_ai/structured_service.py`, `src/nexus_ai/model_adapters.py`
- **Commit:** None; files are untracked.
- **Tasks:**
  - [x] `structured_schemas.py` exists locally with a schema registry and lookup errors.
  - [x] `structured_service.py` exists locally with retry policy, metrics aggregation, and rejection handling.
  - [x] `model_adapters.py` exists locally with a `ChatOllama` structured adapter and completion enforcement.
  - [x] Pair 1 implementation was reported complete.
  - [x] Pair 2 implementation was reported complete.
  - [ ] Pair 1 independent review is confirmed complete.
  - [ ] Pair 2 independent review is confirmed complete.
  - [ ] Dedicated service tests are written and passing.
  - [ ] Dedicated adapter tests are written and passing.
  - [ ] FastAPI integration is implemented.
  - [ ] Files are committed with owner approval.
- **Acceptance criteria:**
  - [ ] The registry rejects unknown schemas and invalid specs deterministically.
  - [ ] The service enforces the retry cap and never returns a rejected result as success.
  - [ ] Provider-category failures propagate with metrics attached and without fabricated values.
  - [ ] The adapter rejects parsing failures, missing completion metadata, `done=False`, and `done_reason="length"`.
  - [ ] Unit tests cover schema lookup, retries, metrics, and completion failure categories.
  - [ ] API integration tests cover the public boundary once it exists.
  - [ ] Independent reviews are recorded for both implementation pairs.
- **Required test commands:**
  - Future: `python -m pytest tests/test_structured_service.py -v`
  - Future: `python -m pytest tests/test_model_adapters.py -v`
  - Future: `python -m pytest tests/test_structured_api.py -v`
  - Existing regression: `python -m pytest tests/test_structured_output_pipeline.py tests/test_langchain_structured.py -v`
- **Actual verification evidence:** File existence verified 2026-11-10. The files are untracked and therefore not part of HEAD `e200aad`. No dedicated tests exist for the service or adapter. `src/nexus_ai/main.py` does not import the service, registry, or adapter. No review report is present in the repository.
- **Review status:** Independent reviews not confirmed complete. No reviewer names, diff coverage, or disposition are recorded.
- **Remaining blockers:** Review confirmation, dedicated tests, API integration, and owner-approved commit.
- **Next action:** Complete and record independent reviews of both pairs, then add dedicated tests before attempting FastAPI integration.

## P3-CP5 — FastAPI structured-output integration

- **Phase:** 3
- **Objective:** Expose an approved structured-output contract through FastAPI with documented request, response, error mapping, and metrics behavior.
- **Status:** `NOT_STARTED`
- **Dependencies:** P3-CP4, TQ-05, TQ-09, TQ-11
- **Files affected:** None yet. Likely `src/nexus_ai/main.py`, `src/nexus_ai/schemas.py`, and a new API test file, subject to an approved design.
- **Commit:** None.
- **Tasks:**
  - [ ] Approve the public contract and schema selection mechanism.
  - [ ] Approve the error mapping and metrics exposure.
  - [ ] Implement the route and service wiring.
  - [ ] Add API tests including negative paths.
  - [ ] Record evidence and review.
- **Acceptance criteria:**
  - [ ] A valid request returns a validated structured result and measured metrics.
  - [ ] Unknown schemas, blank prompts, provider failures, incomplete generations, and final validation rejection map to documented errors.
  - [ ] No secret or prompt content leaks in errors or logs.
  - [ ] Existing endpoints and tests remain unchanged and passing.
- **Required test commands:** Future: `python -m pytest tests/test_structured_api.py -v`; full regression after integration.
- **Actual verification evidence:** None. `src/nexus_ai/main.py` has no structured-output route as of 2026-11-10.
- **Review status:** Not started.
- **Remaining blockers:** Open decisions and `P3-CP4` review/tests.
- **Next action:** Do not implement until `P3-CP4` is reviewed and the API contract is approved.

## P3-CP6 — Dedicated production service, adapter, and API tests

- **Phase:** 3
- **Objective:** Provide dedicated tests for the production structured-output service, model adapter, and API boundary, separate from historical engine and REST-demo tests.
- **Status:** `NOT_STARTED`
- **Dependencies:** P3-CP4, P3-CP5
- **Files affected:** New test files only, names subject to approval.
- **Commit:** None.
- **Tasks:**
  - [ ] Add service tests for schema lookup, retry policy, metrics, and rejection.
  - [ ] Add adapter tests for completion enforcement and provider error mapping.
  - [ ] Add API tests for the public contract and negative paths.
  - [ ] Run focused and full regression suites with recorded output.
- **Acceptance criteria:**
  - [ ] Every production structured-output failure category has a deterministic test.
  - [ ] Tests do not depend on a live Ollama service.
  - [ ] Full regression passes against PostgreSQL with exact totals recorded.
- **Required test commands:** `python -m pytest -v` and focused test commands from `P3-CP4`/`P3-CP5`.
- **Actual verification evidence:** None. No dedicated service, adapter, or API test file exists as of 2026-11-10.
- **Review status:** Not started.
- **Remaining blockers:** `P3-CP4` and `P3-CP5`.
- **Next action:** Create tests only after the interface and contract are approved and reviewed.

## P3-DEC1 — LangChain necessity decision

- **Phase:** 3
- **Objective:** Decide whether LangChain is required for a concrete approved Phase 3 use case, or should be deferred or rejected.
- **Status:** `NOT_STARTED`
- **Dependencies:** TQ-01, TQ-04
- **Files affected:** A decision record under `docs/adr/` if approved.
- **Commit:** None.
- **Tasks:**
  - [ ] Identify a concrete use case or state that none exists.
  - [ ] Record adopt, defer, or reject with rationale.
  - [ ] If adopt, record dependency, license, resource, test, and rollback impact.
  - [ ] Confirm no dependency or production code changed during the decision.
- **Acceptance criteria:**
  - [ ] The decision cites the Phase 3 roadmap item and the use case.
  - [ ] The decision is one of adopt, defer, or reject.
  - [ ] The owner approves the record.
- **Required test commands:** None; decision record only.
- **Actual verification evidence:** None. LangChain dependencies exist in `pyproject.toml`, and a demo/local adapter uses them, but no production use case is approved.
- **Review status:** Not started.
- **Remaining blockers:** Owner decision.
- **Next action:** Record the decision before treating LangChain as part of the production architecture.

## P3-QG — Phase 3 quality gate

- **Phase:** 3
- **Objective:** Verify Phase 3 against approved acceptance criteria, tests, regression, cross-phase integration, benchmarks, performance targets, review, and evidence.
- **Status:** `BLOCKED`
- **Dependencies:** P3-CP1 to P3-CP6, P3-DEC1, TQ-01 to TQ-11
- **Files affected:** Evidence package only
- **Commit:** Not applicable
- **Tasks:**
  - [ ] Resolve TQ-01 to TQ-08 (the Phase 3 draft's D1-D8).
  - [ ] Complete and record `P3-CP4` reviews.
  - [ ] Complete `P3-CP5` and `P3-CP6`.
  - [ ] Run phase tests and full regression against PostgreSQL.
  - [ ] Run cross-phase integration tests.
  - [ ] Re-run or cite benchmark reports with model, Ollama version, hardware, settings, tokens, and completion state.
  - [ ] Record performance and resource results against pre-approved targets.
  - [ ] Record review and gate decision.
- **Acceptance criteria:** All eight Mandatory Phase Quality Gate criteria, plus the Phase 3 closure checklist in `docs/PHASE3_COMPLETION_PLAN_DRAFT.md`.
- **Required test commands:** `python -m pytest -v`; Phase 3 focused tests; cross-phase integration tests; `python -m pip check`; `alembic check`; benchmark CLI as approved.
- **Actual verification evidence:** No gate evidence package exists. Historical results: the Phase 3 draft records 116 passed after PostgreSQL restoration; the owner brief records a later 162 passed. Neither was rerun in this documentation session. The Phase 3 draft remains unapproved.
- **Review status:** Not started.
- **Remaining blockers:** Unresolved decisions, unconfirmed reviews, missing tests, missing API integration, and no durable evidence artifact.
- **Next action:** Treat Phase 3 as open. The immediate next checkpoint is completing `P3-CP4` review and tests.

## FACTORY-001 — Software Factory V2 configuration

- **Phase:** Supporting infrastructure
- **Objective:** Provide OpenCode agent profiles for bounded implementation and independent review pairs.
- **Status:** `IMPLEMENTED`
- **Dependencies:** None
- **Files affected:** `.opencode/agents/factory-v2-*`, `.opencode/agents/impl-*`, `.opencode/agents/review-*`, `docs/SOFTWARE_FACTORY_V2.md`
- **Commit:** `38a28138eaba10d3a1029dd56b6f9feb7848fdf6`
- **Tasks:**
  - [x] Add the orchestrator and capacity-slot profiles.
  - [x] Add reviewer profiles with read-only permissions.
  - [x] Document allocation, review limits, and reporting.
  - [ ] Verify native custom-profile invocation and child model identity.
- **Acceptance criteria:**
  - [ ] Custom profiles are selectable in the runtime.
  - [ ] Native Task invocation reaches the configured profiles.
  - [ ] Child-session model identity is verified or explicitly marked unverified.
- **Required test commands:** Runtime smoke test only; no application test.
- **Actual verification evidence:** Commit `38a2813` contains the profiles and documentation. `docs/SOFTWARE_FACTORY_V2.md` records the native Task invocation smoke test as `BLOCKED` in the setup harness.
- **Review status:** Configuration documented; runtime smoke test not passed.
- **Remaining blockers:** Native custom-profile invocation and model-identity verification.
- **Next action:** Do not claim Factory V2 runtime enforcement until the smoke test passes in an OpenCode session that exposes the profiles.

## Final documentation verification

This section records only commands actually run during the documentation session on 2026-11-10. It does not record a test run; a documentation-only task does not require rerunning the application suite.

- **Markdown links:** `PASS` — 88 Markdown files scanned, excluding `.git`, `.venv`, `node_modules`, `local_data`, and `.pytest_cache`; all local relative links resolve.
- **`git diff --check`:** `PASS` — exit 0; no tracked changes.
- **Untracked whitespace:** `PASS` — `git diff --no-index --check` against an empty file over `docs/**/*.md` and `GLOSSARY.md`; no whitespace errors.
- **Final `git status --short --branch`:** branch `phase-1/foundation`; no staged changes; the documentation baseline is untracked, alongside preserved untracked `.agents/`, `skills-lock.json`, and the three local structured-output source files. HEAD remains `e200aad34646f7b58cdd94db26ba735b2834aac5`.
- **Contradiction review:** `PASS` — one factual correction was made to `docs/PROJECT_PLAN.md` (the model-generation endpoint is not OpenAI-compatible). The 37 decisions are distinct from the 24 open technical questions. No document treats a planned, local-only, or untracked capability as accepted or verified.
- **Owner review:** Pending. No checkpoint is `ACCEPTED`.
