# Phase 3 Gate and RAG Readiness Audit — 2026-11-11

## Scope and repository identity

This audit uses the experimental branch snapshot at
`fd04898e9517d9cc164d0984add6caf69baaa9d9`
(`experiment: harden bilingual RAG evaluation and Windows safety`). The
checkout was created as an isolated detached clone. No `.env` or credential
files were opened. No production RAG activation, database operation, commit,
push, or merge occurred.

The tracked files `docs/P3_GATE_RECONCILIATION_2026-11-11.md`,
`docs/P3_QG_EVIDENCE_2026-11-11.md`, `docs/PROJECT_CHECKPOINTS.md`, and
`docs/ARCHITECTURE.md` describe a different snapshot: `phase-1/foundation` at
`19269930...`. Their results remain useful historical evidence for that
snapshot, but they are not a current identity record for `fd04898`. The
checkpoint ledger's Phase 3 status is `BLOCKED`; nothing in this audit changes
that decision.

The owner reports that the Windows checkout at the requested baseline passed
500 tests, PostgreSQL/Alembic, compilation, and dependency checks. This report
does not contain the Windows console transcript, command line, dependency
versions, or database/runtime details, and those checks were not rerun here.
Treat them as owner-reported evidence, not as a run performed by this audit.

## Quality-gate matrix

The official requirements are the eight criteria in
`docs/PROJECT_BLUEPRINT.md` under “Mandatory Phase Quality Gate.” The more
detailed D1–D8 / D1–D8 checklist in `docs/PHASE3_COMPLETION_PLAN_DRAFT.md` is
explicitly a proposal pending owner approval; it must not be described as an
approved contract.

| Official criterion | Current status | Evidence and remaining acceptance evidence |
| --- | --- | --- |
| 1. Pre-agreed acceptance criteria | **BLOCKED** | The blueprint gives general gate criteria. Phase 3 reliability, factual-quality, performance/resource thresholds, and the specific cross-phase matrix are not approved. Draft questions D1–D8 remain proposals. Record owner-approved criteria and decision outcomes before judging results. |
| 2. Phase unit/API/negative/integration tests | **PARTIAL** | The tree contains extensive deterministic tests for Ollama timeout/error mapping, structured generation, invalid/incomplete output, FastAPI error handling, and RAG fixtures. The owner reports 500 Windows tests passed. No current transcript was supplied, and this environment lacks pytest. Live Ollama smoke is opt-in and was not run here. |
| 3. Earlier-phase full regression | **PARTIAL** | The owner reports the full suite passed on Windows. `P1-QG` remains `PROPOSED`; `P2-QG` remains `NOT_STARTED` in the ledger. Current candidate evidence must include exact Windows command/environment and a PostgreSQL-backed full-suite run. |
| 4. Cross-phase integration | **PARTIAL** | The suite has FastAPI↔structured-service/adapter tests using fakes, FastAPI↔task/PostgreSQL integration tests, and benchmark runner/scoring tests. Live Ollama and PostgreSQL execution were not available here. D8's approved integration matrix and execution evidence remain absent. |
| 5. Quality/security/resource/performance against predefined targets | **BLOCKED** | No approved Phase 3 target values were found. A single model call or timeout is not reliability evidence. RAG measurements in this repository use public synthetic fixtures, not real corpus evidence. Record live model/runtime/hardware/settings/completion/tokens and compare against targets approved before measurement. |
| 6. Review of code/dependencies/config/docs/risks | **PARTIAL** | CP5 review notes and RAG hardening reviews are recorded. Independent review of this audit's limited changes found and corrected a test seal ordering issue and strategy-metadata issue. Current docs still contain stale branch identity. Full candidate review and owner review remain required. |
| 7. Reproducible evidence record | **PARTIAL** | Historical and owner-reported totals exist, but the current 500-test Windows output is not attached. This audit records its checkout SHA and local limitations. Run logs, versions, benchmark records, and a current evidence ledger entry remain required. |
| 8. Gate decision | **BLOCKED** | Phase 3 remains blocked. The owner has not supplied an explicit acceptance decision, and criteria/evidence above remain incomplete. |

### Explicit evidence gaps before Phase 3 can be accepted

1. Owner approval/disposition for the Phase 3 scope questions, including the
   LangChain decision, default-model/factual reliability expectations, retry
   policy, performance/resource targets, and cross-phase matrix. Preserve
   proposals as proposals until the owner decides.
2. Phase 1 and Phase 2 gate evidence and decisions; they are not accepted in
   the current checkpoint ledger.
3. A current Windows transcript for full regression, focused Phase 3 tests,
   `pip check`, `alembic check`, compilation, and `git diff --check` on the
   exact candidate SHA, including environment and exact totals.
4. PostgreSQL-backed and live-Ollama integration evidence on that candidate.
   If infrastructure is unavailable, mark the relevant check blocked rather
   than substitute a fake-client test.
5. Reproducible benchmark evidence against pre-approved targets, including
   model and Ollama versions, hardware/device, settings, completion status,
   timing, tokens, and preserved reports.
6. Current branch-specific architecture/checkpoint documentation and a final
   independent review plus explicit owner gate decision.

## Implemented, reproducible RAG tooling improvements in this snapshot

- The human-judgment conversion now validates its completed evaluation fixture
  before returning it. A contradictory `evidence_language` and accepted
  relevant-chunk labels fail at fixture construction, rather than waiting for
  a later evaluation command.
- Optional hybrid E5+BM25 retrieval now accepts a separate minimum fused RRF
  score for abstention. The CLI option is `--hybrid-minimum-rrf-score`, and the
  result metadata reports the cutoff only for the hybrid strategy. The dense
  cosine cutoff remains separate as `--e5-minimum-score`.
- Regression tests cover those paths. Focused and full test execution results
  must be recorded separately below; no live model or corpus scores are claimed.

The current dataset workflow remains intentionally bounded: it exports
exhaustive query×document×chunk annotation rows and stops above 100,000 rows.
It does not implement candidate-pool manifests or blind reviewer sheets. For a
larger real corpus, add and review that capability before reducing the pool.
Document-level judgments are preserved as annotations; current retrieval
metrics are chunk-level.

## Verification record in this environment

- Repository: isolated clone of `experiment/p4-rag-prototype`.
- HEAD: `fd04898e9517d9cc164d0984add6caf69baaa9d9`.
- Working-tree changes: this audit's docs, code, and regression tests only.
- Python: 3.12.14.
- `python -m unittest discover -s tests -p 'test_rag*.py' -v`: **PASS** — 71
  tests run, 69 passed, and 2 Windows-junction-only tests skipped on Linux.
  This is the RAG unittest inventory; it does not include pytest-style tests
  outside this RAG subset.
- `python -m pytest -q`: **NOT RUN** — pytest is not installed in this
  environment.
- PostgreSQL/Alembic checks: **NOT RUN** — no local PostgreSQL service is
  configured for this clone.
- Live Ollama/E5: **NOT RUN** — no local live-service/model-cache verification
  was performed. The E5 CLI reported that optional `torch` and `transformers`
  packages are unavailable; no weights were downloaded.
- `python -m compileall -q src tests scripts experiments`: **PASS**.
- `git diff --check`: **PASS**.
- Synthetic dev CLI: **PASS**, completed for six synthetic questions; its
  displayed numbers are only fixture diagnostics and are not real-corpus
  retrieval quality evidence.
- E5 threshold without `--with-e5`: **PASS** — rejected with exit code 2.
  E5 run without optional dependencies: **NOT RUN**, rejected with an explicit
  message and exit code 2.

Phase 3 remains **BLOCKED** after this audit. No synthetic metric is evidence
of real retrieval quality.
