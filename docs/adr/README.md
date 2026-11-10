# Architecture Decision Records

This directory records decisions that are hard to reverse, surprising without context, and the result of a real trade-off. The format follows the project's domain-modeling convention: a short title, one to three sentences of context and decision, and optional status, considered options, or consequences.

ADRs describe decisions, not implementation status. Check `docs/PROJECT_CHECKPOINTS.md` before treating an accepted decision as an implemented capability.

## Index

| ADR | Title | Status |
| --- | --- | --- |
| [0001](0001-local-first-zero-budget-core.md) | Local-first core with optional cloud providers | Accepted |
| [0002](0002-phase-gated-evidence-based-delivery.md) | Phase-gated, evidence-based delivery | Accepted |
| [0003](0003-fastapi-sqlalchemy-postgresql-backend.md) | FastAPI, SQLAlchemy, and PostgreSQL backend | Accepted |
| [0004](0004-ollama-as-default-local-runtime.md) | Ollama as the default local model runtime | Accepted |
| [0005](0005-defer-frontend-until-backend-complete.md) | Defer the frontend until backend core is complete | Accepted |
| [0006](0006-multi-agent-orchestration-target.md) | Dynamic multi-agent orchestration as the target | Accepted |
| [0007](0007-pgvector-proposed-for-vector-search.md) | pgvector proposed for vector search | Proposed |
| [0008](0008-schema-registry-and-adapter-proposal.md) | Schema registry and model adapter for structured outputs | Proposed |
| [0009](0009-durable-workflow-engine-deferred.md) | Durable workflow engine selection deferred | Proposed |

## Status vocabulary

- **Accepted:** approved direction; implementation still requires checkpoints and evidence.
- **Proposed:** a technical choice under consideration; not approved for production.
- **Deprecated:** no longer recommended.
- **Superseded by ADR-NNNN:** replaced by a later decision.

## Adding an ADR

1. Scan this directory for the highest number and increment by one.
2. Use a short, specific title.
3. Record the context, decision, and why.
4. Add optional sections only when they add genuine value.
5. Update this index and any affected plan or architecture document.
6. Do not mark a proposal as accepted without an owner decision.
