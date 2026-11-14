"""Fail-closed candidate extraction from source-verified financial table text.

This is NOT Arabic visual-table reconstruction. Only explicitly delimited
two-column rows with a nearby, unambiguous year/unit header are eligible.
Anything else abstains for human review. The returned candidate is never a
ReviewedFinancialObservation and cannot enter financial analytics directly.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from nexus_ai.data_analytics import AnalyticsInputError
from nexus_ai.financial_evidence_analytics import _evidence_contains_amount

# Strong, language-specific exact row labels only. Substrings such as
# "segment revenue" or "other income" are not eligible.
_LABELS = {
    "revenue": frozenset(("total revenue", "إجمالي الإيرادات", "اجمالي الايرادات")),
    "net_income": frozenset(("net income", "صافي الربح", "صافي الدخل")),
}
_UNITS = {"SAR thousands": ("SAR", "thousands"),
          "SAR millions": ("SAR", "millions"),
          "ألف ريال سعودي": ("SAR", "thousands"),
          "مليون ريال سعودي": ("SAR", "millions")}
_NUM = re.compile(r"-?(?:[0-9٠-٩۰-۹]{1,3}(?:[,٬][0-9٠-٩۰-۹]{3})+|[0-9٠-٩۰-۹]+)(?:\.[0-9٠-٩۰-۹]+)?")
_YEAR = re.compile(r"(?<![0-9])(?:19|20)[0-9]{2}(?![0-9])")


@dataclass(frozen=True)
class FinancialRowCandidate:
    workspace_id: str
    document_id: str
    version_id: str
    source_sha256: str
    source_path: str
    page_number: int
    chunk_id: str
    start_char: int
    end_char: int
    metric: str
    year: int
    amount: str
    currency: str
    unit: str
    status: str = "HUMAN_ROW_REVIEW_REQUIRED"


def _latin_digits(text: str) -> str:
    return text.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789"))


def _parse_amount(token: str) -> str | None:
    normalized = _latin_digits(token)
    if "," in normalized or "٬" in normalized:
        groups = re.split(r"[,٬]", normalized)
        if len(groups) < 2 or not (1 <= len(groups[0].lstrip("-")) <= 3):
            return None
        if any(len(g) != 3 or not g.isdigit() for g in groups[1:-1]):
            return None
        final = groups[-1]
        if not re.fullmatch(r"[0-9]{3}(?:\.[0-9]+)?", final):
            return None
        normalized = normalized.replace(",", "").replace("٬", "")
    if not re.fullmatch(r"-?[0-9]+(?:\.[0-9]+)?", normalized):
        return None
    return normalized


def extract_table_candidates(
    *,
    repository,
    workspace_id: str,
    document_id: str,
    max_candidates: int = 100,
) -> dict[str, object]:
    """Find strict label | amount rows under a year and currency/unit header.

    A row is eligible only when a *same-chunk* single-year, single-unit
    header precedes it and it has exactly two pipe- or tab-separated cells.
    Standalone numbers, arbitrary whitespace and multi-year matrix layouts
    are intentionally rejected to prevent incorrect column attribution.
    """
    if (not isinstance(workspace_id, str) or not workspace_id.strip()
            or not isinstance(document_id, str) or not document_id.strip()
            or type(max_candidates) is not int or not 1 <= max_candidates <= 100):
        raise AnalyticsInputError("invalid extraction scope or limits")
    indexed = repository.get_active(workspace_id, document_id)
    if indexed is None or indexed.document.workspace_id != workspace_id or indexed.document.document_id != document_id:
        raise AnalyticsInputError("active document not found in workspace")
    doc = indexed.document
    pages = {page.page_number: page.text for page in doc.pages}
    found = []
    abstentions = {"ambiguous_or_missing_header": 0, "ambiguous_row": 0,
                   "unreliable_citation": 0}
    inspected = 0
    for chunk in indexed.chunks:
        if chunk.document_id != document_id or chunk.version_id != doc.version_id or chunk.source_sha256 != doc.content_sha256 or chunk.source_path != doc.source_path:
            raise AnalyticsInputError("chunk provenance mismatch")
        text = pages.get(chunk.page_number)
        if (text is None or chunk.start_char is None or chunk.end_char is None
                or not chunk.offsets_reliable or chunk.start_char < 0
                or text[chunk.start_char:chunk.end_char] != chunk.text):
            abstentions["unreliable_citation"] += 1
            continue
        inspected += 1
        lines = chunk.text.splitlines(keepends=True)
        header_year = None
        header_unit = None
        header_valid = False
        offset = chunk.start_char
        for line in lines:
            stripped = line.strip()
            # Header requires an explicit marker to avoid treating an
            # ordinary row year or footnote as a table column header.
            if stripped.lower().startswith(("year:", "السنة:")):
                years = _YEAR.findall(_latin_digits(stripped))
                # findall yields year values because there are no capturing groups
                unit_hits = [u for token, u in _UNITS.items() if token.casefold() in stripped.casefold()]
                header_valid = len(years) == 1 and len(unit_hits) == 1
                header_year = int(years[0]) if header_valid else None
                header_unit = unit_hits[0] if header_valid else None
                offset += len(line)
                continue
            separator = "\t" if "\t" in line else "|" if "|" in line else None
            if separator is None:
                offset += len(line)
                continue
            pieces = [item.strip() for item in stripped.split(separator)]
            labels = [metric for metric, forms in _LABELS.items()
                      if len(pieces) >= 1 and pieces[0].casefold() in {f.casefold() for f in forms}]
            if not labels:
                offset += len(line)
                continue
            if not header_valid:
                abstentions["ambiguous_or_missing_header"] += 1
                offset += len(line)
                continue
            if len(pieces) != 2 or len(labels) != 1 or not _NUM.fullmatch(pieces[1]):
                abstentions["ambiguous_row"] += 1
                offset += len(line)
                continue
            amount = _parse_amount(pieces[1])
            if amount is None or not _evidence_contains_amount(line, amount):
                abstentions["ambiguous_row"] += 1
                offset += len(line)
                continue
            if len(found) >= max_candidates:
                raise AnalyticsInputError("candidate extraction limit exceeded")
            found.append(FinancialRowCandidate(
                workspace_id=workspace_id, document_id=document_id,
                version_id=doc.version_id, source_sha256=doc.content_sha256,
                source_path=doc.source_path, page_number=chunk.page_number,
                chunk_id=chunk.chunk_id, start_char=offset,
                end_char=offset + len(line.rstrip("\r\n")),
                metric=labels[0], year=header_year, amount=amount,
                currency=header_unit[0], unit=header_unit[1],
            ))
            offset += len(line)
    current = repository.get_active(workspace_id, document_id)
    if (current is None or current.document.version_id != doc.version_id
            or current.document.content_sha256 != doc.content_sha256
            or current.document.source_path != doc.source_path):
        raise AnalyticsInputError("active source changed during candidate extraction")
    return {
        "status": "CANDIDATES_FOR_REVIEW" if found else "ABSTAIN_NO_STRICT_ROWS",
        "candidate_count": len(found),
        "candidates": [item.__dict__ for item in found],
        "abstentions": abstentions,
        "inspected_chunks": inspected,
        "automatically_verified_financial_facts": 0,
        "scope": {"llm_calls": 0, "database_writes": 0},
    }
