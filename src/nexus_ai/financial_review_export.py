"""Deterministic, bounded CSV export of approved financial review analytics.

Never accept raw spreadsheet cells from the client: the trusted review
ledger produces the series and provenance after revalidating source identity.
All text cells are escaped against spreadsheet formula interpretation.
"""
from __future__ import annotations

import csv
import io
import re
from fastapi import Response
from nexus_ai.data_analytics import AnalyticsInputError, _amount

MAX_EXPORT_ROWS = 201
MAX_EXPORT_CITATIONS = 500
MAX_EXPORT_BYTES = 256 * 1024
_CANONICAL_DECIMAL = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?\Z")


def _checked_decimal(value: object, field: str) -> str:
    if (not isinstance(value, str) or len(value) > 40
            or _CANONICAL_DECIMAL.fullmatch(value) is None):
        raise AnalyticsInputError(f"invalid {field}")
    _amount(value)  # Enforce the existing exact precision/range contract.
    return value


def _safe_text(value: object) -> str:
    if not isinstance(value, str) or len(value) > 2048 or any(
        ch in value for ch in "\x00\r\n"
    ):
        raise AnalyticsInputError("invalid reviewed export field")
    if value.lstrip(" \t\ufeff").startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def render_reviewed_financial_csv(analysis: dict[str, object]) -> Response:
    if not isinstance(analysis, dict):
        raise AnalyticsInputError("invalid reviewed export")
    annual = analysis.get("annual")
    provenance = analysis.get("provenance")
    if (not isinstance(annual, list) or not 1 <= len(annual) <= MAX_EXPORT_ROWS
            or not isinstance(provenance, list) or len(provenance) != len(annual)):
        raise AnalyticsInputError("invalid reviewed export rows")
    dimensions = [
        _safe_text(analysis.get(key))
        for key in ("company", "metric", "currency", "unit")
    ]
    out = io.StringIO(newline="")
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow(("company", "metric", "currency", "unit", "year",
                     "amount_decimal", "yoy_percent", "yoy_unavailable_reason",
                     "citation_document_ids", "citation_pages"))
    count = 0
    for row in annual:
        if not isinstance(row, dict):
            raise AnalyticsInputError("invalid reviewed export row")
        year = row.get("year")
        amount = row.get("amount")
        if type(year) is not int or not 1900 <= year <= 2100:
            raise AnalyticsInputError("invalid reviewed year")
        amount = _checked_decimal(amount, "reviewed amount")
        matches = [p for p in provenance if isinstance(p, dict)
                   and p.get("year") == year and p.get("amount") == amount]
        if len(matches) != 1:
            raise AnalyticsInputError("reviewed provenance missing or conflicting")
        citations = matches[0].get("citations")
        if not isinstance(citations, list) or not citations:
            raise AnalyticsInputError("missing cited source")
        count += len(citations)
        if count > MAX_EXPORT_CITATIONS:
            raise AnalyticsInputError("reviewed export provenance budget exceeded")
        docs, pages = [], []
        for citation in citations:
            if not isinstance(citation, dict):
                raise AnalyticsInputError("invalid export citation")
            doc_id = _safe_text(citation.get("document_id"))
            page = citation.get("page_number")
            if type(page) is not int or not 1 <= page <= 500:
                raise AnalyticsInputError("invalid citation page")
            docs.append(doc_id)
            pages.append(str(page))
        yoy = row.get("yoy_percent")
        reason = row.get("yoy_unavailable_reason")
        if yoy is not None:
            yoy = _checked_decimal(yoy, "year-over-year result")
        writer.writerow([*dimensions, year, amount, yoy or "",
                         _safe_text(reason) if reason is not None else "",
                         "; ".join(docs), "; ".join(pages)])
    raw = out.getvalue().encode("utf-8-sig")
    if len(raw) > MAX_EXPORT_BYTES:
        raise AnalyticsInputError("reviewed export byte budget exceeded")
    return Response(
        content=raw, media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="reviewed-financial-analysis.csv"',
            "Cache-Control": "private, no-store",
            "Pragma": "no-cache",
            "X-Content-Type-Options": "nosniff",
        },
    )
