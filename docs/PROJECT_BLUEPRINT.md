# Nexus AI Workspace — Project Blueprint

## Project goals

Nexus AI Workspace is a local-first, open-source multi-agent AI workspace and learning project. It will help a user analyze documents and structured data, research information, coordinate specialized AI agents, and generate evidence-backed reports. The initial version must run locally and avoid paid APIs or cloud hosting.

Features described below are planned until implemented and verified.

## Non-negotiable engineering principles

- **$0 software budget:** Core workflows run locally without paid API keys, subscriptions, or paid hosting. External integrations are optional and never required for core functionality.
- **Learn by building:** The project owner is the primary developer. Each task has a learning goal, implementation, review, and tests.
- **Phase gates:** Do not start the next phase until the current phase passes acceptance criteria, phase tests, regression tests for all completed earlier phases, and cross-phase integration tests.
- **Evidence over claims:** Record real test and benchmark results. Never claim performance or accuracy without measurements.
- **Security by default:** Restrict tool permissions and filesystem access. Require explicit approval for sensitive actions.
- **Stable main branch:** Work on a dedicated development branch and merge only after review.

## Target hardware and execution

Initial development is on Windows. Target machine: Intel Core i7-1165G7, 16 GB RAM, NVIDIA MX450 with 2 GB VRAM. Benchmark local models on this machine; do not assume GPU acceleration will fit a given model. Run only the services required for the current phase.

## Proposed technology stack

Subject to validation during implementation:

- Python, FastAPI, Pydantic, SQLAlchemy, Alembic
- PostgreSQL and pgvector
- Ollama for local language models and local embeddings
- LangChain and LangGraph
- MCP Python SDK
- Pandas and OpenPyXL for structured data analysis
- React, TypeScript, and Vite
- Pytest and HTTPX
- OpenTelemetry and lightweight local evaluation/experiment tooling
- Docker Compose when the project reaches the packaging phase

Choose and install tools only when needed. Check current licenses and resource requirements before adoption. Use GitHub Actions only within free usage limits; local tests must remain possible.

## Target architecture

The intended end state is a modular FastAPI backend, a React/TypeScript dashboard, PostgreSQL/pgvector persistence, a local LLM runtime, RAG pipelines, MCP integrations, and LangGraph-based workflows.

Five logical agent roles are planned:

1. **Supervisor Agent** — routes work, manages workflow state, and coordinates approvals.
2. **Document Agent** — retrieves evidence from indexed documents.
3. **Data Agent** — analyzes CSV and Excel using deterministic Python tools.
4. **Research Agent** — accesses explicitly permitted local or optional external research tools.
5. **Report Agent** — composes results with sources into reports.

These are logical roles, not a requirement to run five separate LLMs. Agents will be added gradually and may share one local model. Prefer deterministic tools over an LLM for calculations and other well-defined operations.

## 12-phase roadmap

1. **FastAPI Foundation** — project setup, application, health endpoint, Pydantic, error handling, logging, API tests.
2. **Database & Persistence** — PostgreSQL, SQLAlchemy, Alembic, persistence models.
3. **Local LLM Integration** — Ollama, LangChain, structured outputs, local model benchmarks.
4. **Production-Oriented RAG** — parsing, chunking, embeddings, vector retrieval, citations, evaluation, incremental indexing.
5. **Data Analytics** — CSV/Excel validation, Pandas analytics, charts, deterministic calculations.
6. **Multi-Agent Orchestration** — LangGraph supervisor, shared state, routing, checkpoints, approval flow.
7. **MCP Integration** — local MCP server/client, permissions, safe tools, optional GitHub/web integrations.
8. **React Dashboard** — TypeScript UI, chat, uploads, task status, approvals, reports.
9. **Background Processing** — introduce a queue only when needed; evaluate Redis/Celery against simpler alternatives.
10. **LLMOps & Evaluation** — reproducible evaluations, tracing, experiment comparisons, prompt versioning, performance measurements.
11. **Security & Packaging** — security tests, configuration, Docker Compose, CI and user documentation.
12. **Enterprise Extensions** — authentication, teams, RBAC, tenant isolation, and related access-control tests.

The roadmap may be refined when implementation evidence justifies it, while preserving phase-gate policy.

## Mandatory Phase Quality Gate

A phase is complete only when all of these pass:

1. **Acceptance criteria:** Every criterion agreed before implementation has explicit evidence.
2. **Phase tests:** Relevant unit, API, negative-path, and integration tests pass.
3. **Regression tests:** All tests from every earlier completed phase pass against the candidate state.
4. **Cross-phase integration:** Interfaces and data flows between this phase and all relevant earlier phases are tested.
5. **Quality and performance:** Run applicable quality, security, resource, and performance checks. Define targets before judging the results.
6. **Review:** Review code, dependencies, configuration, documentation, and outstanding risks.
7. **Evidence:** Record commands, environment, test totals, failures, and benchmark results. Never describe tests that were not run as passing.
8. **Gate decision:** Any failed criterion or unresolved critical/high-severity issue blocks progression. Fix it and rerun affected tests plus the full regression suite.

Tests should run throughout implementation, not just at the phase end. The final gate is verification, not an additional implementation task.

## Phase 1 — seven implementation tasks

- **1.1** Verify and prepare the development environment.
- **1.2** Create the Python project structure and virtual environment.
- **1.3** Create the initial FastAPI application.
- **1.4** Add a health-check endpoint.
- **1.5** Introduce Pydantic request/response models where appropriate.
- **1.6** Add baseline error handling and structured logging.
- **1.7** Add and run Pytest/API tests.

After Task 1.7, execute the Phase 1 Quality Gate. It is not an eighth implementation task. No later phase begins until the gate passes.

## Development workflow

- Work in small, reviewable tasks.
- Use hint-first mentorship; provide a full implementation when requested or necessary.
- Keep secrets, private data, model files, generated artifacts, and local environment files out of Git.
- Document commands and decisions so another developer can reproduce the setup.

## Current status

**Planning / repository setup.** The blueprint is documented; application functionality has not yet been implemented or tested. The next step is Task 1.1: verify local Python, Git, and editor tooling.