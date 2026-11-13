"""Opt-in, local-only real PDF evidence and answering pilot.

This pilot indexes exactly one explicitly named trusted local PDF into a volatile
in-memory index. It uses cached E5 and local Ollama; no database, deployment,
cloud model, directory crawling, or persistent document indexing is involved.
This is not a financial-accuracy certification or a hostile-PDF sandbox.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


WORKSPACE_ID = "nexus-real-pdf-owner-pilot"


def validate_pdf_path(value: str) -> Path:
    """Require an existing ordinary .pdf; do not discover or crawl directories."""
    # Copy-as-path and interactive shells commonly add quotes or whitespace.
    # Strip only surrounding whitespace/quotes; preserve spaces in filenames.
    cleaned = value.strip().strip('"').strip()
    path = Path(cleaned).expanduser()
    if not path.is_absolute() or path.suffix.casefold() != ".pdf":
        raise ValueError("provide an absolute path to one .pdf file")
    if path.is_symlink():
        raise ValueError("symlink PDF paths are not supported by this pilot")
    if not path.is_file():
        raise ValueError("PDF path must be an existing file")
    resolved = path.resolve(strict=True)
    if not resolved.is_file():
        raise ValueError("PDF path must be an existing file")
    return resolved


def run_pilot(pdf: Path, question: str) -> dict[str, object]:
    """Run one PDF through real bounded extraction, E5 retrieval, and local Gemma."""
    if not isinstance(question, str) or not question.strip() or len(question) > 8000:
        raise ValueError("question must contain 1 to 8000 non-whitespace characters")
    from nexus_ai.documents.service import DocumentIngestionService
    from nexus_ai.model_adapters import LangChainChatOllamaAdapter
    from nexus_ai.ollama import OllamaClient
    from nexus_ai.retrieval.answering import GroundedAnswerService
    from nexus_ai.retrieval.embeddings import E5EmbeddingProvider
    from nexus_ai.retrieval.repository import InMemoryDocumentIndex
    from nexus_ai.retrieval.service import RetrievalService

    # The existing filesystem gate and bounded PDF worker remain mandatory.
    embedder = E5EmbeddingProvider()
    repository = InMemoryDocumentIndex()
    ingestion = DocumentIngestionService(
        approved_root=pdf.parent, repository=repository, embedder=embedder
    )
    ingested = ingestion.ingest(WORKSPACE_ID, pdf.name)
    indexed = repository.get_active(WORKSPACE_ID, ingested.document_id)
    if indexed is None:
        raise RuntimeError("PDF index was not activated")
    retrieval = RetrievalService(repository=repository, embedder=embedder)
    found = retrieval.retrieve(question, workspace_id=WORKSPACE_ID, top_k=5)
    citations = tuple(row.citation for row in found.results)

    from scripts.run_pdf_rag_e2e import _citation_maps_to_extracted_pdf
    if not all(_citation_maps_to_extracted_pdf(c, {pdf.name: indexed}) for c in citations):
        raise RuntimeError("retrieved citation did not map to an extracted source page")
    client = OllamaClient()
    if not client.base_url.startswith(("http://127.0.0.1:", "http://localhost:")):
        raise ValueError("real-PDF pilot requires loopback-only Ollama")
    adapter = LangChainChatOllamaAdapter(
        base_url=client.base_url,
        default_model=client.default_model,
        temperature=0.0,
        num_predict=384,
        timeout_seconds=client.timeout_seconds,
    )
    answerer = GroundedAnswerService(adapter=adapter, default_model=client.default_model)
    answered = answerer.answer(question, citations)
    if not all(c in citations and _citation_maps_to_extracted_pdf(c, {pdf.name: indexed}) for c in answered.citations):
        raise RuntimeError("generated answer citation failed source validation")
    return {
        "report_kind": "single trusted real PDF pilot; unreviewed",
        "status": "PASS",
        "not_an_accuracy_benchmark": True,
        "document_sha256": indexed.document.content_sha256,
        "page_count": len(indexed.document.pages),
        "extractable_pages": sum(bool(p.text.strip()) for p in indexed.document.pages),
        "source_warning_count": len(indexed.document.warnings),
        "indexed_chunks": len(indexed.chunks),
        "indexed_windows": len(indexed.windows),
        "retrieved_evidence_count": len(citations),
        "retrieved_pages": sorted({c.page_number for c in citations if c.page_number is not None}),
        "model": client.default_model,
        "question": question,
        "answer": answered.answer,
        "abstained": answered.abstained,
        "citations": [{
            "page_number": c.page_number,
            "start_char": c.start_char,
            "end_char": c.end_char,
            "source_sha256": c.source_sha256,
            "chunk_id": c.chunk_id,
        } for c in answered.citations],
        "limitations": [
            "no human-reviewed correctness score",
            "PDF tables and scanned pages may extract incorrectly",
            "one PDF only; no cross-year corpus validation",
            "retrieval top-k does not prove relevance",
            "Windows Job Objects do not isolate filesystem or network",
        ],
        "side_effects": {"database": "NONE", "deployment": "NONE", "index": "MEMORY_ONLY"},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-live", action="store_true", required=True)
    parser.add_argument("--pdf", required=True, help="absolute path to trusted local PDF")
    parser.add_argument("--question", required=True)
    parser.add_argument("--report", type=Path, help="optional JSON output outside repository")
    args = parser.parse_args(argv)
    try:
        pdf = validate_pdf_path(args.pdf)
        report = run_pilot(pdf, args.question)
    except Exception as exc:
        report = {
            "report_kind": "single trusted real PDF pilot; unreviewed",
            "status": "BLOCKED",
            "error_type": type(exc).__name__,
            "not_an_accuracy_benchmark": True,
            "side_effects": {"database": "NONE", "deployment": "NONE", "index": "MEMORY_ONLY"},
        }
    if args.report:
        root = Path(__file__).resolve().parents[1]
        path = args.report.expanduser().resolve()
        if path == root or root in path.parents:
            raise ValueError("pilot report path must be outside repository")
        if path.is_symlink():
            raise ValueError("pilot report cannot overwrite a symlink")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
