"""Explicitly reviewed financial observations backed by active document citations.

A reviewed record is not an automatically extracted table row. Numeric
presence, version, offsets, workspace, and duplicate identity are verified
here; metric/year/currency/unit attribution is a separate human assertion
required on every record. Do not call this function with untrusted clients'
workspace IDs as an authorization substitute.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Sequence

from nexus_ai.data_analytics import AnalyticsInputError, _amount
from nexus_ai.financial_analytics import analyze_financial_series


@dataclass(frozen=True)
class ReviewedFinancialObservation:
    workspace_id: str
    document_id: str
    document_version_id: str
    source_sha256: str
    source_path: str
    page_number: int
    chunk_id: str
    start_char: int
    end_char: int
    company: str
    year: int
    metric: str
    amount: str
    currency: str
    unit: str
    reviewer_asserted_row: bool


def _number_pattern(value: str) -> re.Pattern[str]:
    """Match exact number allowing Arabic digits and optional 3-digit grouping."""
    amount = _amount(value)
    if value.strip() != format(amount, "f"):
        raise AnalyticsInputError("amount must be canonical ASCII decimal")
    # For source presence, normalized decimal digits (including Arabic-Indic)
    # are compared without grouping separators; no arithmetic inferred.
    digits = re.escape(value)
    return re.compile(r"(?<![0-9])" + digits + r"(?![0-9])")


def _normalized_numerals(value: str) -> str:
    return value.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789"))


def _evidence_contains_amount(text: str, amount: str) -> bool:
    normalized = _normalized_numerals(text)
    # A textual number can be grouped with English comma, Arabic thousands
    # separator, narrow space, or plain digits. Decimal point is preserved.
    stripped = re.sub(r"(?<=\d)[,٬\u202f ](?=\d{3}(?:\D|$))", "", normalized)
    return bool(_number_pattern(amount).search(stripped))


def analyze_reviewed_evidence(
    observations: Sequence[ReviewedFinancialObservation],
    *,
    repository,
    workspace_id: str,
    company: str,
    metric: str,
    currency: str,
    unit: str,
    start_year: int,
    end_year: int,
) -> dict[str, object]:
    """Validate all observations before deriving a deduplicated annual series.

    Same financial cell supported by several source pages counts only once.
    Inconsistent values for the same company/year/metric/currency/unit are
    blocked rather than summed or silently chosen. This is appropriate for
    single *total financial metrics*, not additive ledger line items.
    """
    if not isinstance(observations, (tuple, list)) or not 1 <= len(observations) <= 500:
        raise AnalyticsInputError("between 1 and 500 reviewed observations required")
    if not isinstance(workspace_id, str) or not workspace_id.strip() or len(workspace_id) > 128:
        raise AnalyticsInputError("trusted workspace scope required")
    selected = {}
    sources = {}
    used_documents = {}
    for item in observations:
        if not isinstance(item, ReviewedFinancialObservation) or item.reviewer_asserted_row is not True:
            raise AnalyticsInputError("every observation must have an explicit row review")
        if item.workspace_id != workspace_id:
            raise AnalyticsInputError("cross-workspace citation")
        if type(item.page_number) is not int or type(item.start_char) is not int or type(item.end_char) is not int:
            raise AnalyticsInputError("invalid citation coordinates")
        if item.page_number < 1 or item.start_char < 0 or item.end_char <= item.start_char:
            raise AnalyticsInputError("invalid citation offset range")
        indexed = repository.get_active(workspace_id, item.document_id)
        if indexed is None:
            raise AnalyticsInputError("missing active indexed document")
        doc = indexed.document
        if (doc.document_id != item.document_id or doc.workspace_id != workspace_id
                or doc.version_id != item.document_version_id or doc.content_sha256 != item.source_sha256
                or doc.source_path != item.source_path):
            raise AnalyticsInputError("stale or mismatched document identity")
        page = next((p for p in doc.pages if p.page_number == item.page_number), None)
        chunk = next((c for c in indexed.chunks if c.chunk_id == item.chunk_id), None)
        if page is None or chunk is None or not chunk.offsets_reliable:
            raise AnalyticsInputError("missing or unreliable citation")
        if (chunk.page_number != item.page_number
                or chunk.document_id != item.document_id
                or chunk.version_id != item.document_version_id
                or chunk.source_sha256 != item.source_sha256
                or chunk.source_path != item.source_path
                or chunk.start_char != item.start_char or chunk.end_char != item.end_char
                or page.text[item.start_char:item.end_char] != chunk.text):
            raise AnalyticsInputError("citation offsets or source text do not match")
        if not _evidence_contains_amount(chunk.text, item.amount):
            raise AnalyticsInputError("cited source span does not contain exact stated amount")
        amount = _amount(item.amount)
        if not (isinstance(item.company, str) and item.company.strip() and len(item.company) <= 160):
            raise AnalyticsInputError("invalid company")
        if not all(isinstance(x, str) for x in (item.metric, item.currency, item.unit)):
            raise AnalyticsInputError("invalid metric or unit")
        if type(item.year) is not int or not 1900 <= item.year <= 2100:
            raise AnalyticsInputError("invalid year")
        if item.company != company or item.metric != metric or item.year < start_year or item.year > end_year:
            # Validated nonselected evidence is not included in the result.
            continue
        if item.currency != currency or item.unit != unit:
            raise AnalyticsInputError("mixed currency or unit in reviewed series")
        key = (item.company, item.year, item.metric, item.currency, item.unit)
        if key in selected and selected[key] != amount:
            raise AnalyticsInputError("conflicting reviewed financial values for the same year")
        selected[key] = amount
        provenance = (item.document_id, item.document_version_id, item.source_sha256,
                      item.source_path, item.page_number, item.chunk_id,
                      item.start_char, item.end_char)
        sources.setdefault(key, set()).add(provenance)
        used_documents[item.document_id] = (item.document_version_id, item.source_sha256, item.source_path)
    if not selected:
        raise AnalyticsInputError("no matching reviewed financial observations")
    # Recheck source generation identity after all reads, disallowing a
    # concurrent source replacement from entering the summary.
    for document_id, (version_id, digest, path) in used_documents.items():
        current = repository.get_active(workspace_id, document_id)
        if (current is None or current.document.version_id != version_id
                or current.document.content_sha256 != digest
                or current.document.source_path != path):
            raise AnalyticsInputError("source version changed during analysis")
    out = io.StringIO(newline="")
    writer = csv.writer(out)
    writer.writerow(("Company", "Year", "Metric", "Value", "Currency", "Unit"))
    for key in sorted(selected):
        co, year, me, cu, un = key
        writer.writerow((co, year, me, format(selected[key], "f"), cu, un))
    result = analyze_financial_series(
        out.getvalue().encode("utf-8"), file_type="csv", company=company,
        metric=metric, currency=currency, unit=unit,
        start_year=start_year, end_year=end_year,
    )
    result["provenance"] = [
        {"year": key[1], "amount": format(selected[key], "f"),
         "citations": [
             {"document_id": p[0], "version_id": p[1], "source_sha256": p[2],
              "source_path": p[3], "page_number": p[4], "chunk_id": p[5],
              "start_char": p[6], "end_char": p[7]}
             for p in sorted(sources[key])
         ]}
        for key in sorted(selected)
    ]
    result["reviewed_observation_count"] = len(observations)
    result["unique_financial_facts"] = len(selected)
    result["provenance_policy"] = (
        "Source identity, chunk offsets and exact numeric token checked; "
        "company/metric/year/currency/unit relationships remain human-reviewed assertions"
    )
    return result
