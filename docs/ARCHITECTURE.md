# Nexus AI Architecture

**Document role:** Verified current architecture and intended target architecture, kept separate.

**Last verified:** 2026-11-11 against the isolated `phase-1/foundation` baseline `e45a7aa2a7b7d69dea808b6811e69ca1afd74ec4` and CP5 working diff. CP5 changes remain uncommitted and require owner review.

**Rule:** A module is "implemented" only when code exists in the stated location. A module is "accepted" only when `docs/PROJECT_CHECKPOINTS.md` records tests, evidence, and review. Future modules must never be drawn or described as if they exist.

## 1. Verified current architecture

### 1.1 Runtime topology

```text
Windows host
├── FastAPI application (src/nexus_ai/main.py)
│   ├── GET /
│   ├── GET /health
│   ├── POST /llm/generate
│   ├── POST /structured/generate (CP5 working diff; review verified)
│   └── /tasks CRUD
├── Ollama service (host, default http://127.0.0.1:11434)
└── Docker Compose
    └── PostgreSQL 17 container
        └── 127.0.0.1:${POSTGRES_PORT} -> 5432
```

The application, Ollama, and tests run on the host. Only PostgreSQL is defined in `compose.yaml`. There is no application container, reverse proxy, queue, worker, frontend, or cloud integration.

### 1.2 Component status

| Component | Location | Verified status | Notes |
| --- | --- | --- | --- |
| FastAPI application | `src/nexus_ai/main.py` | Implemented and committed | Sync handlers; generic exception handler; logging |
| Request/response schemas | `src/nexus_ai/schemas.py` | Implemented and committed | Pydantic v2 models |
| SQLAlchemy database layer | `src/nexus_ai/database.py` | Implemented and committed | Sync engine; `pool_pre_ping=True`, `pool_size=2`, `max_overflow=0` |
| ORM models | `src/nexus_ai/models.py` | Implemented and committed | One model: `WorkspaceTask` -> `workspace_tasks` |
| Alembic migration | `alembic/versions/65cff3cc4088_create_workspace_tasks_table.py` | Implemented and committed | Creates `workspace_tasks` with status check constraint |
| PostgreSQL 17 | `compose.yaml` | Implemented and running locally | Container healthy at `127.0.0.1:5433` during last check |
| Ollama HTTP client | `src/nexus_ai/ollama.py` | Implemented and committed | `urllib`; `/api/generate`; non-streaming |
| LLM endpoint | `src/nexus_ai/main.py` | Implemented and committed | `POST /llm/generate`; 503/502 mapping |
| Benchmark subsystem | `src/nexus_ai/benchmark/` | Implemented and committed | Cases, client, metrics, scoring, runner |
| Benchmark CLI | `scripts/run_llm_benchmark.py` | Implemented and committed | Writes JSON reports under `local_data/` |
| Generic structured-output engine | `src/nexus_ai/structured_output_pipeline.py` | Implemented and committed | Generate/validate/retry; max two attempts |
| REST structured-output adapter | `src/nexus_ai/structured_outputs.py` | Implemented and committed | Pydantic schema, semantic validator, demo path |
| LangChain structured demo | `scripts/try_langchain_structured.py` | Implemented and committed | Uses `ChatOllama`; not an API |
| Schema registry | `src/nexus_ai/structured_schemas.py` | Committed at e45; CP4 owner-accepted | `StructuredSchemaSpec`, `SCHEMA_REGISTRY`, lookup error |
| Structured service | `src/nexus_ai/structured_service.py` | Committed at e45; CP4 owner-accepted | Retry policy, metrics, rejection handling |
| ChatOllama model adapter | `src/nexus_ai/model_adapters.py` | Committed at e45; CP4 owner-accepted | Completion enforcement; provider error mapping |
| Structured-output API | `src/nexus_ai/main.py`, `src/nexus_ai/schemas.py` | CP5 working diff; focused tests and two review cycles pass; owner review pending | `/structured/generate`, configured Ollama dependency, sanitized errors, result and metrics schema |
| Document intelligence | Not present | Not implemented | Planned for Phase 4 |
| Memory system | Not present | Not implemented | Planned product capability |
| Multi-agent orchestration | Not present | Not implemented | Planned for Phase 6 |
| Durable workflow engine | Not present | Not implemented | Engine not selected |
| RBAC, audit log, approvals | Not present | Not implemented | Planned product capability |
| Frontend | Not present | Deferred by decision | Phase 8 remains gated |

### 1.3 HTTP surface

| Method | Path | Behavior |
| --- | --- | --- |
| `GET` | `/` | Returns a welcome message |
| `GET` | `/health` | Returns `{"status": "ok"}` |
| `POST` | `/llm/generate` | Sends a prompt to Ollama; returns text, model, completion flag, and available metrics |
| `POST` | `/structured/generate` | Uses the CP4 registry/service/adapter; returns validated result and available metrics; generic 404/422/502/503 errors |
| `POST` | `/tasks` | Creates a workspace task; 201 |
| `GET` | `/tasks` | Lists workspace tasks ordered by ID |
| `GET` | `/tasks/{task_id}` | Returns one task or 404 |
| `PATCH` | `/tasks/{task_id}` | Updates title and/or status; rejects empty or invalid payloads |
| `DELETE` | `/tasks/{task_id}` | Deletes a task; 204 or 404 |

There is no structured-output, document, memory, agent, workflow, approval, audit, or metrics endpoint.

### 1.4 Actual data flows

#### Flow A — Task CRUD

```text
HTTP request
  -> FastAPI route in src/nexus_ai/main.py
  -> get_db dependency
  -> SQLAlchemy Session
  -> PostgreSQL workspace_tasks table
  -> ORM object
  -> TaskRead response model
```

Validation occurs in `TaskCreate`, `TaskUpdate`, and route-level checks. The status constraint is enforced by both Pydantic and the database check constraint. There is no service layer between the route and the session.

#### Flow B — Local text generation

```text
POST /llm/generate
  -> LLMGenerateRequest validation
  -> OllamaClient.generate()
  -> POST {OLLAMA_BASE_URL}/api/generate with stream=false
  -> Ollama
  -> response JSON parsed
  -> LLMGenerateResponse
```

The client records response text, model, `done`, total duration in milliseconds, prompt token count, and generated token count. Timeout and connection failures map to 503; invalid or unsuccessful responses map to 502. The route does not persist prompts or responses.

#### Flow C — Benchmark run

```text
scripts/run_llm_benchmark.py
  -> load and validate benchmarks/cases.json (version 1.0.1)
  -> OllamaBenchmarkClient
  -> optional warm-up request
  -> measured trials per case
  -> metric extraction
  -> completion validation
  -> deterministic scoring
  -> JSON report in local_data/llm_benchmarks/
```

The benchmark runner is separate from the FastAPI application. It never overwrites an existing report. The report records model name, Ollama version when available, settings, case file hash, environment, warm-up, trials, metrics, and scoring. A report is local evidence, not a general model-quality certification.

#### Flow D — Committed structured-output engine and demo

```text
scripts/try_langchain_structured.py
  -> ChatOllama.with_structured_output(RESTExplanation)
  -> generate_rest_explanation_with_retry()
  -> generate_with_validation()
       -> generate(prompt)
       -> validate_rest_explanation(result)
       -> on ValueError: build correction prompt, retry once
       -> on final failure: StructuredOutputRejectedError
  -> print validated result or exit 1
```

The engine itself is provider-agnostic and accepts an injected `generate` callable. The committed adapter defines the REST schema and semantic validation. The demo is not exposed through FastAPI.

#### Flow E — Local structured generation API (CP4 owner-accepted; CP5 diff pending owner review)

```text
Caller -> POST /structured/generate
  -> StructuredOutputService.generate(schema_name, prompt, model)
  -> get_schema_spec(schema_name)
  -> StructuredModelAdapter.generate_structured()
       -> ChatOllama.with_structured_output(..., include_raw=True)
       -> completion metadata verification
  -> generate_with_validation()
       -> schema validator
       -> bounded semantic retry
  -> StructuredGenerationResult with aggregate metrics
```

The service and adapter are in owner-accepted baseline commit e45a7aa. The HTTP route and schemas are present in the current CP5 working diff and have deterministic tests plus two independent review cycles. The route is not included in the baseline commit or yet owner-accepted. No live Ollama call was run in this environment.

### 1.5 Persistence model

Current table: `workspace_tasks`.

| Column | Type | Constraints |
| --- | --- | --- |
| `id` | integer | Primary key |
| `title` | string(200) | Not null |
| `status` | string(20) | Not null; default `pending`; check constraint allows `pending`, `in_progress`, `completed`, `failed` |
| `created_at` | timestamptz | Not null; server default `now()` |

There are no workspace, project, user, membership, document, chunk, embedding, memory, agent, workflow, approval, or audit tables.

### 1.6 Error and failure behavior

| Failure | Current behavior |
| --- | --- |
| Missing database settings | Application startup raises `RuntimeError` |
| Database connection failure | SQLAlchemy/connection error propagates to the generic 500 handler or CLIENT command |
| Ollama timeout | `503` with `Ollama request timed out` |
| Ollama unavailable | `503` with `Ollama service is unavailable` |
| Ollama HTTP or malformed response | `502` with `Ollama returned an invalid response` |
| Unexpected exception | Generic `500 Internal server error`; internal details are not returned |
| Benchmark incomplete generation | Score `0.0`; cannot pass |
| Structured validation exhausted | `StructuredOutputRejectedError` / `StructuredServiceRejectedError`; never returned as success |

### 1.7 Security and operations boundaries

- Database credentials and Ollama settings are read from environment variables loaded from `.env`; `.env` is Git-ignored and must not be read.
- `.env.example` documents required variable names without real secrets.
- There is no authentication, authorization, RBAC, tenant isolation, audit log, or approval gate.
- There is no tool permission layer or filesystem sandbox in the application.
- Logging is Python standard logging. Prompts are not intentionally logged; error messages are generic.
- Local benchmark reports may contain prompts and model responses and are Git-ignored under `local_data/`.
- The application is intended for local development only at this stage.

## 2. Intended target architecture (not implemented)

Everything in this section is a target design. It is not a description of current code. See `docs/PROJECT_PLAN.md` for requirements and `docs/adr/` for decision status.

### 2.1 Target layers

```text
Client / future frontend
        |
API layer (FastAPI)
        |
Application services
  - workspace/project service
  - document intelligence service
  - structured extraction service
  - memory service
  - orchestration service
  - workflow service
  - approval service
        |
Domain and provider boundaries
  - agent roles
  - provider abstraction / model adapters
  - schema registry and validators
  - retrieval and embedding interfaces
        |
Infrastructure
  - PostgreSQL (+ proposed pgvector)
  - local Ollama and optional cloud providers
  - durable workflow store
  - observability pipeline
  - audit log
```

### 2.2 Target capabilities

| Capability | Target design | Status |
| --- | --- | --- |
| Workspace and project management | Workspaces contain projects, members, documents, memory, and workflows | Proposed; no schema or API |
| Document Intelligence | Parse, chunk, embed, index, retrieve, cite, and evaluate documents | Proposed; Phase 4 |
| Grounded answers | Answers must carry evidence references and abstain when evidence is insufficient | Proposed |
| Structured extraction | Schema-driven extraction with deterministic and semantic validation | Partially explored by the REST demo; general capability proposed |
| Personal and project memory | Separate scopes, retention, deletion, provenance, and access rules | Proposed |
| Multi-agent orchestration | Supervisor selects Document, Data, Research, and Report roles dynamically | Proposed; Phase 6 |
| Provider abstraction | One interface for local and optional cloud providers; no silent fallback | Proposed |
| Durable execution | Persisted workflow state, resumable steps, bounded retries, approval waits | Proposed; engine unselected |
| RBAC and audit | Roles, permissions, tenant boundaries, append-only audit events | Proposed; Phase 12 |
| Human approvals | Sensitive actions pause for an authorized human decision | Proposed |
| Observability | Tokens, latency, resources, and cost per request and workflow | Proposed; current metrics are partial |
| Self-hosted deployment | Packaged local/private deployment | Proposed; Phase 11 |
| SaaS-ready architecture | Tenant-aware design without premature SaaS implementation | Proposed; Phase 12 |

### 2.3 Target data flows (conceptual)

These flows do not exist. They describe the intended integration points so future work does not invent incompatible modules.

#### Target Flow 1 — Document question answering

```text
Upload/document -> parse -> chunk -> embed -> index
Question -> retrieve evidence -> build grounded prompt -> model
         -> answer with citations -> record metrics and audit event
```

#### Target Flow 2 — Structured extraction

```text
Source content -> selected schema -> model adapter -> parsed candidate
               -> schema validation -> semantic/domain validation
               -> accept, bounded retry, or explicit failure
               -> persist result with provenance and metrics
```

#### Target Flow 3 — Orchestrated durable workflow

```text
User request -> orchestrator selects roles and steps
             -> workflow state persisted
             -> agents/tools execute with permissions
             -> sensitive action pauses for approval
             -> results, metrics, and audit events recorded
             -> workflow resumes after failure or restart
```

### 2.4 Target technology mapping

| Technology | Target role | Status |
| --- | --- | --- |
| FastAPI | Public API and dependency injection | Implemented |
| SQLAlchemy and Alembic | Persistence and migrations | Implemented |
| PostgreSQL | Operational database | Implemented |
| pgvector | Vector search inside PostgreSQL | Proposed |
| Ollama | Default local model runtime | Implemented |
| LangChain / `langchain-ollama` | Structured demo and candidate adapter stack | Partial; production use unresolved |
| LangGraph | Candidate orchestration and durable state | Proposed |
| MCP Python SDK | Tool/integration boundary | Proposed; Phase 7 |
| React, TypeScript, Vite | Frontend | Deferred |
| OpenTelemetry | Observability instrumentation | Proposed |
| Docker Compose | Local service packaging | Implemented for PostgreSQL only |

## 3. Architecture evolution rules

1. When a proposed module becomes implemented, move it from Section 2 to Section 1 and update `docs/PROJECT_CHECKPOINTS.md` with evidence.
2. Do not draw a future module inside the current runtime topology.
3. Do not claim a capability because a dependency is installed or a schema exists.
4. Keep provider-specific code behind the model-adapter boundary before adding a second provider.
5. Do not add a durable workflow engine, vector store, or queue without an ADR and owner decision.
6. Treat schema validity as structural only; factual correctness and grounding require separate validation.
7. Keep the frontend out of the backend architecture until the owner unblocks Phase 8.

## 4. Related documents

- `docs/PROJECT_PLAN.md` — requirements, decisions, risks, open questions.
- `docs/PROJECT_CHECKPOINTS.md` — implementation and acceptance evidence.
- `docs/ROADMAP.md` — preserved 12-phase roadmap.
- `docs/adr/README.md` — ADR index and status.
- `GLOSSARY.md` — canonical terminology.
- `docs/BENCHMARKS.md` — benchmark design and historical model evidence.
- `docs/PHASE3_COMPLETION_PLAN_DRAFT.md` — unapproved Phase 3 completion proposal.
