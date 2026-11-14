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

## Engineering acceptance for Slice A

- CSV validation, malformed headers/numbers, row/group/file limits.
- Excel sheet selection, formula rejection, ZIP errors and normal numeric cells.
- Arabic grouping labels, negative adjustments, exact Decimal totals.
- Combined Phase 4 collection/retrieval synthetic and disposable PostgreSQL
  regression in `.github/workflows/p5-analytics-acceptance.yml`.
- No model calls, hosted writes, PRs or merge to `main`.

**Remaining Phase 5 work:** richer financial derivations and source-linked
provenance, authorization/API integration, real workload performance and
formal full-repository quality gate. Slice A/B tests alone do not make Phase 5
production-complete.
