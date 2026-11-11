# Nexus AI Project Plan

**Document role:** Master plan and requirements baseline.

**Status:** Operational plan reconciled on 2026-11-11. CP5 changes remain uncommitted for owner review; this does not imply Phase 3 gate acceptance.

**Repository identity:** isolated branch `phase-1/foundation`, baseline `e45a7aa2a7b7d69dea808b6811e69ca1afd74ec4`; see the checkpoint evidence for the uncommitted CP5/CP6 diff.

**Authoritative sources:** `docs/PROJECT_BLUEPRINT.md`, `docs/PHASE3_COMPLETION_PLAN_DRAFT.md`, `docs/BENCHMARKS.md`, committed source and tests, and the owner-approved direction recorded for this documentation task. Where this plan and the code disagree, the code and the owner's decision prevail. Update this plan instead of relying on chat history.

## 1. Product vision and goals

Nexus AI is an All-in-One AI Workspace and Multi-Agent Platform. It is intended to combine workspace and project management, document intelligence, structured data extraction, memory, multi-agent orchestration, and observable, durable workflows in one local-first system.

The product is also a learning project: the owner is the primary developer, and each phase must produce evidence, tests, and reviewable decisions rather than unsupported claims.

### Goals

1. **Unify work:** one workspace for projects, documents, tasks, agents, memory, and results.
2. **Ground answers:** document answers must be supported by retrieved, citable evidence.
3. **Extract reliably:** structured outputs must pass deterministic schema and semantic validation.
4. **Orchestrate deliberately:** agents are selected dynamically for a task, not hard-wired into one fixed pipeline.
5. **Remember with scope:** personal and project memory are separate, permissioned concepts.
6. **Serve bilingual users:** Arabic and English are first-class product requirements.
7. **Run locally first:** core workflows use local models and local infrastructure; cloud providers are optional.
8. **Operate safely:** role-based permissions, audit logging, and human approval for sensitive actions.
9. **Observe honestly:** record tokens, latency, resources, and costs only from measured data.
10. **Evolve without rework:** local development must not block future self-hosted or SaaS-ready deployment.

### Current non-goals

- No frontend until core backend functionality and integration are complete.
- No claim that planned memory, RAG, agents, durable execution, RBAC, audit logging, or SaaS tenancy exist.
- No paid dependency is required for core workflows.
- No benchmark, scoring rule, threshold, or historical report may be rewritten to manufacture a pass.

## 2. Target users

These are product hypotheses, not validated personas.

| User group | Primary need | Notes |
| --- | --- | --- |
| Owner/developer | Build and learn in small, evidence-backed phases | Current primary user |
| Individual knowledge worker | Analyze documents and structured data; get grounded answers | Arabic or English |
| Small team | Share projects, memory, workflows, and approvals | Requires RBAC and audit |
| Self-hoster | Run the stack on local or private infrastructure | Future deployment target |
| Future SaaS customer | Use the same capabilities as a managed service | Architecture should not block it; not implemented |

## 3. Owner-approved requirements

### 3.1 Decision register source note

The owner reports that 37 product decisions are complete. No separate 37-item decision log existed in the repository when this plan was written. The register below is an atomic restatement of the owner-approved direction supplied for this documentation task and the approved engineering principles already recorded in `docs/PROJECT_BLUEPRINT.md`. It adds no new commitments. If the owner's original enumeration differs, the owner's record prevails and this table must be reconciled.

Approval of a product decision does not imply that the capability is implemented, tested, reviewed, or accepted. Implementation status is tracked in `docs/PROJECT_CHECKPOINTS.md`.

### 3.2 The 37 approved decisions

| ID | Approved decision | Source | Implementation status |
| --- | --- | --- | --- |
| D-01 | Nexus AI is an All-in-One AI Workspace and Multi-Agent Platform. | Owner brief | Product identity; not a runtime claim |
| D-02 | Workspace management is a core capability. | Owner brief | Approved direction; not implemented |
| D-03 | Project management is a core capability. | Owner brief | Approved direction; not implemented |
| D-04 | Multi-agent orchestration is dynamic, not a fixed single-agent pipeline. | Owner brief | Approved direction; not implemented |
| D-05 | Personal memory is a core capability. | Owner brief | Approved direction; not implemented |
| D-06 | Project memory is a core capability. | Owner brief | Approved direction; not implemented |
| D-07 | Arabic is a supported product language. | Owner brief | Approved direction; no localization implementation |
| D-08 | English is a supported product language. | Owner brief | Approved direction; documentation is English; no localization implementation |
| D-09 | Core AI execution is local-first. | Owner brief, blueprint | Partially implemented with local Ollama and PostgreSQL |
| D-10 | Cloud AI providers are optional and never required for core workflows. | Owner brief, blueprint | Approved direction; no provider abstraction or cloud integration |
| D-11 | Document Intelligence is a core capability. | Owner brief | Approved direction; not implemented |
| D-12 | Answers about documents must be grounded in retrieved evidence. | Owner brief | Approved direction; not implemented |
| D-13 | The product extracts structured data from content. | Owner brief | Approved direction; only a REST-explanation schema demo exists |
| D-14 | Extracted structured data is semantically validated. | Owner brief | Demonstrated only for the REST demo; not a general capability |
| D-15 | PostgreSQL is the primary operational database. | Owner brief | Implemented for the current `workspace_tasks` model |
| D-16 | pgvector is proposed for vector search; it is not yet adopted. | Owner brief | Proposed only |
| D-17 | Workflow execution must be durable. | Owner brief | Approved direction; not implemented |
| D-18 | Access control is role-based. | Owner brief | Approved direction; not implemented |
| D-19 | Security-relevant actions are recorded in an audit log. | Owner brief | Approved direction; not implemented |
| D-20 | Sensitive actions require human approval. | Owner brief | Approved direction; not implemented |
| D-21 | Observability includes token usage. | Owner brief | Partial: Ollama counts and benchmark reports; no product telemetry |
| D-22 | Observability includes latency. | Owner brief | Partial: Ollama durations and benchmark medians; no product telemetry |
| D-23 | Observability includes resource usage. | Owner brief | Partial: benchmark runtime metrics only |
| D-24 | Observability includes cost. | Owner brief | Approved direction; no cost accounting implemented |
| D-25 | Local development is the first deployment mode. | Owner brief | Implemented as the current mode |
| D-26 | Self-hosted deployment is a future target. | Owner brief | Approved direction; not implemented |
| D-27 | The architecture should be SaaS-ready without claiming SaaS is implemented. | Owner brief | Approved direction; no tenancy or SaaS implementation |
| D-28 | The frontend is deferred until core backend functionality and integration are complete. | Owner brief | Deferred; no frontend exists |
| D-29 | Core workflows must run with a $0 software budget. | Blueprint | Operating principle; no cost audit recorded |
| D-30 | The owner is the primary developer and learning is an explicit project goal. | Blueprint | Operating principle |
| D-31 | Work proceeds through phase gates; the next phase does not start until the current gate passes. | Blueprint | Policy adopted; formal gate evidence is incomplete for Phases 1-2 |
| D-32 | Claims require measured evidence; unrun tests must never be reported as passing. | Blueprint, task brief | Policy adopted; evidence gaps are recorded in the checkpoints |
| D-33 | Security by default: restrict tool and filesystem permissions and require approval for sensitive actions. | Blueprint | Partial: `.env` is ignored; no auth or tool-permission layer |
| D-34 | Development uses a dedicated branch; `main` stays stable; merges follow review. | Blueprint | Development is on `phase-1/foundation`; no merge evidence recorded |
| D-35 | Initial development targets Windows on the documented 16 GB RAM / 2 GB VRAM machine. | Blueprint | Environment target documented; hardware was not re-verified |
| D-36 | The official 12-phase roadmap numbering is preserved; changes need a documented proposal. | Blueprint, task brief | Policy adopted; preserved in `docs/ROADMAP.md` |
| D-37 | Five logical agent roles are planned; they may share one local model, and deterministic tools are preferred for well-defined operations. | Blueprint | Proposed architecture; no agents implemented |

### 3.3 What approval does mean

- These are commitments about product direction and engineering discipline.
- They may be refined only through a recorded decision that cites the affected IDs.
- They do not override the phase gates, acceptance criteria, or evidence requirements.

## 4. Functional requirements

Status values here describe implementation, not approval. Detailed checkpoint evidence lives in `docs/PROJECT_CHECKPOINTS.md`.

| ID | Requirement | Related decisions | Current status |
| --- | --- | --- | --- |
| FR-01 | Create and manage workspaces and projects with clear ownership and scope. | D-02, D-03 | Not implemented |
| FR-02 | Select and coordinate agents dynamically for a task. | D-04, D-37 | Not implemented |
| FR-03 | Store and retrieve personal and project memory with separate scope. | D-05, D-06 | Not implemented |
| FR-04 | Support Arabic and English input, retrieval, output, and evaluation. | D-07, D-08 | Not implemented |
| FR-05 | Use local models by default and optional cloud providers through one abstraction. | D-09, D-10 | Local generation only; no provider abstraction |
| FR-06 | Ingest documents and answer questions with grounded, cited evidence. | D-11, D-12 | Not implemented |
| FR-07 | Extract structured data and validate it against schema and domain rules. | D-13, D-14 | REST demo only |
| FR-08 | Execute workflows durably and resume after failure or restart. | D-17 | Not implemented |
| FR-09 | Enforce RBAC, audit security-relevant actions, and require approvals. | D-18, D-19, D-20 | Not implemented |
| FR-10 | Record tokens, latency, resources, and costs for observable runs. | D-21 to D-24 | Partial runtime and benchmark metrics |
| FR-11 | Support local development now and self-hosted/SaaS-ready deployment later. | D-25 to D-27 | Local only |
| FR-12 | Defer the frontend until backend core and integration are complete. | D-28 | Deferred by decision |
| FR-13 | Persist workspace tasks with validated CRUD operations. | D-15 | Implemented and committed |
| FR-14 | Generate text through a local Ollama endpoint with categorized failures. | D-09 | Implemented and committed |

## 5. Non-functional requirements

| ID | Requirement | Current status |
| --- | --- | --- |
| NFR-01 | Local-first execution and privacy by default. | Partial: local stack; no data-governance features |
| NFR-02 | Core workflows must not require paid software or cloud APIs. | Operating principle; no formal cost audit |
| NFR-03 | Reproducible tests and benchmarks with recorded evidence. | Partial: tests and benchmark reports exist; evidence retention is inconsistent |
| NFR-04 | Security by default, including secret handling and least privilege. | Partial: `.env` ignored; no auth/permission layer |
| NFR-05 | Auditability of sensitive actions. | Not implemented |
| NFR-06 | Performance and resource targets defined before judging results. | Open; Phase 3 targets not approved |
| NFR-07 | Reliability: incomplete generations and failed workflows must not be reported as success. | Implemented for benchmarks; not implemented for workflows |
| NFR-08 | Bilingual quality for Arabic and English. | Not implemented or evaluated |
| NFR-09 | Portability across local, self-hosted, and future SaaS deployment. | Local only; target design only |
| NFR-10 | Observability without fabricated metrics. | Partial |
| NFR-11 | Maintainable, typed, tested code with small reviewable changes. | Partial; review evidence gaps exist |
| NFR-12 | API compatibility and versioning strategy. | Open |

## 6. Implemented capabilities

Implemented means code exists in the repository at the stated commit. It does not mean accepted. Acceptance requires the evidence and review rules in Section 11.

| Capability | Evidence | Status |
| --- | --- | --- |
| FastAPI application, root, health, OpenAPI, generic error handler | `src/nexus_ai/main.py`, `tests/test_api.py`, commit `98cdb77` | Implemented; no formal phase-gate acceptance recorded |
| PostgreSQL persistence and task CRUD | `src/nexus_ai/database.py`, `src/nexus_ai/models.py`, `src/nexus_ai/schemas.py`, Alembic migration, commit `50663ad` | Implemented; no formal phase-gate acceptance recorded |
| Ollama HTTP client and `/llm/generate` endpoint | `src/nexus_ai/ollama.py`, `tests/test_ollama_client.py`, `tests/test_llm_api.py`, commit `9b8227e` | Implemented; no formal phase-gate acceptance recorded |
| Reproducible local benchmark subsystem | `src/nexus_ai/benchmark/`, `benchmarks/cases.json`, `scripts/run_llm_benchmark.py`, commit `17eb240` | Implemented; benchmark results are local evidence |
| Generic structured-output generate/validate/retry engine and REST adapter | `src/nexus_ai/structured_output_pipeline.py`, `src/nexus_ai/structured_outputs.py`, commit `328c823` | Implemented and committed; historical regression coverage reported |
| Local schema registry, structured service, and ChatOllama adapter | `src/nexus_ai/structured_schemas.py`, `src/nexus_ai/structured_service.py`, `src/nexus_ai/model_adapters.py` | In baseline e45; CP4 accepted by owner; owner-reported Windows checks recorded in checkpoint ledger |
| Registry-backed structured generation API | `POST /structured/generate`; `src/nexus_ai/main.py`, `src/nexus_ai/schemas.py` | Implemented in uncommitted CP5 diff; 300 focused tests pass; two review cycles clear; owner review pending |
| Documentation foundation | This document set | Implemented; owner review pending |
| Software Factory V2 profiles | `.opencode/agents/`, `docs/SOFTWARE_FACTORY_V2.md`, commit `38a2813` | Configured; native smoke test reported blocked |

The model-generation endpoints are `POST /llm/generate` and the uncommitted CP5 `POST /structured/generate`. There is no document endpoint, memory endpoint, agent endpoint, or workflow endpoint.

## 7. Proposed technical design (not implemented)

Everything in this section is a proposal unless an ADR marked accepted says otherwise. See `docs/ARCHITECTURE.md` for the current-versus-target separation.

### 7.1 AI provider strategy

- Local Ollama is the default provider.
- Cloud providers are optional adapters behind a provider abstraction.
- Core workflows must remain functional without cloud credentials.
- Model selection should be task-aware and evidence-based, not speed-only.
- Every provider adapter must expose completion status and measured usage metadata.
- Fallback to a cloud provider must never happen silently.

### 7.2 Memory and document strategy

- Personal memory is scoped to one user; project memory is scoped to one project.
- Memory requires retention, deletion, access-control, and provenance rules.
- Document ingestion requires parsing, chunking, embeddings, indexing, and citation metadata.
- Grounded answers must cite retrieved evidence; retrieval success does not prove factual truth.
- Incremental indexing and evaluation are required before the RAG phase can close.
- pgvector is the proposed vector store because PostgreSQL is already the operational database.

### 7.3 Agent orchestration

- Planned logical roles: Supervisor, Document, Data, Research, Report.
- Roles are not a requirement to run five separate models or processes.
- The orchestrator selects only the roles needed for a task and records the routing decision.
- Shared state, checkpoints, approvals, and deterministic tools are part of the target design.
- Orchestration is not implemented.

### 7.4 Durable execution

- Workflow state must survive process restarts.
- Steps should be idempotent or compensated; retries must be bounded.
- Human approval waits and failure recovery must be explicit states.
- The execution engine is not selected; see ADR-0009.

### 7.5 Permissions and security

- Target: roles, permissions, tenant boundaries, audit events, and approval gates.
- Current: local environment variables, Git-ignored `.env`, no authentication, no RBAC, and no audit log.
- Sensitive actions must never rely on prompt instructions alone for authorization.

### 7.6 Observability

- Target: per-request and per-workflow token, latency, resource, and cost records.
- Current: Python logging, Ollama response metrics, benchmark JSON reports, and local uncommitted service metrics.
- Observability data must be measured or explicitly marked unavailable; never fabricated.
- Audit logging is a separate security concern from performance observability.

### 7.7 Deployment

- Current: Windows host running FastAPI and Ollama; PostgreSQL 17 in Docker Compose.
- Target: self-hosted packaging, then SaaS-ready architecture without premature multi-tenancy.
- No application container, CI pipeline, reverse proxy, or production deployment exists.

## 8. Technology choices and rationale

| Technology | Status | Rationale |
| --- | --- | --- |
| Python 3.12 | Implemented | Declared runtime requirement; local-first tooling |
| FastAPI | Implemented | Typed HTTP API, OpenAPI, test client support |
| Pydantic v2 | Implemented | Request/response schemas and structured-output models |
| SQLAlchemy 2 | Implemented | Typed ORM and explicit transaction control |
| psycopg 3 | Implemented | PostgreSQL driver |
| Alembic | Implemented | Versioned schema migrations |
| PostgreSQL 17 | Implemented | Operational database; proposed pgvector extension point |
| Docker Compose | Implemented for PostgreSQL only | Reproducible local database service |
| Ollama | Implemented | Local model runtime without paid APIs |
| LangChain Core and `langchain-ollama` | Dependency and CP4 adapter present; used by uncommitted CP5 route | Proposed local structured-output integration; ADR-0011 owner decision and dependency/resource review remain open |
| Pytest and FastAPI TestClient | Implemented | Unit and API testing |
| React, TypeScript, Vite | Proposed, deferred | Frontend phase is blocked by owner decision |
| pgvector | Proposed | Keeps vector search in PostgreSQL if validated |
| LangGraph | Proposed | Candidate for orchestration and durable state |
| MCP Python SDK | Proposed | Roadmap Phase 7 integration |
| Pandas and OpenPyXL | Proposed | Roadmap Phase 5 deterministic data analysis |
| OpenTelemetry | Proposed | Observability standard candidate |
| GitHub Actions | Proposed | CI within free usage limits; no workflow exists |

Dependency hygiene note: `pyproject.toml` declares `httpx2` in the `dev` extra, while the local structured adapter imports `httpx` and `ollama` directly. These are potential environment reproduction gaps and are recorded as TQ-22.

## 9. Development roadmap

The official roadmap remains the 12 phases in `docs/PROJECT_BLUEPRINT.md`. Phase numbering is preserved. Phase 3 has internal tracking checkpoints, not new phases. See `docs/ROADMAP.md` for the reconciled view.

| Phase | Name | Current status |
| --- | --- | --- |
| 1 | FastAPI Foundation | Implementation exists; formal gate not recorded |
| 2 | Database and Persistence | Implementation exists; formal gate not recorded |
| 3 | Local LLM Integration | In progress; quality gate blocked |
| 4 | Production-Oriented RAG | Not started |
| 5 | Data Analytics | Not started |
| 6 | Multi-Agent Orchestration | Not started |
| 7 | MCP Integration | Not started |
| 8 | React Dashboard | Deferred until backend core and integration are complete |
| 9 | Background Processing | Not started |
| 10 | LLMOps and Evaluation | Not started |
| 11 | Security and Packaging | Not started |
| 12 | Enterprise Extensions | Not started |

## 10. Major dependencies

### Current declared dependencies

- Python 3.12
- FastAPI, Uvicorn, Pydantic
- SQLAlchemy, psycopg, Alembic
- python-dotenv
- langchain-core, langchain-ollama
- pytest (development)
- PostgreSQL 17 (runtime service)
- Ollama (runtime service)

### Proposed or unapproved dependencies

- pgvector extension for PostgreSQL
- LangGraph
- MCP Python SDK
- Pandas and OpenPyXL
- OpenTelemetry
- React, TypeScript, Vite
- A queue/broker system only if Phase 9 evidence requires one

Do not install a proposed dependency merely because it appears in this plan. It requires the decision and checkpoint process.

## 11. Definition of Done

### 11.1 Checkpoint Definition of Done

A checkpoint may move to `ACCEPTED` only when all of the following are true:

1. Every task and acceptance criterion is satisfied.
2. Required tests were actually run against the stated environment and the output is recorded.
3. The review disposition is recorded and no unresolved critical or high-severity issue remains.
4. Documentation and checkpoint evidence match the implementation.
5. The owner or delegated reviewer explicitly accepts the checkpoint.

Implementation does not equal acceptance. File existence, a green commit, or an agent report does not equal acceptance.

### 11.2 Phase Definition of Done

The eight criteria in `docs/PROJECT_BLUEPRINT.md` apply:

1. Acceptance criteria have explicit evidence.
2. Phase tests pass.
3. Regression tests for all earlier completed phases pass.
4. Cross-phase integration is tested.
5. Quality, security, resource, and performance checks are run against pre-defined targets.
6. Code, dependencies, configuration, documentation, and risks are reviewed.
7. Commands, environment, totals, failures, and benchmark results are recorded.
8. A gate decision is made; any failed criterion or unresolved critical/high issue blocks progress.

### 11.3 Documentation Definition of Done

- Internal links resolve.
- Claims distinguish approved, implemented, proposed, and unapproved work.
- Historical results are labeled as historical and not presented as newly executed.
- The checkpoint tracker is updated with actual evidence.
- `.env` contents are never read, printed, or committed.

## 12. Open technical questions

These are not product decisions. They require technical evidence, owner approval, or both. IDs TQ-01 to TQ-08 correspond to D1-D8 in `docs/PHASE3_COMPLETION_PLAN_DRAFT.md`.

| ID | Open question | Needed before |
| --- | --- | --- |
| TQ-01 | Is the proposed Phase 3 checkpoint sequence approved? | Any further Phase 3 checkpoint work |
| TQ-02 | Is factual model reliability a Phase 3 exit criterion? If so, which cases, models, and threshold? | Phase 3 quality gate |
| TQ-03 | Is the `llama3.2:latest` REST factual limitation accepted or remediated? | Phase 3 quality gate |
| TQ-04 | Is LangChain required for a defined Phase 3 use case, or deferred/rejected? | Production structured-output design |
| TQ-05 | Is schema-constrained structured output a production requirement? If so, what contract and failure behavior? | Structured-output API integration |
| TQ-06 | Which model remains the production default? | Phase 3 quality gate |
| TQ-07 | What performance and resource targets apply to Phase 3? | Performance evaluation |
| TQ-08 | What cross-phase integration evidence is required for Phase 3 closure? | Phase 3 quality gate |
| TQ-09 | What is the public structured-output API contract: endpoint, schema selection, error mapping, and metrics exposure? | FastAPI structured-output integration |
| TQ-10 | How are schema names, versions, and migrations governed? | Schema registry production use |
| TQ-11 | Is the current two-attempt retry cap correct, and which failure classes are retryable? | Structured-output acceptance |
| TQ-12 | Which durable execution engine or pattern will be evaluated: LangGraph checkpoints, database-backed state, or a queue? | Phase 6 or Phase 9 design |
| TQ-13 | What are the memory scope, retention, deletion, and access rules for personal and project memory? | Memory design |
| TQ-14 | Which embedding model and vector index strategy are required, and is pgvector adopted? | RAG design |
| TQ-15 | What document parsing, chunking, and citation format is required for Document Intelligence? | RAG design |
| TQ-16 | What RBAC role and permission model applies, and where is the tenant boundary? | Security design |
| TQ-17 | Which audit events are mandatory, and what are their retention and immutability rules? | Security design |
| TQ-18 | What approval workflow, timeout, and escalation rules apply to sensitive actions? | Human-in-the-loop design |
| TQ-19 | Which observability backend and cost-accounting source are authoritative? | Observability implementation |
| TQ-20 | What Arabic/English localization and evaluation strategy is required? | Bilingual implementation |
| TQ-21 | What deployment packaging and CI target is approved: local, self-hosted, or SaaS-first? | Phase 11 |
| TQ-22 | How will the `httpx2` dev-extra discrepancy, undeclared direct imports, and PostgreSQL-dependent tests be resolved? | Reproducible test environment |
| TQ-23 | What durable evidence artifact will make test runs auditable beyond terminal output and pytest cache? | Any acceptance decision |
| TQ-24 | What frontend contract and backend readiness criteria unblock Phase 8? | Frontend phase |

## 13. Risks and limitations

| Risk | Impact | Current mitigation |
| --- | --- | --- |
| Documentation drift, including the stale Current status in the blueprint | Future agents may trust wrong status | This document set and checkpoints are the operational source; update them |
| Untracked structured-output files could be lost or overwritten | Unreviewed implementation loss | Preserve files; review and commit only with owner approval |
| No durable test artifact for the reported 162-pass run | Acceptance evidence is weak | Record commands and output per checkpoint going forward |
| Pytest cache contains 166 test node IDs while the reported pass count is 162 | Counts may be conflated | Treat the cache as collection data, not proof of a pass |
| Default model has documented factual failures | Product quality risk | Keep limitation visible; do not certify model reliability |
| Incomplete generations could be mistaken for answers | False success | Completion checks exist in benchmarks and local adapter; not yet in an API |
| `pyproject.toml` dev dependency `httpx2` and undeclared direct imports | Environment reproduction may fail | Record as TQ-22 before relying on a fresh environment |
| PostgreSQL is required for the full suite | Tests fail without the service | Keep the Compose service healthy; record environment state |
| No authentication, RBAC, audit, or approval enforcement | Security claims would be false | Do not claim them; implement before exposing beyond local use |
| No Arabic/English evaluation | Bilingual claims would be unverified | Define evaluation before claiming support |
| SaaS-ready language may encourage premature multi-tenancy | Scope and security risk | Keep SaaS as target design only; require a phase decision |
| Benchmark is small and deterministic | Results do not generalize | Report benchmark scope and limitations with every result |
| LangChain API/version drift | Local adapter may break | Pin compatible ranges; review before production use |
| Prompt or report leakage of secrets | Security and privacy risk | Never read `.env`; keep reports local and review prompts |

## 14. Current state summary

- **Branch:** `phase-1/foundation`
- **Baseline:** `e45a7aa2a7b7d69dea808b6811e69ca1afd74ec4` on `phase-1/foundation`; the owner's Windows checkout was not touched
- **Working tree:** CP5 source/tests and synchronized documentation are modified/untracked in this isolated clone; owner-local `.agents/` and `skills-lock.json` were not present and have not been overwritten
- **PostgreSQL:** unavailable in this environment; no server was listening at test port 59999
- **CP4:** owner-accepted; owner reports 398 passed and `pip check`, `alembic check`, and `git diff --check` passed on Windows
- **CP5:** 300 focused tests passed; full suite had 419 passed and four PostgreSQL connection failures; owner review pending
- **Next action:** owner reviews exported CP5 patch, then reruns full tests and database checks locally; no phase closure is claimed

## 15. Unapproved future ideas

The following are not approved commitments. Some are roadmap scope, but they are still unimplemented and must not be described as current capabilities:

- Owner acceptance of the LangChain adapter use in the CP5 structured-output API, plus dependency/resource review (TQ-04; proposed ADR-0011).
- Adoption of pgvector, a specific embedding model, or a specific vector index (TQ-14).
- Changing the production default model away from `llama3.2:latest` (TQ-06).
- Selecting a durable workflow or queue engine (TQ-12).
- Starting the frontend before backend core and integration are complete (D-28).
- Claiming SaaS, multi-tenancy, RBAC, audit logging, or approval enforcement.
- Adding new roadmap phases or renumbering the existing 12 phases.
- Autonomous agents that modify their own permissions, tools, or deployment.
- Billing, marketplace, mobile, or other commercial features not present in the owner-approved direction.

Roadmap Phases 4-12 are approved scope but unimplemented. They are not "unapproved ideas"; they are future work behind their phase gates.
