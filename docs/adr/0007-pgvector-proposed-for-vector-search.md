# pgvector proposed for vector search

**Status:** Proposed

PostgreSQL is the operational database, so pgvector is the leading candidate for vector search: it would keep embeddings and relational data in one system and reduce operational surface. It is not adopted. The proposal requires validation of the extension, index strategy, embedding model, migration path, backup/restore behavior, and resource cost on the target hardware.

## Considered options

- A dedicated vector database.
- PostgreSQL with pgvector.
- A file-based or in-memory index for early local development.

## Consequences

- No vector store is implemented.
- RAG and memory work must not assume pgvector until this ADR is accepted.
- A future acceptance must include retrieval quality and resource evidence, not only installation success.
