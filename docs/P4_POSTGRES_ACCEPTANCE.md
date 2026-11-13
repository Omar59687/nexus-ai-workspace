# Phase 4 PostgreSQL persistence acceptance

**Status:** adapter hardening and fake-DB-API regression tests completed on
`feature/p4-postgres-acceptance`. The disposable PostgreSQL acceptance gate is
**NOT RUN** in this environment.

## Changes in this slice

- Serialize initial document creation and replacements by inserting the
  workspace/document row before selecting it `FOR UPDATE`.
- Bind a workspace/document identity to one source path. The candidate DDL
  enforces workspace/path uniqueness and a composite source-version foreign
  key; the adapter rejects attempts to rebind an existing identity.
- Store and compare a canonical SHA-256 digest of each index generation's
  source, chunks, windows, and vectors. Reusing a generation identity with a
  different payload now fails instead of reporting a successful no-op.
- Bind extracted pages and parser warnings to the persisted source-version
  identity, including when a later retry requests a different model generation.
- Reject autocommit-enabled DB-API connections before issuing repository SQL.
- Constrain window vectors to non-empty, one-dimensional PostgreSQL arrays.

The DDL is still inert candidate schema returned by
`candidate_schema_ddl()`. It has not been installed in a database. No Alembic
migration was added: the schema has no deployed predecessor to upgrade, and a
reversible migration should be prepared only after the candidate is approved
and the PostgreSQL integration suite passes against a disposable database.

## Tests

Focused tests from the repository root:

```sh
PYTHONPATH=src python -m pytest -q \
  tests/persistence/test_postgres_repository.py \
  tests/persistence/test_postgres_integration.py \
  tests/documents/test_collection_index.py
```

The live suite requires `NEXUS_P4_TEST_DATABASE_URL` pointing to a newly
created loopback database whose name matches `nexus_ai_p4_it_<suffix>`. It
rejects the protected `nexus_ai` databases and refuses to create its random
test schema unless the database contains no user objects. Each test method
uses its own schema and removes it afterward.

## Authorization and deployment boundary

The adapter scopes SQL by a caller-supplied `workspace_id`; that identifier is
not authentication or authorization. This branch does not add an API
principal-to-workspace authorization layer. Do not expose the repository to
untrusted callers until the application entry point derives workspace scope
from an authenticated principal and enforces membership. No production
database, hosted database, extension, or migration was accessed or changed.
