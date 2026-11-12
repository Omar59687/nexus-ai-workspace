"""Deterministic evaluation helpers for the isolated RAG prototype.

This module consumes a versioned JSON fixture, not arbitrary user documents. It
uses the prototype's existing BM25 implementation and metrics and deliberately
keeps synthetic retrieval scores separate from answerability/abstention counts.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import secrets
import stat
import time
import tempfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from experiments.rag_prototype import (
    BM25Index,
    Chunk,
    RetrievalMetrics,
    retrieval_metrics,
)


LANGUAGES = ("ar", "en")
DIRECTIONS = ("ar->ar", "en->en", "ar->en", "en->ar")
EVALUATION_VERSION = "nexus-rag-eval-v1"
MAX_FIXTURE_BYTES = 50_000_000


class FixtureError(ValueError):
    """Raised when the evaluation fixture is ambiguous or inconsistent."""


_CANONICAL_SCORE_POLICIES = {
    "score descending, chunk ID ascending",
    "BM25 score descending, chunk ID ascending",
    "cosine descending, chunk ID ascending",
    "RRF score descending, chunk ID ascending",
}


def _score_tie_policy_is_canonical(policy: str) -> bool:
    return policy in _CANONICAL_SCORE_POLICIES


@dataclass(frozen=True)
class RetrieverSpec:
    """A retriever plus honest ordering and abstention metadata.

    Legacy callables remain accepted, but their order contract is reported as
    caller-supplied and their tie behavior as unknown.
    """

    retrieve: Callable[[str, int], Sequence[Any]]
    tie_policy: str
    minimum_score: float | None = None
    metadata: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if not callable(self.retrieve):
            raise TypeError("retrieve must be callable")
        if not isinstance(self.tie_policy, str) or not self.tie_policy.strip():
            raise ValueError("tie_policy must be a non-empty string")
        if self.minimum_score is not None and not math.isfinite(self.minimum_score):
            raise ValueError("minimum_score must be finite")
        if self.metadata is not None and not isinstance(self.metadata, Mapping):
            raise ValueError("metadata must be a mapping")


def _string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FixtureError(f"{field} must be a non-empty string")
    return value


def _integer(value: Any, field: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        expected = "a non-negative integer" if minimum == 0 else f"an integer >= {minimum}"
        raise FixtureError(f"{field} must be {expected} (booleans are invalid)")
    return value


def _unique_index(rows: Any, id_field: str, collection: str) -> dict[str, dict[str, Any]]:
    if not isinstance(rows, list):
        raise FixtureError(f"{collection} must be a list")
    index: dict[str, dict[str, Any]] = {}
    for position, row in enumerate(rows):
        if not isinstance(row, dict):
            raise FixtureError(f"{collection}[{position}] must be an object")
        item_id = _string(row.get(id_field), f"{collection}[{position}].{id_field}")
        if item_id in index:
            raise FixtureError(f"duplicate {id_field}: {item_id}")
        index[item_id] = row
    return index


def validate_fixture(fixture: Any) -> dict[str, Any]:
    """Validate identities, language labels, complete judgments, and split safety."""
    if not isinstance(fixture, dict):
        raise FixtureError("fixture root must be an object")
    if type(fixture.get("schema_version")) is not int or fixture["schema_version"] != 1:
        raise FixtureError("schema_version must be 1")
    _string(fixture.get("dataset_id"), "dataset_id")
    if type(fixture.get("synthetic")) is not bool:
        raise FixtureError("fixture must explicitly declare synthetic as a boolean")

    documents = _unique_index(fixture.get("documents"), "document_id", "documents")
    chunks = _unique_index(fixture.get("chunks"), "chunk_id", "chunks")
    questions = _unique_index(fixture.get("queries"), "question_id", "queries")
    if not documents or not chunks or not questions:
        raise FixtureError("documents, chunks, and queries must all be non-empty")

    document_content_hashes: dict[str, str] = {}
    source_owner: dict[str, str] = {}
    document_chunks: dict[str, list[dict[str, Any]]] = defaultdict(list)
    chunks_by_split: dict[str, set[str]] = {"dev": set(), "holdout": set()}
    documents_by_split: dict[str, set[str]] = {"dev": set(), "holdout": set()}

    for document_id, document in documents.items():
        _string(document.get("version_id"), f"documents[{document_id}].version_id")
        language = document.get("language")
        if language not in LANGUAGES:
            raise FixtureError(f"documents[{document_id}].language must be ar or en")
        split = document.get("split")
        if split not in documents_by_split:
            raise FixtureError(f"documents[{document_id}].split must be dev or holdout")
        source = _string(document.get("source"), f"documents[{document_id}].source")
        if source in source_owner:
            raise FixtureError(f"duplicate document source: {source}")
        source_owner[source] = document_id
        content = document.get("text")
        if not isinstance(content, str) or not content:
            raise FixtureError(f"documents[{document_id}].text must be non-empty text")
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        document_content_hashes[document_id] = digest
        documents_by_split[split].add(document_id)

    for document_id, digest in document_content_hashes.items():
        split = documents[document_id]["split"]
        other_split = "holdout" if split == "dev" else "dev"
        if any(document_content_hashes[other_id] == digest for other_id in documents_by_split[other_split]):
            raise FixtureError("duplicate document content across splits")

    populated_splits = {name for name, ids in documents_by_split.items() if ids}
    if len(populated_splits) != 1:
        raise FixtureError("each evaluation fixture must contain exactly one split")
    fixture_split = next(iter(populated_splits))

    for chunk_id, chunk in chunks.items():
        document_id = chunk.get("document_id")
        if document_id not in documents:
            raise FixtureError(f"chunks[{chunk_id}] references unknown document")
        document = documents[document_id]
        if chunk.get("version_id") != document["version_id"]:
            raise FixtureError(f"chunks[{chunk_id}].version_id does not match its document")
        if chunk.get("language") != document["language"]:
            raise FixtureError(f"chunks[{chunk_id}].language does not match its document")
        if chunk.get("split") != document["split"]:
            raise FixtureError(f"chunks[{chunk_id}].split does not match its document")
        if chunk.get("source") != document["source"]:
            raise FixtureError(f"chunks[{chunk_id}].source does not match its document")
        text = chunk.get("text")
        if not isinstance(text, str) or not text:
            raise FixtureError(f"chunks[{chunk_id}].text must be non-empty text")
        start = _integer(chunk.get("start_char", 0), f"chunks[{chunk_id}].start_char")
        end = _integer(chunk.get("end_char", len(document["text"])), f"chunks[{chunk_id}].end_char")
        if end < start or end > len(document["text"]) or document["text"][start:end] != text:
            raise FixtureError(f"chunks[{chunk_id}] source span does not match document text")
        document_chunks[document_id].append(chunk)
        chunks_by_split[document["split"]].add(chunk_id)

    if any(not document_chunks.get(document_id) for document_id in documents):
        raise FixtureError("every document must have at least one chunk")

    answerable_directions: dict[str, set[str]] = {"dev": set(), "holdout": set()}
    for question_id, question in questions.items():
        _string(question.get("text"), f"queries[{question_id}].text")
        query_language = question.get("query_language")
        if query_language not in LANGUAGES:
            raise FixtureError(f"queries[{question_id}].query_language must be ar or en")
        split = question.get("split")
        if split not in chunks_by_split:
            raise FixtureError(f"queries[{question_id}].split must be dev or holdout")
        if type(question.get("answerable")) is not bool:
            raise FixtureError(f"queries[{question_id}].answerable must be boolean")

        judged = question.get("judged_chunk_ids")
        if not isinstance(judged, list) or any(not isinstance(item, str) for item in judged):
            raise FixtureError(f"queries[{question_id}].judged_chunk_ids must be a list of IDs")
        if len(judged) != len(set(judged)):
            raise FixtureError(f"queries[{question_id}].judged_chunk_ids contains duplicates")
        expected_judged = chunks_by_split[split]
        if set(judged) != expected_judged:
            raise FixtureError(
                f"queries[{question_id}].judged_chunk_ids must include every chunk in its split"
            )

        relevance = question.get("relevance")
        if not isinstance(relevance, dict) or set(relevance) != set(judged):
            raise FixtureError(f"queries[{question_id}].relevance must label every judged_chunk_id")
        for chunk_id, grade in relevance.items():
            _integer(grade, f"queries[{question_id}].relevance[{chunk_id}]")
        relevant = [chunk_id for chunk_id, grade in relevance.items() if grade > 0]
        evidence_language = question.get("evidence_language")
        if question["answerable"]:
            if not relevant:
                raise FixtureError(f"answerable question {question_id} needs relevant evidence")
            if evidence_language not in LANGUAGES:
                raise FixtureError(f"answerable question {question_id} needs evidence_language ar/en")
            if any(chunks[chunk_id]["language"] != evidence_language for chunk_id in relevant):
                raise FixtureError(f"question {question_id} evidence language conflicts with its labels")
            answerable_directions[split].add(f"{query_language}->{evidence_language}")
        else:
            if evidence_language is not None or relevant:
                raise FixtureError(f"unanswerable question {question_id} must have no evidence language or positive labels")

    missing_directions = set(DIRECTIONS) - answerable_directions[fixture_split]
    if missing_directions:
        raise FixtureError(
            f"{fixture_split} split lacks bilingual directions: {', '.join(sorted(missing_directions))}"
        )
    if fixture["synthetic"] is False:
        _validate_human_review_evidence(fixture, questions, chunks)
    return fixture


def _validate_human_review_evidence(
    fixture: Mapping[str, Any],
    questions: Mapping[str, Mapping[str, Any]],
    chunks: Mapping[str, Mapping[str, Any]],
) -> None:
    evidence = fixture.get("human_review")
    if not isinstance(evidence, dict):
        raise FixtureError("real evaluation fixture requires human_review evidence")
    records = evidence.get("review_records")
    adjudications = evidence.get("adjudications")
    if not isinstance(records, list) or not isinstance(adjudications, list):
        raise FixtureError("human_review must include review_records and adjudications")
    canonical = json.dumps(records, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if hashlib.sha256(canonical).hexdigest() != evidence.get("records_sha256"):
        raise FixtureError("human_review records_sha256 does not match records")
    if evidence.get("dataset_release_sha256") is None or not _valid_sha256(evidence["dataset_release_sha256"]):
        raise FixtureError("human_review dataset_release_sha256 is missing or invalid")
    if evidence.get("fixture_content_sha256") != _fixture_content_sha256(fixture):
        raise FixtureError("human_review fixture_content_sha256 does not match fixture content")
    votes: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        if not isinstance(record, dict) or record.get("status") != "submitted":
            raise FixtureError("human_review contains an invalid submitted record")
        key = (record.get("question_id"), record.get("target_kind"), record.get("target_id"))
        votes[key].append(record)
    accepted = {}
    for row in adjudications:
        if not isinstance(row, dict):
            raise FixtureError("human_review adjudication rows must be objects")
        key = (row.get("question_id"), row.get("target_kind"), row.get("target_id"))
        status = row.get("status")
        if status not in ("accepted_by_agreement", "accepted_by_adjudicator"):
            continue
        ballot = votes.get(key, [])
        reviewers = {v.get("reviewer_id") for v in ballot}
        grades = {v.get("relevance") for v in ballot}
        if len(reviewers) < 2:
            raise FixtureError("accepted judgment lacks two independent reviewer votes")
        if row.get("reviewer_ids") != sorted(reviewers):
            raise FixtureError("accepted judgment reviewer list does not match submitted votes")
        if status == "accepted_by_agreement":
            if len(grades) != 1 or row.get("relevance") not in grades:
                raise FixtureError("accepted agreement lacks matching independent reviewer votes")
        else:
            adjudicator = row.get("adjudicator_id")
            if len(grades) < 2 or not isinstance(adjudicator, str) or not adjudicator.strip() or adjudicator in reviewers:
                raise FixtureError("adjudicator decision lacks a disagreement or independent adjudicator")
            if not isinstance(row.get("adjudication_rationale"), str) or not row["adjudication_rationale"].strip():
                raise FixtureError("adjudicator decision requires a rationale")
        accepted[key] = row["relevance"]
    for question_id, question in questions.items():
        answer_grade = accepted.get((question_id, "answerability", question_id))
        if answer_grade not in (0, 3) or question["answerable"] != (answer_grade == 3):
            raise FixtureError(f"query {question_id} lacks matching accepted answerability judgment")
        for chunk_id in chunks:
            grade = accepted.get((question_id, "chunk", chunk_id))
            if grade is None or question["relevance"].get(chunk_id) != grade:
                raise FixtureError(f"query {question_id} lacks matching accepted chunk judgment {chunk_id}")


def _valid_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value.lower())


def _fixture_content_sha256(fixture: Mapping[str, Any]) -> str:
    """Hash provenance and retrieval inputs while excluding judgments and labels."""
    payload = {key: fixture.get(key) for key in ("dataset_id", "dataset_version", "split", "synthetic", "provenance")}
    payload["documents"] = sorted(fixture.get("documents", []), key=lambda row: row.get("document_id", ""))
    payload["chunks"] = sorted(fixture.get("chunks", []), key=lambda row: row.get("chunk_id", ""))
    payload["queries"] = sorted(({
        "question_id": row.get("question_id"), "text": row.get("text"),
        "query_language": row.get("query_language"), "evidence_language": row.get("evidence_language"),
        "split": row.get("split"),
    } for row in fixture.get("queries", [])), key=lambda row: row.get("question_id", ""))
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
def load_fixture(path: str | Path) -> dict[str, Any]:
    """Load UTF-8 JSON and fail closed on malformed or incomplete fixture data."""
    fixture_path = Path(path)
    try:
        with fixture_path.open("rb") as stream:
            raw = stream.read(MAX_FIXTURE_BYTES + 1)
        if len(raw) > MAX_FIXTURE_BYTES:
            raise FixtureError("fixture exceeds MAX_FIXTURE_BYTES")
        fixture = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_json_pairs)
    except FixtureError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FixtureError(f"cannot read fixture: {exc}") from exc
    validate_fixture(fixture)
    fixture["_source_sha256"] = hashlib.sha256(raw).hexdigest()
    return fixture


def _unique_json_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    output = {}
    for key, value in pairs:
        if key in output:
            raise FixtureError(f"duplicate JSON object key: {key}")
        output[key] = value
    return output


def _chunks(fixture: Mapping[str, Any], split: str) -> tuple[Chunk, ...]:
    docs = {doc["document_id"]: doc for doc in fixture["documents"]}
    output = []
    for item in fixture["chunks"]:
        if item["split"] != split:
            continue
        document = docs[item["document_id"]]
        start = item.get("start_char", 0)
        end = item.get("end_char", len(document["text"]))
        start_line = document["text"][:start].count("\n") + 1
        end_line = document["text"][:max(start, end - 1)].count("\n") + 1
        output.append(
            Chunk(
                source=item["source"],
                document_id=item["document_id"],
                version_id=item["version_id"],
                chunk_id=item["chunk_id"],
                start_char=start,
                end_char=end,
                start_line=start_line,
                end_line=end_line,
                heading_path=(),
                text=item["text"],
            )
        )
    return tuple(output)


Retriever = Callable[[str, int], Sequence[Any]]


def _default_retrievers(chunks: Sequence[Chunk], *, measure_timing: bool = False) -> dict[str, RetrieverSpec]:
    raw_started = time.perf_counter() if measure_timing else 0.0
    raw_index = BM25Index(chunks)
    raw_index_seconds = time.perf_counter() - raw_started if measure_timing else None
    normalized_started = time.perf_counter() if measure_timing else 0.0
    normalized_index = BM25Index(chunks, normalize_arabic=True)
    normalized_index_seconds = time.perf_counter() - normalized_started if measure_timing else None
    return {
        "bm25_arabic_normalized": RetrieverSpec(
            lambda query, k: normalized_index.search(query, top_k=k),
            "score descending, chunk ID ascending",
            metadata={"strategy": "arabic-normalized BM25", **({"index_build_seconds": normalized_index_seconds} if measure_timing else {})},
        ),
        "bm25_raw": RetrieverSpec(
            lambda query, k: raw_index.search(query, top_k=k),
            "score descending, chunk ID ascending",
            metadata={"strategy": "raw BM25", **({"index_build_seconds": raw_index_seconds} if measure_timing else {})},
        ),
    }


def _mean_metrics(rows: Sequence[RetrievalMetrics]) -> dict[str, float | int]:
    count = len(rows)
    if not count:
        return {
            "query_count": 0,
            "precision_at_k": 0.0,
            "recall_at_k": 0.0,
            "mrr_at_k": 0.0,
            "ndcg_at_k": 0.0,
        }
    return {
        "query_count": count,
        "precision_at_k": math.fsum(row.precision for row in rows) / count,
        "recall_at_k": math.fsum(row.recall for row in rows) / count,
        "mrr_at_k": math.fsum(row.mrr for row in rows) / count,
        "ndcg_at_k": math.fsum(row.ndcg for row in rows) / count,
    }


def _metric_groups(
    rows: Sequence[tuple[dict[str, Any], RetrievalMetrics]],
) -> dict[str, Any]:
    overall = [metrics for _, metrics in rows]
    by_query_language = {}
    by_evidence_language = {}
    by_direction = {}
    for language in LANGUAGES:
        by_query_language[language] = _mean_metrics(
            [metrics for question, metrics in rows if question["query_language"] == language]
        )
        by_evidence_language[language] = _mean_metrics(
            [metrics for question, metrics in rows if question["evidence_language"] == language]
        )
    for direction in DIRECTIONS:
        by_direction[direction] = _mean_metrics(
            [
                metrics
                for question, metrics in rows
                if f"{question['query_language']}->{question['evidence_language']}" == direction
            ]
        )
    return {
        "overall": _mean_metrics(overall),
        "by_query_language": by_query_language,
        "by_evidence_language": by_evidence_language,
        "by_direction": by_direction,
    }


def run_evaluation(
    fixture: Mapping[str, Any],
    *,
    split: str = "dev",
    k: int = 3,
    allow_holdout: bool = False,
    retrievers: Mapping[str, Retriever | RetrieverSpec] | None = None,
    measure_latency: bool = False,
) -> dict[str, Any]:
    """Run deterministic retrieval evaluation on one document-disjoint split."""
    validate_fixture({key: value for key, value in fixture.items() if not key.startswith("_")})
    if split not in ("dev", "holdout"):
        raise ValueError("split must be dev or holdout")
    if split == "holdout" and not allow_holdout:
        raise ValueError("holdout evaluation requires allow_holdout=True")
    fixture_splits = {item["split"] for item in fixture["documents"]}
    if fixture_splits != {split}:
        raise FixtureError(f"requested {split} evaluation requires a {split}-only fixture")
    if type(k) is not int or k <= 0:
        raise ValueError("k must be a positive integer")

    corpus = _chunks(fixture, split)
    if not corpus:
        raise FixtureError(f"split {split} has no chunks")
    available = {chunk.chunk_id: chunk for chunk in corpus}
    active_questions = [q for q in fixture["queries"] if q["split"] == split]
    if not active_questions:
        raise FixtureError(f"split {split} has no questions")
    strategy_map = dict(retrievers or _default_retrievers(corpus, measure_timing=measure_latency))
    if not strategy_map or any(
        not isinstance(name, str) or not name
        or not (callable(retrieve) or isinstance(retrieve, RetrieverSpec))
        for name, retrieve in strategy_map.items()
    ):
        raise ValueError("retrievers must have non-empty string names")

    strategies: dict[str, Any] = {}
    performance: dict[str, Any] = {}
    for strategy_name in sorted(strategy_map):
        configured = strategy_map[strategy_name]
        if isinstance(configured, RetrieverSpec):
            spec = configured
        else:
            spec = RetrieverSpec(configured, "caller-supplied order; tie behavior unspecified")
        retrieve = spec.retrieve
        metric_rows: list[tuple[dict[str, Any], RetrievalMetrics]] = []
        query_results: dict[str, Any] = {}
        no_answer_results: dict[str, Any] = {}
        empty_answerable: list[str] = []
        missed_answerable: list[str] = []
        unjudged_count = 0
        retrieved_relevant_count = 0
        query_durations_ms: dict[str, float] = {}

        for question in active_questions:
            query_started = time.perf_counter_ns() if measure_latency else 0
            raw_hits = list(retrieve(question["text"], k))
            if measure_latency:
                query_durations_ms[question["question_id"]] = (time.perf_counter_ns() - query_started) / 1_000_000
            # Enforce declared score ordering instead of reporting a tie policy
            # that a custom retriever did not actually follow.
            if _score_tie_policy_is_canonical(spec.tie_policy) and all(
                hasattr(hit, "chunk") and hasattr(hit, "score") for hit in raw_hits
            ):
                raw_hits.sort(key=lambda hit: (-float(hit.score), hit.chunk.chunk_id))
            ranked_ids = [hit.chunk.chunk_id if hasattr(hit, "chunk") else hit for hit in raw_hits]
            if any(not isinstance(item_id, str) for item_id in ranked_ids):
                raise ValueError(f"strategy {strategy_name} returned a non-string chunk ID")
            if len(ranked_ids) != len(set(ranked_ids)):
                raise ValueError(f"strategy {strategy_name} returned duplicate chunk IDs")
            unknown = [item_id for item_id in ranked_ids if item_id not in available]
            if unknown:
                raise ValueError(f"strategy {strategy_name} returned unknown chunk ID: {unknown[0]}")
            hit_scores = {
                hit.chunk.chunk_id: float(hit.score)
                for hit in raw_hits
                if hasattr(hit, "chunk") and hasattr(hit, "score")
            }
            if any(not math.isfinite(score) for score in hit_scores.values()):
                raise ValueError(f"strategy {strategy_name} returned a non-finite score")
            if spec.minimum_score is not None:
                if len(hit_scores) != len(ranked_ids):
                    raise ValueError("minimum_score requires scored retrieval hits")
                ranked_ids = [item_id for item_id in ranked_ids if hit_scores[item_id] >= spec.minimum_score]
            unjudged = [item_id for item_id in ranked_ids if item_id not in set(question["judged_chunk_ids"])]
            unjudged_count += len(unjudged)
            doc_by_id = {row["document_id"]: row for row in fixture["documents"]}
            chunk_by_id = {row["chunk_id"]: row for row in fixture["chunks"]}
            provenance = []
            for rank, item_id in enumerate(ranked_ids, start=1):
                chunk = available[item_id]
                document = doc_by_id[chunk.document_id]
                fixture_chunk = chunk_by_id[item_id]
                hit = next(
                    (
                        candidate
                        for candidate in raw_hits
                        if getattr(getattr(candidate, "chunk", None), "chunk_id", None) == item_id
                    ),
                    None,
                )
                row = {
                    "rank": rank,
                    "chunk_id": item_id,
                    "document_id": chunk.document_id,
                    "document_version_id": chunk.version_id,
                    "source": chunk.source,
                    "source_ref": document.get("source_ref", document.get("source", chunk.source)),
                    "document_sha256": hashlib.sha256(document["text"].encode("utf-8")).hexdigest(),
                    "chunk_sha256": hashlib.sha256(chunk.text.encode("utf-8")).hexdigest(),
                    "evidence_language": fixture_chunk["language"],
                    "start_char": chunk.start_char,
                    "end_char": chunk.end_char,
                    **({"score": hit_scores[item_id]} if item_id in hit_scores else {}),
                }
                window_chunks = getattr(hit, "window_chunks", None)
                if window_chunks is not None:
                    row["window_chunk_ids"] = [window.chunk_id for window in window_chunks]
                    row["window_provenance"] = [
                        {
                            "chunk_id": window.chunk_id,
                            "document_id": window.document_id,
                            "document_version_id": window.version_id,
                            "source_ref": doc_by_id[window.document_id].get(
                                "source_ref", doc_by_id[window.document_id].get("source", window.source)
                            ),
                            "document_sha256": hashlib.sha256(
                                doc_by_id[window.document_id]["text"].encode("utf-8")
                            ).hexdigest(),
                            "chunk_sha256": hashlib.sha256(window.text.encode("utf-8")).hexdigest(),
                            "start_char": window.start_char,
                            "end_char": window.end_char,
                        }
                        for window in window_chunks
                    ]
                provenance.append(row)
            if question["answerable"]:
                metric = retrieval_metrics(ranked_ids, question["relevance"], k=k)
                metric_rows.append((question, metric))
                is_hit = any(question["relevance"].get(item_id, 0) > 0 for item_id in ranked_ids[:k])
                retrieved_relevant_count += int(is_hit)
                if not ranked_ids:
                    empty_answerable.append(question["question_id"])
                if not is_hit:
                    missed_answerable.append(question["question_id"])
                query_results[question["question_id"]] = {
                    "query_language": question["query_language"],
                    "evidence_language": question["evidence_language"],
                    "direction": f"{question['query_language']}->{question['evidence_language']}",
                    "ranked_chunks": provenance,
                    "metrics": {
                        "precision_at_k": metric.precision,
                        "recall_at_k": metric.recall,
                        "mrr_at_k": metric.mrr,
                        "ndcg_at_k": metric.ndcg,
                    },
                }
            else:
                no_answer_results[question["question_id"]] = {
                    "query_language": question["query_language"],
                    "ranked_chunks": provenance,
                    "false_positive": bool(ranked_ids),
                    "abstained": not ranked_ids,
                }

        no_answer_values = list(no_answer_results.values())
        false_positives = sum(row["false_positive"] for row in no_answer_values)
        strategies[strategy_name] = {
            "metrics": _metric_groups(metric_rows),
            "query_results": query_results,
            "answerable_coverage": {
                "query_count": len(metric_rows),
                "retrieved_relevant_at_k": retrieved_relevant_count,
                "retrieval_hit_rate_at_k": retrieved_relevant_count / len(metric_rows) if metric_rows else 0.0,
                "empty_retrievals": len(empty_answerable),
            },
            "no_answer": {
                "query_count": len(no_answer_values),
                "false_positive_queries": false_positives,
                "abstained_queries": sum(row["abstained"] for row in no_answer_values),
                "false_positive_rate": false_positives / len(no_answer_values) if no_answer_values else 0.0,
                "results": no_answer_results,
            },
            "diagnostics": {
                "empty_answerable_retrieval_question_ids": empty_answerable,
                "missed_relevant_question_ids": missed_answerable,
                "unjudged_retrieved_chunk_count": unjudged_count,
                "ordering_policy": spec.tie_policy,
                "minimum_score": spec.minimum_score,
                "metadata": dict(spec.metadata or {}),
            },
        }
        if measure_latency:
            durations = list(query_durations_ms.values())
            performance[strategy_name] = {
                "index_build_seconds": (spec.metadata or {}).get("index_build_seconds"),
                "passage_embedding_seconds": (spec.metadata or {}).get("passage_embedding_seconds"),
                "model_load_seconds": (spec.metadata or {}).get("model_load_seconds"),
                "query_latency_ms_by_question": query_durations_ms,
                "total_query_latency_ms": math.fsum(durations),
                "mean_query_latency_ms": math.fsum(durations) / len(durations) if durations else 0.0,
                "max_query_latency_ms": max(durations, default=0.0),
            }

    source_hash = fixture.get("_source_sha256")
    if not isinstance(source_hash, str):
        canonical = json.dumps(fixture, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        source_hash = hashlib.sha256(canonical).hexdigest()
    report = {
        "report_schema_version": 1,
        "evaluation_version": EVALUATION_VERSION,
        "dataset": {
            "dataset_id": fixture["dataset_id"],
            "synthetic": fixture["synthetic"],
            "dataset_version": fixture.get("dataset_version"),
            "split": split,
            "fixture_sha256": source_hash,
        },
        "configuration": {
            "k": k,
            "metrics_include_answerable_queries_only": True,
            "missing_judgments": "rejected; each question must judge every chunk in its split",
            "tie_break": "per strategy; unknown unless declared by RetrieverSpec",
        },
        "environment": {"python": platform.python_version()},
        "query_count": len(active_questions),
        "answerable_query_count": sum(q["answerable"] for q in active_questions),
        "no_answer_query_count": sum(not q["answerable"] for q in active_questions),
        "strategies": strategies,
    }
    if measure_latency:
        report["performance"] = {
            "measured": True,
            "clock": "time.perf_counter_ns",
            "system": {
                "platform": platform.platform(),
                "machine": platform.machine(),
                "processor": platform.processor(),
                "logical_cpu_count": os.cpu_count(),
            },
            "by_strategy": performance,
        }
    return report


def serialize_report(report: Mapping[str, Any]) -> str:
    """Serialize a report canonically for stable diffs and repeated-run checks."""
    return json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"


def _validated_output_path(path: str | Path, output_root: str | Path | None) -> tuple[Path, str]:
    requested = Path(path)
    if output_root is not None:
        root = Path(output_root).resolve(strict=True)
        if requested.is_absolute() or ".." in requested.parts:
            raise ValueError("report path must be relative to output_root and contain no '..'")
        destination = root / requested
        if not destination.resolve(strict=False).is_relative_to(root):
            raise ValueError("report path resolves outside output_root")
    else:
        destination = requested.absolute()
    if not destination.name or destination.name in {".", ".."}:
        raise ValueError("report path must name a file")
    parent = destination.parent
    # Reject symlinks, junctions, and other reparse points at every existing
    # parent component and at the destination before any file is opened.
    current = Path(parent.anchor)
    for component in parent.parts[1:]:
        current = current / component
        try:
            if _is_reparse_path(current):
                raise ValueError("report path contains a symlink or reparse point")
        except OSError as exc:
            raise ValueError("cannot validate report path") from exc
    try:
        if _is_reparse_path(destination):
            raise ValueError("report destination must not be a symlink or reparse point")
    except FileNotFoundError:
        pass
    except OSError as exc:
        raise ValueError("cannot validate report destination") from exc
    if not parent.is_dir():
        raise ValueError("report parent directory must already exist")
    return destination, destination.name


def _is_reparse_path(path: Path) -> bool:
    """Detect symlinks, Windows junctions, and other Windows reparse points."""
    info = path.lstat()
    is_junction = getattr(path, "is_junction", None)
    if path.is_symlink() or (callable(is_junction) and is_junction()):
        return True
    if os.name == "nt":
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        return bool(getattr(info, "st_file_attributes", 0) & reparse_flag)
    return False


def write_report(
    report: Mapping[str, Any],
    path: str | Path,
    *,
    overwrite: bool = False,
    output_root: str | Path | None = None,
) -> Path:
    """Atomically write a report; reject traversal and symlinks, never clobber by default."""
    destination, name = _validated_output_path(path, output_root)
    payload = serialize_report(report).encode("utf-8")
    flags = os.O_WRONLY | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    supports_dir_fd = _supports_dir_fd()
    parent_fd = None
    if supports_dir_fd:
        if output_root is not None:
            relative = Path(path)
            parent_fd = os.open(Path(output_root).resolve(strict=True), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                for component in relative.parent.parts:
                    if component in ("", "."):
                        continue
                    child_fd = os.open(
                        component,
                        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
                        dir_fd=parent_fd,
                    )
                    os.close(parent_fd)
                    parent_fd = child_fd
            except BaseException:
                os.close(parent_fd)
                raise
        else:
            parent_fd = os.open(
                destination.parent,
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
            )

    if not overwrite:
        try:
            _validated_output_path(path, output_root)
            open_target = name if parent_fd is not None else destination
            fd = os.open(
                open_target,
                flags | os.O_EXCL,
                0o600,
                **({"dir_fd": parent_fd} if parent_fd is not None else {}),
            )
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
            except BaseException:
                try:
                    if parent_fd is not None:
                        os.unlink(name, dir_fd=parent_fd)
                    else:
                        destination.unlink()
                except OSError:
                    pass
                raise
            return destination
        finally:
            if parent_fd is not None:
                os.close(parent_fd)

    if parent_fd is not None:
        temp_name = f".{name}.{secrets.token_hex(8)}.tmp"
        try:
            fd = os.open(temp_name, flags | os.O_EXCL, 0o600, dir_fd=parent_fd)
            with os.fdopen(fd, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                info = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
                if stat.S_ISLNK(info.st_mode):
                    raise ValueError("report destination must not be a symlink")
            except FileNotFoundError:
                pass
            os.replace(temp_name, name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
            return destination
        finally:
            try:
                os.unlink(temp_name, dir_fd=parent_fd)
            except FileNotFoundError:
                pass
            os.close(parent_fd)

    fd, temp_path = tempfile.mkstemp(prefix=f".{name}.", suffix=".tmp", dir=destination.parent)
    temporary = Path(temp_path)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        if _is_reparse_path(destination):
            raise ValueError("report destination must not be a symlink or reparse point")
        _validated_output_path(path, output_root)
        os.replace(temporary, destination)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    return destination


def _supports_dir_fd() -> bool:
    """Whether report writes can use POSIX directory-relative operations."""
    return os.name == "posix" and os.open in os.supports_dir_fd and os.rename in os.supports_dir_fd


def render_summary(report: Mapping[str, Any]) -> str:
    """Render a compact, deterministic console summary."""
    lines = [
        f"Dataset: {report['dataset']['dataset_id']} ({'synthetic' if report['dataset']['synthetic'] else 'real'})",
        f"Split: {report['dataset']['split']} | k={report['configuration']['k']} | questions={report['query_count']}",
        "Retrieval metrics include answerable questions only; no-answer results are separate.",
    ]
    for name, strategy in report["strategies"].items():
        lines.append(f"\n{name}")
        for direction, metrics in strategy["metrics"]["by_direction"].items():
            lines.append(
                f"  {direction}: n={metrics['query_count']} "
                f"P@k={metrics['precision_at_k']:.4f} "
                f"R@k={metrics['recall_at_k']:.4f} "
                f"MRR@k={metrics['mrr_at_k']:.4f} "
                f"nDCG@k={metrics['ndcg_at_k']:.4f}"
            )
        overall = strategy["metrics"]["overall"]
        lines.append(
            f"  overall: n={overall['query_count']} "
            f"P@k={overall['precision_at_k']:.4f} "
            f"R@k={overall['recall_at_k']:.4f} "
            f"MRR@k={overall['mrr_at_k']:.4f} "
            f"nDCG@k={overall['ndcg_at_k']:.4f}"
        )
        no_answer = strategy["no_answer"]
        lines.append(
            f"  no-answer: n={no_answer['query_count']} "
            f"false_positives={no_answer['false_positive_queries']} "
            f"abstentions={no_answer['abstained_queries']}"
        )
    lines.append("\nSynthetic fixture results do not establish real-world retrieval quality.")
    return "\n".join(lines)
