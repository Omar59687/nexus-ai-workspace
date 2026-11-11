# Nexus AI Roadmap

**Document role:** Reconciled view of the official roadmap.

**Status:** The official 12-phase structure and numbering come from `docs/PROJECT_BLUEPRINT.md`. This document does not add phases, renumber phases, or amend the blueprint. It records actual status and maps Phase 3 internal checkpoints to the checkpoint ledger.

**Last verified:** 2026-11-11 against isolated baseline `19269930c25392343219587d6b70f1db6f6cca76` and the timeout/harness follow-up diff.

## 1. Roadmap reconciliation rule

- The blueprint's 12 phases remain the official roadmap.
- A phase is not complete because its implementation files exist. It is complete only after the Mandatory Phase Quality Gate in `docs/PROJECT_BLUEPRINT.md` passes and the gate decision is recorded.
- Phase 3 has internal tracking checkpoints (`P3-CP1` to `P3-CP6`) and a quality gate. These are checkpoints, not new phases.
- The frontend is Phase 8 by number, but it is deliberately deferred by owner decision until backend core functionality and integration are complete. Deferral does not change the phase number.
- No roadmap change is approved. Any proposal must explain why the existing numbering should change and must be approved by the owner.

## 2. Phase status

| Phase | Official name | Objective | Status | Evidence |
| --- | --- | --- | --- | --- |
| 1 | FastAPI Foundation | Project setup, application, health endpoint, Pydantic, error handling, logging, API tests | Implementation exists; formal gate not recorded | `P1-CP1`, `P1-CP2`; `P1-QG` proposed, not accepted |
| 2 | Database and Persistence | PostgreSQL, SQLAlchemy, Alembic, persistence models | Implementation exists; formal gate not recorded | `P2-CP1`; `P2-QG` not started |
| 3 | Local LLM Integration | Ollama, LangChain, structured outputs, local model benchmarks | In progress; quality gate blocked | `P3-CP1` to `P3-CP6`, `P3-DEC1`; `P3-QG` blocked |
| 4 | Production-Oriented RAG | Parsing, chunking, embeddings, vector retrieval, citations, evaluation, incremental indexing | Not started | No implementation |
| 5 | Data Analytics | CSV/Excel validation, Pandas analytics, charts, deterministic calculations | Not started | No implementation |
| 6 | Multi-Agent Orchestration | LangGraph supervisor, shared state, routing, checkpoints, approval flow | Not started | No implementation |
| 7 | MCP Integration | Local MCP server/client, permissions, safe tools, optional integrations | Not started | No implementation |
| 8 | React Dashboard | TypeScript UI, chat, uploads, task status, approvals, reports | Deferred by owner decision | No frontend; blocked until backend core and integration are complete |
| 9 | Background Processing | Introduce a queue only when needed; evaluate alternatives | Not started | No implementation |
| 10 | LLMOps and Evaluation | Reproducible evaluations, tracing, experiment comparisons, prompt versioning, performance measurement | Not started | No implementation |
| 11 | Security and Packaging | Security tests, configuration, Docker Compose packaging, CI, user documentation | Not started | No implementation |
| 12 | Enterprise Extensions | Authentication, teams, RBAC, tenant isolation, access-control tests | Not started | No implementation |

## 3. Phase 3 detail

Phase 3 is the only phase with active implementation work. Its status is not "complete."

| Checkpoint | Scope | Status |
| --- | --- | --- |
| `P3-CP1` | Local Ollama integration and `/llm/generate` | `IMPLEMENTED` |
| `P3-CP2` | Reproducible benchmark suite | `IMPLEMENTED` |
| `P3-CP3` | Generic structured-output engine and REST adapter | `IMPLEMENTED` |
| `P3-CP4` | Schema registry, structured service, model adapter | `ACCEPTED` by owner at `e45a7aa` |
| `P3-CP5` | FastAPI structured-output integration | `VERIFIED` in baseline commit `1926993`; owner reports Windows regression passed |
| `P3-CP6` | Dedicated service, adapter, API, and live-smoke safety tests | `BLOCKED` pending final Windows/PostgreSQL verification |
| `P3-DEC1` | LangChain necessity decision | `PROPOSED`; owner decision pending |
| `P3-QG` | Phase 3 quality gate | `BLOCKED` |

Phase 3 remains open and its quality gate is blocked. Checkpoint evidence and specific blockers are recorded in `docs/PROJECT_CHECKPOINTS.md` and `docs/P3_QG_EVIDENCE_2026-11-11.md`. The Phase 3 completion draft remains a proposal, not an approved plan.

## 4. Phase dependencies

```text
Phase 1 -> Phase 2 -> Phase 3 -> Phase 4 -> Phase 5 -> Phase 6 -> Phase 7
                                                              |
                                                              v
                                                         Phase 8 (deferred)
                                                              |
                                                              v
                                                         Phase 9 -> Phase 10 -> Phase 11 -> Phase 12
```

The arrows express the blueprint's intended order. They do not authorize starting a phase early. Phase 6 depends on the orchestration and state design; Phase 9 should introduce a queue only when evidence shows it is necessary.

## 5. Gate policy

Every phase must satisfy the eight Mandatory Phase Quality Gate criteria:

1. Acceptance criteria have explicit evidence.
2. Phase tests pass.
3. Regression tests for earlier completed phases pass.
4. Cross-phase integration is tested.
5. Quality, security, resource, and performance checks run against pre-defined targets.
6. Code, dependencies, configuration, documentation, and risks are reviewed.
7. Commands, environment, totals, failures, and benchmark results are recorded.
8. A gate decision is recorded; any failed criterion or unresolved critical/high issue blocks progress.

See `docs/PROJECT_CHECKPOINTS.md` for the evidence ledger and `docs/PROJECT_PLAN.md` for requirements and open questions.

## 6. Roadmap change proposals

None approved.

If a future proposal changes phase order, numbering, or scope, record it as a decision with:

- the affected phase numbers,
- the reason the current structure no longer fits,
- the impact on dependencies and earlier gates,
- the migration plan for status and evidence,
- owner approval.

Do not invent a new phase to make the current product vision fit the roadmap.
