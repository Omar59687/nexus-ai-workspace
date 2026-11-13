# Phase 4 unified integration acceptance checklist

**Status: review candidate, not accepted / not deployed.**
This branch combines the source-text collection index, metadata filtering,
model-free BM25 retrieval and synthetic financial-evidence benchmark.
No LLM is required for this acceptance slice.

## Evidence received

- Collection preflight/extraction: 17 focused tests passed on owner's Windows checkout at earlier SHA.
- Durable collection index: 68 tests reported passing on source feature branch.
- Company/year filter: 87 tests reported passing on source feature branch.
- Financial synthetic harness: 81 passed, one skipped on source feature branch.
- **Combined candidate:** not yet verified; these counts overlap and must not be summed.
- Synthetic benchmark: 9/9 page targets at Recall@5 and @10, 25/25
  source-citation checks, 0/25 metadata leaks, 3 currency-decoy candidates.
  These only measure invented fixtures.

## Unified gate — commands in a clean isolated checkout

```powershell
$env:PYTHONPATH = "$PWD;$PWD\src"
& "C:\AI Projects\Nexus AI\.venv\Scripts\python.exe" -m pytest -q `
 tests/documents/test_collection_preflight.py `
 tests/documents/test_collection_extraction.py `
 tests/documents/test_collection_index.py `
 tests/retrieval/test_company_year_metadata.py `
 tests/retrieval/test_collection_registration.py `
 tests/retrieval/test_collection_lexical.py `
 tests/test_financial_evidence_evaluation.py `
 tests/retrieval/test_service.py
& "C:\AI Projects\Nexus AI\.venv\Scripts\python.exe" -m nexus_ai.benchmark.financial_evidence
```

Compare benchmark output with
`benchmarks/results/financial_evidence_synthetic_v1.json`.
Do not start Gemma, Ollama, or E5.

## Quality risks to resolve before real financial accuracy claims

1. **No true PDF extraction tested by synthetic benchmark.** Its page adapter
   uses form-feed-delimited text; real Arabic PDF tables can rearrange cells,
   lose labels, or produce no text. Annotate real report page coverage.
2. **Passage co-occurrence is not row-level factual entailment.**
   `_fact_supported` checks company/year/metric/amount/currency aliases
   within a passage. They can appear in different table rows. Never
   interpret the synthetic recall metric as correct cell extraction.
3. **No answer generation/abstention benchmark.** Finding a passage that
   states 'EPS not disclosed' does not prove that a generator abstains.
4. **No production PostgreSQL acceptance.** Candidate DDL has not been
   migrated or executed against disposable PostgreSQL. Review DDL, transaction
   lifecycle, actual connection semantics and rollback before deployment.
5. **Authorized HTTP request scoping still absent.** Callers must provide a
   trusted workspace identity and mandatory company/year scope.
6. **Real collection volume unverified.** A limit of 150 records is a safety
   ceiling, not a passed throughput or retrieval quality benchmark.
7. **Model choice remains deferred.** No cloud fees, local GPU tests, or LLM
   tuning are prerequisites for model-free acceptance.

## Next decisive acceptance milestone

Use a small, explicitly approved real annual-report collection (first 2–5
PDFs), with human-checked source page, year, metric, amount, unit/currency and
company for each labeled question. Keep independent judgments and private
document contents outside source control. Produce extraction-page coverage,
retrieval Recall@5/@10, exact citation validation, and per-failure root causes.
Then scale to 50 and 150 documents with resource measurements.

Do not merge to main or apply migrations without owner approval.
