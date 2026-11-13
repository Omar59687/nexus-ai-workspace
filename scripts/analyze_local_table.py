"""Owner-invoked Phase 5 CSV/XLSX grouped financial summary.

Use explicit local file path; no crawling, HTTP route, cloud API, LLM or DB.
Reports are optional and JSON contains only requested group summaries, not
the full raw spreadsheet content.
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

from nexus_ai.data_analytics import AnalyticsInputError, AnalyticsLimits, analyze_table


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--group-by", required=True)
    parser.add_argument("--sum", required=True, dest="sum_column")
    parser.add_argument("--sheet", default=None)
    parser.add_argument("--report", type=Path, default=None)
    args = parser.parse_args(argv)
    limits = AnalyticsLimits()
    try:
        path = args.input.expanduser()
        if not path.is_absolute() or path.is_symlink() or not path.is_file():
            raise AnalyticsInputError("a regular absolute local file path is required")
        file_type = path.suffix.casefold().lstrip(".")
        if file_type not in ("csv", "xlsx"):
            raise AnalyticsInputError("only CSV and XLSX supported")
        if path.stat().st_size > limits.max_file_bytes:
            raise AnalyticsInputError("file exceeds analytics byte budget")
        raw = path.read_bytes()
        if len(raw) > limits.max_file_bytes:
            raise AnalyticsInputError("file exceeds analytics byte budget")
        output = analyze_table(
            raw, file_type=file_type, group_column=args.group_by,
            amount_column=args.sum_column, sheet_name=args.sheet, limits=limits,
        )
        encoded = (json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
        if args.report:
            report = args.report.expanduser()
            if (not report.is_absolute() or report.is_symlink() or
                    report.suffix.casefold() != ".json" or
                    report.resolve() == path.resolve()):
                raise AnalyticsInputError("invalid report path")
            report.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(prefix=".nexus-analytics-", suffix=".tmp", dir=report.parent)
            try:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(encoded)
                os.replace(temporary, report)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
        print(encoded.decode("utf-8"), end="")
        return 0
    except (AnalyticsInputError, OSError, ValueError):
        print('{"status":"BLOCKED","reason":"invalid_or_unsafe_input"}')
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
