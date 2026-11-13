"""Opt-in generated-PDF to local E5/Ollama diagnostic; not an accuracy benchmark.

The live path creates only temporary synthetic PDFs, ingests into an in-memory
index, and never contacts PostgreSQL. Model execution requires ``--run-live``.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


WORKSPACE_ID = "p4-pdf-rag-e2e-fixture"


@dataclass(frozen=True)
class PdfFixture:
    source_path: str
    pages: tuple[str, ...]


PDF_FIXTURES = (
    PdfFixture("english_revenue.pdf", (
        "Northstar Systems reported revenue of 42 million dollars for 2024.",
        "This generated fixture contains no real company disclosure.",
    )),
    PdfFixture("arabic_revenue.pdf", (
        "بلغت إيرادات شركة نورث ستار التجريبية لعام 2024 مقدار 42 مليون دولار.",
    )),
    PdfFixture("english_headcount.pdf", (
        "Northstar Systems employed 1,200 people in 2024.",
    )),
    PdfFixture("english_location_control.pdf", (
        "The generated fixture places the fictional Northstar office in Amman.",
    )),
)


@dataclass(frozen=True)
class PdfQueryCase:
    case_id: str
    direction: str
    query: str
    language: Literal["ar", "en"]
    expected_sources: tuple[str, ...]
    empty_evidence: bool = False
    expected_numeric_facts: tuple[str, ...] = ()


PDF_QUERY_CASES = (
    PdfQueryCase("en_to_en", "EN→EN", "What was Northstar's 2024 revenue?", "en",
                 ("english_revenue.pdf",), expected_numeric_facts=("42 million dollars",)),
    PdfQueryCase("ar_to_ar", "AR→AR", "كم بلغت إيرادات نورث ستار التجريبية لعام 2024؟", "ar",
                 ("arabic_revenue.pdf",), expected_numeric_facts=("42 million dollars",)),
    PdfQueryCase("ar_to_en", "AR→EN", "ما قيمة إيرادات Northstar في عام 2024؟", "ar",
                 ("english_revenue.pdf",), expected_numeric_facts=("42 million dollars",)),
    PdfQueryCase("en_to_ar", "EN→AR", "What revenue did the experimental Northstar report state?", "en",
                 ("arabic_revenue.pdf",), expected_numeric_facts=("42 million dollars",)),
    PdfQueryCase("multi_document", "EN→EN", "What were Northstar's 2024 revenue and employee count?", "en",
                 ("english_revenue.pdf", "english_headcount.pdf"), expected_numeric_facts=("42 million dollars", "1,200")),
    PdfQueryCase("no_answer", "EN→EN", "What was Northstar's 2024 net income?", "en", (), True),
)


def generated_text_pdf(pages: tuple[str, ...]) -> bytes:
    """Build a tiny self-contained PDF with a ToUnicode text layer.

    The fixture font maps each BMP Unicode code point to itself. Arabic text is
    source text in the PDF content stream; no external fonts or assets are read.
    """
    if not pages or any(not isinstance(page, str) or not page.strip() for page in pages):
        raise ValueError("generated PDF pages must contain non-empty text")
    characters = sorted({char for page in pages for char in page})
    if any(ord(char) > 0xFFFF for char in characters):
        raise ValueError("generated PDF fixture supports BMP text only")
    page_ids = [3 + index * 2 for index in range(len(pages))]
    font_id = 3 + len(pages) * 2
    descendant_id = font_id + 1
    cmap_id = font_id + 2
    descriptor_id = font_id + 3
    kids = b" ".join(f"{page_id} 0 R".encode("ascii") for page_id in page_ids)
    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [" + kids + f"] /Count {len(pages)} >>".encode("ascii"),
    ]
    for index, (page_id, text) in enumerate(zip(page_ids, pages)):
        content_id = page_id + 1
        encoded = text.encode("utf-16-be").hex().upper()
        stream = f"BT /F1 12 Tf 30 250 Td <{encoded}> Tj ET".encode("ascii")
        objects.extend((
            (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 500 300] "
             f"/Resources << /Font << /F1 {font_id} 0 R >> >> "
             f"/Contents {content_id} 0 R >>").encode("ascii"),
            b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream",
        ))
    objects.append(
        f"<< /Type /Font /Subtype /Type0 /BaseFont /NexusUnicode /Encoding /Identity-H "
        f"/DescendantFonts [{descendant_id} 0 R] /ToUnicode {cmap_id} 0 R >>".encode("ascii")
    )
    objects.append(
        b"<< /Type /Font /Subtype /CIDFontType2 /BaseFont /NexusUnicode "
        b"/CIDSystemInfo << /Registry (Adobe) /Ordering (Identity) /Supplement 0 >> "
        + f"/FontDescriptor {descriptor_id} 0 R /DW 1000 >>".encode("ascii")
    )
    cmap = [
        "/CIDInit /ProcSet findresource begin", "12 dict begin", "begincmap",
        "/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def",
        "/CMapName /Adobe-Identity-UCS def", "/CMapType 2 def",
        "1 begincodespacerange", "<0000> <FFFF>", "endcodespacerange",
    ]
    for offset in range(0, len(characters), 100):
        batch = characters[offset:offset + 100]
        cmap.append(f"{len(batch)} beginbfchar")
        cmap.extend(f"<{ord(char):04X}> <{ord(char):04X}>" for char in batch)
        cmap.append("endbfchar")
    cmap.extend(("endcmap", "CMapName currentdict /CMap defineresource pop", "end", "end"))
    cmap_bytes = "\n".join(cmap).encode("ascii")
    objects.append(
        b"<< /Length " + str(len(cmap_bytes)).encode("ascii") + b" >>\nstream\n"
        + cmap_bytes + b"\nendstream"
    )
    objects.append(
        b"<< /Type /FontDescriptor /FontName /NexusUnicode /Flags 4 "
        b"/FontBBox [0 0 1000 1000] /ItalicAngle 0 /Ascent 800 /Descent -200 "
        b"/CapHeight 700 /StemV 80 >>"
    )

    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for object_id, payload in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{object_id} 0 obj\n".encode("ascii"))
        output.extend(payload)
        output.extend(b"\nendobj\n")
    xref_offset = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    )
    return bytes(output)


def write_pdf_fixtures(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for fixture in PDF_FIXTURES:
        (root / fixture.source_path).write_bytes(generated_text_pdf(fixture.pages))


def ingest_fixture_pdfs(root: Path, embedder):
    """Use the real bounded PDF worker and ingestion/index contracts."""
    from nexus_ai.documents.service import DocumentIngestionService
    from nexus_ai.retrieval.repository import InMemoryDocumentIndex

    repository = InMemoryDocumentIndex()
    service = DocumentIngestionService(
        approved_root=root,
        repository=repository,
        embedder=embedder,
        limits=_small_fixture_limits(),
    )
    indexed = {}
    for fixture in PDF_FIXTURES:
        result = service.ingest(WORKSPACE_ID, fixture.source_path)
        active = repository.get_active(WORKSPACE_ID, result.document_id)
        if active is None:
            raise RuntimeError("fixture index activation failed")
        extracted = tuple(page.text for page in active.document.pages)
        if extracted != fixture.pages:
            raise ValueError("PDF text extraction did not preserve generated source text")
        if tuple(page.page_number for page in active.document.pages) != tuple(range(1, len(fixture.pages) + 1)):
            raise ValueError("PDF extraction did not preserve one-based page numbers")
        indexed[fixture.source_path] = active
    return repository, indexed


def _small_fixture_limits():
    from nexus_ai.documents.service import DocumentIngestionLimits

    return DocumentIngestionLimits(
        max_file_bytes=2 * 1024 * 1024,
        max_total_extracted_chars=100_000,
        max_pdf_page_chars=50_000,
        max_pdf_pages=10,
        max_chunks=100,
        max_windows=100,
        window_chars=500,
        window_overlap_chars=50,
        embedding_batch_size=8,
        max_vector_coordinates=100_000,
        pdf_timeout_seconds=30,
        pdf_memory_limit_bytes=512 * 1024 * 1024,
        pdf_cpu_limit_seconds=30,
    )


def _citation_maps_to_extracted_pdf(citation, indexed_by_path) -> bool:
    document = indexed_by_path.get(citation.source_path)
    if document is None:
        return False
    if (citation.document_id != document.document.document_id
            or citation.document_version_id != document.document.version_id
            or citation.source_sha256 != document.document.content_sha256):
        return False
    chunk = next((row for row in document.chunks if row.chunk_id == citation.chunk_id), None)
    if chunk is None or chunk.page_number != citation.page_number or chunk.text != citation.exact_text:
        return False
    if citation.offsets_reliable:
        page = next((row for row in document.document.pages if row.page_number == citation.page_number), None)
        return bool(page and page.text[citation.start_char:citation.end_char] == citation.exact_text)
    return citation.start_char is None and citation.end_char is None


def _safe_error_category(exc: Exception) -> str:
    from nexus_ai.retrieval.answering import AnswerGenerationError, AnswerOutputRejectedError

    if isinstance(exc, AnswerOutputRejectedError):
        allowed = {
            "fabricated_citation_id", "unsupported_numeric_claim", "citation_id_leaked_into_answer", "invalid_model_output",
            "empty_answer", "answer_without_citations", "duplicate_citation_id",
            "duplicate_evidence_identity", "evidence_limit_exceeded", "workspace_mismatch",
        }
        return exc.reason_code if exc.reason_code in allowed else "answer_rejected"
    if isinstance(exc, AnswerGenerationError):
        return "model_runtime_failure"
    return "case_execution_failure"


def _fixture_numeric_facts_present(answer_text: str, expected_facts: tuple[str, ...]) -> bool:
    """Check explicit numeric fixture facts, not open-domain semantic correctness."""
    from nexus_ai.retrieval.answering import _claim_supported, _numeric_claims

    actual_claims = _numeric_claims(answer_text)
    for expected_text in expected_facts:
        expected = _numeric_claims(expected_text)
        if len(expected) != 1 or not any(
            _claim_supported(gold, actual) for gold in expected for actual in actual_claims
        ):
            return False
    return True


def _run_case(retrieval, answerer, case, indexed_by_path):
    from nexus_ai.documents.types import RetrievalFilters

    filters = (RetrievalFilters(document_id="fixture-no-answer-control")
               if case.empty_evidence else None)
    response = retrieval.retrieve(
        case.query, workspace_id=WORKSPACE_ID, top_k=3, filters=filters,
    )
    retrieved = [row.citation for row in response.results]
    retrieval_integrity = all(_citation_maps_to_extracted_pdf(row, indexed_by_path) for row in retrieved)
    found_sources = {citation.source_path for citation in retrieved}
    expected_found = (not retrieved) if case.empty_evidence else set(case.expected_sources) <= found_sources
    record = {
        "case_id": case.case_id,
        "direction": case.direction,
        "question": case.query,
        "retrieval_status": response.status,
        "expected_evidence_retrieved": expected_found,
        "retrieval_citations_integrity": retrieval_integrity,
        "retrieved_evidence": [
            {
                "document_id": c.document_id,
                "document_version_id": c.document_version_id,
                "source_path": c.source_path,
                "page_number": c.page_number,
                "chunk_id": c.chunk_id,
                "source_sha256": c.source_sha256,
                "start_char": c.start_char,
                "end_char": c.end_char,
                "text": c.exact_text,
            }
            for c in retrieved
        ],
        "semantic_accuracy": "NOT_SCORED",
        "abstention_quality": "NOT_SCORED",
    }
    record["fixture_answerability"] = "UNANSWERABLE" if case.empty_evidence else "ANSWERABLE"
    try:
        answer = answerer.answer(case.query, tuple(retrieved), language=case.language)
    except Exception as exc:
        record.update({
            "execution_status": "FAIL",
            "error_category": _safe_error_category(exc),
            "answer": None,
            "abstained": None,
            "answer_citations": [],
            "answer_coverage_status": "GENERATION_FAILED",
            "fixture_numeric_facts_match": False,
        })
        return record
    answer_citations_valid = all(
        citation in retrieved and _citation_maps_to_extracted_pdf(citation, indexed_by_path)
        for citation in answer.citations
    )
    if case.empty_evidence:
        execution_ok = answer.abstained and not answer.citations
        generation_status = "SKIPPED_EMPTY_EVIDENCE"
    else:
        execution_ok = bool(retrieved) and answer_citations_valid and (answer.abstained or bool(answer.citations))
        generation_status = "STRUCTURED_OUTPUT_ACCEPTED"
    facts_match = (
        None if case.empty_evidence or answer.abstained
        else _fixture_numeric_facts_present(answer.answer, case.expected_numeric_facts)
    )
    record.update({
        "execution_status": "PASS" if execution_ok and retrieval_integrity and expected_found else "FAIL",
        "fixture_numeric_facts_match": facts_match,
        "generation_status": generation_status,
        "answer": answer.answer,
        "abstained": answer.abstained,
        "answer_coverage_status": (
            "EXPECTED_ABSTENTION" if case.empty_evidence and answer.abstained
            else "UNEXPECTED_ANSWER" if case.empty_evidence
            else "UNNECESSARY_ABSTENTION" if answer.abstained and expected_found
            else "ANSWERED_WITH_CITATIONS" if answer.citations and answer_citations_valid
            else "NOT_ANSWERED"
        ),
        "answer_citations_valid": answer_citations_valid,
        "answer_citations": [
            {
                "document_id": c.document_id,
                "document_version_id": c.document_version_id,
                "source_path": c.source_path,
                "page_number": c.page_number,
                "chunk_id": c.chunk_id,
                "source_sha256": c.source_sha256,
            }
            for c in answer.citations
        ],
    })
    return record


def run_live_pdf_rag() -> dict[str, object]:
    """Run generated PDFs through isolated extraction, cached E5 and local Ollama."""
    from nexus_ai.model_adapters import LangChainChatOllamaAdapter
    from nexus_ai.ollama import OllamaClient
    from nexus_ai.retrieval.answering import GroundedAnswerService
    from nexus_ai.retrieval.embeddings import E5EmbeddingProvider
    from nexus_ai.retrieval.service import RetrievalConfig, RetrievalService

    embedder = E5EmbeddingProvider()
    client = OllamaClient()
    adapter = LangChainChatOllamaAdapter(
        base_url=client.base_url,
        default_model=client.default_model,
        temperature=0.0,
        num_predict=384,
        timeout_seconds=client.timeout_seconds,
    )
    answerer = GroundedAnswerService(adapter=adapter, default_model=client.default_model)

    with tempfile.TemporaryDirectory(prefix="nexus-p4-pdf-rag-") as temp_dir:
        root = Path(temp_dir)
        write_pdf_fixtures(root)
        repository, indexed = ingest_fixture_pdfs(root, embedder)
        retrieval = RetrievalService(
            repository=repository,
            embedder=embedder,
            config=RetrievalConfig(max_top_k=20),
        )
        cases = [_run_case(retrieval, answerer, case, indexed) for case in PDF_QUERY_CASES]
        success = all(case["execution_status"] == "PASS" for case in cases)
        answerable = [case for case in cases if case["fixture_answerability"] == "ANSWERABLE"]
        answered = sum(case["answer_coverage_status"] == "ANSWERED_WITH_CITATIONS" for case in answerable)
        unnecessary_abstentions = sum(
            case["answer_coverage_status"] == "UNNECESSARY_ABSTENTION" for case in answerable
        )
        numeric_fact_matches = sum(
            case["answer_coverage_status"] == "ANSWERED_WITH_CITATIONS"
            and case["fixture_numeric_facts_match"] is True for case in answerable
        )
        return {
            "report_version": 1,
            "diagnostic_kind": "synthetic generated-PDF end-to-end diagnostic",
            "execution_status": "PASS" if success else "FAIL",
            "not_an_accuracy_benchmark": True,
            "fixture_answer_coverage": {
                "answerable_cases": len(answerable),
                "answered_with_citations": answered,
                "answered_with_expected_numeric_facts": numeric_fact_matches,
                "all_expected_numeric_facts_present": numeric_fact_matches == len(answerable),
                "unnecessary_abstentions": unnecessary_abstentions,
                "coverage_fraction": round(answered / len(answerable), 3) if answerable else None,
                "all_answerable_cases_answered": answered == len(answerable),
                "not_a_semantic_correctness_score": True,
            },
            "semantic_accuracy": "NOT_SCORED",
            "abstention_quality": "NOT_SCORED",
            "side_effects": {"database": "NONE", "deployment": "NONE", "source_files": "TEMPORARY_SYNTHETIC_ONLY"},
            "e5_model_id": embedder.model_id,
            "e5_revision": embedder.revision,
            "ollama_model": client.default_model,
            "indexed_documents": [
                {
                    "document_id": row.document.document_id,
                    "document_version_id": row.document.version_id,
                    "source_path": row.document.source_path,
                    "source_sha256": row.document.content_sha256,
                    "pages": [page.page_number for page in row.document.pages],
                    "extracted_text_readable": all(page.text.strip() for page in row.document.pages),
                }
                for row in indexed.values()
            ],
            "cases": cases,
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-live", action="store_true",
                        help="explicitly opt into cached E5 and configured local Ollama")
    parser.add_argument("--report", type=Path,
                        help="optional JSON report path; choose a location outside the repository")
    args = parser.parse_args(argv)
    if not args.run_live:
        print(json.dumps({
            "execution_status": "BLOCKED",
            "error_category": "explicit_live_opt_in_required",
            "message": "Pass --run-live to load cached E5 and call configured local Ollama.",
        }, ensure_ascii=False), file=sys.stderr)
        return 2
    try:
        report = run_live_pdf_rag()
    except Exception as exc:
        from nexus_ai.retrieval.embeddings import EmbeddingUnavailableError

        category = "cached_e5_unavailable" if isinstance(exc, EmbeddingUnavailableError) else "live_pipeline_blocked"
        report = {
            "report_version": 1,
            "diagnostic_kind": "synthetic generated-PDF end-to-end diagnostic",
            "execution_status": "BLOCKED",
            "error_category": category,
            "error_type": type(exc).__name__,
            "not_an_accuracy_benchmark": True,
            "semantic_accuracy": "NOT_SCORED",
            "abstention_quality": "NOT_SCORED",
            "side_effects": {"database": "NONE", "deployment": "NONE", "source_files": "TEMPORARY_SYNTHETIC_ONLY"},
        }
    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(serialized + "\n", encoding="utf-8")
    # PowerShell/Windows stdout may use a legacy code page. Keep console JSON
    # ASCII-only while the UTF-8 report file retains readable Arabic text.
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 0 if report.get("execution_status") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
