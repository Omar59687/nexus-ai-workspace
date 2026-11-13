# Phase 4 — Final integrated acceptance candidate

**Status: candidate, not accepted or deployed.** This branch starts at
`69cd2ebf3f2b6488554c8aeb782637723bd11160` and includes the prior
Phase 4 closure fixes plus the independent PostgreSQL adapter hardening.

## Critical separation of persistence layers

Nexus AI currently has TWO distinct PostgreSQL persistence adapters:

1. `PostgresCollectionIndexRepository` in
   `src/nexus_ai/retrieval/collection_repository.py`: stores extracted
   document pages and chunks **without embeddings**. This is the adapter
   supporting 50–150-PDF model-independent intake.
2. `PostgresDocumentIndex` in
   `src/nexus_ai/retrieval/postgres_repository.py`: stores the legacy
   embedding-capable index with chunk vectors and search windows.

The second-account hardening at `69cd2eb` applies directly to the **second**
adapter. It does **not** establish runtime PostgreSQL acceptance for the
first adapter. The final integration suite now installs both inert DDL proposals
only inside a private, newly-created disposable test schema and runs source-only
round-trip, idempotency, replacement, immutable-payload, delete and isolation
checks for the first adapter alongside the existing vector-index tests.

## Zero-owner-setup CI acceptance

`.github/workflows/p4-disposable-postgres.yml` runs on the
`feature/p4-final-acceptance-candidate` branch with an **ephemeral PostgreSQL
17 service**. It targets a disposable database named
`nexus_ai_p4_it_ci2026` on 127.0.0.1 and refuses pre-existing user DB objects.
This is GitHub's job-local database, **not Supabase or any live database**.
It runs focused integration tests, live PostgreSQL integration tests (skips
fail the acceptance step), then verifies the synthetic financial JSON.
No downloads of language models or GPU calls are intended.

Do not claim this acceptance gate passed until the workflow reports green.
A CI failure is a blocker requiring a bounded correction, not an invitation
to bypass or weaken the checks.

## Remaining explicit acceptance boundaries

- **Real Arabic financial fact:** page 114 extracted source text indicates an
  audit discussion around 19.6 billion for 2025, but the correct amount and
  currency have not been independently checked against the consolidated
  financial statement; page-level lexical relevance does not prove correct
  row/column association. The earlier "إيرادات" missing-anchor result could
  arise from PowerShell Unicode argument handling or Arabic variants. Latest
  diagnostic code supports UTF-8 JSON anchors and Arabic diacritics/alef forms;
  local real-PDF retest is needed.
- **Application authorization:** trusted, authenticated principal-to-workspace
  mapping must be enforced at every route invoking retrieval or indexing.
- **Migration:** candidate DDL is not a reviewed/reversible production
  migration. No production schema changes authorized.
- **Scale:** 150-document limits and synthetic retrieval recall are not
  real-PDF workload or financial accuracy benchmarks.

**Phase 4 closure recommendation:** accept the *engineering integration
candidate* only after CI PostgreSQL tests and owner-held real-PDF acceptance
pass. Keep production deployment and a large-scale 150-file pilot as separate,
explicitly named gates. No merge to `main` or production writes without owner
approval.
