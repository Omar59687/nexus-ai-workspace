# Phase 4 — Real PDF model-free evidence diagnostic

**Status:** committed candidate; no Windows real-PDF execution yet. This is
not a financial-accuracy acceptance test.

## What it checks

- Exactly one owner-selected local PDF (no directory scan)
- Existing bounded isolated PDF parser worker and source filesystem limits
- Source hash, active source/processing identities, page count and warnings
- Per-page text coverage: character count, Arabic character count, digit count,
  lines and nonblank indicator
- Deterministic source-aware chunking and company/year-scoped BM25 citations
- Top-k retrieved page/offset/source-version identities for 1–12 queries

**No raw PDF content, query text, names, or extracted financial amounts are
written to the JSON report.** Query identity is a SHA-256 digest only. Source
paths are intentionally omitted. The index lives only in RAM.

The diagnostic does not check whether a retrieved numerical amount is the
correct revenue, reporting unit or table column. It enables manual review of
*where* retrieval looked. Financial acceptance still needs independent page
labels and review of the actual source, preferably in an approved private
environment. It is not a PDF hostile-content security sandbox.

## Run with owner-approved Mobily FY2025 PDF on Windows

From a clean checkout at the diagnostic branch, with the existing virtualenv
and PYTHONPATH:

```powershell
$env:PYTHONPATH = "$PWD;$PWD\src"

& "C:\AI Projects\Nexus AI\.venv\Scripts\python.exe" `
  scripts/diagnose_real_pdf_evidence.py --run `
  --pdf "C:\Users\HP PAVILION\Downloads\Mobily Annual Report 2025 - Arabic.pdf" `
  --company "Mobily" --year 2025 `
  --query "إيرادات موبايلي لعام 2025" `
  --query "Mobily revenue 2025 SAR" `
  --report "$env:LOCALAPPDATA\NexusAI\reports\mobily-real-pdf-diagnostic.json"
```

Unlike shell redirection `>`, the CLI writes **atomic UTF-8 JSON directly**;
there is no PowerShell cp1252/UTF-16 issue. It does not call Ollama, E5, GPU,
network services, or a database. It re-extracts and chunks the PDF once; may
take time and may be blocked by worker resource limits or missing pypdf.

The output has `status=PASS` for technical extraction/retrieval completion,
or `BLOCKED` with a generic non-sensitive reason. A PASS **does not** mean
the extracted financial figure is correct.

## Focused, synthetic-only tests

```powershell
& "C:\AI Projects\Nexus AI\.venv\Scripts\python.exe" `
  -m pytest -q tests/retrieval/test_real_pdf_diagnostic.py
```

The tests patch the PDF worker boundary to supply deterministic page text.
They verify UTF-8 output, Arabic coverage, source-text omission, citation
metadata and generic blocked handling. They **do not** verify real pypdf output.
Never include a private full report or source text in GitHub commits.

## Next acceptance gate

1. Inspect technical coverage and ranking page IDs from private diagnostic
   output.
2. Human-review a small number of real page-level financial judgments
   (company, report year, *fact* year, metric, amount, unit/currency, page).
3. Score actual fact-bearing retrieval and extraction/table integrity against
   reviewed labels; separate retrieval failures from extraction failures.
4. Do not conclude model/GPU failure without independently confirming what
   evidence the model actually received.
