"""Bounded *diagnostic-only* layout signals from PDF worker geometry.

Fragments can be missed by extract_text() and remain unanchored to the
ordinary BM25 index. Their only independent provenance is the PDF digest
verified by extract_pdf_positions. Nothing in this module is a citation,
a ReviewedFinancialObservation, or a financial-row assertion.

This module groups fragments in narrow Y bands, tests both RTL and LTR
reading orders for split Arabic labels, and reports counts and orientation
ambiguity without returning text or numeric values.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from nexus_ai.data_analytics import AnalyticsInputError
from nexus_ai.financial_arabic_signals import financial_signal_counts, normalize_arabic
from nexus_ai.financial_positioned_tables import PositionedText


@dataclass(frozen=True)
class _Fragment:
    x: float
    y: float
    text: str


def _match_layout_phrase(normalized_line: str) -> tuple[bool, bool]:
    # Only explicitly written complete metric / unit phrases are signals.
    # These flags are NOT accounting assertions or reconstructed cells.
    text = " ".join(normalized_line.split())
    revenue = any(phrase in text for phrase in (
        "اجمالي الايرادات", "مجموع الايرادات", "total revenue",
        "الايرادات", "revenue",
    ))
    # A unit needs both an explicit magnitude and a SAR/riyals component.
    cues = financial_signal_counts(text)
    scale = bool(cues["thousand_word"] or cues["million_word"])
    sar = bool(cues["saudi_riyals"])
    return revenue, scale and sar


def inspect_pdf_layout_signals(
    boxes: tuple[PositionedText, ...],
    *,
    page_number: int,
    band_tolerance: float = 3.0,
    max_fragments: int = 3000,
) -> dict[str, object]:
    """Return bounded aggregate text-layout *signals*, never candidate rows.

    Each fragment is already page/hash-bound by the bounded PDF worker.
    This call does not claim that text exists in the indexed plain-text
    representation or that the worker geometry describes a visible table.
    """
    if not isinstance(boxes, tuple) or not 0 <= len(boxes) <= max_fragments:
        raise AnalyticsInputError("invalid PDF geometry inventory")
    if type(max_fragments) is not int or not 1 <= max_fragments <= 3000:
        raise AnalyticsInputError("invalid PDF geometry budget")
    if type(page_number) is not int or not 1 <= page_number <= 500:
        raise AnalyticsInputError("invalid page identity")
    if (type(band_tolerance) not in (int, float)
            or not math.isfinite(band_tolerance)
            or not 1 <= band_tolerance <= 8):
        raise AnalyticsInputError("invalid Y band tolerance")
    fragments: list[_Fragment] = []
    for box in boxes:
        if not isinstance(box, PositionedText) or box.page_number != page_number:
            raise AnalyticsInputError("PDF geometry page mismatch")
        if (type(box.x) not in (float, int) or type(box.y) not in (float, int)
                or not math.isfinite(box.x) or not math.isfinite(box.y)
                or not 0 <= box.x <= 5000 or not 0 <= box.y <= 5000
                or not isinstance(box.text, str) or not 0 < len(box.text) <= 400):
            raise AnalyticsInputError("invalid PDF geometry fragment")
        fragments.append(_Fragment(float(box.x), float(box.y), box.text.strip()))
    # Quantizing positions limits the amount of grouping work. Each
    # fragment is assigned exactly once; grouping is O(n log n).
    lines: dict[int, list[_Fragment]] = {}
    for fragment in fragments:
        band = int(round(fragment.y / band_tolerance))
        lines.setdefault(band, []).append(fragment)
    full_revenue = 0
    full_unit = 0
    joined_revenue = 0
    joined_unit = 0
    ambiguous_orders = 0
    for fragment_line in lines.values():
        if len(fragment_line) > 100:
            # Excessively busy lines are not trustworthy for reconstruction.
            ambiguous_orders += 1
            continue
        # Source-preserving fragment order is not guaranteed by pypdf.
        # Run LTR and RTL, recording uncertainty when only one order matches.
        asc = sorted(fragment_line, key=lambda part: part.x)
        desc = list(reversed(asc))
        direct = [_match_layout_phrase(normalize_arabic(part.text)) for part in fragment_line]
        full_revenue += int(any(pair[0] for pair in direct))
        full_unit += int(any(pair[1] for pair in direct))
        left_flags = _match_layout_phrase(normalize_arabic(" ".join(x.text for x in asc)))
        right_flags = _match_layout_phrase(normalize_arabic(" ".join(x.text for x in desc)))
        joined_revenue += int(left_flags[0] or right_flags[0])
        joined_unit += int(left_flags[1] or right_flags[1])
        # Flag different text orders even if both happen to contain a
        # diagnostic keyword; this prevents overstating RTL certainty.
        ambiguous_orders += int(
            left_flags != right_flags or (
                len(fragment_line) > 1
                and normalize_arabic(" ".join(x.text for x in asc))
                    != normalize_arabic(" ".join(x.text for x in desc))
                and (any(left_flags) or any(right_flags))
            )
        )
    return {
        "status": "GEOMETRY_LEXICAL_DIAGNOSTIC_ONLY",
        "page_number": page_number,
        "fragments": len(fragments),
        "horizontal_bands": len(lines),
        "single_fragment_revenue_bands": full_revenue,
        "single_fragment_currency_unit_bands": full_unit,
        "joined_fragment_revenue_bands": joined_revenue,
        "joined_fragment_currency_unit_bands": joined_unit,
        "reading_order_disagreements": ambiguous_orders,
        "source_binding": "PDF_DIGEST_ONLY_NOT_INDEX_TEXT_CITATION",
        "candidate_count": 0,
        "automatically_verified_financial_facts": 0,
    }
