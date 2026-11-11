"""Run the isolated, deterministic bilingual retrieval fixture."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from experiments.rag_prototype.evaluation import (
    load_fixture,
    render_summary,
    run_evaluation,
    write_report,
)


DEFAULT_FIXTURE = REPOSITORY_ROOT / "benchmarks" / "rag_eval_synthetic_v1.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--split", choices=("dev", "holdout"), default="dev")
    parser.add_argument("--allow-holdout", action="store_true", help="explicitly permit evaluation on holdout")
    parser.add_argument("-k", type=int, default=3)
    parser.add_argument("--json-out", type=Path, help="write a machine-readable report; existing files are protected")
    parser.add_argument("--overwrite", action="store_true", help="replace the requested JSON report path")
    args = parser.parse_args()

    fixture = load_fixture(args.fixture)
    report = run_evaluation(
        fixture,
        split=args.split,
        k=args.k,
        allow_holdout=args.allow_holdout,
    )
    print(render_summary(report))
    if args.json_out:
        written = write_report(report, args.json_out, overwrite=args.overwrite)
        print(f"\nJSON report written: {written}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
