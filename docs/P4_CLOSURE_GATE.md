# Phase 4 closure — single gate, no more exploratory micro-sprints

**Branch:** `feature/p4-closure-integration` (not merged; locally unverified).

## Recent verified baseline

Owner's Windows checkout passed 84 focused integration tests, regenerated
UTF-8 synthetic financial report, and successfully extracted 142 nonblank
pages and 2,139 chunks from the actual Mobily FY2025 Arabic report.
Five real-PDF diagnostic tests and six chunk-forensics tests passed.
However, no reviewed, exact financial statement fact has passed the acceptance
gate and no disposable PostgreSQL runtime test has been reported.

## Fixes in closure candidate

1. Fix `CollectionLexicalRetriever` empty-corpus path: preserve selected
   source-version validation instead of calling the helper without its required
   `selected` argument.
2. Allow `--anchors-json` (UTF-8 or UTF-8 BOM) for Arabic anchor values.
   This avoids dependence on the Windows console/codepage when passing
   Arabic characters directly through command-line arguments.

The page-114 forensic run found `19.6` and `2025` but not the literal
anchor `إيرادات`. Do not conclude this is an extraction defect without
ruling out command-line encoding, U+0640 tatweel, Arabic diacritics or
different Arabic spellings. The original PDF text remains private.

## One-time diagnostic repeat with escape-safe anchors

Create an ASCII-only JSON file representing the exact Unicode anchors.
No Arabic characters are passed on the command line.

```powershell
$terms = "$env:LOCALAPPDATA\NexusAI\reports\anchors-page114.json"
@('["\\u0625\\u064a\\u0631\\u0627\\u062f\\u0627\\u062a","19.6","2025"]') |
  Set-Content -Path $terms -Encoding ascii

& "C:\AI Projects\Nexus AI\.venv\Scripts\python.exe" `
  scripts/inspect_financial_pdf_page.py --run `
  --pdf "C:\Users\HP PAVILION\Downloads\Mobily Annual Report 2025 - Arabic.pdf" `
  --year 2025 --page 114 --anchors-json $terms `
  --report "$env:LOCALAPPDATA\NexusAI\reports\mobily-page114-closure.json"
```

Note: JSON Unicode escapes must have a **single** backslash in the
file. Inspect the saved file if PowerShell quoting changes them.

## Phase 4 definition of done

- One clean integrated candidate with focused collection, metadata, lexical,
  synthetic benchmark, Arabic forensic and real-PDF tests passing.
- Independently verified real financial facts: report/statement year, amount,
  unit/currency, and PDF page; evidence must stay together in a chunk or be
  traced across aligned source spans. Report actual source reading-order
  defects and abstain when unable to confirm.
- Approved disposable PostgreSQL database test covering DDL, transaction
  rollback, restart persistence, replacement and deletion. No production
  migrations without owner approval.
- Authorization scope enforced at application entrypoint (no caller-provided
  workspace identity used as authentication).
- Record explicit risks; do not claim 150-PDF throughput or answer-generation
  accuracy from a two-query diagnostic.

No more branch hopping or single-anchor investigations after this; execute
one final combined acceptance matrix once PostgreSQL and real fact labels
are ready.
