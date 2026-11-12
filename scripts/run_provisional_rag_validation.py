"""Run the explicitly synthetic, development-only RAG smoke evaluation."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from experiments.rag_prototype.evaluation import render_summary, write_report
from experiments.rag_prototype.provisional_evaluation import (
    load_provisional_fixture,
    run_provisional_evaluation,
)


DEFAULT_FIXTURE = REPOSITORY_ROOT / "benchmarks" / "rag_eval_synthetic_dev_v2.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("-k", type=int, default=3)
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--measure-latency", action="store_true")
    args = parser.parse_args()
    fixture = load_provisional_fixture(args.fixture)
    report = run_provisional_evaluation(
        fixture, k=args.k, measure_latency=args.measure_latency
    )
    print(render_summary(report))
    print("\nStage: provisional-development (synthetic only)")
    print("Synthetic results do not establish retrieval quality on real documents.")
    if args.json_out:
        written = write_report(report, args.json_out, output_root=REPOSITORY_ROOT)
        print(f"\nJSON report written: {written}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
