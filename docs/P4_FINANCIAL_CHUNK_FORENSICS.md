# Phase 4 — Financial page/chunk forensics (real Arabic PDF)

**Status:** isolated candidate, pending Windows tests and owner-provided
real-PDF execution. No model, embedding, GPU, database or migrations.

The Mobily FY2025 pilot extracted 142/142 nonblank pages and 2,139 chunks.
For the Arabic 2025 revenue query its top five included PDF page 114 at
rank 3; the English query's top five did not. Owner inspection of pypdf
page 114 showed a revenue disclosure referring to approximately 19.6 billion
and 2025, but Arabic word order and a stray percent sign were distorted.
**The currency and exact financial-statement revenue amount are not verified
by that excerpt.**

This tool answers only whether independently supplied words or numbers
appear on an identified extracted page, share a 1,200-character source-aware
chunk, and occur in a bounded extracted-line window. The report contains
line numbers, chunk ordinals and booleans, but *never copies source text or
search phrases*. It cannot certify table row association, source accuracy,
reported currency or financial-answer correctness.

## Run

Create a new worktree at
`feature/p4-financial-chunk-forensics`. From that worktree:

```powershell
$env:PYTHONPATH = "$PWD;$PWD\src"
& "C:\AI Projects\Nexus AI\.venv\Scripts\python.exe" -m pytest -q `
  tests/retrieval/test_financial_chunk_forensics.py `
  tests/retrieval/test_real_pdf_diagnostic.py

& "C:\AI Projects\Nexus AI\.venv\Scripts\python.exe" `
  scripts/inspect_financial_pdf_page.py --run `
  --pdf "C:\Users\HP PAVILION\Downloads\Mobily Annual Report 2025 - Arabic.pdf" `
  --year 2025 --page 114 `
  --anchor "إيرادات" --anchor "19.6" --anchor "2025" `
  --report "$env:LOCALAPPDATA\NexusAI\reports\mobily-page114-forensics.json"
```

The report is written atomically as UTF-8 outside the PDF source directory.
The PDF is extracted once into bounded in-memory storage; rerunning incurs
another isolated PDF parse. The tool never creates or edits a repository or
database index on disk. The CLI prints only a summary.

To examine only the numeric diagnostics in PowerShell:

```powershell
$f = Get-Content "$env:LOCALAPPDATA\NexusAI\reports\mobily-page114-forensics.json" -Raw -Encoding UTF8 | ConvertFrom-Json
$f.findings | Select-Object page_number, anchor_count, all_anchors_present_on_page, all_anchors_share_chunk, all_anchors_within_line_window
$f.findings.anchors | Select-Object anchor_index, found_on_page, line_numbers, chunk_ordinals
```

Follow-up currency verification should be based on the actual consolidated
income statement and its document-level financial unit. Do not automatically
treat an audit passage's approximate value as the exact statement figure.
Inspect the corresponding rendered PDF page and table structure manually;
pypdf's reading order can differ from the visually rendered statement.

A failing chunk cooccurrence test indicates a potential chunk-boundary issue;
a passing one alone does *not* demonstrate amount/metric/year entailment.
