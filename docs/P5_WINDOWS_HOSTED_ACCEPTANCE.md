# Phase 5 Windows-hosted analytics regression

This optional *GitHub Actions* check executes the real deterministic Phase 5
CSV, XLSX, financial-series, SVG chart, reviewed-CSV export and bounded
measurement test suites on `windows-2022` with Python 3.12.

Workflow: `.github/workflows/p5-windows-analytics.yml`.
It stores a 5,000-row synthetic benchmark result named
`p5-windows-hosted-analytics` for seven days.

This confirms Windows **compatibility of the selected automated paths** when
the workflow is green. GitHub-hosted Windows is not the owner's local
Windows computer; CPU, memory, security settings, installed application
versions and filesystem state are different.

The benchmark is explicitly **report-only**, uses `tracemalloc` rather
than resident memory, and has no owner-approved latency or memory threshold.
Never claim a performance gate pass based only on this hosted measurement.
No original annual reports, hosted databases, bearer tokens, private
documents or production access are used.

Remaining manual gates: repeat benchmarks on the owner's Windows device,
record RSS/CPU and run independent source-report visual acceptance with
the authorized PDF collection and disposable PostgreSQL database.
