"""One owner-selected PDF -> bounded geometry -> review-only row diagnostics.

No direct document text, untrusted PDF positions, PDF path or financial
amounts are written to the compact report. Explicit user action required.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path

from nexus_ai.data_analytics import AnalyticsInputError
from nexus_ai.documents.collection_index import CollectionIndexService
from nexus_ai.documents.collection_preflight import _manifest_entries
from nexus_ai.documents.collection_types import CollectionIndexLimits
from nexus_ai.financial_pdf_geometry import extract_pdf_positions
from nexus_ai.financial_pdf_layout_diagnostics import inspect_pdf_layout_signals
from nexus_ai.financial_positioned_tables import reconstruct_financial_rows
from nexus_ai.retrieval.collection_repository import InMemoryCollectionIndexRepository


def diagnostic(pdf: Path, *, pages: tuple[int, ...]) -> dict:
    if (not pdf.is_absolute() or pdf.is_symlink() or not pdf.is_file()
            or pdf.suffix.lower() != ".pdf"):
        raise AnalyticsInputError("absolute regular PDF required")
    if type(pages) is not tuple or not 1 <= len(pages) <= 5:
        raise AnalyticsInputError("one to five pages required")
    limit = CollectionIndexLimits(max_documents=1)
    if pdf.stat().st_size > limit.max_file_bytes:
        raise AnalyticsInputError("PDF exceeds input limits")
    raw = pdf.read_bytes()
    if len(raw) > limit.max_file_bytes:
        raise AnalyticsInputError("PDF exceeds input limits")
    repository = InMemoryCollectionIndexRepository()
    workspace = "p5-owner-financial-position-diagnostic"
    entries = _manifest_entries({"documents": [{"path": pdf.name,
                                                "company": "Unknown",
                                                "year": 2025}]})
    outcome = CollectionIndexService(
        approved_root=pdf.parent, repository=repository, limits=limit,
    ).index(workspace, entries)
    if outcome["documents"][0]["status"] not in ("indexed", "unchanged"):
        raise AnalyticsInputError("source indexing failed")
    doc_id = outcome["documents"][0]["document_id"]
    indexed = repository.get_active(workspace, doc_id)
    if indexed is None or hashlib.sha256(raw).hexdigest() != indexed.document.content_sha256:
        raise AnalyticsInputError("PDF contents changed during extraction")
    positioned = extract_pdf_positions(
        raw, expected_sha256=indexed.document.content_sha256, pages=pages,
    )
    reports = []
    for page in pages:
        layout_signals = inspect_pdf_layout_signals(positioned[page], page_number=page)
        try:
            record = reconstruct_financial_rows(
                positioned[page], repository=repository, workspace_id=workspace,
                document_id=doc_id, page_number=page,
            )
            status = record["status"]
            count = record["candidate_count"]
            abstentions = record["abstentions"]
            source_binding = record["source_binding"]
            evidence_signals = record["evidence_signals"]
            lexical_diagnostics = record["lexical_diagnostics"]
            diagnostic_code = record["reason"]
        except AnalyticsInputError as exc:
            # Fixed enums only. Do not include raw exception text, extracted
            # financial content or PDF source paths in diagnostic reports.
            message = str(exc)
            diagnostic_code = (
                "SOURCE_IDENTITY_OR_OFFSETS" if "source" in message or "indexed" in message
                else "INVALID_GEOMETRY_INVENTORY" if "positioned" in message or "coordinate" in message
                else "UNSUPPORTED_LAYOUT"
            )
            status, count, abstentions = "ABSTAIN_SOURCE_GEOMETRY_MISMATCH", 0, {}
            lexical_diagnostics = {"page_text_lexical_hints": {},
                                   "positioned_fragment_lexical_hints": {},
                                   "interpretation": "DIAGNOSTIC_UNAVAILABLE"}
            evidence_signals = {"anchored_year_headers": 0,
                                "anchored_unit_labels": 0,
                                "anchored_metric_labels": 0,
                                "anchored_numeric_fragments": 0}
            source_binding = {"positioned_fragments_total": len(positioned[page]),
                              "source_anchored_fragments": 0,
                              "unmatched_fragments_skipped": 0,
                              "unmatched_numeric_fragments_skipped": 0}
        reports.append({
            "pdf_page_number": page,
            "positioned_fragments": len(positioned[page]),
            "digest_bound_layout_signals": layout_signals,
            "status": status,
            "review_only_candidate_count": count,
            "abstentions": abstentions,
            "source_binding": source_binding,
            "evidence_signals": evidence_signals,
            "lexical_diagnostics": lexical_diagnostics,
            "diagnostic_code": diagnostic_code,
        })
    return {
        "status": "DIAGNOSTIC_ONLY", "pages_processed": len(indexed.document.pages),
        "chunks_indexed": len(indexed.chunks), "page_diagnostics": reports,
        "automatically_verified_financial_facts": 0,
        "source_hash_matches_active_index": True,
        "note": "Spatial coordinates and row attribution are unverified. Review is always required.",
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--pages", type=int, nargs="+", required=True)
    parser.add_argument("--report", type=Path, required=True)
    options = parser.parse_args(argv)
    try:
        result = diagnostic(options.pdf, pages=tuple(options.pages))
        target = options.report
        if (not target.is_absolute() or target.suffix.lower() != ".json"
                or target.is_symlink() or
                options.pdf.parent.resolve() in target.resolve().parents):
            raise AnalyticsInputError("unsafe report path")
        encoded = (json.dumps(result, indent=2, ensure_ascii=True) + "\n").encode("utf-8")
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".nexus-p5-geometry-", dir=target.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(encoded)
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        print(encoded.decode("utf-8"), end="")
        return 0
    except (AnalyticsInputError, OSError, ValueError):
        print('{"status":"ABSTAIN","reason":"input_or_geometry_not_validated"}')
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
