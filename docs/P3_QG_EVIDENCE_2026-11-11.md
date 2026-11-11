# Phase 3 Quality-Gate Evidence — 2026-11-11

## Decision

**Status: BLOCKED. Phase 3 is not accepted and Phase 4 implementation has not started.** Tests and owner checks show useful readiness evidence, but technical exit targets, earlier phase gate records, and explicit gate approval are unresolved.

## Repository and environments

- Repository: `Omar59687/nexus-ai-workspace`, branch `phase-1/foundation`.
- Isolated checkout baseline: `19269930c25392343219587d6b70f1db6f6cca76` (`feat: integrate structured generation API and Phase 3 verification`). Changes described below are uncommitted in the isolated checkout only.
- Owner's Windows checkout is not mounted or modified in this environment.
- Cloud environment: Python 3.12.14, Git 2.52.0, dedicated virtual environment. Docker, PostgreSQL, `psql`, and Ollama executables/services are unavailable. Placeholder database settings use port 59999; no `.env` file was read.
- Owner-reported Windows environment (provided in the assignment, not rerun here): Python project full suite **423 passed in 8.17s**; `pip check`, `alembic check`, `compileall`, and `git diff --check` passed. Ollama 0.40.15 and local models were available.

## Owner-provided live Ollama observation

The owner reports a successful `POST /structured/generate` using `llama3.2:latest`: one attempt, 19.38 seconds end to end, 17,676.107 ms generation duration, 48 prompt tokens, 81 output tokens, and a schema-valid response with correct REST/API expansions. The generated purpose text duplicated the input purpose, so this call demonstrates schema/API execution, not factual quality. A direct adapter call with `num_predict=256` took 18.02 seconds; a separate direct adapter call with `num_predict=128` correctly rejected incomplete output. A direct `/api/generate` two-token “Hello” call took 0.92 seconds. A separate longer prompt timed out after 180 seconds. These are attributed owner observations, not a reliability benchmark or reproduced cloud runs.

## Confirmed timeout configuration defect and fix

At baseline, `LangChainChatOllamaAdapter` omitted HTTP client timeout configuration, while a test asserted that no timeout should be passed. Runtime inspection with installed `langchain-ollama==1.1.0` and `ollama==0.6.3` confirmed both constructed HTTPX clients had `timeout=None`; passing `client_kwargs={"timeout": 90}` configured both clients. This verifies the unbounded client timeout, but does **not** reproduce the owner's specific 180-second timeout.

The isolated change forwards `OllamaClient.timeout_seconds` to `ChatOllama(client_kwargs=...)`, defaults direct adapter construction to the existing 120-second Ollama setting, validates positive finite values, and maps `httpx.TimeoutException` to the existing timeout error. HTTPX timeout is an inactivity/read timeout and is not a guaranteed total wall-clock deadline.

## Tests and checks executed in the isolated checkout

After timeout changes and the smoke harness were added:

- `tests/test_model_adapters.py tests/test_structured_api.py`: **162 passed**.
- `tests/test_live_ollama_smoke.py tests/test_model_adapters.py tests/test_structured_api.py`: **166 passed**.
- Full `python -m pytest -q`: **429 passed, 4 failed in 4.28s** out of 433. All four failures are PostgreSQL-dependent: `test_database_connection_executes_sql`, two `test_tasks_api` cases, and `test_tasks_crud`; connection refused at `127.0.0.1:59999`. The harness test's initial order-dependent failure was corrected, and this final run passed that test.
- Non-database regression subset (`--ignore=tests/test_database.py --ignore=tests/test_tasks_api.py --ignore=tests/test_tasks_crud.py`): **427 passed in 1.96s**.
- `python -m compileall -q src scripts tests`: passed.
- `python -m pip check`: passed; no broken requirements.
- `git diff --check`: passed after the final edits (rerun before export).
- `alembic check`: not run; no PostgreSQL service is available.
- Live Ollama smoke: not run here. The new script is opt-in and disabled unless `NEXUS_LIVE_OLLAMA=1` is explicitly set.

## Checkpoint and gate matrix

| Criterion | Status | Evidence / remaining work |
| --- | --- | --- |
| Acceptance criteria have explicit evidence | BLOCKED | Phase 3 reliability/performance thresholds are not owner-approved. |
| Phase tests pass | PARTIAL | Owner reports 423/423 passing on Windows at baseline; isolated changed tree has 429 passes and four PostgreSQL-dependent failures without service. |
| Earlier-phase regression tests pass | PARTIAL | Owner's Windows suite includes regression coverage; P1-QG is `PROPOSED` and P2-QG is `NOT_STARTED`, with neither gate accepted. |
| Cross-phase integration tested | PARTIAL | Structured route live call is owner-reported; formal end-to-end acceptance criteria and broader integration evidence remain open. |
| Quality/security/resource/performance checks against predefined targets | BLOCKED | Targets are not approved; one successful call and one timeout are observations, not benchmark evidence. |
| Code, dependencies, configuration, docs, and risks reviewed | PASS (review only) | Four independent read-only reviews covered timeout/provider behavior, test/smoke safety, gate evidence, and RAG spec consistency. No unresolved findings remain; owner approval and environment checks remain separate. |
| Commands, environment, totals, failures, benchmarks recorded | PARTIAL | Owner evidence and final cloud test totals are attributed; target benchmark remains outstanding. |
| Gate decision recorded | BLOCKED | This record explicitly blocks closure; owner has not approved Phase 3 gate passage. |

## Outstanding blockers

1. Run the full suite and `alembic check` with a real PostgreSQL test service against the final changed tree; the owner reports the baseline Windows database checks pass, but the new timeout change has not been rerun there.
2. Resolve Phase 3 factual reliability/default-model and performance/resource targets before evaluating acceptance. TQ-11 retry policy and related open technical questions also need disposition.
3. Record Phase 1 and Phase 2 quality-gate evidence; P1-QG is `PROPOSED` and P2-QG is `NOT_STARTED`, and neither is accepted.
4. Obtain owner review of the timeout/smoke/doc change and rerun it on Windows.
5. Obtain explicit owner approval of the Phase 3 gate after all criteria are satisfied.

## Phase 4 readiness

`docs/PHASE4_RAG_SPEC_DRAFT.md` remains a proposal only. It has no Phase 4 production code, dependencies, extension, or migration. It must remain gated until Phase 3 passes and the owner authorizes Phase 4. Candidate RAG metrics and parser limits in that draft are explicitly unapproved proposals.
