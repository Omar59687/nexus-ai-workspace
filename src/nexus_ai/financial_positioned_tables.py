"""Conservative position-aware PDF financial-table candidate reconstruction.

An upstream bounded PDF worker must supply page-local text boxes with pixel/
point coordinates. This module does not open PDFs or execute parsers. The
original active index remains the only source of text citation authority.

It emits review-only candidates when a single year header spatially aligns
with exactly one numeric cell on a uniquely labeled row; ambiguous columns,
repeated labels, mismatched source chunks, or missing unit labels abstain.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass

from nexus_ai.data_analytics import AnalyticsInputError
from nexus_ai.financial_evidence_analytics import _evidence_contains_amount
from nexus_ai.financial_table_candidates import _LABELS, _UNITS, _parse_amount, _latin_digits, _YEAR


@dataclass(frozen=True)
class PositionedText:
    page_number: int
    x: float
    y: float
    text: str


def _coordinate(value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AnalyticsInputError("invalid positioned-text coordinate")
    result = float(value)
    if not math.isfinite(result) or not 0 <= result <= 5000:
        raise AnalyticsInputError("out-of-bounds positioned-text coordinate")
    return result


def reconstruct_financial_rows(
    boxes: tuple[PositionedText, ...],
    *,
    repository,
    workspace_id: str,
    document_id: str,
    page_number: int,
    max_boxes: int = 3000,
    tolerance: float = 5.0,
) -> dict[str, object]:
    """Find year/amount/metric alignments; return candidates, never facts.

    A header row is exactly one explicit year marker per column and exactly
    one explicit unit token anywhere above the candidate financial row.
    Number, label and header boxes must be independently anchored to
    extracted page text; this avoids trusting caller-invented geometry text.
    """
    if not isinstance(boxes, tuple) or len(boxes) > max_boxes or not 1 <= len(boxes):
        raise AnalyticsInputError("invalid positioned-text box inventory")
    if type(page_number) is not int or not 1 <= page_number <= 500:
        raise AnalyticsInputError("invalid page number")
    if type(max_boxes) is not int or not 1 <= max_boxes <= 3000:
        raise AnalyticsInputError("invalid box limit")
    if not isinstance(tolerance, (float, int)) or isinstance(tolerance, bool) or not 1 <= tolerance <= 10:
        raise AnalyticsInputError("invalid row tolerance")
    indexed = repository.get_active(workspace_id, document_id)
    if (indexed is None or indexed.document.workspace_id != workspace_id
            or indexed.document.document_id != document_id):
        raise AnalyticsInputError("active indexed source missing")
    doc = indexed.document
    page = next((p for p in doc.pages if p.page_number == page_number), None)
    if page is None:
        raise AnalyticsInputError("selected source page not indexed")
    canonical = []
    for box in boxes:
        if not isinstance(box, PositionedText) or box.page_number != page_number:
            raise AnalyticsInputError("positioned-text page identity mismatch")
        x, y = _coordinate(box.x), _coordinate(box.y)
        if not isinstance(box.text, str) or not box.text.strip() or len(box.text) > 400:
            raise AnalyticsInputError("invalid positioned-text content")
        if box.text not in page.text:
            raise AnalyticsInputError("positioned text not present in indexed source page")
        canonical.append((x, y, box.text.strip()))
    units = []
    headers = []
    for x, y, value in canonical:
        matches = [unit for term, unit in _UNITS.items() if term.casefold() in value.casefold()]
        if matches:
            units.append((y, *matches[0]))
        years = _YEAR.findall(_latin_digits(value))
        if len(years) == 1 and (value.strip() == years[0] or
                                value.casefold().strip() == ("year: " + years[0])):
            headers.append((x, y, int(years[0])))
    candidates = []
    abstentions = {"no_unambiguous_header": 0, "no_unambiguous_row": 0,
                   "missing_exact_source_chunk": 0}
    all_chunks = [c for c in indexed.chunks if c.page_number == page_number]
    for lx, ly, label in canonical:
        metrics = [metric for metric, forms in _LABELS.items()
                   if label.casefold() in {f.casefold() for f in forms}]
        if len(metrics) != 1:
            continue
        numbers = [(x, y, raw, _parse_amount(raw)) for x, y, raw in canonical
                   if abs(y - ly) <= float(tolerance) and x != lx]
        numbers = [(x, y, raw, number) for x, y, raw, number in numbers if number is not None]
        if not numbers:
            abstentions["no_unambiguous_row"] += 1
            continue
        for nx, ny, raw, number in numbers:
            # Exactly one near-column year, and exactly one unit above row.
            years = [(hx, hy, yr) for hx, hy, yr in headers
                     if hy < ly and abs(hx - nx) <= 12]
            unit_matches = {(currency, unit) for uy, currency, unit in units if uy < ly}
            if len(years) != 1 or len(unit_matches) != 1:
                abstentions["no_unambiguous_header"] += 1
                continue
            if sum(1 for x, y, t in canonical if abs(y - ly) <= float(tolerance)
                   and t.casefold() == label.casefold()) != 1:
                abstentions["no_unambiguous_row"] += 1
                continue
            # Require one and only one row number under this header. Prevent
            # accidental choice among two visually overlapping numeric cells.
            competing = [(x, y, val) for x, y, _, val in numbers
                         if abs(x - nx) <= 12]
            if len(competing) != 1:
                abstentions["no_unambiguous_row"] += 1
                continue
            evidence = [
                c for c in all_chunks
                if c.offsets_reliable and c.start_char is not None
                and c.end_char is not None and
                page.text[c.start_char:c.end_char] == c.text and
                c.document_id == document_id and c.version_id == doc.version_id
                and c.source_sha256 == doc.content_sha256 and
                c.source_path == doc.source_path and
                _evidence_contains_amount(c.text, number)
            ]
            if not evidence:
                abstentions["missing_exact_source_chunk"] += 1
                continue
            source = evidence[0]
            candidates.append({
                "workspace_id": workspace_id, "document_id": document_id,
                "version_id": doc.version_id, "source_sha256": doc.content_sha256,
                "source_path": doc.source_path, "page_number": page_number,
                "chunk_id": source.chunk_id, "start_char": source.start_char,
                "end_char": source.end_char,
                "year": years[0][2], "metric": metrics[0], "amount": number,
                "currency": next(iter(unit_matches))[0],
                "unit": next(iter(unit_matches))[1],
                "position": {"amount_x": nx, "row_y": ny},
                "status": "HUMAN_ROW_REVIEW_REQUIRED",
            })
    # A repeated same-year/metric candidate with divergent amount means
    # table geometry is not reliable. Do not silently pick one.
    fact_keys = {}
    for candidate in candidates:
        key = (candidate["metric"], candidate["year"], candidate["currency"], candidate["unit"])
        if key in fact_keys and fact_keys[key] != candidate["amount"]:
            abstentions["no_unambiguous_row"] += 1
            candidates = []
            break
        fact_keys[key] = candidate["amount"]
    after = repository.get_active(workspace_id, document_id)
    if (after is None or after.document.version_id != doc.version_id
            or after.document.content_sha256 != doc.content_sha256
            or after.document.source_path != doc.source_path):
        raise AnalyticsInputError("indexed source changed during table reconstruction")
    return {
        "status": "CANDIDATES_FOR_REVIEW" if candidates else "ABSTAIN_POSITIONAL_AMBIGUITY",
        "candidate_count": len(candidates), "candidates": candidates,
        "abstentions": abstentions, "automatically_verified_financial_facts": 0,
        "geometry_source": "caller_supplied_requires_independent_approved_pdf_worker",
    }
