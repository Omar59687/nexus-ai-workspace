# Nexus AI Project Checkpoints

**Document role:** Living progress tracker and acceptance ledger.

**Repository identity:** isolated branch `phase-1/foundation`, baseline `19269930c25392343219587d6b70f1db6f6cca76`; this checkout contains uncommitted timeout, live-smoke harness, regression-test, and documentation changes. The owner's Windows checkout is not mounted or modified.

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
| P1-QG | 1 | Phase 1 quality gate | `PROPOSED` | n/a |
| P2-CP1 | 2 | PostgreSQL persistence and task CRUD | `IMPLEMENTED` | `50663ad` |
| P2-QG | 2 | Phase 2 quality gate | `NOT_STARTED` | n/a |
| P3-CP1 | 3 | Local Ollama integration | `IMPLEMENTED` | `9b8227e` |
| P3-CP2 | 3 | Reproducible local benchmark suite | `IMPLEMENTED` | `17eb240` |
| P3-CP3 | 3 | Generic structured-output engine | `IMPLEMENTED` | `328c823` |
| P3-CP4 | 3 | Schema registry, structured service, model adapter | `ACCEPTED` | commit `e45a7aa`; owner-reported Windows verification |
| P3-CP5 | 3 | FastAPI structured-output integration | `VERIFIED` | committed at baseline `1926993`; owner reports full Windows test/check success |
| P3-CP6 | 3 | Dedicated production service, adapter, and API tests | `BLOCKED` | 166 focused tests pass; full isolated suite has four PostgreSQL-dependent failures |
| P3-DEC1 | 3 | LangChain necessity decision | `PROPOSED` | ADR-0011 proposed; owner decision pending |
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
- **Status:** `ACCEPTED`
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
- **Status:** `PROPOSED`
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
- **Status:** `ACCEPTED`
- **Dependencies:** P3-CP3
- **Files affected:** `src/nexus_ai/structured_schemas.py`, `src/nexus_ai/structured_service.py`, `src/nexus_ai/model_adapters.py`
- **Commit:** `e45a7aa2a7b7d69dea808b6811e69ca1afd74ec4`.
- **Tasks:**
  - [x] `structured_schemas.py` exists locally with a schema registry and lookup errors.
  - [x] `structured_service.py` exists locally with retry policy, metrics aggregation, and rejection handling.
  - [x] `model_adapters.py` exists locally with a `ChatOllama` structured adapter and completion enforcement.
  - [x] Pair 1 implementation was reported complete.
  - [x] Pair 2 implementation was reported complete.
  - [x] CP4 review and recovery fixes are included in owner-accepted baseline e45.
  - [x] Dedicated service tests are written and passing.
  - [x] Dedicated adapter tests are written and passing.
  - [x] FastAPI integration was completed in CP5 and committed at baseline `1926993`.
  - [x] Files are present in owner-confirmed commit `e45a7aa`; owner accepted the CP4 checkpoint.
- **Acceptance criteria:**
  - [x] The registry rejects unknown schemas and invalid specs deterministically.
  - [x] The service enforces the retry cap and never returns a rejected result as success.
  - [x] Provider-category failures propagate with metrics attached and without fabricated values.
  - [x] The adapter rejects parsing failures, missing completion metadata, `done=False`, and `done_reason="length"`.
  - [x] Unit tests cover schema lookup, retries, metrics, and completion failure categories.
  - [x] Owner accepted CP4 with review and test evidence.
- **Required test commands:**
  - Future: `python -m pytest tests/test_structured_service.py -v`
  - Future: `python -m pytest tests/test_model_adapters.py -v`
  - Future: `python -m pytest tests/test_structured_api.py -v`
  - Existing regression: `python -m pytest tests/test_structured_output_pipeline.py tests/test_langchain_structured.py -v`
- **Actual verification evidence:** The recovered CP4 code and metrics/test hardening are in owner-confirmed commit `e45a7aa2a7b7d69dea808b6811e69ca1afd74ec4`. The owner explicitly accepted CP4 and reported Windows verification: `398 passed in 8.05s`, `pip check`, `alembic check`, and `git diff --check` passed. These are owner-reported results and were not rerun in this isolated Linux environment. Dedicated service and adapter tests are present in the baseline and pass in the current 166-test focused follow-up command.
- **Review status:** Owner acceptance recorded. The current CP5 review does not recreate prior CP4 reviews.
- **Remaining blockers:** None specific to CP4; phase-wide gates remain separate.
- **Next action:** Carry the accepted CP4 evidence into the Phase 3 quality gate record.

## P3-CP5 — FastAPI structured-output integration

- **Phase:** 3
- **Objective:** Expose registry-backed structured generation with documented request, response, errors, and metrics.
- **Status:** `VERIFIED`
- **Dependencies:** P3-CP4 accepted; reversible HTTP contract recorded in ADR-0010. CP4's bounded two-attempt semantic retry is retained; TQ-11 remains open.
- **Files affected:** `src/nexus_ai/main.py`, `src/nexus_ai/schemas.py`, `tests/test_structured_api.py`.
- **Commit:** Baseline `19269930c25392343219587d6b70f1db6f6cca76`; CP5 implementation is committed. This handoff adds no commit.
- **Tasks:**
  - [x] Define and record a minimal request/response contract and schema registry selection.
  - [x] Implement dependency-injected service wiring from configured Ollama base URL/model.
  - [x] Map unknown schema, validation, timeout, unavailable, malformed, and incomplete outcomes to generic HTTP errors.
  - [x] Add deterministic endpoint tests, including no prompt/error leakage and legacy API compatibility.
  - [x] Complete two independent review cycles and preserve findings.
- **Acceptance criteria:**
  - [x] Valid requests return validated structured data plus available per-attempt and aggregate metrics.
  - [x] Unknown schemas, invalid requests, provider failures, incomplete generations, and semantic rejection have explicit statuses.
  - [x] New route errors and service logs do not reveal prompts, model output, or provider exception details.
  - [x] Existing `/llm/generate` behavior remains covered by regression tests.
- **Required test command:** `python -m pytest -q tests/test_structured_api.py tests/test_structured_service.py tests/test_structured_schemas.py tests/test_structured_output_pipeline.py tests/test_langchain_structured.py tests/test_model_adapters.py tests/test_llm_api.py tests/test_api.py`.
- **Actual verification evidence:** Owner reports 423 passed in 8.17s on Windows at baseline, with `pip check`, `alembic check`, `compileall`, and `git diff --check` passing. Cloud regression tests for this follow-up are recorded in CP6/QG evidence; the owner's baseline run does not include these uncommitted changes.
- **Review status:** API/architecture, security/failure-handling, and test/regression agents completed two cycles. Cycle 1 identified one misleading DI test claim; it was corrected. Cycle 2 found no remaining confirmed issues.
- **Remaining blockers:** No CP5-specific blocker remains. The separate CP6 timeout/harness follow-up is awaiting independent review and an owner Windows rerun.
- **Next action:** Keep the committed endpoint stable; timeout follow-up remains under review and requires owner rerun before integration.

## P3-CP6 — Dedicated production service, adapter, and API tests

- **Phase:** 3
- **Objective:** Provide dedicated tests for the production structured-output service, model adapter, and API boundary, separate from historical engine and REST-demo tests.
- **Status:** `BLOCKED`
- **Dependencies:** P3-CP4, P3-CP5
- **Files affected:** New test files only, names subject to approval.
- **Commit:** None.
- **Tasks:**
  - [x] Existing baseline includes service, adapter, and API suites for schema lookup, retry policy, metrics, completion enforcement, provider errors, and contract behavior.
  - [x] Add adapter timeout/default/validation and API timeout-propagation regression cases.
  - [x] Add opt-in live Ollama smoke harness with fail-closed and output-path safety tests.
  - [x] Run focused, full, and non-database suites with recorded output.
- **Acceptance criteria:**
  - [ ] Every production structured-output failure category has a deterministic test.
  - [ ] Tests do not depend on a live Ollama service.
  - [ ] Full regression passes against PostgreSQL with exact totals recorded.
- **Required test commands:** `python -m pytest -v` and focused test commands from `P3-CP4`/`P3-CP5`.
- **Actual verification evidence:** New focused command (`tests/test_live_ollama_smoke.py tests/test_model_adapters.py tests/test_structured_api.py`) passed **166 tests**. Full suite ran **433 tests: 429 passed, four PostgreSQL-dependent failures** due to no service at `127.0.0.1:59999`. Non-database subset passed **427 tests**. `compileall` and `pip check` passed; `alembic check` cannot run without PostgreSQL. The live Ollama smoke was not run; deterministic tests use fakes. The owner reports 423/423 passing with database checks at the pre-change baseline on Windows.
- **Review status:** Four independent read-only reviews covered timeout/provider behavior, test/smoke safety, gate evidence, and RAG spec consistency. All confirmed findings were corrected; no unresolved review findings remain.
- **Remaining blockers:** Full regression and migration check on the final changed tree against PostgreSQL; owner Windows rerun; approved Phase 3 gate criteria.
- **Next action:** Run the full suite and Alembic check in the owner's configured Windows environment before gate consideration.

## P3-DEC1 — LangChain necessity decision

- **Phase:** 3
- **Objective:** Decide whether LangChain is required for a concrete approved Phase 3 use case, or should be deferred or rejected.
- **Status:** `PROPOSED`
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
- **Actual verification evidence:** The current CP5 route wires the CP4 `LangChainChatOllamaAdapter` into a real API use case. ADR-0011 records a proposed rationale to retain that adapter for this local Ollama integration while preserving a provider boundary. Owner approval remains outstanding; this is not an accepted adoption decision.
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
  - [x] Record owner acceptance of `P3-CP4` and complete `P3-CP5` implementation/review.
  - [ ] Complete PostgreSQL-backed `P3-CP6` regression and Alembic verification.
  - [ ] Run phase tests and full regression against PostgreSQL.
  - [ ] Run cross-phase integration tests.
  - [ ] Re-run or cite benchmark reports with model, Ollama version, hardware, settings, tokens, and completion state.
  - [ ] Record performance and resource results against pre-approved targets.
  - [ ] Record review and gate decision.
- **Acceptance criteria:** All eight Mandatory Phase Quality Gate criteria, plus the Phase 3 closure checklist in `docs/PHASE3_COMPLETION_PLAN_DRAFT.md`.
- **Required test commands:** `python -m pytest -v`; Phase 3 focused tests; cross-phase integration tests; `python -m pip check`; `alembic check`; benchmark CLI as approved.
- **Actual verification evidence:** `docs/P3_QG_EVIDENCE_2026-11-11.md` records owner-provided Windows baseline checks, the isolated timeout fix and smoke harness, test totals, and blockers. The final cloud full run had 429 passed and four PostgreSQL connection failures; `alembic check` could not connect. Phase 3 remains open.
- **Review status:** CP5 received two independent review cycles. The final gate assessment is blocked pending the evidence listed in the evidence record.
- **Remaining blockers:** P1/P2 gate evidence; owner decision on LangChain ADR-0011 and TQ-11; PostgreSQL full regression/Alembic; cross-phase integration; benchmark reproducibility and reliability criteria; pre-approved performance/resource targets; final owner gate decision.
- **Next action:** Keep Phase 3 open and complete the listed evidence and decisions before requesting owner gate acceptance.

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

## Historical documentation verification (2026-11-10)

This section records only commands actually run during the documentation session on 2026-11-10. It does not record a test run; a documentation-only task does not require rerunning the application suite.

- **Markdown links:** `PASS` — 88 Markdown files scanned, excluding `.git`, `.venv`, `node_modules`, `local_data`, and `.pytest_cache`; all local relative links resolve.
- **`git diff --check`:** `PASS` — exit 0; no tracked changes.
- **Untracked whitespace:** `PASS` — `git diff --no-index --check` against an empty file over `docs/**/*.md` and `GLOSSARY.md`; no whitespace errors.
- **Historical `git status --short --branch`:** at that documentation session, the documentation baseline and CP4 files were untracked and HEAD was `e200aad34646f7b58cdd94db26ba735b2834aac5`. This is not the current repository state; see the 2026-11-11 evidence above.
- **Contradiction review:** `PASS` — one factual correction was made to `docs/PROJECT_PLAN.md` (the model-generation endpoint is not OpenAI-compatible). The 37 decisions are distinct from the 24 open technical questions. No document treats a planned, local-only, or untracked capability as accepted or verified.
- **Owner review at that date:** Pending. CP4 acceptance was recorded later against commit e45a7aa.
