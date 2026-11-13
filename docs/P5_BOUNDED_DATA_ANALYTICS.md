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

## Engineering acceptance for Slice A

- CSV validation, malformed headers/numbers, row/group/file limits.
- Excel sheet selection, formula rejection, ZIP errors and normal numeric cells.
- Arabic grouping labels, negative adjustments, exact Decimal totals.
- Combined Phase 4 collection/retrieval synthetic and disposable PostgreSQL
  regression in `.github/workflows/p5-analytics-acceptance.yml`.
- No model calls, hosted writes, PRs or merge to `main`.

**Future Phase 5 work:** explicit unit/currency declarations and mixed-unit
rejection, richer metrics and filters, deterministic chart rendering, API
authorization integration, measured workload targets, formal quality gate.
Do not claim Phase 5 complete because Slice A tests pass.
