"""Run the FY2025 revenue acceptance benchmark on one local Mobily PDF.

Usage:
    python scripts/verify_mobily_2025_revenue.py --run --pdf ABSOLUTE.pdf --report ABSOLUTE.json

The report contains no source page text and no PDF path. Exit code zero
means the technical diagnostic ran, NOT that financial correctness passed.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from nexus_ai.benchmark.mobily_real_acceptance import run, write_report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", required=True)
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = run(args.pdf)
        write_report(args.report, result, args.pdf)
    except (OSError, ValueError) as exc:
        print(json.dumps({"status": "BLOCKED", "error_class": type(exc).__name__}))
        return 2
    evaluation = result.get("evaluation", {})
    print(json.dumps({
        "status": result["status"],
        "page_count": result.get("page_count"),
        "chunk_count": result.get("chunk_count"),
        "candidate_pages": evaluation.get("candidate_pages"),
        "technical_status": evaluation.get("technical_status"),
        "financial_truth_status": evaluation.get("financial_truth_status"),
        "queries": [
            {"language": row["language"], "top_5_pages": row["top_5_pages"],
             "candidate_at_5": row["relevant_candidate_page_at_5"],
             "candidate_at_10": row["relevant_candidate_page_at_10"]}
            for row in evaluation.get("languages", [])
        ],
    }, ensure_ascii=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
