"""Deterministic evaluation helpers for the isolated RAG prototype.

This module consumes a versioned JSON fixture, not arbitrary user documents. It
uses the prototype's existing BM25 implementation and metrics and deliberately
keeps synthetic retrieval scores separate from answerability/abstention counts.
"""

from __future__ import annotations

import hashlib
import json
import math
import platform
from collections import defaultdict
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


class FixtureError(ValueError):
    """Raised when the evaluation fixture is ambiguous or inconsistent."""


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
    if fixture.get("synthetic") is not True:
        raise FixtureError("fixture must explicitly declare synthetic=true")

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

    answerable_directions: set[str] = set()
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
            answerable_directions.add(f"{query_language}->{evidence_language}")
        else:
            if evidence_language is not None or relevant:
                raise FixtureError(f"unanswerable question {question_id} must have no evidence language or positive labels")

    missing_directions = set(DIRECTIONS) - answerable_directions
    if missing_directions:
        raise FixtureError(f"fixture lacks bilingual directions: {', '.join(sorted(missing_directions))}")
    return fixture


def load_fixture(path: str | Path) -> dict[str, Any]:
    """Load UTF-8 JSON and fail closed on malformed or incomplete fixture data."""
    fixture_path = Path(path)
    try:
        raw = fixture_path.read_bytes()
        fixture = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FixtureError(f"cannot read fixture: {exc}") from exc
    validate_fixture(fixture)
    fixture["_source_sha256"] = hashlib.sha256(raw).hexdigest()
    return fixture


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


def _default_retrievers(chunks: Sequence[Chunk]) -> dict[str, Retriever]:
    raw_index = BM25Index(chunks)
    normalized_index = BM25Index(chunks, normalize_arabic=True)
    return {
        "bm25_arabic_normalized": lambda query, k: normalized_index.search(query, top_k=k),
        "bm25_raw": lambda query, k: raw_index.search(query, top_k=k),
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
    retrievers: Mapping[str, Retriever] | None = None,
) -> dict[str, Any]:
    """Run deterministic retrieval evaluation on one document-disjoint split."""
    validate_fixture({key: value for key, value in fixture.items() if not key.startswith("_")})
    if split not in ("dev", "holdout"):
        raise ValueError("split must be dev or holdout")
    if split == "holdout" and not allow_holdout:
        raise ValueError("holdout evaluation requires allow_holdout=True")
    if type(k) is not int or k <= 0:
        raise ValueError("k must be a positive integer")

    corpus = _chunks(fixture, split)
    if not corpus:
        raise FixtureError(f"split {split} has no chunks")
    available = {chunk.chunk_id: chunk for chunk in corpus}
    active_questions = [q for q in fixture["queries"] if q["split"] == split]
    if not active_questions:
        raise FixtureError(f"split {split} has no questions")
    strategy_map = dict(retrievers or _default_retrievers(corpus))
    if not strategy_map or any(
        not isinstance(name, str) or not name or not callable(retrieve)
        for name, retrieve in strategy_map.items()
    ):
        raise ValueError("retrievers must have non-empty string names")

    strategies: dict[str, Any] = {}
    for strategy_name in sorted(strategy_map):
        retrieve = strategy_map[strategy_name]
        metric_rows: list[tuple[dict[str, Any], RetrievalMetrics]] = []
        query_results: dict[str, Any] = {}
        no_answer_results: dict[str, Any] = {}
        empty_answerable: list[str] = []
        missed_answerable: list[str] = []
        unjudged_count = 0

        for question in active_questions:
            raw_hits = list(retrieve(question["text"], k))
            ranked_ids = [hit.chunk.chunk_id if hasattr(hit, "chunk") else hit for hit in raw_hits]
            if any(not isinstance(item_id, str) for item_id in ranked_ids):
                raise ValueError(f"strategy {strategy_name} returned a non-string chunk ID")
            if len(ranked_ids) != len(set(ranked_ids)):
                raise ValueError(f"strategy {strategy_name} returned duplicate chunk IDs")
            unknown = [item_id for item_id in ranked_ids if item_id not in available]
            if unknown:
                raise ValueError(f"strategy {strategy_name} returned unknown chunk ID: {unknown[0]}")
            unjudged = [item_id for item_id in ranked_ids if item_id not in set(question["judged_chunk_ids"])]
            unjudged_count += len(unjudged)
            provenance = [
                {
                    "rank": rank,
                    "chunk_id": item_id,
                    "document_id": available[item_id].document_id,
                    "source": available[item_id].source,
                    "evidence_language": next(c["language"] for c in fixture["chunks"] if c["chunk_id"] == item_id),
                    "start_char": available[item_id].start_char,
                    "end_char": available[item_id].end_char,
                }
                for rank, item_id in enumerate(ranked_ids, start=1)
            ]
            if question["answerable"]:
                metric = retrieval_metrics(ranked_ids, question["relevance"], k=k)
                metric_rows.append((question, metric))
                is_hit = any(question["relevance"].get(item_id, 0) > 0 for item_id in ranked_ids[:k])
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
                "tie_break": "BM25 score descending, chunk ID ascending",
            },
        }

    source_hash = fixture.get("_source_sha256")
    if not isinstance(source_hash, str):
        canonical = json.dumps(fixture, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        source_hash = hashlib.sha256(canonical).hexdigest()
    return {
        "report_schema_version": 1,
        "evaluation_version": EVALUATION_VERSION,
        "dataset": {
            "dataset_id": fixture["dataset_id"],
            "synthetic": fixture["synthetic"],
            "split": split,
            "fixture_sha256": source_hash,
        },
        "configuration": {
            "k": k,
            "metrics_include_answerable_queries_only": True,
            "missing_judgments": "rejected; each question must judge every chunk in its split",
            "tie_break": "score descending, stable chunk ID ascending",
        },
        "environment": {"python": platform.python_version()},
        "query_count": len(active_questions),
        "answerable_query_count": sum(q["answerable"] for q in active_questions),
        "no_answer_query_count": sum(not q["answerable"] for q in active_questions),
        "strategies": strategies,
    }


def serialize_report(report: Mapping[str, Any]) -> str:
    """Serialize a report canonically for stable diffs and repeated-run checks."""
    return json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"


def write_report(report: Mapping[str, Any], path: str | Path, *, overwrite: bool = False) -> Path:
    """Write a report without replacing prior evidence unless explicitly requested."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    mode = "w" if overwrite else "x"
    with destination.open(mode, encoding="utf-8", newline="\n") as stream:
        stream.write(serialize_report(report))
    return destination


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
