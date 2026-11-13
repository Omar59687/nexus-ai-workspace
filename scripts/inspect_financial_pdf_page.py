"""Opt-in model-free single-page financial extraction/chunking forensics.

Runs bounded isolated PDF extraction once, writes UTF-8 metadata only.
No PDF text, queried anchors, database writes, embeddings, or models leave RAM.
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

from nexus_ai.benchmark.financial_chunk_forensics import inspect_page_anchors
from nexus_ai.documents.collection_index import CollectionIndexService
from nexus_ai.documents.collection_types import CollectionIndexLimits
from nexus_ai.retrieval.collection_repository import InMemoryCollectionIndexRepository


def run_page_forensics(pdf: Path, *, page: int, year: int, anchors: list[str]) -> dict[str, object]:
    if not pdf.is_absolute() or pdf.suffix.casefold() != ".pdf":
        raise ValueError("owner must supply an absolute PDF path")
    if not pdf.is_file() or pdf.is_symlink():
        raise ValueError("PDF must be a regular, non-symlink file")
    if type(year) is not int or not 1900 <= year <= 2100:
        raise ValueError("report year is invalid")
    repo = InMemoryCollectionIndexRepository()
    service = CollectionIndexService(
        approved_root=pdf.parent,
        repository=repo,
        limits=CollectionIndexLimits(max_documents=1),
    )
    outcome = service.index("local-financial-page-forensics", [
        {"path": pdf.name, "company": "OwnerSelected", "year": year}
    ])
    record = outcome["documents"][0]
    if record["status"] not in ("indexed", "unchanged"):
        return {"status": "BLOCKED", "reason": "pdf_extraction_or_indexing_failed"}
    indexed = repo.get_active("local-financial-page-forensics", record["document_id"])
    findings = inspect_page_anchors(
        pages=indexed.document.pages, chunks=indexed.chunks,
        page_number=page, anchors=anchors,
    )
    return {
        "status": "PASS",
        "source_sha256": indexed.document.content_sha256,
        "page_count": len(indexed.document.pages),
        "chunk_count": len(indexed.chunks),
        "findings": findings,
        "limitations": [
            "Co-occurrence of anchors does not prove financial-table row correctness.",
            "The original PDF must be reviewed by a human for exact values and currency.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, action="store_true")
    parser.add_argument("--pdf", required=True, type=Path)
    parser.add_argument("--page", required=True, type=int)
    parser.add_argument("--year", required=True, type=int)
    anchor_input = parser.add_mutually_exclusive_group(required=True)
    anchor_input.add_argument("--anchor", action="append", dest="anchors")
    anchor_input.add_argument("--anchors-json", type=Path, dest="anchors_json")
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args(argv)

    try:
        if args.anchors_json is not None:
            anchor_file = args.anchors_json.expanduser()
            if not anchor_file.is_file() or anchor_file.is_symlink() or anchor_file.stat().st_size > 4096:
                raise ValueError("anchor file is missing, linked, or too large")
            anchors = json.loads(anchor_file.read_text(encoding="utf-8-sig"))
        else:
            anchors = args.anchors
        if not isinstance(anchors, list) or not 2 <= len(anchors) <= 8:
            raise ValueError("require 2 to 8 anchors")
        report = args.report.expanduser()
        if report.is_symlink():
            raise ValueError("symlink report output is forbidden")
        report = report.resolve()
        pdf = args.pdf.expanduser()
        root = pdf.parent.resolve(strict=True)
        if report == root or root in report.parents or report == pdf.resolve(strict=True):
            raise ValueError("report must be outside the PDF's source directory")
        output = run_page_forensics(pdf, page=args.page, year=args.year, anchors=anchors)
        report.parent.mkdir(parents=True, exist_ok=True)
        encoded = (json.dumps(output, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
        fd, tmp = tempfile.mkstemp(prefix=".nexus-forensic-", suffix=".tmp", dir=report.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(encoded)
            os.replace(tmp, report)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
        print(json.dumps({
            "status": output["status"],
            "page_count": output.get("page_count"),
            "all_anchors_present_on_page": output.get("findings", {}).get("all_anchors_present_on_page"),
            "all_anchors_share_chunk": output.get("findings", {}).get("all_anchors_share_chunk"),
            "all_anchors_within_line_window": output.get("findings", {}).get("all_anchors_within_line_window"),
        }, ensure_ascii=True))
        return 0 if output["status"] == "PASS" else 1
    except (OSError, ValueError, UnicodeError):
        print('{"status":"BLOCKED","reason":"invalid_input_or_output"}')
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
