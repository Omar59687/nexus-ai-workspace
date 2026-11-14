"""Owner-run multi-year financial analytics with optional deterministic SVG.

Example:
  python scripts/analyze_financial_series.py --input /abs/path.csv \
    --company Mobily --metric revenue --currency SAR --unit thousands \
    --start-year 2024 --end-year 2025 --report /abs/report.json --svg /abs/chart.svg

This is a local CLI, not an authenticated HTTP endpoint or automated PDF
extraction. Input records and their currency/unit are caller-supplied.
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

from nexus_ai.data_analytics import AnalyticsInputError, AnalyticsLimits
from nexus_ai.financial_analytics import analyze_financial_series
from nexus_ai.financial_charts import render_financial_line_svg


def _output_path(value: Path | None, source: Path, *, extension: str) -> Path | None:
    if value is None:
        return None
    value = value.expanduser()
    if not value.is_absolute() or value.is_symlink() or value.suffix.lower() != extension:
        raise AnalyticsInputError("invalid output path")
    result = value.resolve()
    if result == source.resolve():
        raise AnalyticsInputError("output must differ from input")
    return result


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".nexus-p5-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--company", required=True)
    parser.add_argument("--metric", required=True)
    parser.add_argument("--currency", required=True)
    parser.add_argument("--unit", required=True)
    parser.add_argument("--start-year", required=True, type=int)
    parser.add_argument("--end-year", required=True, type=int)
    parser.add_argument("--sheet")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--svg", type=Path)
    args = parser.parse_args(argv)
    try:
        path = args.input.expanduser()
        if not path.is_absolute() or path.is_symlink() or not path.is_file():
            raise AnalyticsInputError("absolute regular input required")
        file_type = path.suffix.lower().lstrip(".")
        limits = AnalyticsLimits()
        if path.stat().st_size > limits.max_file_bytes:
            raise AnalyticsInputError("input exceeds file budget")
        result_path = _output_path(args.report, path, extension=".json")
        svg_path = _output_path(args.svg, path, extension=".svg")
        if result_path is not None and result_path == svg_path:
            raise AnalyticsInputError("output paths must be different")
        output = analyze_financial_series(
            path.read_bytes(), file_type=file_type, company=args.company,
            metric=args.metric, currency=args.currency, unit=args.unit,
            start_year=args.start_year, end_year=args.end_year,
            sheet_name=args.sheet, limits=limits,
        )
        encoded = (json.dumps(output, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
        chart = render_financial_line_svg(output).encode("utf-8") if svg_path else None
        if result_path:
            _write_atomic(result_path, encoded)
        if svg_path and chart is not None:
            _write_atomic(svg_path, chart)
        print(json.dumps({
            "status": output["status"],
            "company": output["company"],
            "metric": output["metric"],
            "currency": output["currency"],
            "unit": output["unit"],
            "rows_selected": output["rows_selected"],
            "annual": output["annual"],
            "chart_written": svg_path is not None,
        }, ensure_ascii=True))
        return 0
    except (AnalyticsInputError, OSError, ValueError):
        print('{"status":"BLOCKED","reason":"invalid_or_unsafe_analytics_input"}')
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
