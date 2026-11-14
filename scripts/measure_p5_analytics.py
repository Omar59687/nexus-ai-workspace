"""Reproducible bounded Phase 5 CSV/XLSX performance evidence.

A report-only measurement harness, not a formal Windows performance gate.
No network services, database credentials, PDF inputs, or model calls.
"""
from __future__ import annotations

import argparse
from io import BytesIO
import json
import platform
import sys
from time import perf_counter
import tracemalloc

from nexus_ai.data_analytics import analyze_table

DEFAULT_ROWS = 5000
GROUPS = 20


def _data(rows: int):
    if type(rows) is not int or not 1 <= rows <= 20000:
        raise ValueError("rows must be between 1 and 20000")
    records = [
        (f"group-{i % GROUPS:02d}", str(i % 17 + 1))
        for i in range(rows)
    ]
    total = sum(i % 17 + 1 for i in range(rows))
    csv_bytes = (
        "Group,Amount\n" +
        "".join(f"{group},{value}\n" for group, value in records)
    ).encode("utf-8")

    from openpyxl import Workbook
    wb = Workbook(write_only=True)
    sheet = wb.create_sheet("Data")
    sheet.append(["Group", "Amount"])
    for group, value in records:
        sheet.append([group, int(value)])
    stream = BytesIO()
    wb.save(stream)
    return csv_bytes, stream.getvalue(), str(total)


def measure(rows: int = DEFAULT_ROWS) -> dict[str, object]:
    csv_bytes, xlsx_bytes, expected = _data(rows)
    results = {}
    for kind, blob in (("csv", csv_bytes), ("xlsx", xlsx_bytes)):
        tracemalloc.start()
        start = perf_counter()
        try:
            outcome = analyze_table(
                blob, file_type=kind, group_column="Group",
                amount_column="Amount",
            )
            elapsed_ms = (perf_counter() - start) * 1000
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        if outcome["total"] != expected or outcome["row_count"] != rows:
            raise AssertionError("benchmark result does not match exact reference total")
        results[kind] = {
            "input_bytes": len(blob),
            "elapsed_ms": round(elapsed_ms, 2),
            "traced_peak_bytes": peak,
            "total_decimal": outcome["total"],
            "row_count": outcome["row_count"],
            "group_count": outcome["group_count"],
        }
    return {
        "kind": "p5_local_analytics_measurement_v1",
        "purpose": "REPORT_ONLY_NOT_AN_ACCEPTANCE_THRESHOLD",
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "rows": rows,
        "groups": GROUPS if rows >= GROUPS else rows,
        "measurements": results,
        "limitations": [
            "tracemalloc excludes native allocations and external process memory",
            "timings vary with host load, Python and dependency versions",
            "synthetic data does not validate real financial files",
            "Windows target-machine acceptance remains unmeasured",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=DEFAULT_ROWS)
    args = parser.parse_args()
    print(json.dumps(measure(rows=args.rows), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
