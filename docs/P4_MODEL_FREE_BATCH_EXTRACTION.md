# Nexus AI — model-free batch extraction milestone

**Status:** code committed on `feature/p4-live-integration-hardening`; focused Windows
tests and real-document acceptance have **not** been run yet.

## Purpose and boundary

Owner-defined 1–150 document collection, entered in the exact JSON manifest
defined in [P4_MODEL_FREE_COLLECTION_PREFLIGHT.md](P4_MODEL_FREE_COLLECTION_PREFLIGHT.md).
This adds extraction on top of the previously verified collection inventory.

The service:

1. Rejects unsafe manifest paths and limits per-file and aggregate reads.
2. Reads **only explicitly listed** files through the existing filesystem gate.
3. Routes each PDF through the existing bounded isolated parser worker; never
   silently runs PDF parsing directly in the API process.
4. Extracts PDF page/text coverage, UTF-8 Markdown and TXT.
5. Records company, year, content digest, file bytes, extracted page count,
   nonblank page count, character count, extractor identity and warning count.
6. Builds an ephemeral source-aware chunk preview (count, deterministic identity\n   digest and chunker fingerprint); verifies source-character offsets before\n   discarding text. No embeddings, vector storage, or persisted chunks.\n7. Skips identical byte-content duplicates within a run.
8. Isolates failed documents with safe status codes, continuing the batch.

No source text is included in the output JSON. **No permanent index is built**:
extracted text is discarded after coverage statistics are recorded. This is not
full RAG ingestion and is not a 150-file semantic search benchmark. No LLM,
embeddings, database migration, GitHub PR or deployment.

## Run locally

Use the branch and Python environment already verified on Windows:

```powershell
Set-Location "C:\AI Projects\Nexus AI P4 Live Validation"
$env:PYTHONPATH = "$PWD;$PWD\src"
& "C:\AI Projects\Nexus AI\.venv\Scripts\python.exe" -m pytest -q `
    tests/documents/test_collection_preflight.py `
    tests/documents/test_collection_extraction.py
```

For an **owner-approved list** of reports already defined in
`$env:LOCALAPPDATA\NexusAI\collection-manifest.json`:

```powershell
& "C:\AI Projects\Nexus AI\.venv\Scripts\python.exe" scripts/extract_document_collection.py `
  --run-extraction `
  --root "C:\Users\HP PAVILION\Downloads" `
  --manifest "$env:LOCALAPPDATA\NexusAI\collection-manifest.json" `
  --report "$env:LOCALAPPDATA\NexusAI\reports\collection-extraction.json"
```

Runs synchronously and may take time for long PDFs. Output can be PASS, PARTIAL
or BLOCKED. A PASS means extraction succeeded or matching duplicate content was
skipped, **not** that the financial tables or figures are correct.

## Next independent milestones

- Durable collection index with explicit metadata mapping and version-lifecycle
  rules; do not deploy schema changes without owner approval.
- Company/year filtering and evidence retrieval tests independent of any LLM.
- Ground-truth financial fact/page alignment for real Arabic annual reports.
- Cloud/local LLM provider selection is deferred until evidence-quality gates pass.
