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
    _chunks,
    _default_retrievers,
)


DEFAULT_DEV_FIXTURE = REPOSITORY_ROOT / "benchmarks" / "rag_eval_synthetic_dev_v2.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, help="single-split fixture; required for holdout runs")
    parser.add_argument("--split", choices=("dev", "holdout"), default="dev")
    parser.add_argument("--allow-holdout", action="store_true", help="explicitly permit evaluation on holdout")
    parser.add_argument("-k", type=int, default=3)
    parser.add_argument("--json-out", type=Path, help="write a machine-readable report; existing files are protected")
    parser.add_argument("--overwrite", action="store_true", help="replace the requested JSON report path")
    parser.add_argument("--with-e5", action="store_true", help="include local cached multilingual E5 and BM25+E5 RRF")
    parser.add_argument("--e5-minimum-score", type=float, help="dev-selected cosine threshold; can cause explicit abstention")
    parser.add_argument("--hybrid-minimum-rrf-score", type=float, help="dev-selected RRF threshold for hybrid abstention")
    parser.add_argument("--measure-latency", action="store_true", help="record this host's query timing and system metadata")
    args = parser.parse_args()

    if not args.with_e5 and (
        args.e5_minimum_score is not None
        or args.hybrid_minimum_rrf_score is not None
    ):
        parser.error("E5 score thresholds require --with-e5")

    if args.split == "holdout" and args.fixture is None:
        parser.error("holdout requires an explicit --fixture path")
    fixture_path = args.fixture or DEFAULT_DEV_FIXTURE
    fixture = load_fixture(fixture_path)
    retrievers = None
    if args.with_e5:
        from experiments.rag_prototype.dense_retrieval import (
            DenseRuntimeUnavailable,
            LocalE5Encoder,
            build_dense_hybrid_retrievers,
        )

        corpus = _chunks(fixture, args.split)
        retrievers = _default_retrievers(corpus, measure_timing=args.measure_latency)
        try:
            retrievers.update(
                build_dense_hybrid_retrievers(
                    corpus,
                    LocalE5Encoder(),
                    minimum_score=args.e5_minimum_score,
                    hybrid_minimum_score=args.hybrid_minimum_rrf_score,
                )
            )
        except DenseRuntimeUnavailable as exc:
            parser.error(f"optional local E5 retrieval is unavailable: {exc}")
    report = run_evaluation(
        fixture,
        split=args.split,
        k=args.k,
        allow_holdout=args.allow_holdout,
        retrievers=retrievers,
        measure_latency=args.measure_latency,
    )
    print(render_summary(report))
    if args.json_out:
        written = write_report(
            report,
            args.json_out,
            overwrite=args.overwrite,
            output_root=REPOSITORY_ROOT,
        )
        print(f"\nJSON report written: {written}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
