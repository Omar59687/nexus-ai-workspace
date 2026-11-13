# Model-free document collection preflight (Phase 4 follow-on)

**Status: code committed; Windows/local tests not yet verified.** This is a
collection-inventory slice, not document ingestion or end-to-end financial RAG.

## Why this exists

Document extraction and E5 embedding on the real Mobily Arabic annual report
reached the answering stage, but financial answer accuracy remains unverified.
This model-free slice allows collection management to advance independently of
choosing Gemma, another local model, or a paid cloud provider.

## Input

Create an owner-controlled folder containing **explicitly authorized** PDFs,
Markdown, or UTF-8 TXT documents. No recursive scans. Supply a separate UTF-8
JSON manifest containing between 1 and 150 explicitly enumerated relative
paths with owner-assigned company and year. Company/year are not inferred from
filenames. Example for two files in the root:

```json
{
  "documents": [
    {"path": "Mobily Annual Report 2025 - Arabic.pdf", "company": "Mobily", "year": 2025},
    {"path": "Mobily Annual Report 2024.pdf", "company": "Mobily", "year": 2024}
  ]
}
```

Manifests can include relative subfolders using `/`. Duplicate paths, traversal,
absolute paths, symlinks, and unsupported extensions are rejected or blocked.
Arabic company names are supported. A PDF's contents are **not** parsed here.

## One run on Windows

Use the project's existing Python virtual environment and project import roots:

```powershell
$target = "C:\AI Projects\Nexus AI P4 Live Validation"
$env:PYTHONPATH = "$target;$target\src"
Set-Location $target
& "C:\AI Projects\Nexus AI\.venv\Scripts\python.exe" scripts/preflight_document_collection.py `
  --run-preflight `
  --root "C:\Users\HP PAVILION\Downloads" `
  --manifest "$env:LOCALAPPDATA\NexusAI\collection-manifest.json" `
  --report "$env:LOCALAPPDATA\NexusAI\reports\collection-preflight.json"
```

The manifest is written by the owner outside the root directory. The report is
also outside the root. No model environment, Ollama, E5, API token, GPU, Docker,
or database is required. If some listed files fail, the report status is
`PARTIAL` and their entries show safe failure codes; other files can still
be inventoried. Existing per-file 25 MiB and aggregate 1 GiB limits apply.

## Acceptance gates and non-claims

- Runs with no LLM, embedding, database writes or folder crawling.
- Records path, explicit company/year, byte size, SHA-256, and duplicate-content
  reference for each readable document; failed entries never report source text.
- Does not certify financial facts, PDF table extraction, OCR, source-page citations,
  model performance, or 150-file RAG end-to-end capacity.
- The manifest is the intended contract for a future bounded ingestion scheduler
  and persisted source collection; neither is delivered by this slice.
- Run `python -m pytest -q tests/documents/test_collection_preflight.py`
  before marking the local gate passed.
