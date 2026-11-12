"""Run an explicitly opted-in, provisional owner-review RAG diagnostic."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from experiments.rag_prototype import BM25Index, Chunk, ChunkHit
from experiments.rag_prototype.benchmark_dataset import write_json_no_clobber
from experiments.rag_prototype.dense_retrieval import (
    DenseRuntimeUnavailable,
    LocalE5Encoder,
    build_dense_hybrid_retrievers,
)
from experiments.rag_prototype.evaluation import RetrieverSpec
from experiments.rag_prototype.owner_review_diagnostic import (
    SUPPORTED_REVIEWERS,
    load_owner_dev_manifest,
    run_owner_dev_diagnostic,
)
from experiments.rag_prototype.window_retrieval import build_windowed_e5_retrievers


def _chunks(dataset):
    documents = {row["document_id"]: row for row in dataset["documents"]}
    output = []
    for row in dataset["chunks"]:
        doc = documents[row["document_id"]]
        text = doc["text"]
        start_line = text.count("\n", 0, row["start_char"]) + 1
        end_line = text.count("\n", 0, row["end_char"]) + 1
        output.append(Chunk(
            doc["source_ref"], doc["document_id"], row["version_id"], row["chunk_id"],
            row["start_char"], row["end_char"], start_line, end_line, (), row["text"],
        ))
    return tuple(output)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True, help="schema-v2 dev manifest")
    parser.add_argument("--allow-provisional", action="store_true", required=True,
                        help="explicitly opt into submitted, non-adjudicated owner labels")
    parser.add_argument("--reviewer", choices=sorted(SUPPORTED_REVIEWERS), required=True)
    parser.add_argument("-k", type=int, default=3)
    parser.add_argument("--with-e5", action="store_true", help="compare original full-chunk E5")
    parser.add_argument("--with-windowed-e5", action="store_true",
                        help="compare actual E5 retrieval over overlapping subwindows and weighted-RRF hybrid")
    parser.add_argument("--window-chars", type=int, default=500)
    parser.add_argument("--window-overlap", type=int, default=100)
    parser.add_argument("--dense-rrf-weight", type=float, default=0.75)
    parser.add_argument("--json-out", type=Path, help="safe exclusive output; existing files are not replaced")
    args = parser.parse_args()
    if not (args.with_e5 or args.with_windowed_e5):
        parser.error("select --with-e5 and/or --with-windowed-e5")
    try:
        dataset = load_owner_dev_manifest(args.manifest, reviewer_id=args.reviewer)
        chunks = _chunks(dataset)
        lexical = BM25Index(chunks)
        retrievers = {
            "bm25_raw": RetrieverSpec(
                lambda query, k: tuple(ChunkHit(hit.chunk, hit.score) for hit in lexical.search(query, top_k=k)),
                "BM25 score descending, chunk ID ascending", metadata={"strategy": "original full-chunk BM25"},
            ),
        }
        if args.with_e5 or args.with_windowed_e5:
            # LocalE5Encoder only loads the pinned revision from the existing cache.
            encoder = LocalE5Encoder()
            if args.with_e5:
                retrievers["original_e5"] = build_dense_hybrid_retrievers(chunks, encoder)["dense_e5_small"]
            if args.with_windowed_e5:
                retrievers.update(build_windowed_e5_retrievers(
                    chunks, encoder, window_chars=args.window_chars,
                    overlap_chars=args.window_overlap, dense_weight=args.dense_rrf_weight,
                ))
        report = run_owner_dev_diagnostic(dataset, retrievers, reviewer_id=args.reviewer, k=args.k)
    except DenseRuntimeUnavailable as exc:
        parser.error(f"offline cached E5 unavailable; no model was downloaded: {exc}")
    except (ValueError, OSError) as exc:
        parser.error(str(exc))

    print(report["evaluation_status"])
    print(f"Dataset: {report['dataset']['dataset_id']} v{report['dataset']['dataset_version']} "
          f"({report['dataset']['query_count']} queries); k={report['k']}")
    for strategy, result in report["strategies"].items():
        print(f"\n{strategy}")
        for direction, values in result["by_direction"].items():
            print(f"  {direction}: Recall@{args.k}={values['recall_at_k']:.3f}; "
                  f"MRR@{args.k}={values['mrr_at_k']:.3f}; nDCG@{args.k}={values['ndcg_at_k']:.3f}")
        print(f"  no-answer false positives={result['no_answer']['false_positive_queries']}/"
              f"{result['no_answer']['query_count']}; abstentions={result['no_answer']['abstained_queries']}")
    print("\nThese results describe submitted owner-review decisions only; they are not independently "
          "adjudicated ground truth and do not satisfy the formal acceptance gate.")
    if args.json_out:
        written = write_json_no_clobber(report, args.json_out)
        print(f"Provisional diagnostic report written: {written}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
