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

## Verified real-PDF engineering gate (owner-run, 13 Nov 2026)

The isolated source-only pipeline indexed the real Mobily FY2025 Arabic annual
report: 142 pages, 2,139 chunks. Owner visual inspection of original PDF
tables identified the precise FY2025 revenue **19,641,705 SAR thousands** in
PDF pages **140 and 142**, with 2024 comparison **18,206,447 SAR thousands**.

On commit `a688220c34683b3beb124b6a45935a773defacf8`, the real local
Arabic and English queries both retrieved visually verified gold pages in
top-10 after bounded adjacent-page context expansion, without inspecting gold
labels during search. Arabic top-five pages included **140 and 142**. English
had gold pages in top-10 (not top-5). The source-PDF amount extraction also
passed for both gold pages.

**These results establish bilingual gold-PAGE retrieval, not necessarily
a cited chunk that independently contains the amount or a machine-proven
metric/year/currency/row link.** The newer `acceptance_gates` distinguishes
page retrieval, exact amount in returned chunk, and automatic row association.
Automatic row association is deliberately not marked as passed.

A separate legacy same-page Arabic keyword check remains invalid for
visually confirmed table layouts: the numerical value survives pypdf, but
the Arabic revenue label is not co-detected on those extracted page texts.
Do not use that obsolete cooccurrence status as the overall Phase 4 verdict.

## Remaining boundaries and deployment prerequisites

- Exact numerical **citation-span** presence and automatic table-row
  association remain a separate quality gate. Owner's original screenshots
  confirm the real financial facts; NLP/table extraction does not yet fully
  reproduce their structural associations.
- **Application authorization:** trusted authenticated-principal-to-workspace
  binding must be enforced at every route invoking indexing or retrieval.
  Source workspace identifiers only scope database queries.
- **Production migration:** DDL remains a proposal, not reviewed reversible
  Alembic migration. No production/hosted schema changes authorized.
- **Scale:** configured 150-document support does not prove a 150-real-PDF
  workload, benchmark latency, or end-to-end answer accuracy.
- **Model-generated answers:** no LLM/embedding provider was invoked in this
  Phase 4 model-free acceptance; grounded answer generation is not tested.

**Phase 4 closure recommendation:** accept the *engineering integration
candidate* after the reproducible CI PostgreSQL gate and bilingual gold-page
retrieval pass; keep exact citation-value/row-association and application
production-readiness as explicit follow-on gates. Keep production deployment and a large-scale 150-file pilot as separate,
explicitly named gates. No merge to `main` or production writes without owner
approval.
