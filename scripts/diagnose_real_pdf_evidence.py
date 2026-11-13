"""Owner opt-in read-only real PDF diagnostic; writes a UTF-8 report directly.

Avoid PowerShell stdout redirection, which may create UTF-16 JSON on Windows.
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

from nexus_ai.benchmark.real_pdf_diagnostic import run_diagnostic


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", required=True)
    parser.add_argument("--pdf", required=True, type=Path)
    parser.add_argument("--company", required=True)
    parser.add_argument("--year", required=True, type=int)
    parser.add_argument("--query", required=True, action="append", dest="queries")
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.report.is_symlink():
            raise ValueError("report symlinks forbidden")
        pdf = args.pdf.expanduser()
        report = args.report.expanduser().resolve()
        # Keep generated files completely outside the owner-selected PDF root.
        root = pdf.parent.resolve(strict=True)
        if report == pdf.resolve(strict=True) or report == root or root in report.parents:
            raise ValueError("report must be outside PDF source directory")
        result = run_diagnostic(
            pdf, company=args.company, year=args.year, queries=args.queries,
        )
        report.parent.mkdir(parents=True, exist_ok=True)
        encoded = (json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
        # Replace the complete report atomically, avoiding stale partial JSON.
        fd, temp_path = tempfile.mkstemp(prefix=".nexus-pdf-", suffix=".json.tmp", dir=report.parent)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(encoded)
            os.replace(temp_path, report)
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
        print(json.dumps({
            "status": result["status"],
            "page_count": result.get("source", {}).get("page_count"),
            "chunk_count": result.get("source", {}).get("chunk_count"),
            "query_count": len(result.get("queries", [])),
        }, ensure_ascii=True))
        return 0 if result["status"] == "PASS" else 1
    except (OSError, ValueError) as exc:
        print('{"status":"BLOCKED","reason":"invalid_args_or_output"}')
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
