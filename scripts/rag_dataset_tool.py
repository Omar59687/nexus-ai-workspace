"""Prepare, validate, export, and collect human review for RAG datasets."""

from __future__ import annotations

import argparse
import csv
import io
import json
from pathlib import Path
import sys

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from experiments.rag_prototype import IngestionLimits
from experiments.rag_prototype.benchmark_dataset import (
    adjudicate_reviews,
    build_corpus_manifest,
    dataset_release_sha256,
    export_review_sheet,
    import_review_sheet,
    validate_dataset,
    validate_split_pair,
    write_json_no_clobber,
    resolve_adjudications,
    to_evaluation_fixture,
    validate_adjudication_summary,
    _read_bounded_bytes,
)


MAX_JSON_INPUT_BYTES = 250_000_000
MAX_CSV_INPUT_BYTES = 100_000_000


def _load(path: Path) -> dict:
    payload = _read_bounded_bytes(path, MAX_JSON_INPUT_BYTES, "dataset JSON")
    return json.loads(payload.decode("utf-8-sig"), object_pairs_hook=_unique_pairs)


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _csv_text(path: Path, label: str) -> str:
    return _read_bounded_bytes(path, MAX_CSV_INPUT_BYTES, label).decode("utf-8-sig")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    ingest = commands.add_parser("ingest", help="create an unjudged bounded corpus manifest")
    ingest.add_argument("--root", type=Path, required=True)
    ingest.add_argument("--metadata-csv", type=Path, required=True, help="columns: relative_path,language,source_ref")
    ingest.add_argument("--output", type=Path, required=True)
    ingest.add_argument("--dataset-id", required=True)
    ingest.add_argument("--dataset-version", required=True)
    ingest.add_argument("--split", choices=("dev", "holdout"), required=True)
    ingest.add_argument("--source-name", required=True)
    ingest.add_argument("--source-version", required=True)
    ingest.add_argument("--license", required=True)
    ingest.add_argument("--retrieved-at", required=True)
    ingest.add_argument("--synthetic", action="store_true")

    validate = commands.add_parser("validate", help="validate one split dataset and its annotations")
    validate.add_argument("dataset", type=Path)

    pair = commands.add_parser("validate-pair", help="check split separation before protecting a holdout release")
    pair.add_argument("dev_dataset", type=Path)
    pair.add_argument("holdout_dataset", type=Path)

    export = commands.add_parser("export-review", help="export blank human-review rows")
    export.add_argument("dataset", type=Path)
    export.add_argument("--reviewer-id", required=True)
    export.add_argument("--output", type=Path, required=True)

    import_reviews = commands.add_parser("import-review", help="record submitted decisions without approval")
    import_reviews.add_argument("dataset", type=Path)
    import_reviews.add_argument("--csv", type=Path, required=True)
    import_reviews.add_argument("--reviewer-id", required=True, help="assigned reviewer identity; must match every CSV row")
    import_reviews.add_argument("--output", type=Path, required=True)

    adjudicate = commands.add_parser("adjudicate", help="summarize independent votes; disagreements remain open")
    adjudicate.add_argument("dataset", type=Path)
    adjudicate.add_argument("--output", type=Path, required=True)

    resolve = commands.add_parser("resolve", help="record a separate adjudicator's decision for disagreements")
    resolve.add_argument("dataset", type=Path)
    resolve.add_argument("--adjudications", type=Path, required=True)
    resolve.add_argument("--csv", type=Path, required=True,
                         help="columns: question_id,target_kind,target_id,adjudicator_id,relevance,rationale")
    resolve.add_argument("--output", type=Path, required=True)

    build_eval = commands.add_parser("build-eval", help="build a fixture only from accepted human labels")
    build_eval.add_argument("dataset", type=Path)
    build_eval.add_argument("--adjudications", type=Path, required=True)
    build_eval.add_argument("--output", type=Path, required=True)

    args = parser.parse_args()
    if args.command == "ingest":
        metadata = {}
        with io.StringIO(_csv_text(args.metadata_csv, "metadata CSV"), newline="") as stream:
            reader = csv.DictReader(stream)
            if tuple(reader.fieldnames or ()) != ("relative_path", "language", "source_ref"):
                parser.error("metadata CSV needs columns relative_path,language,source_ref in that order")
            for row in reader:
                if row["relative_path"] in metadata:
                    parser.error(f"duplicate metadata path: {row['relative_path']}")
                metadata[row["relative_path"]] = {
                    "language": row["language"], "source_ref": row["source_ref"]
                }
        manifest = build_corpus_manifest(
            args.root,
            metadata,
            dataset_id=args.dataset_id,
            dataset_version=args.dataset_version,
            split=args.split,
            source_name=args.source_name,
            source_version=args.source_version,
            license_name=args.license,
            retrieved_at=args.retrieved_at,
            synthetic=args.synthetic,
            limits=IngestionLimits(),
        )
        write_json_no_clobber(manifest, args.output)
        print(f"Created unjudged corpus manifest: {args.output}")
        print(f"Documents: {len(manifest['documents'])}; chunks: {len(manifest['chunks'])}; queries: 0")
        return 0

    if args.command == "validate-pair":
        validate_split_pair(_load(args.dev_dataset), _load(args.holdout_dataset))
        print("Split pair passed exact identity, source, normalized document, and chunk separation checks")
        return 0

    dataset = _load(args.dataset)
    validated = validate_dataset(dataset, require_coverage=(args.command == "validate"))
    if args.command == "validate":
        print(f"Valid {validated['split']} dataset {validated['dataset_id']}@{validated['dataset_version']}")
        print(f"Documents: {len(validated['_indexes']['documents'])}; chunks: {len(validated['_indexes']['chunks'])}; queries: {len(validated['_indexes']['queries'])}")
        print(f"Submitted review records: {len(validated.get('review_records', []))}")
        return 0
    if args.command == "export-review":
        destination = export_review_sheet(validated, args.output, reviewer_id=args.reviewer_id)
        print(f"Review sheet created with blank judgments: {destination}")
        return 0
    if args.command == "import-review":
        records = import_review_sheet(validated, args.csv, expected_reviewer_id=args.reviewer_id)
        updated = {key: value for key, value in validated.items() if key != "_indexes"}
        updated["review_records"] = [*updated.get("review_records", []), *records]
        validate_dataset(updated, require_coverage=False)
        write_json_no_clobber(updated, args.output)
        print(f"Recorded {len(records)} submitted decisions; no approval was assigned")
        return 0
    if args.command == "adjudicate":
        summary = {
            "dataset_id": validated["dataset_id"],
            "dataset_version": validated["dataset_version"],
            "split": validated["split"],
            "dataset_release_sha256": dataset_release_sha256(validated),
            "decisions": adjudicate_reviews(validated.get("review_records", [])),
        }
        write_json_no_clobber(summary, args.output)
        print(f"Adjudication summary written; unresolved decisions remain marked")
        return 0
    if args.command == "resolve":
        previous = _load(args.adjudications)
        validate_adjudication_summary(validated, previous)
        resolutions = []
        required = ("question_id", "target_kind", "target_id", "adjudicator_id", "relevance", "rationale")
        with io.StringIO(_csv_text(args.csv, "adjudication CSV"), newline="") as stream:
            reader = csv.DictReader(stream)
            if tuple(reader.fieldnames or ()) != required:
                parser.error("adjudication CSV columns do not match the documented order")
            for row in reader:
                try:
                    row["relevance"] = int(row["relevance"])
                except (TypeError, ValueError):
                    parser.error("each adjudication relevance must be an integer")
                resolutions.append(row)
        resolved = resolve_adjudications(previous.get("decisions", []), resolutions)
        output = {
            "dataset_id": validated["dataset_id"],
            "dataset_version": validated["dataset_version"],
            "split": validated["split"],
            "dataset_release_sha256": dataset_release_sha256(validated),
            "decisions": resolved,
        }
        write_json_no_clobber(output, args.output)
        print("Recorded explicit adjudicator decisions; reviewer ballots remain in the dataset")
        return 0
    if args.command == "build-eval":
        adjudication_data = _load(args.adjudications)
        fixture = to_evaluation_fixture(validated, adjudication_data)
        from experiments.rag_prototype.evaluation import validate_fixture
        validate_fixture(fixture)
        write_json_no_clobber(fixture, args.output)
        print(f"Built evaluation fixture from accepted decisions: {args.output}")
        return 0
    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
