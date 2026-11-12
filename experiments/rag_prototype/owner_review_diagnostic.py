"""Guarded diagnostic for submitted owner-reviewed development manifests.

This path intentionally bypasses the formal acceptance validator: one owner's
submitted decisions are provisional evidence, never independently adjudicated
benchmark ground truth. It emits identifiers and metrics, not query/document text.
"""
from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

from experiments.rag_prototype import Chunk, retrieval_metrics
from experiments.rag_prototype.benchmark_dataset import (
    _read_bounded_bytes,
    dataset_release_sha256,
    validate_dataset,
)
from experiments.rag_prototype.evaluation import FixtureError, RetrieverSpec

SUPPORTED_REVIEWERS = frozenset({"reviewer-a"})
PROVISIONAL_LABEL = "submitted_provisional_not_independently_adjudicated"
MAX_PROVISIONAL_MANIFEST_BYTES = 250_000_000


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise FixtureError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def load_owner_dev_manifest(path: str | Path, *, reviewer_id: str) -> dict[str, Any]:
    """Load one bounded schema-v2 dev manifest and enforce complete submitted votes."""
    if reviewer_id not in SUPPORTED_REVIEWERS:
        raise FixtureError("unsupported reviewer identity")
    payload = _read_bounded_bytes(Path(path), MAX_PROVISIONAL_MANIFEST_BYTES, "provisional dataset JSON")
    try:
        dataset = json.loads(payload.decode("utf-8-sig"), object_pairs_hook=_unique_pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FixtureError("manifest is not valid UTF-8 JSON") from exc
    return validate_owner_dev_manifest(dataset, reviewer_id=reviewer_id)


def validate_owner_dev_manifest(dataset: Any, *, reviewer_id: str) -> dict[str, Any]:
    if reviewer_id not in SUPPORTED_REVIEWERS:
        raise FixtureError("unsupported reviewer identity")
    if not isinstance(dataset, dict):
        raise FixtureError("manifest must be an object")
    if any("holdout" in str(key).casefold() for key in dataset):
        raise FixtureError("provisional diagnostics reject manifests containing holdout fields")
    if dataset.get("split") != "dev":
        raise FixtureError("provisional diagnostics accept dev split only")
    checked = validate_dataset(dataset, require_coverage=True)
    if checked["synthetic"] is True:
        raise FixtureError("owner-review diagnostic requires a non-synthetic dev manifest")

    queries = checked["_indexes"]["queries"]
    chunks = checked["_indexes"]["chunks"]
    docs = checked["_indexes"]["documents"]
    records: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in checked.get("review_records", []):
        if row.get("reviewer_id") != reviewer_id:
            raise FixtureError("manifest contains an unsupported reviewer identity")
        if row.get("status") != "submitted":
            raise FixtureError("provisional review records must remain submitted")
        key = (row["question_id"], row["target_kind"], row["target_id"])
        records[key] = row
        if row["target_kind"] == "chunk":
            chunk = chunks[row["target_id"]]
            doc = docs[chunk["document_id"]]
            if chunk["version_id"] != doc["version_id"] or chunk["text"] != doc["text"][chunk["start_char"] : chunk["end_char"]]:
                raise FixtureError("reviewed chunk provenance is malformed")

    required = {
        (qid, "answerability", qid) for qid in queries
    } | {
        (qid, "chunk", chunk_id) for qid in queries for chunk_id in chunks
    }
    if not required <= set(records):
        missing = len(required - set(records))
        raise FixtureError(f"submitted reviews must cover every query and chunk (missing={missing})")
    document_review_keys = {key for key in records if key[1] == "document"}
    if document_review_keys:
        required_documents = {(qid, "document", doc_id) for qid in queries for doc_id in docs}
        if document_review_keys != required_documents:
            raise FixtureError("document-level reviews, when present, must cover every query and document")

    for qid, query in queries.items():
        answer_vote = records[(qid, "answerability", qid)]["relevance"]
        if (answer_vote == 3) != query["answerable"]:
            raise FixtureError(f"submitted answerability decision conflicts with query {qid}")
        positives = [
            chunk_id for chunk_id in chunks
            if records[(qid, "chunk", chunk_id)]["relevance"] > 0
        ]
        if query["answerable"] and not positives:
            raise FixtureError(f"answerable query {qid} has no positively reviewed chunk")
        if not query["answerable"] and positives:
            raise FixtureError(f"unanswerable query {qid} has positive chunk reviews")
        if positives:
            expected = query["evidence_language"]
            if any(docs[chunks[cid]["document_id"]]["language"] != expected for cid in positives):
                raise FixtureError(f"reviewed evidence language conflicts for query {qid}")
        if document_review_keys:
            positive_docs = [doc_id for doc_id in docs
                             if records[(qid, "document", doc_id)]["relevance"] > 0]
            if query["answerable"] and not positive_docs:
                raise FixtureError(f"answerable query {qid} has no positively reviewed document")
            if not query["answerable"] and positive_docs:
                raise FixtureError(f"unanswerable query {qid} has positive document reviews")
            if any(docs[doc_id]["language"] != query["evidence_language"] for doc_id in positive_docs):
                raise FixtureError(f"reviewed document evidence language conflicts for query {qid}")
    return checked


def run_owner_dev_diagnostic(
    dataset: Mapping[str, Any],
    retrievers: Mapping[str, RetrieverSpec],
    *,
    reviewer_id: str = "reviewer-a",
    k: int = 3,
) -> dict[str, Any]:
    checked = validate_owner_dev_manifest(dataset, reviewer_id=reviewer_id)
    if type(k) is not int or k <= 0:
        raise ValueError("k must be a positive integer")
    if not retrievers or any(not isinstance(spec, RetrieverSpec) for spec in retrievers.values()):
        raise ValueError("retrievers must contain RetrieverSpec values")
    idx = checked["_indexes"]
    chunks = idx["chunks"]
    docs = idx["documents"]
    queries = idx["queries"]
    labels = {
        (row["question_id"], row["target_id"]): row["relevance"]
        for row in checked["review_records"] if row["target_kind"] == "chunk"
    }
    document_labels = {
        (row["question_id"], row["target_id"]): row["relevance"]
        for row in checked["review_records"] if row["target_kind"] == "document"
    }
    strategies = {}
    for name, spec in retrievers.items():
        if not isinstance(name, str) or not name.strip():
            raise ValueError("strategy names must be non-empty strings")
        result_rows = {}
        directions: dict[str, list] = defaultdict(list)
        document_directions: dict[str, list] = defaultdict(list)
        false_positives = abstentions = no_answer_count = 0
        for qid, query in sorted(queries.items()):
            raw = list(spec.retrieve(query["text"], k))
            ids = [getattr(getattr(hit, "chunk", None), "chunk_id", None) for hit in raw]
            if any(not isinstance(cid, str) or cid not in chunks for cid in ids):
                raise FixtureError(f"strategy {name} returned unknown or malformed chunk provenance")
            if len(ids) != len(set(ids)):
                raise FixtureError(f"strategy {name} returned duplicate chunk IDs")
            for hit in raw:
                retrieved = hit.chunk
                manifest_chunk = chunks[retrieved.chunk_id]
                manifest_doc = docs[manifest_chunk["document_id"]]
                identity = (retrieved.source, retrieved.document_id, retrieved.version_id,
                            retrieved.start_char, retrieved.end_char, retrieved.text)
                expected = (manifest_doc["source_ref"], manifest_chunk["document_id"],
                            manifest_chunk["version_id"], manifest_chunk["start_char"],
                            manifest_chunk["end_char"], manifest_chunk["text"])
                if identity != expected:
                    raise FixtureError(f"strategy {name} returned mismatched chunk provenance")
                matched = getattr(hit, "matched_window", None)
                if matched is not None:
                    window = matched.window
                    if (
                        window.chunk_id != retrieved.chunk_id
                        or window.document_id != retrieved.document_id
                        or window.document_version_id != retrieved.version_id
                        or window.source != retrieved.source
                        or window.chunk_start_char != retrieved.start_char
                        or window.chunk_end_char != retrieved.end_char
                        or window.start_char < retrieved.start_char
                        or window.end_char > retrieved.end_char
                        or window.end_char - window.start_char != len(window.text)
                        or not math.isfinite(float(matched.cosine_similarity))
                    ):
                        raise FixtureError(f"strategy {name} returned malformed matched-window provenance")
            scores = {}
            for hit in raw:
                if not hasattr(hit, "score"):
                    continue
                score = float(hit.score)
                if not math.isfinite(score):
                    raise FixtureError(f"strategy {name} returned a non-finite score")
                scores[hit.chunk.chunk_id] = score
            if spec.minimum_score is not None:
                if len(scores) != len(ids):
                    raise FixtureError("minimum_score requires scored hits")
                ids = [cid for cid in ids if scores[cid] >= spec.minimum_score]
            relevant = {cid: labels[(qid, cid)] for cid in chunks}
            if query["answerable"]:
                directions[f"{query['query_language']}->{query['evidence_language']}"].append(
                    retrieval_metrics(ids, relevant, k=k)
                )
                if document_labels:
                    ranked_documents = list(dict.fromkeys(chunks[cid]["document_id"] for cid in ids))
                    relevant_documents = {
                        doc_id: document_labels[(qid, doc_id)] for doc_id in docs
                    }
                    document_directions[f"{query['query_language']}->{query['evidence_language']}"].append(
                        retrieval_metrics(ranked_documents, relevant_documents, k=k)
                    )
            else:
                no_answer_count += 1
                fp = bool(ids)
                false_positives += int(fp)
                abstentions += int(not fp)
            ranked = []
            hit_by_id = {hit.chunk.chunk_id: hit for hit in raw if hasattr(hit, "chunk")}
            for rank, cid in enumerate(ids, 1):
                chunk = chunks[cid]
                doc = docs[chunk["document_id"]]
                item = {
                    "rank": rank, "chunk_id": cid, "document_id": chunk["document_id"],
                    "document_version_id": chunk["version_id"], "source_ref": doc["source_ref"],
                    "start_char": chunk["start_char"], "end_char": chunk["end_char"],
                }
                hit = hit_by_id.get(cid)
                matched = getattr(hit, "matched_window", None)
                if matched is not None:
                    window = matched.window
                    item["matched_subwindow"] = {
                        "window_id": window.window_id, "start_char": window.start_char,
                        "end_char": window.end_char, "cosine_similarity": matched.cosine_similarity,
                    }
                ranked.append(item)
            result_rows[qid] = {
                "direction": f"{query['query_language']}->{query['evidence_language']}" if query["answerable"] else "no_answer",
                "answerable": query["answerable"], "ranked_chunks": ranked,
            }
        by_direction = {}
        for direction, metrics in sorted(directions.items()):
            by_direction[direction] = _aggregate_metrics(metrics)
        if set(by_direction) != {"ar->ar", "ar->en", "en->ar", "en->en"}:
            raise FixtureError("submitted answerable queries do not cover all four directions")
        strategies[name] = {
            "by_direction": by_direction,
            "no_answer": {
                "query_count": no_answer_count, "false_positive_queries": false_positives,
                "abstained_queries": abstentions,
                "false_positive_rate": false_positives / no_answer_count if no_answer_count else 0.0,
            },
            "query_results": result_rows,
            "metadata": dict(spec.metadata or {}),
        }
        if document_labels:
            strategies[name]["document_level_by_direction"] = {
                direction: _aggregate_metrics(metrics)
                for direction, metrics in sorted(document_directions.items())
            }
    return {
        "diagnostic_schema_version": 1,
        "evaluation_status": "PROVISIONAL ONLY — submitted owner-approved decisions; not independently adjudicated ground truth",
        "label_status": PROVISIONAL_LABEL,
        "reviewer_id": reviewer_id,
        "dataset": {
            "dataset_id": checked["dataset_id"], "dataset_version": checked["dataset_version"],
            "split": "dev", "dataset_release_sha256": dataset_release_sha256(checked),
            "document_count": len(docs), "chunk_count": len(chunks), "query_count": len(queries),
        },
        "k": k,
        "strategies": strategies,
    }


def _aggregate_metrics(rows: Sequence[Any]) -> dict[str, float | int]:
    count = len(rows)
    return {
        "query_count": count,
        "precision_at_k": math.fsum(row.precision for row in rows) / count,
        "recall_at_k": math.fsum(row.recall for row in rows) / count,
        "mrr_at_k": math.fsum(row.mrr for row in rows) / count,
        "ndcg_at_k": math.fsum(row.ndcg for row in rows) / count,
    }
