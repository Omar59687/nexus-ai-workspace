# Phase 3 Gate Closure and Phase 4 Entry Checklist

**Status: Phase 3 remains BLOCKED.** This checklist records acceptance evidence
and owner decisions still required by the existing project documents. It does
not redefine the gate, approve draft thresholds, or accept Phase 3 or Phase 4.

**Evidence basis:** `docs/PROJECT_BLUEPRINT.md`, `docs/PROJECT_CHECKPOINTS.md`,
`docs/P3_GATE_AND_RAG_READINESS_2026-11-11.md`, and
`docs/PHASE4_RAG_SPEC_DRAFT.md`. The checkpoint ledger and readiness audit are
the status record used here. Their reported results are historical or
owner-reported unless an exact run transcript says otherwise. This checklist
does not convert those reports into a new test run.

## Gate criteria and evidence still required

The blueprint's eight mandatory criteria remain authoritative. The more
detailed Phase 3 D1–D8 questions are explicitly proposals until the owner
approves them.

| Mandatory criterion | Ledger/audit status | Evidence or decision still required |
| --- | --- | --- |
| 1. Pre-agreed acceptance criteria | **BLOCKED** | Owner disposition of D1–D8 and TQ-01–TQ-11; approved reliability, factual-quality, performance/resource targets and integration matrix. Preserve unapproved values as proposals. |
| 2. Phase tests | **PARTIAL** | Current-candidate focused API, negative-path, integration and regression transcripts with environment/version details. The ledger records 166 focused tests for CP6, but the full candidate was not green. Live Ollama smoke remains unrun; fake-based tests do not replace it. |
| 3. Earlier-phase regression | **PARTIAL / BLOCKED** | Phase 1 is `PROPOSED`; Phase 2 is `NOT_STARTED`. Both need evidence packages and gate decisions; Phase 2 also needs PostgreSQL CRUD, migration, dependency, and review evidence. |
| 4. Cross-phase integration | **PARTIAL** | Owner-approved D8 matrix and current-candidate execution evidence. Include API/service, structured-output/model adapter, benchmark, and PostgreSQL flows as applicable. Live Ollama and PostgreSQL were not available in the cited cloud run. |
| 5. Quality, security, resources, performance | **BLOCKED** | Targets approved before measurement, followed by reproducible candidate results with model/runtime versions, hardware, settings, completion state, timing, tokens and resource data. Synthetic RAG fixtures are not real-corpus accuracy evidence. |
| 6. Review | **PARTIAL** | Final review of the exact candidate diff, dependencies, configuration, documentation, and risks, with reviewer identity, inspected scope, and disposition. Existing checkpoint reviews do not substitute for candidate review. |
| 7. Reproducible evidence | **PARTIAL** | Exact Windows transcript and current candidate SHA covering full suite, focused tests, `pip check`, `alembic check`, compile and whitespace checks; preserve benchmark reports and environment details. Historical owner totals remain historical. |
| 8. Gate decision | **BLOCKED** | Explicit owner gate decision after criteria and evidence are complete, with unresolved high/critical issues cleared. |

## Phase 3 checkpoint blockers

- `P3-CP1`–`P3-CP3` are recorded as implemented, but their sections do not
  provide complete checkpoint-specific run and review evidence.
- `P3-CP4` is recorded as owner-accepted at `e45a7aa`; its Windows results are
  owner-reported and were not rerun in the later isolated environment.
- `P3-CP5` is recorded as verified, with owner-reported Windows results. The
  current ledger does not establish final full-candidate integration evidence.
- `P3-CP6` is **BLOCKED**. The recorded focused command passed 166 tests; the
  full isolated run had 429 passes and four PostgreSQL connection failures.
  PostgreSQL-backed regression and Alembic verification remain necessary.
- `P3-DEC1` / ADR-0011 is **PROPOSED**. The owner must decide whether LangChain
  is adopted, deferred, or rejected for a defined use case.
- The readiness audit records `TQ-01`–`TQ-11` as dependencies. Resolve and
  record owner decisions before calling the Phase 3 gate complete. In
  particular, D1–D8 cover checkpoint sequence, factual reliability, the
  default model and its known limitation, LangChain, structured-output scope,
  performance/resource targets, and cross-phase integration.

## Minimum ordered closure sequence

1. Reconcile and approve Phase 1 and Phase 2 gate evidence; do not assume their
   implementation checkpoints imply acceptance.
2. Record owner decisions for D1–D8, TQ-01–TQ-11, and ADR-0011. Do not change
   the default LLM or adopt new thresholds by inference.
3. Run CP6 and the full regression on one exact candidate in the configured
   Windows environment with PostgreSQL available. Record the exact commands,
   Python/dependency/database versions, test totals, and output. Run
   `pip check`, `alembic check`, compilation, and `git diff --check` on that
   same candidate.
4. Run the approved cross-phase matrix and live Ollama checks where required.
   Mark unavailable infrastructure as blocked; do not substitute fakes for
   live integration evidence.
5. Run approved benchmark cases against pre-approved criteria and preserve
   machine-readable reports. Record model/Ollama versions, device/hardware,
   generation completion, settings, tokens, latency, and resource use.
6. Obtain an independent review of the final candidate and resolve any
   critical/high findings. Record reviewer, scope, and disposition.
7. Assemble the final evidence ledger and request the explicit owner gate
   decision. Keep Phase 3 open until that decision is recorded.

## Phase 4 entry and acceptance boundary

`docs/PHASE4_RAG_SPEC_DRAFT.md` remains a proposal and states production Phase
4 is not authorized until Phase 3 passes and the owner approves Phase 4. Work
on an explicitly authorized experimental branch can be reviewed as isolated
engineering; it does not satisfy either condition and must not be activated
through a public route or presented as production-ready.

Before Phase 4 acceptance, the owner must approve its scope and any proposed
thresholds. Evidence must include a frozen document-level development/holdout
split, bilingual and cross-language evaluation, answerable and no-answer
behavior, citation span validity, deterministic re-ingestion, path safety,
resource limits, and a reviewable workload report. Holdout data must not be
used for tuning. The draft's numerical retrieval and resource thresholds are
candidate values only, not accepted targets.

The current experimental candidate includes an in-memory service plus a
PostgreSQL DB-API adapter and candidate DDL, but it has no reviewed/applied
migration and no disposable-PostgreSQL verification. It still has no real
application authentication/authorization boundary, public routes, or durable
workers. The POSIX PDF worker applies resource limits but is not a full OS
sandbox; PDF ingestion fails closed on Windows. The no-route candidate's
process-local idempotency is bounded, but production jobs require durable
idempotency. Grounded-answer tests verify citation identity and numeric-token
constraints, not semantic entailment. No PostgreSQL extension or migration is
approved by the RAG draft; resolve TQ-14 and obtain owner approval before
selecting or applying one. A synthetic test result or a small provisional
owner-reviewed corpus cannot establish production accuracy or independent
ground truth.

## Documentation consistency note

`docs/PROJECT_BLUEPRINT.md` still says the project is in “Planning / repository
setup” and points to Task 1.1. That current-status paragraph is stale relative
to the implemented checkpoints in `docs/PROJECT_CHECKPOINTS.md`; reconcile it
as a separately reviewed documentation change. Do not change the official
gate criteria while doing so.
