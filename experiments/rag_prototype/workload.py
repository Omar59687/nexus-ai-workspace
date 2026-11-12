"""Reproducible synthetic workload preparation and measurement for RAG.

This module measures the current in-process BM25 implementation against a
synthetic, versioned corpus. Its deliberately shared ITEM identifiers make
cross-language direction plumbing measurable, but do not test multilingual
semantic understanding. Real-corpus acceptance requires human-reviewed data.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import platform
import time
import tracemalloc
from pathlib import Path
from typing import Any, Mapping

from experiments.rag_prototype import BM25Index
from experiments.rag_prototype.evaluation import (
    DIRECTIONS,
    RetrieverSpec,
    _chunks,
    run_evaluation,
    write_report,
)


WORKLOAD_SCHEMA_VERSION = 1
MAX_DOCUMENTS = 150
MAX_CHUNKS_PER_DOCUMENT = 20
MAX_QUESTIONS = 1_000
MAX_UPDATES = MAX_DOCUMENTS
_DIRECTION_ROWS = ("ar", "ar"), ("en", "en"), ("ar", "en"), ("en", "ar")


def build_workload_fixture(
    *,
    document_count: int = 50,
    chunks_per_document: int = 4,
    question_count: int = 32,
    seed: int = 17,
) -> dict[str, Any]:
    """Build a deterministic dev-only fixture with cross-language/no-answer cases.

    The first four questions guarantee one answerable example for each language
    direction. Question 5 is no-answer, and periodic later questions require
    evidence from two documents. Shared ASCII item keys intentionally simplify
    synthetic lexical matching and are not an Arabic/English quality claim.
    """
    _bounded_int(document_count, "document_count", minimum=4, maximum=MAX_DOCUMENTS)
    _bounded_int(chunks_per_document, "chunks_per_document", minimum=1, maximum=MAX_CHUNKS_PER_DOCUMENT)
    _bounded_int(question_count, "question_count", minimum=8, maximum=MAX_QUESTIONS)
    _bounded_int(seed, "seed", minimum=0, maximum=2**31 - 1)
    if type(document_count) is not int:
        raise ValueError("document_count must be an integer")

    documents: list[dict[str, Any]] = []
    chunks: list[dict[str, Any]] = []
    by_language: dict[str, list[str]] = {"ar": [], "en": []}
    chunk_by_key: dict[tuple[str, int], dict[str, Any]] = {}

    for doc_number in range(document_count):
        document_id = f"doc-{doc_number:04d}"
        language = "ar" if (doc_number + seed) % 2 == 0 else "en"
        by_language[language].append(document_id)
        source = f"synthetic://nexus-workload/{seed}/{document_id}.txt"
        parts: list[str] = []
        document_chunks: list[dict[str, Any]] = []
        offset = 0
        for chunk_number in range(chunks_per_document):
            item_key = _item_key(seed, doc_number, chunk_number)
            amount = 100 + (doc_number * 13 + chunk_number * 7 + seed) % 9_900
            text = _synthetic_fact(language, item_key, amount, revision=0)
            start = offset
            end = start + len(text)
            parts.append(text)
            document_chunks.append({
                "chunk_id": f"chunk-{doc_number:04d}-{chunk_number:02d}-v0",
                "document_id": document_id,
                "version_id": "version-0",
                "language": language,
                "split": "dev",
                "source": source,
                "start_char": start,
                "end_char": end,
                "text": text,
            })
            offset = end
        document_text = "\n".join(parts)
        # Account for the separators included between adjacent source chunks.
        for index, chunk in enumerate(document_chunks):
            if index:
                chunk["start_char"] += index
                chunk["end_char"] += index
            chunk_by_key[(document_id, index)] = chunk
        documents.append({
            "document_id": document_id,
            "version_id": "version-0",
            "language": language,
            "split": "dev",
            "source": source,
            "text": document_text,
        })
        chunks.extend(document_chunks)

    if min(map(len, by_language.values())) < 2:
        raise ValueError("workload requires at least two documents in each language")

    all_chunk_ids = [chunk["chunk_id"] for chunk in chunks]
    queries: list[dict[str, Any]] = []
    for question_number in range(question_count):
        query_language, evidence_language = _DIRECTION_ROWS[question_number % 4]
        no_answer = question_number == 4 or (question_number > 4 and question_number % 13 == 4)
        multi_document = not no_answer and question_number >= 7 and question_number % 8 == 7
        question_id = f"question-{question_number:04d}"
        target_ids: list[str] = []
        markers: list[str] = []
        if not no_answer:
            eligible = by_language[evidence_language]
            first_position = (question_number * 7 + seed) % len(eligible)
            selected = [eligible[first_position]]
            if multi_document:
                selected.append(eligible[(first_position + 1) % len(eligible)])
            for selected_document in selected:
                selected_chunk_number = (question_number + seed) % chunks_per_document
                chunk = chunk_by_key[(selected_document, selected_chunk_number)]
                target_ids.append(chunk["chunk_id"])
                markers.append(_item_key(seed, int(selected_document[-4:]), selected_chunk_number))
        if no_answer:
            query_text = _query_text(query_language, [f"MISSING{seed:04d}{question_number:05d}"])
            scenario = "no_answer"
            evidence_language_value = None
        else:
            query_text = _query_text(query_language, markers)
            scenario = "multi_document" if multi_document else "single_document"
            evidence_language_value = evidence_language
        relevance = {chunk_id: (3 if chunk_id in target_ids else 0) for chunk_id in all_chunk_ids}
        queries.append({
            "question_id": question_id,
            "text": query_text,
            "query_language": query_language,
            "evidence_language": evidence_language_value,
            "split": "dev",
            "answerable": not no_answer,
            "scenario": scenario,
            "target_document_ids": sorted({chunk["document_id"] for chunk in chunks if chunk["chunk_id"] in target_ids}),
            "judged_chunk_ids": list(all_chunk_ids),
            "relevance": relevance,
        })

    fixture = {
        "schema_version": 1,
        "dataset_id": f"nexus-synthetic-workload-{seed}",
        "dataset_version": "1",
        "synthetic": True,
        "split": "dev",
        "workload": {
            "kind": "synthetic_capacity_fixture",
            "seed": seed,
            "cross_language_matching": "shared ASCII item identifiers; not semantic evidence",
            "document_count": document_count,
            "chunk_count": len(chunks),
            "chunks_per_document": chunks_per_document,
            "question_count": question_count,
        },
        "documents": documents,
        "chunks": chunks,
        "queries": queries,
    }
    return fixture


def apply_synthetic_updates(fixture: Mapping[str, Any], *, update_count: int) -> dict[str, Any]:
    """Return a copy with deterministic document versions replaced in-place.

    Each updated document gets a new version and new chunk IDs. Query judgments
    are remapped to those IDs; old IDs are removed. This models version identity
    and full-index rebuild workloads, not a durable repository transaction.
    """
    _bounded_int(update_count, "update_count", minimum=0, maximum=MAX_UPDATES)
    updated = copy.deepcopy(dict(fixture))
    documents = updated.get("documents")
    chunks = updated.get("chunks")
    queries = updated.get("queries")
    if not isinstance(documents, list) or not isinstance(chunks, list) or not isinstance(queries, list):
        raise ValueError("fixture must contain documents, chunks, and queries lists")
    if update_count > len(documents):
        raise ValueError("update_count cannot exceed the document count")
    if update_count == 0:
        return updated

    target_docs = sorted(documents, key=lambda row: row["document_id"])[:update_count]
    id_remap: dict[str, str] = {}
    for revision, document in enumerate(target_docs, start=1):
        document_id = document["document_id"]
        old_version = document["version_id"]
        new_version = f"version-{revision}"
        text_chunks = [row for row in chunks if row["document_id"] == document_id and row["version_id"] == old_version]
        text_chunks.sort(key=lambda row: row["start_char"])
        replacements: list[tuple[dict[str, Any], str, str]] = []
        for chunk_number, chunk in enumerate(text_chunks):
            old_text = chunk["text"]
            new_text = old_text.replace("revision-0", f"revision-{revision}")
            new_id = f"chunk-{document_id[-4:]}-{chunk_number:02d}-v{revision}"
            id_remap[chunk["chunk_id"]] = new_id
            replacements.append((chunk, new_id, new_text))
        new_document_parts: list[str] = []
        new_doc_chunks: list[dict[str, Any]] = []
        offset = 0
        for chunk_number, (chunk, new_id, new_text) in enumerate(replacements):
            if chunk_number:
                new_document_parts.append("\n")
                offset += 1
            start = offset
            new_document_parts.append(new_text)
            offset += len(new_text)
            new_doc_chunks.append({
                **chunk,
                "chunk_id": new_id,
                "version_id": new_version,
                "start_char": start,
                "end_char": offset,
                "text": new_text,
            })
        updated_text = "".join(new_document_parts)
        document["text"] = updated_text
        document["version_id"] = new_version
        chunks[:] = [chunk for chunk in chunks if chunk["document_id"] != document_id]
        chunks.extend(new_doc_chunks)

    new_chunk_ids = {row["chunk_id"] for row in chunks}
    for query in queries:
        old_relevance = query["relevance"]
        new_relevance = {id_remap.get(chunk_id, chunk_id): grade for chunk_id, grade in old_relevance.items()}
        for old_id, new_id in id_remap.items():
            new_relevance.setdefault(new_id, 0)
        query["relevance"] = {chunk_id: new_relevance.get(chunk_id, 0) for chunk_id in sorted(new_chunk_ids)}
        query["judged_chunk_ids"] = sorted(new_chunk_ids)
        query["target_document_ids"] = sorted({
            chunk["document_id"] for chunk in chunks if query["relevance"].get(chunk["chunk_id"], 0) > 0
        })
    updated["dataset_version"] = f"{fixture.get('dataset_version', '1')}+updates-{update_count}"
    updated_workload = dict(updated.get("workload", {}))
    updated_workload["simulated_document_updates"] = update_count
    updated["workload"] = updated_workload
    return updated


def citation_fidelity_diagnostics(fixture: Mapping[str, Any], report: Mapping[str, Any]) -> dict[str, Any]:
    """Check that every reported ranked span still maps to its exact fixture text."""
    documents = {row["document_id"]: row for row in fixture["documents"]}
    chunks = {row["chunk_id"]: row for row in fixture["chunks"]}
    strategy_reports = report.get("strategies", {})
    output: dict[str, Any] = {}
    for strategy, result in strategy_reports.items():
        checked = 0
        invalid: list[str] = []
        result_groups = (result.get("query_results", {}), result.get("no_answer", {}).get("results", {}))
        for group in result_groups:
            for question_id, question_result in group.items():
                for row in question_result.get("ranked_chunks", []):
                    checked += 1
                    chunk_id = row.get("chunk_id")
                    chunk = chunks.get(chunk_id)
                    document = documents.get(row.get("document_id"))
                    if chunk is None or document is None:
                        invalid.append(f"{question_id}:{chunk_id}:unknown_id")
                        continue
                    start, end = row.get("start_char"), row.get("end_char")
                    valid_offsets = (
                        type(start) is int and type(end) is int
                        and 0 <= start <= end <= len(document["text"])
                    )
                    valid = valid_offsets and (
                        chunk["document_id"] == document["document_id"] == row.get("document_id")
                        and chunk["version_id"] == document["version_id"] == row.get("document_version_id")
                        and chunk["source"] == document["source"] == row.get("source")
                        and start == chunk["start_char"]
                        and end == chunk["end_char"]
                        and document["text"][start:end] == chunk["text"]
                        and hashlib.sha256(document["text"].encode("utf-8")).hexdigest() == row.get("document_sha256")
                        and hashlib.sha256(chunk["text"].encode("utf-8")).hexdigest() == row.get("chunk_sha256")
                    )
                    matched = row.get("matched_subwindow")
                    if matched is not None:
                        matched_start, matched_end = matched.get("start_char"), matched.get("end_char")
                        valid = valid and type(matched_start) is int and type(matched_end) is int and (
                            matched.get("document_id") == document["document_id"]
                            and matched.get("document_version_id") == document["version_id"]
                            and matched.get("chunk_id") == chunk["chunk_id"]
                            and chunk["start_char"] <= matched_start < matched_end <= chunk["end_char"]
                        )
                    if not valid:
                        invalid.append(f"{question_id}:{chunk_id}:source_span_mismatch")
        output[strategy] = {
            "checked_ranked_evidence": checked,
            "valid_ranked_evidence": checked - len(invalid),
            "invalid_count": len(invalid),
            "valid_rate": (checked - len(invalid)) / checked if checked else None,
            "invalid_evidence": invalid,
            "interpretation": "provenance integrity only; does not establish answer correctness",
        }
    return output


def run_workload(
    *,
    document_count: int = 50,
    chunks_per_document: int = 4,
    question_count: int = 32,
    update_count: int = 0,
    seed: int = 17,
    k: int = 3,
) -> dict[str, Any]:
    """Run raw/normalized BM25 over the synthetic corpus and capture conditions."""
    _bounded_int(update_count, "update_count", minimum=0, maximum=MAX_UPDATES)
    _bounded_int(k, "k", minimum=1, maximum=100)
    started = time.perf_counter()
    fixture = build_workload_fixture(
        document_count=document_count,
        chunks_per_document=chunks_per_document,
        question_count=question_count,
        seed=seed,
    )
    if update_count > document_count:
        raise ValueError("update_count cannot exceed document_count")
    fixture = apply_synthetic_updates(fixture, update_count=update_count)
    fixture_generation_seconds = time.perf_counter() - started
    corpus = _chunks(fixture, "dev")

    tracemalloc.start()
    try:
        raw_started = time.perf_counter()
        raw_index = BM25Index(corpus)
        raw_index_seconds = time.perf_counter() - raw_started
        normalized_started = time.perf_counter()
        normalized_index = BM25Index(corpus, normalize_arabic=True)
        normalized_index_seconds = time.perf_counter() - normalized_started
        retrievers = {
            "bm25_raw": RetrieverSpec(
                lambda query, top_k: raw_index.search(query, top_k=top_k),
                "BM25 score descending, chunk ID ascending",
                metadata={"strategy": "raw BM25", "index_build_seconds": raw_index_seconds},
            ),
            "bm25_arabic_normalized": RetrieverSpec(
                lambda query, top_k: normalized_index.search(query, top_k=top_k),
                "BM25 score descending, chunk ID ascending",
                metadata={"strategy": "Arabic-normalized BM25", "index_build_seconds": normalized_index_seconds},
            ),
        }
        evaluation = run_evaluation(fixture, split="dev", k=k, retrievers=retrievers, measure_latency=True)
        _, peak_traced_bytes = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    index_metrics = {
        "bm25_raw": _index_metrics(raw_index_seconds, len(fixture["documents"]), len(fixture["chunks"])),
        "bm25_arabic_normalized": _index_metrics(normalized_index_seconds, len(fixture["documents"]), len(fixture["chunks"])),
    }
    evaluation["performance"]["indexing"] = index_metrics
    evaluation["performance"]["resource_observations"] = {
        "peak_traced_python_bytes_from_index_build_start_through_evaluation": peak_traced_bytes,
        "tracemalloc_scope": "Python allocations only; excludes native allocations and total process RSS",
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "logical_cpu_count": __import__("os").cpu_count(),
        },
    }
    evaluation["performance"]["workload_generation_seconds"] = fixture_generation_seconds
    evaluation["performance"]["total_elapsed_seconds"] = time.perf_counter() - started
    evaluation["synthetic_workload"] = {
        **fixture["workload"],
        "updates_are_full_fixture_rebuild_scenarios": True,
        "split": "dev only",
        "not_real_corpus_performance": True,
    }
    evaluation["citation_fidelity"] = citation_fidelity_diagnostics(fixture, evaluation)
    return evaluation


def render_workload_summary(report: Mapping[str, Any]) -> str:
    workload = report.get("synthetic_workload", {})
    performance = report.get("performance", {})
    lines = [
        "SYNTHETIC WORKLOAD — NOT REAL-CORPUS QUALITY EVIDENCE",
        f"documents={workload.get('document_count')} chunks={workload.get('chunk_count')} "
        f"questions={report.get('query_count')} seed={workload.get('seed')}",
        f"updates_applied={workload.get('simulated_document_updates', 0)} split={workload.get('split')}",
    ]
    for strategy in sorted(report.get("strategies", {})):
        strategy_report = report["strategies"][strategy]
        timing = performance.get("by_strategy", {}).get(strategy, {})
        index = performance.get("indexing", {}).get(strategy, {})
        fidelity = report.get("citation_fidelity", {}).get(strategy, {})
        hit_rate = strategy_report.get("answerable_coverage", {}).get("retrieval_hit_rate_at_k", 0.0)
        false_positives = strategy_report.get("no_answer", {}).get("false_positive_queries", 0)
        lines.append(
            f"{strategy}: answerable_hit@k={hit_rate:.3f}; no_answer_false_positives={false_positives}; "
            f"index_s={index.get('index_build_seconds', 0.0):.6f}; "
            f"mean_query_ms={timing.get('mean_query_latency_ms', 0.0):.4f}; "
            f"citation_span_valid={fidelity.get('valid_ranked_evidence', 0)}/{fidelity.get('checked_ranked_evidence', 0)}"
        )
    lines.append("Cross-language questions use shared synthetic item keys; no human labels or real-world accuracy are represented.")
    return "\n".join(lines)


def _index_metrics(seconds: float, document_count: int, chunk_count: int) -> dict[str, float | int]:
    return {
        "index_build_seconds": seconds,
        "documents_indexed": document_count,
        "chunks_indexed": chunk_count,
        "documents_per_second": document_count / seconds if seconds > 0 else 0.0,
        "chunks_per_second": chunk_count / seconds if seconds > 0 else 0.0,
    }


def _synthetic_fact(language: str, item_key: str, amount: int, *, revision: int) -> str:
    if language == "ar":
        return f"سجل اصطناعي {item_key} revision-{revision}: القيمة {amount} وحدة. مصدر تجريبي للتحميل."
    return f"Synthetic record {item_key} revision-{revision}: the value is {amount} units. Example workload source."


def _item_key(seed: int, document_number: int, chunk_number: int) -> str:
    return f"ITEM{seed:04d}{document_number:04d}{chunk_number:03d}"


def _query_text(language: str, markers: list[str]) -> str:
    joined = " and ".join(markers)
    if language == "ar":
        return f"ما القيمة المرتبطة بالمعرّف {joined}؟"
    return f"What value is associated with identifier {joined}?"


def _bounded_int(value: Any, name: str, *, minimum: int, maximum: int) -> None:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be an integer between {minimum} and {maximum}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--documents", type=int, default=50, choices=range(4, MAX_DOCUMENTS + 1))
    parser.add_argument("--chunks-per-document", type=int, default=4, choices=range(1, MAX_CHUNKS_PER_DOCUMENT + 1))
    parser.add_argument("--questions", type=int, default=32, choices=range(8, MAX_QUESTIONS + 1))
    parser.add_argument("--updates", type=int, default=0, choices=range(0, MAX_UPDATES + 1))
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--k", type=int, default=3)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args(argv)
    report = run_workload(
        document_count=args.documents,
        chunks_per_document=args.chunks_per_document,
        question_count=args.questions,
        update_count=args.updates,
        seed=args.seed,
        k=args.k,
    )
    print(render_workload_summary(report))
    if args.json_out:
        write_report(report, args.json_out)
        print(f"JSON report written: {args.json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
