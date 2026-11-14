# Phase 5 — Bounded Data Analytics, Slice A

**Status:** integrated backend candidate on `feature/p5-bounded-data-analytics`.
This is Phase 5 of the official 12-phase plan, not a new roadmap phase.
This slice covers explicitly selected CSV/XLSX inputs, validation, exact
financial aggregation, and bar-chart-ready grouped values. It does **not**
implement an authenticated HTTP endpoint, dashboard, persistence or chart
rendering.

## Contract

`nexus_ai.data_analytics.analyze_table(data, file_type, group_column,
amount_column, sheet_name=None)` accepts only bounded file bytes. Defaults:
3 MB file, 30 MB expanded XLSX central-directory size, 20,000 data rows,
64 columns, and 500 output groups. No filesystem search, model call,
cloud call or database write occurs.

- CSV must be UTF-8. Rows must have equal widths and unique, valid headers.
- XLSX is read from a regular in-memory workbook with formula cells rejected
  (not evaluated); macros/binary components and oversized ZIPs fail closed.
  This is a bounded parser, not a hostile-document sandbox.
- Group labels must be nonempty text. Amounts must be finite plain decimals;
  missing values, currency symbols, commas and exponents are rejected rather
  than silently guessed. For XLSX numeric cells, the finite stored numeric
  value is converted to its shortest round-trip decimal representation, never
  summed as a binary float; original display formats aren't applied.
- Decimal arithmetic prevents familiar `0.1+0.2` binary-float errors.
  Pandas is used for grouping, then a separate direct Decimal sum checks
  aggregate integrity.
- `total` and `chart_data[].value` are **decimal strings**. A charting
  client must convert them deliberately and preserve units/currency supplied
  by its caller; this service never invents those units.

## Example

From the project checkout with the optional analytics dependencies installed:

```powershell
python -m pip install -e ".[analytics]"
$env:PYTHONPATH = "$PWD;$PWD\src"
python scripts/analyze_local_table.py `
  --input "C:\Users\Public\Documents\revenue.csv" `
  --group-by Company --sum Revenue
```

Sample CSV:

```csv
Company,Revenue
Mobily,19.641705
Mobily,-0.641705
Aramco,2.00
```

Expected groups: `Aramco=2.00`, `Mobily=19.000000`;
grand total `21.000000`. The examples are **synthetic**, not financial
facts about either company.

## Slice B — multi-year financial series and deterministic chart output

Implemented on the same isolated Phase 5 branch:

- `nexus_ai.financial_analytics.analyze_financial_series` reads explicitly
  selected CSV/XLSX records with named company, year, metric, value,
  currency, and unit columns. Exact identity and financial year filters
  apply before annual aggregation.
- Currency and units are **not inferred, converted or mixed**: a mismatched
  currency/unit for the requested company, year and metric fails closed.
  Supported currencies: SAR, USD, EUR, GBP, JOD, AED, QAR. Supported units:
  ones, thousands, millions, billions. Supported metrics: revenue,
  net_income, operating_income, assets, liabilities, equity, cash_flow.
- Each input row, including filtered-out records, must have valid values.
  Missing financial years are not interpolated; zero-year baselines yield
  `yoy_percent: null` with a reason. Year-over-year figures are calculated
  using `Decimal` and reported as percentages with four decimal places.
  Aggregation presumes additive, nonduplicated input rows.
- `nexus_ai.financial_charts.render_financial_line_svg` produces a
  deterministic, locally generated SVG. Data labels show exact Decimal
  strings; plot coordinates are approximations. SVG labels are escaped and
  the renderer rejects malformed inputs.
- `scripts/analyze_financial_series.py` is the optional owner-invoked
  command line interface, allowing `--report` JSON and `--svg` output.
  It is not yet an authenticated service endpoint.

Example (synthetic CSV whose numbers happen to match the verified Mobily
annual-report revenue amounts):

```csv
Company,Year,Metric,Value,Currency,Unit
Mobily,2024,revenue,18206447,SAR,thousands
Mobily,2025,revenue,19641705,SAR,thousands
```

```powershell
python scripts/analyze_financial_series.py `
  --input "C:\Reports\revenue.csv" --company Mobily --metric revenue `
  --currency SAR --unit thousands --start-year 2024 --end-year 2025 `
  --report "C:\Reports\results\revenue.json" `
  --svg "C:\Reports\results\revenue.svg"
```

The values in this input are **caller-entered CSV values**, not financial
cells extracted by this Phase 5 service from the annual-report PDF.
Automated table-row extraction from PDF remains a different acceptance
requirement. No output is evidence of a source document unless the
caller supplies trusted source data and validates its provenance.

## Slice C — Source-backed reviewed financial observations

`src/nexus_ai/financial_evidence_analytics.py` now provides an explicit
bridge from a live, active Phase 4 document index to the Phase 5 annual
financial-series engine. This bridge **does not automatically interpret PDF
financial tables**.

Each `ReviewedFinancialObservation` is supplied by a trusted caller with
an explicitly asserted company, metric, year, amount, currency and unit,
plus `reviewer_asserted_row=True`, and a complete citation:
workspace/document/version, source path/hash, page number, chunk identifier,
and exact character offsets.

The service checks the active repository generation and source identity,
the cited chunk's page/offset/text integrity, and presence of the **exact
numeric value** inside the cited text (including English/Arabic thousand
separators and Arabic-Indic digits). It rechecks source versions after
processing the batch to reject replaced documents. It never infers a unit,
year or row label from the appearance of a number alone.

For single-total financial metrics, repeated citations (e.g. an annual
consolidated statement and an operating segment note repeating total
revenue) are **deduplicated**. Conflicting values for the same
company/year/metric/unit/currency are rejected, not summed or silently
selected. The output includes citation-level provenance by year while
delegating the mathematical series/Y-o-Y computation to
`analyze_financial_series`.

This is a **reviewed-input contract**, not cryptographic proof of a review
or a replacement for authentication. The caller must trust/authorize the
workspace scope and the human review assertion; untrusted user payloads
must not be exposed as automatically verified financial facts. Source
documents are read through the supplied repository, not from caller-provided
filesystem paths, and no database writes, model calls, or hosted requests
are made.

Additional tests cover Arabic numeric punctuation, stale versions,
cross-workspace identity, wrong offsets, exact-number mismatches, duplicate
citations, year-total conflicts, mixed units/currencies, and a source
generation being replaced mid-analysis.

**Not included yet:** automatic metric/table-row extraction, signed review
approvals, a durable reviewed-facts store, authenticated HTTP integration, or
an end-to-end 150-PDF financial benchmark. Do not treat this as completed
financial statement parsing or finished Phase 5.

## Slice D — Strict PDF-text financial row candidates

`src/nexus_ai/financial_table_candidates.py` now inspects **active indexed
document chunks**, not arbitrary filenames or model-generated snippets.
Only an explicitly structured, two-cell row such as `Total revenue |
19,641,705` or `إجمالي الإيرادات<TAB>١٩٬٦٤١٬٧٠٥`, following a
**single-year, single-currency/unit** header inside the same chunk, produces
a candidate. It carries the workspace, document, version, source hash,
page, chunk, and line-character offsets. The source version is checked
again after extraction. The module is an opt-in backend service, **not**
a public HTTP route, PDF visual-layout parser, or approved fact generator.

Every candidate is marked `HUMAN_ROW_REVIEW_REQUIRED`; the response
always reports `automatically_verified_financial_facts: 0`. Multi-year
columns, missing or ambiguous headers, malformed numerics, label variants
that are not in the bounded lexicon, and unstructured Arabic PDF extraction
**abstain** rather than infer a row from nearby keywords. A document's
financial row can be visible in the PDF but impossible to infer from the
plain pypdf text order, as the earlier Mobily acceptance showed.

The candidate's line-character offsets locate a candidate **inside** an
indexed chunk. They are **not directly interchangeable** with the
`ReviewedFinancialObservation` whole-chunk offset contract. A separate,
authorized human-review adapter must connect them, verify the financial
row visually, and cite a valid source chunk. No human review assertion is
created automatically.

This is deliberately a narrow, high-precision parser to establish
safe behavior and measurable abstention. It does not yet provide usable
automatic extraction for complex real annual-report tables. Extending it
requires positional table reconstruction, independent real-document
annotations, and negative controls for year/currency/metric ambiguity.

## Slice E — Position-aware financial PDF diagnostic (experimental)

This branch now contains `financial_positioned_tables.py` and
`financial_pdf_geometry.py`. The former analyzes text fragments with
page/X/Y coordinates; the latter retrieves those fragments using a
bounded child process under the same POSIX resource limits or Windows
Job Object framework as the existing Phase 4 PDF extractor.

The geometry worker is **not** a new PDF security sandbox. It has CPU,
memory, wall-time, byte, output and per-page fragment budgets, but does
not prohibit file/network access by a potentially hostile parser. The
owner should use it only on a trusted local PDF until stronger
filesystem/network isolation is implemented.

The positional parser accepts multi-year columns only when each amount
aligns with exactly one year header, a recognized metric row label, and
a single explicit unit/currency heading. Every detected number must
also occur in an unchanged, source-checked document chunk. Collisions,
overlapping values, unreliable offsets and unanchored geometry abstain.
Returned candidates have `HUMAN_ROW_REVIEW_REQUIRED`, never automatic
row-verified status. In particular, geometry fragments returned by
pypdf may be inaccurate for Arabic RTL layouts; only a real-document
diagnostic can establish usefulness for the Mobily report.

**Owner-only diagnostic (optional, no paid model or hosted database):**

```powershell
Set-Location "C:\AI Projects\Nexus AI P4 Forensics"
git fetch origin feature/p5-bounded-data-analytics
# Switch only if the worktree is clean and you are intentionally testing P5.
git switch --detach origin/feature/p5-bounded-data-analytics
$env:PYTHONPATH = "$PWD;$PWD\src"
& "C:\AI Projects\Nexus AI\.venv\Scripts\python.exe" `
  scripts/diagnose_pdf_financial_geometry.py `
  --pdf "C:\Users\HP PAVILION\Downloads\Mobily Annual Report 2025 - Arabic.pdf" `
  --pages 140 142 `
  --report "$env:LOCALAPPDATA\NexusAI\reports\p5-mobily-geometry.json"
```

After the first real Mobily run (142 PDF pages, 2,139 chunks), the worker
successfully emitted 174 positional fragments on PDF page 140 and 263 on
page 142, but the old strict equality test aborted each entire page at
`ABSTAIN_SOURCE_GEOMETRY_MISMATCH`. The follow-up implementation
independently checks each fragment against the existing indexed source,
**skips** fragments whose text cannot be reconciled, and reports counts
for source-backed years, metric labels, unit labels, and numbers. It
does not use skipped fragments to create candidates or change the rule
that reviewed facts require human confirmation. This follow-up
still requires a new owner-side real-PDF run to assess usefulness.

The second owner-side Mobily run (commit `b983fbb`) recovered
**62/174** source-anchored fragments on page 140 and **89/263** on page
142. It recognized **16 and 24 year-like positioned fragments**, and
**40 and 69 numeric fragments**, respectively, but **zero matched
whole-phrase metric labels or unit headings on both pages**. No financial
row candidate was generated, correctly.

The next diagnostic extension distinguishes whether revenue, total,
thousands/millions and currency words appear in the **full indexed page
text**, **source-anchored position fragments**, or **unanchored PDF font
fragments**. Unanchored fragments are *never* promoted into trusted
citations or accepted facts; these counts only help locate the Arabic
font/layout failure. When source-anchored phrase geometry remains
insufficient, the extractor continues to abstain rather than assuming
that nearby values belong to a certain metric or year.

The report contains **only diagnostics and candidate counts**, not
financial values or page text. A passing program exit status means
diagnostic execution succeeded, not that table interpretation passed.
A failed or empty report is evidence of remaining geometry/reading-order
gaps, not justification to guess revenue rows.

The code does **not** inject reviewed facts into analytics. An
authorized human must still confirm a candidate's row/year/metric/unit
and invoke the separately validated `ReviewedFinancialObservation`
interface. Real-PDF geometry acceptance is pending owner-side testing.

## Engineering acceptance for Slice A

- CSV validation, malformed headers/numbers, row/group/file limits.
- Excel sheet selection, formula rejection, ZIP errors and normal numeric cells.
- Arabic grouping labels, negative adjustments, exact Decimal totals.
- Combined Phase 4 collection/retrieval synthetic and disposable PostgreSQL
  regression in `.github/workflows/p5-analytics-acceptance.yml`.
- No model calls, hosted writes, PRs or merge to `main`.

**Remaining Phase 5 work:** position-aware real-PDF table extraction, durable reviewed
observation lifecycle, authorization/API integration, real workload
performance and formal full-repository quality gate. Slice A/B tests alone do not make Phase 5
production-complete.
