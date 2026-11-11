"""Dataset provenance and human-review utilities for RAG benchmarks.

This module never fabricates relevance labels. Imported reviewer decisions stay
submitted until independent agreement or an explicit adjudicator resolution.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import threading
import unicodedata
from contextlib import contextmanager
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping

from experiments.rag_prototype.evaluation import DIRECTIONS, FixtureError, _string
from experiments.rag_prototype import IngestionLimits, ingest_corpus


DATASET_SCHEMA_VERSION = 2
MAX_REVIEW_EXPORT_BYTES = 100_000_000
MAX_REVIEW_IMPORT_BYTES = 100_000_000
MAX_REVIEW_FIELD_CHARS = 2_000_000
_CSV_FIELD_LIMIT_LOCK = threading.RLock()
REVIEW_FIELDS = (
    "dataset_id", "dataset_version", "dataset_provenance_sha256", "split", "question_id",
    "query_language", "evidence_language", "query_sha256", "query_text", "target_kind", "target_id",
    "document_id", "document_version_id", "source_ref", "document_language", "document_content_sha256",
    "chunk_id", "chunk_content_sha256", "evidence_sha256", "evidence_text",
    "reviewer_id", "relevance", "rationale",
)


def validate_dataset(dataset: Any, *, require_coverage: bool = True) -> dict[str, Any]:
    """Validate one split's provenance, identities, offsets, and annotation records."""
    if not isinstance(dataset, dict) or dataset.get("schema_version") != DATASET_SCHEMA_VERSION:
        raise FixtureError("dataset schema_version must be 2")
    for key in ("dataset_id", "dataset_version"):
        _string(dataset.get(key), key)
    split = dataset.get("split")
    if split not in ("dev", "holdout"):
        raise FixtureError("split must be dev or holdout")
    if type(dataset.get("synthetic")) is not bool:
        raise FixtureError("synthetic must be an explicit boolean")
    provenance = dataset.get("provenance")
    if not isinstance(provenance, dict):
        raise FixtureError("provenance must be an object")
    for key in ("source_name", "source_version", "license", "retrieved_at", "source_sha256"):
        _string(provenance.get(key), f"provenance.{key}")
    if len(provenance["source_sha256"]) != 64 or any(c not in "0123456789abcdef" for c in provenance["source_sha256"].lower()):
        raise FixtureError("provenance.source_sha256 must be a SHA-256 hex digest")

    documents = dataset.get("documents")
    chunks = dataset.get("chunks")
    queries = dataset.get("queries")
    if not all(isinstance(rows, list) and rows for rows in (documents, chunks, queries)):
        raise FixtureError("documents, chunks, and queries must be non-empty lists")
    docs = _index(documents, "document_id", "documents")
    chunk_index = _index(chunks, "chunk_id", "chunks")
    query_index = _index(queries, "question_id", "queries")
    for document_id, doc in docs.items():
        if doc.get("split") != split or doc.get("language") not in ("ar", "en"):
            raise FixtureError(f"documents[{document_id}] has invalid split or language")
        _string(doc.get("source_ref"), f"documents[{document_id}].source_ref")
        _string(doc.get("version_id"), f"documents[{document_id}].version_id")
        _string(doc.get("text"), f"documents[{document_id}].text")
        if len(doc["text"].encode("utf-8")) > 2_000_000:
            raise FixtureError(f"documents[{document_id}].text exceeds 2 MB")
        digest = hashlib.sha256(doc["text"].encode("utf-8")).hexdigest()
        if doc.get("content_sha256") != digest:
            raise FixtureError(f"documents[{document_id}].content_sha256 does not match text")

    chunk_docs: dict[str, str] = {}
    for chunk_id, chunk in chunk_index.items():
        doc_id = chunk.get("document_id")
        if doc_id not in docs:
            raise FixtureError(f"chunks[{chunk_id}] references unknown document")
        doc = docs[doc_id]
        if chunk.get("split") != split or chunk.get("version_id") != doc["version_id"]:
            raise FixtureError(f"chunks[{chunk_id}] has inconsistent split or version")
        start, end = chunk.get("start_char"), chunk.get("end_char")
        if type(start) is not int or type(end) is not int or start < 0 or end < start or end > len(doc["text"]):
            raise FixtureError(f"chunks[{chunk_id}] has invalid source offsets")
        if doc["text"][start:end] != chunk.get("text"):
            raise FixtureError(f"chunks[{chunk_id}] text does not match source offsets")
        if len(chunk["text"]) > 4_000:
            raise FixtureError(f"chunks[{chunk_id}].text exceeds 4,000 characters")
        if chunk.get("content_sha256") != hashlib.sha256(chunk["text"].encode("utf-8")).hexdigest():
            raise FixtureError(f"chunks[{chunk_id}].content_sha256 does not match text")
        chunk_docs[chunk_id] = doc_id

    directions = set()
    for question_id, query in query_index.items():
        if query.get("split") != split or query.get("query_language") not in ("ar", "en"):
            raise FixtureError(f"queries[{question_id}] has invalid split or language")
        _string(query.get("text"), f"queries[{question_id}].text")
        if len(query["text"].encode("utf-8")) > 32_000:
            raise FixtureError(f"queries[{question_id}].text exceeds 32 KB")
        answerable = query.get("answerable")
        if type(answerable) is not bool:
            raise FixtureError(f"queries[{question_id}].answerable must be boolean")
        if answerable:
            evidence_language = query.get("evidence_language")
            if evidence_language not in ("ar", "en"):
                raise FixtureError(f"queries[{question_id}] needs evidence_language")
            directions.add(f"{query['query_language']}->{evidence_language}")
        elif query.get("evidence_language") is not None:
            raise FixtureError(f"unanswerable query {question_id} must not name evidence_language")
    if require_coverage and directions != set(DIRECTIONS):
        raise FixtureError(f"{split} split lacks bilingual directions: {', '.join(sorted(set(DIRECTIONS)-directions))}")

    annotations = dataset.get("review_records", [])
    if not isinstance(annotations, list):
        raise FixtureError("review_records must be a list")
    seen = set()
    for row in annotations:
        if not isinstance(row, dict):
            raise FixtureError("review record must be an object")
        question_id = row.get("question_id")
        target_kind = row.get("target_kind")
        target_id = row.get("target_id")
        reviewer_id = _string(row.get("reviewer_id"), "reviewer_id")
        if question_id not in query_index or target_kind not in ("document", "chunk", "answerability"):
            raise FixtureError("review record has unknown question or target_kind")
        if target_kind == "answerability" and target_id != question_id:
            raise FixtureError("answerability target_id must equal question_id")
        if (target_kind == "document" and target_id not in docs) or (target_kind == "chunk" and target_id not in chunk_index):
            raise FixtureError("review record has unknown target_id")
        grade = row.get("relevance")
        allowed = (0, 3) if target_kind == "answerability" else (0, 1, 2, 3)
        if type(grade) is not int or grade not in allowed:
            raise FixtureError("relevance grade is invalid for the target kind")
        _string(row.get("rationale"), "rationale")
        if row.get("status") != "submitted":
            raise FixtureError("imported review records must remain submitted")
        key = (question_id, target_kind, target_id, reviewer_id)
        if key in seen:
            raise FixtureError("duplicate reviewer decision for a target")
        seen.add(key)
    validated = dict(dataset)
    validated["_indexes"] = {"documents": docs, "chunks": chunk_index, "queries": query_index}
    return validated


def _index(rows: list[Any], key: str, label: str) -> dict[str, dict[str, Any]]:
    output = {}
    for row in rows:
        if not isinstance(row, dict):
            raise FixtureError(f"{label} rows must be objects")
        item_id = _string(row.get(key), f"{label}.{key}")
        if item_id in output:
            raise FixtureError(f"duplicate {key}: {item_id}")
        output[item_id] = row
    return output


def dataset_release_sha256(dataset: Mapping[str, Any]) -> str:
    """Hash the immutable dataset content that reviewer judgments refer to."""
    payload = {
        "schema_version": dataset.get("schema_version"),
        "dataset_id": dataset.get("dataset_id"),
        "dataset_version": dataset.get("dataset_version"),
        "split": dataset.get("split"),
        "synthetic": dataset.get("synthetic"),
        "provenance": dataset.get("provenance"),
        "documents": sorted(dataset.get("documents", []), key=lambda row: row.get("document_id", "")),
        "chunks": sorted(dataset.get("chunks", []), key=lambda row: row.get("chunk_id", "")),
        "queries": sorted(dataset.get("queries", []), key=lambda row: row.get("question_id", "")),
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def validate_split_pair(dev: Mapping[str, Any], holdout: Mapping[str, Any]) -> None:
    """Check release-time separation without loading holdout during dev runs."""
    dev_data = validate_dataset(dict(dev), require_coverage=True)
    holdout_data = validate_dataset(dict(holdout), require_coverage=True)
    if dev_data["split"] != "dev" or holdout_data["split"] != "holdout":
        raise FixtureError("split pair must be supplied in dev, holdout order")
    if (dev_data["dataset_id"], dev_data["dataset_version"]) != (holdout_data["dataset_id"], holdout_data["dataset_version"]):
        raise FixtureError("split pair must share dataset_id and dataset_version")
    dev_docs = dev_data["_indexes"]["documents"]
    holdout_docs = holdout_data["_indexes"]["documents"]
    for key in ("document_id", "source_ref"):
        left = {row[key] for row in dev_docs.values()}
        right = {row[key] for row in holdout_docs.values()}
        if left & right:
            raise FixtureError(f"dev and holdout share {key}")
    def normalized(text: str) -> str:
        value = unicodedata.normalize("NFKC", text).casefold()
        return " ".join(value.split())
    doc_hashes = {hashlib.sha256(normalized(row["text"]).encode("utf-8")).hexdigest() for row in dev_docs.values()}
    holdout_doc_hashes = {hashlib.sha256(normalized(row["text"]).encode("utf-8")).hexdigest() for row in holdout_docs.values()}
    if doc_hashes & holdout_doc_hashes:
        raise FixtureError("dev and holdout share normalized document text")
    dev_chunks = dev_data["_indexes"]["chunks"]
    holdout_chunks = holdout_data["_indexes"]["chunks"]
    chunk_hashes = {hashlib.sha256(normalized(row["text"]).encode("utf-8")).hexdigest() for row in dev_chunks.values()}
    holdout_chunk_hashes = {hashlib.sha256(normalized(row["text"]).encode("utf-8")).hexdigest() for row in holdout_chunks.values()}
    if chunk_hashes & holdout_chunk_hashes:
        raise FixtureError("dev and holdout share normalized chunk text")


def export_review_sheet(
    dataset: Mapping[str, Any],
    path: str | Path,
    *,
    reviewer_id: str,
    max_rows: int = 100_000,
    max_output_bytes: int = MAX_REVIEW_EXPORT_BYTES,
) -> Path:
    """Export query/document and query/chunk candidates with blank human labels."""
    _string(reviewer_id, "reviewer_id")
    if type(max_rows) is not int or max_rows <= 0:
        raise ValueError("max_rows must be a positive integer")
    if type(max_output_bytes) is not int or max_output_bytes <= 0:
        raise ValueError("max_output_bytes must be a positive integer")
    checked = validate_dataset(dict(dataset), require_coverage=False)
    indexes = checked["_indexes"]
    destination = _safe_output_path(path)
    row_count = len(indexes["queries"]) * (1 + len(indexes["documents"]) + len(indexes["chunks"]))
    if row_count > max_rows:
        raise ValueError("review sheet exceeds max_rows; create a frozen candidate pool first")
    estimated_chars = sum(
        (len(query["text"]) * (1 + len(indexes["documents"]) + len(indexes["chunks"])))
        + sum(len(row["text"]) for row in indexes["documents"].values())
        + sum(len(row["text"]) for row in indexes["chunks"].values())
        for query in indexes["queries"].values()
    )
    if estimated_chars > max_output_bytes:
        raise ValueError("review sheet exceeds max_output_bytes before export")
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=REVIEW_FIELDS)
    writer.writeheader()
    for qid in sorted(indexes["queries"]):
        query = indexes["queries"][qid]
        writer.writerow(_review_row(checked, query, "answerability", qid, "", "", reviewer_id))
        for doc_id in sorted(indexes["documents"]):
            writer.writerow(_review_row(checked, query, "document", doc_id, doc_id, "", reviewer_id))
        for chunk_id in sorted(indexes["chunks"]):
            doc_id = indexes["chunks"][chunk_id]["document_id"]
            writer.writerow(_review_row(checked, query, "chunk", chunk_id, doc_id, chunk_id, reviewer_id))
    payload = buffer.getvalue().encode("utf-8")
    if len(payload) > max_output_bytes:
        raise ValueError("review sheet exceeds max_output_bytes")
    _create_exclusive_file(destination, payload)
    return destination


def _review_row(dataset: Mapping[str, Any], query: Mapping[str, Any], kind: str,
                target_id: str, document_id: str, chunk_id: str, reviewer: str) -> dict[str, str]:
    indexes = dataset["_indexes"]
    doc = indexes["documents"].get(document_id) if document_id else None
    chunk = indexes["chunks"].get(chunk_id) if chunk_id else None
    evidence = chunk["text"] if chunk else doc["text"] if doc else ""
    provenance = json.dumps(dataset["provenance"], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {
        "dataset_id": dataset["dataset_id"],
        "dataset_version": dataset["dataset_version"],
        "dataset_provenance_sha256": hashlib.sha256(provenance.encode("utf-8")).hexdigest(),
        "split": dataset["split"],
        "question_id": query["question_id"],
        "query_language": query["query_language"],
        "evidence_language": query.get("evidence_language") or "",
        "query_sha256": hashlib.sha256(query["text"].encode("utf-8")).hexdigest(),
        "query_text": query["text"],
        "target_kind": kind,
        "target_id": target_id,
        "document_id": document_id,
        "document_version_id": doc["version_id"] if doc else "",
        "source_ref": doc["source_ref"] if doc else "",
        "document_language": doc["language"] if doc else "",
        "document_content_sha256": doc["content_sha256"] if doc else "",
        "chunk_id": chunk_id,
        "chunk_content_sha256": chunk["content_sha256"] if chunk else "",
        "evidence_sha256": hashlib.sha256(evidence.encode("utf-8")).hexdigest() if evidence else "",
        "evidence_text": evidence,
        "reviewer_id": reviewer,
        "relevance": "",
        "rationale": "",
    }


def import_review_sheet(
    dataset: Mapping[str, Any],
    path: str | Path,
    *,
    expected_reviewer_id: str,
) -> list[dict[str, Any]]:
    """Parse submitted judgments; this function never adjudicates or approves them."""
    expected_reviewer_id = _string(expected_reviewer_id, "expected_reviewer_id")
    checked = validate_dataset(dict(dataset), require_coverage=False)
    indexes = checked["_indexes"]
    records = []
    raw = _read_bounded_bytes(path, MAX_REVIEW_IMPORT_BYTES, "review sheet")
    with _bounded_csv_field_limit():
        with io.StringIO(raw.decode("utf-8-sig"), newline="") as stream:
            reader = csv.DictReader(stream)
            if tuple(reader.fieldnames or ()) != REVIEW_FIELDS:
                raise FixtureError("review sheet columns do not match the required schema")
            for line, row in enumerate(reader, start=2):
                if row["dataset_id"] != checked["dataset_id"] or row["dataset_version"] != checked["dataset_version"] or row["split"] != checked["split"]:
                    raise FixtureError(f"review sheet line {line} belongs to a different dataset version or split")
                if row["reviewer_id"] != expected_reviewer_id:
                    raise FixtureError(f"review sheet line {line} reviewer_id does not match the assigned reviewer")
                question_id, kind, target_id = row["question_id"], row["target_kind"], row["target_id"]
                if question_id not in indexes["queries"]:
                    raise FixtureError(f"review sheet line {line} has unknown question")
                query = indexes["queries"][question_id]
                expected_provenance = json.dumps(checked["provenance"], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                if row["dataset_provenance_sha256"] != hashlib.sha256(expected_provenance.encode("utf-8")).hexdigest():
                    raise FixtureError(f"review sheet line {line} provenance context was changed")
                if row["query_language"] != query["query_language"] or row["query_text"] != query["text"]:
                    raise FixtureError(f"review sheet line {line} query context was changed")
                if row["query_sha256"] != hashlib.sha256(query["text"].encode("utf-8")).hexdigest():
                    raise FixtureError(f"review sheet line {line} query hash was changed")
                if row["evidence_language"] != (query.get("evidence_language") or ""):
                    raise FixtureError(f"review sheet line {line} evidence language was changed")
                target_index = indexes["documents"] if kind == "document" else indexes["chunks"] if kind == "chunk" else indexes["queries"] if kind == "answerability" else {}
                if target_id not in target_index:
                    raise FixtureError(f"review sheet line {line} has unknown target")
                if kind == "document":
                    expected_doc = indexes["documents"][target_id]
                    expected_chunk_id, expected_evidence = "", expected_doc["text"]
                elif kind == "chunk":
                    expected_chunk = indexes["chunks"][target_id]
                    expected_doc = indexes["documents"][expected_chunk["document_id"]]
                    expected_chunk_id, expected_evidence = target_id, expected_chunk["text"]
                else:
                    expected_doc = None
                    expected_chunk_id, expected_evidence = "", ""
                if (
                    row["document_id"] != (expected_doc["document_id"] if expected_doc else "")
                    or row["document_version_id"] != (expected_doc["version_id"] if expected_doc else "")
                    or row["source_ref"] != (expected_doc["source_ref"] if expected_doc else "")
                    or row["document_language"] != (expected_doc["language"] if expected_doc else "")
                    or row["document_content_sha256"] != (expected_doc["content_sha256"] if expected_doc else "")
                    or row["chunk_id"] != expected_chunk_id
                    or row["chunk_content_sha256"] != (indexes["chunks"][expected_chunk_id]["content_sha256"] if expected_chunk_id else "")
                    or row["evidence_text"] != expected_evidence
                    or row["evidence_sha256"] != (hashlib.sha256(expected_evidence.encode("utf-8")).hexdigest() if expected_evidence else "")
                ):
                    raise FixtureError(f"review sheet line {line} evidence context was changed")
                try:
                    if not row["relevance"].strip() and not row["rationale"].strip():
                        continue
                    grade = int(row["relevance"])
                except (TypeError, ValueError) as exc:
                    raise FixtureError(f"review sheet line {line} needs a relevance grade") from exc
                rationale = row["rationale"].strip()
                if kind == "answerability" and grade not in (0, 3):
                    raise FixtureError(f"review sheet line {line} answerability grade must be 0 or 3")
                if grade > 0 and not rationale:
                    raise FixtureError(f"review sheet line {line} needs rationale for a positive grade")
                records.append({
                    "question_id": question_id, "target_kind": kind, "target_id": target_id,
                    "reviewer_id": row["reviewer_id"].strip(), "relevance": grade,
                    "rationale": rationale, "status": "submitted",
                })
    # Reuse the dataset validator for duplicate identities and bounds.
    validate_dataset({**checked, "review_records": records}, require_coverage=False)
    return records


@contextmanager
def _bounded_csv_field_limit():
    # csv.field_size_limit is process-global; serialize changes and always restore it.
    with _CSV_FIELD_LIMIT_LOCK:
        previous = csv.field_size_limit()
        try:
            csv.field_size_limit(MAX_REVIEW_FIELD_CHARS)
            yield
        finally:
            csv.field_size_limit(previous)


def adjudicate_reviews(records: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Summarize independent votes; only two matching reviewers become accepted."""
    grouped: dict[tuple[str, str, str], list[Mapping[str, Any]]] = defaultdict(list)
    unique_votes = set()
    for row in records:
        question_id = _string(row.get("question_id"), "question_id")
        kind = row.get("target_kind")
        target_id = _string(row.get("target_id"), "target_id")
        reviewer = _string(row.get("reviewer_id"), "reviewer_id")
        grade = row.get("relevance")
        if kind not in ("answerability", "document", "chunk"):
            raise FixtureError("review record has invalid target_kind")
        if type(grade) is not int or grade not in ((0, 3) if kind == "answerability" else (0, 1, 2, 3)):
            raise FixtureError("review record has invalid relevance grade")
        key = (question_id, kind, target_id)
        vote_key = (*key, reviewer)
        if vote_key in unique_votes:
            raise FixtureError("reviewer has duplicate votes for one target")
        unique_votes.add(vote_key)
        grouped[key].append(row)
    results = []
    for key in sorted(grouped):
        votes = grouped[key]
        reviewers = {row["reviewer_id"] for row in votes}
        grades = {row["relevance"] for row in votes}
        accepted = len(reviewers) >= 2 and len(grades) == 1
        results.append({
            "question_id": key[0], "target_kind": key[1], "target_id": key[2],
            "reviewer_ids": sorted(reviewers),
            "status": "accepted_by_agreement" if accepted else "needs_adjudication" if len(reviewers) >= 2 else "pending_second_review",
            "relevance": next(iter(grades)) if accepted else None,
        })
    return results


def resolve_adjudications(
    adjudications: Iterable[Mapping[str, Any]],
    resolutions: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Apply explicit adjudicator decisions to disagreements with rationale."""
    output = [dict(row) for row in adjudications]
    by_key = {(row["question_id"], row["target_kind"], row["target_id"]): i for i, row in enumerate(output)}
    seen = set()
    for resolution in resolutions:
        key = (resolution.get("question_id"), resolution.get("target_kind"), resolution.get("target_id"))
        if key in seen:
            raise FixtureError("duplicate adjudicator resolution")
        seen.add(key)
        if key not in by_key or output[by_key[key]]["status"] != "needs_adjudication":
            raise FixtureError("resolution must target a disagreement needing adjudication")
        grade = resolution.get("relevance")
        kind = key[1]
        if type(grade) is not int or grade not in ((0, 3) if kind == "answerability" else (0, 1, 2, 3)):
            raise FixtureError("adjudicator relevance grade is invalid")
        adjudicator_id = _string(resolution.get("adjudicator_id"), "adjudicator_id")
        _string(resolution.get("rationale"), "rationale")
        result = output[by_key[key]]
        if adjudicator_id in result["reviewer_ids"]:
            raise FixtureError("adjudicator must be independent of the reviewers")
        result.update({
            "status": "accepted_by_adjudicator",
            "relevance": grade,
            "adjudicator_id": adjudicator_id,
            "adjudication_rationale": resolution["rationale"],
        })
    return output


def validate_adjudication_summary(
    dataset: Mapping[str, Any],
    summary: Mapping[str, Any],
) -> list[Mapping[str, Any]]:
    """Bind an adjudication envelope to this exact dataset release."""
    checked = validate_dataset(dict(dataset), require_coverage=False)
    for key in ("dataset_id", "dataset_version", "split"):
        if summary.get(key) != checked[key]:
            raise FixtureError(f"adjudication summary {key} does not match dataset")
    if summary.get("dataset_release_sha256") != dataset_release_sha256(checked):
        raise FixtureError("adjudication summary dataset_release_sha256 does not match dataset content")
    decisions = summary.get("decisions")
    if not isinstance(decisions, list):
        raise FixtureError("adjudication summary must include a decisions list")
    return decisions


def to_evaluation_fixture(
    dataset: Mapping[str, Any],
    adjudication_summary: Mapping[str, Any],
) -> dict[str, Any]:
    """Build an evaluation fixture only from accepted human judgments.

    Every query needs agreed answerability and every candidate chunk needs an
    agreed relevance grade. Document-level annotations remain available for a
    separate document retrieval evaluation.
    """
    checked = validate_dataset(dict(dataset), require_coverage=False)
    adjudication_rows = list(validate_adjudication_summary(dataset, adjudication_summary))
    accepted = {}
    for row in adjudication_rows:
        if row.get("status") in ("accepted_by_agreement", "accepted_by_adjudicator"):
            key = (row["question_id"], row["target_kind"], row["target_id"])
            if key in accepted:
                raise FixtureError("duplicate accepted adjudication")
            accepted[key] = row["relevance"]
    docs = checked["_indexes"]["documents"]
    chunks = checked["_indexes"]["chunks"]
    queries = checked["_indexes"]["queries"]
    converted_queries = []
    for question_id, query in queries.items():
        answer_grade = accepted.get((question_id, "answerability", question_id))
        if answer_grade not in (0, 3):
            raise FixtureError(f"query {question_id} has no accepted answerability judgment")
        relevance = {}
        for chunk_id, chunk in chunks.items():
            grade = accepted.get((question_id, "chunk", chunk_id))
            if grade is None:
                raise FixtureError(f"query {question_id} has an unadjudicated chunk {chunk_id}")
            relevance[chunk_id] = grade
        answerable = answer_grade == 3
        if not answerable and any(relevance.values()):
            raise FixtureError(f"unanswerable query {question_id} has accepted relevant chunks")
        converted_queries.append({
            "question_id": question_id,
            "text": query["text"],
            "query_language": query["query_language"],
            "evidence_language": query.get("evidence_language") if answerable else None,
            "split": checked["split"],
            "answerable": answerable,
            "judged_chunk_ids": sorted(chunks),
            "relevance": relevance,
        })
    records = list(checked.get("review_records", []))
    review_bytes = json.dumps(records, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {
        "schema_version": 1,
        "dataset_id": checked["dataset_id"],
        "dataset_version": checked["dataset_version"],
        "split": checked["split"],
        "synthetic": checked["synthetic"],
        "provenance": checked["provenance"],
        "documents": [
            {"document_id": row["document_id"], "version_id": row["version_id"],
             "language": row["language"], "split": checked["split"],
             "source": row["source_ref"], "text": row["text"]}
            for row in docs.values()
        ],
        "chunks": [
            {"chunk_id": row["chunk_id"], "document_id": row["document_id"],
             "version_id": row["version_id"], "language": docs[row["document_id"]]["language"],
             "split": checked["split"], "source": docs[row["document_id"]]["source_ref"],
             "start_char": row["start_char"], "end_char": row["end_char"], "text": row["text"]}
            for row in chunks.values()
        ],
        "queries": converted_queries,
        "human_review": {
            "review_records": records,
            "adjudications": adjudication_rows,
            "records_sha256": hashlib.sha256(review_bytes).hexdigest(),
            "dataset_release_sha256": dataset_release_sha256(checked),
            "fixture_content_sha256": _evaluation_content_sha256({
                "dataset_id": checked["dataset_id"],
                "dataset_version": checked["dataset_version"],
                "split": checked["split"],
                "synthetic": checked["synthetic"],
                "provenance": checked["provenance"],
                "documents": [
                    {"document_id": row["document_id"], "version_id": row["version_id"], "language": row["language"],
                     "split": checked["split"], "source": row["source_ref"], "text": row["text"]}
                    for row in docs.values()
                ],
                "chunks": [
                    {"chunk_id": row["chunk_id"], "document_id": row["document_id"], "version_id": row["version_id"],
                     "language": docs[row["document_id"]]["language"], "split": checked["split"],
                     "source": docs[row["document_id"]]["source_ref"], "start_char": row["start_char"],
                     "end_char": row["end_char"], "text": row["text"]}
                    for row in chunks.values()
                ],
                "queries": [
                    {"question_id": row["question_id"], "text": row["text"], "query_language": row["query_language"],
                     "evidence_language": row.get("evidence_language"), "split": checked["split"]}
                    for row in converted_queries
                ],
            }),
        },
    }


def _evaluation_content_sha256(fixture: Mapping[str, Any]) -> str:
    payload = {
        key: fixture.get(key) for key in ("dataset_id", "dataset_version", "split", "synthetic", "provenance")
    }
    payload["documents"] = sorted(fixture.get("documents", []), key=lambda row: row.get("document_id", ""))
    payload["chunks"] = sorted(fixture.get("chunks", []), key=lambda row: row.get("chunk_id", ""))
    payload["queries"] = sorted(({
        "question_id": row.get("question_id"), "text": row.get("text"),
        "query_language": row.get("query_language"), "evidence_language": row.get("evidence_language"),
        "split": row.get("split"),
    } for row in fixture.get("queries", [])), key=lambda row: row.get("question_id", ""))
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def write_json_no_clobber(value: Any, path: str | Path) -> Path:
    """Create JSON output exclusively; do not follow an existing symlink or overwrite."""
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
    encoded = payload.encode("utf-8")
    if len(encoded) > 250_000_000:
        raise ValueError("JSON output exceeds 250 MB safety limit")
    destination = _safe_output_path(path)
    _create_exclusive_file(destination, encoded)
    return destination


def _read_bounded_bytes(path: str | Path, limit: int, label: str) -> bytes:
    with Path(path).open("rb") as stream:
        payload = stream.read(limit + 1)
    if len(payload) > limit:
        raise FixtureError(f"{label} exceeds {limit} byte safety limit")
    return payload


def _safe_output_path(path: str | Path) -> Path:
    requested = Path(path)
    if ".." in requested.parts:
        raise ValueError("output path must not contain '..'")
    destination = requested.absolute()
    if not destination.name or destination.is_symlink():
        raise ValueError("output must name a non-symlink file")
    current = Path(destination.parent.anchor)
    for component in destination.parent.parts[1:]:
        current /= component
        if current.is_symlink():
            raise ValueError("output path contains a symlinked parent")
    if not destination.parent.is_dir():
        raise ValueError("output parent directory must already exist")
    return destination


def _create_exclusive_file(destination: Path, payload: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    if os.name == "posix" and os.open in os.supports_dir_fd:
        parent_fd = os.open(destination.parent.anchor, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            for component in destination.parent.parts[1:]:
                child_fd = os.open(
                    component,
                    os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=parent_fd,
                )
                os.close(parent_fd)
                parent_fd = child_fd
            fd = os.open(destination.name, flags, 0o600, dir_fd=parent_fd)
        finally:
            os.close(parent_fd)
    else:
        fd = os.open(destination, flags, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        try:
            destination.unlink()
        except OSError:
            pass
        raise


def build_corpus_manifest(
    root: str | Path,
    metadata: Mapping[str, Mapping[str, str]],
    *,
    dataset_id: str,
    dataset_version: str,
    split: str,
    source_name: str,
    source_version: str,
    license_name: str,
    retrieved_at: str,
    synthetic: bool = False,
    limits: IngestionLimits = IngestionLimits(),
) -> dict[str, Any]:
    """Ingest explicit-language UTF-8 documents into an unjudged manifest draft."""
    documents, chunks = ingest_corpus(root, limits=limits)
    by_source = {doc.source: doc for doc in documents}
    if set(metadata) != set(by_source):
        missing = sorted(set(by_source) - set(metadata))
        extra = sorted(set(metadata) - set(by_source))
        raise FixtureError(f"metadata path set mismatch (missing={missing[:1]}, extra={extra[:1]})")
    doc_rows = []
    if split not in ("dev", "holdout"):
        raise FixtureError("split must be dev or holdout")
    for doc in documents:
        details = metadata[doc.source]
        if details.get("language") not in ("ar", "en"):
            raise FixtureError(f"metadata for {doc.source} must specify language ar or en")
        doc_rows.append({
            "document_id": doc.document_id,
            "version_id": doc.version_id,
            "split": split,
            "language": details["language"],
            "source_ref": _string(details.get("source_ref"), f"metadata[{doc.source}].source_ref"),
            "text": doc.text,
            "content_sha256": hashlib.sha256(doc.text.encode("utf-8")).hexdigest(),
        })
    chunk_rows = []
    for chunk in chunks:
        row = {
            "chunk_id": chunk.chunk_id,
            "document_id": chunk.document_id,
            "version_id": chunk.version_id,
            "split": split,
            "start_char": chunk.start_char,
            "end_char": chunk.end_char,
            "text": chunk.text,
            "content_sha256": hashlib.sha256(chunk.text.encode("utf-8")).hexdigest(),
        }
        chunk_rows.append(row)
    fingerprint_payload = "\n".join(f"{d['source_ref']}\t{d['content_sha256']}" for d in doc_rows)
    return {
        "schema_version": DATASET_SCHEMA_VERSION,
        "dataset_id": _string(dataset_id, "dataset_id"),
        "dataset_version": _string(dataset_version, "dataset_version"),
        "split": split,
        "synthetic": synthetic,
        "provenance": {
            "source_name": _string(source_name, "source_name"),
            "source_version": _string(source_version, "source_version"),
            "license": _string(license_name, "license"),
            "retrieved_at": _string(retrieved_at, "retrieved_at"),
            "source_sha256": hashlib.sha256(fingerprint_payload.encode("utf-8")).hexdigest(),
        },
        "documents": doc_rows,
        "chunks": chunk_rows,
        "queries": [],
        "review_records": [],
        "annotation_policy": {
            "grade_scale": {"0": "not relevant", "1": "marginal", "2": "relevant", "3": "highly relevant"},
            "required_independent_reviewers": 2,
            "acceptance": "two independent matching grades; disagreements require adjudication",
        },
    }


def export_review_csv(dataset: Mapping[str, Any], path: str | Path, *, reviewer_id: str) -> Path:
    """Convenience alias with a name matching the dataset CLI terminology."""
    return export_review_sheet(dataset, path, reviewer_id=reviewer_id)
