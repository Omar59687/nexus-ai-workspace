"""Privacy-preserving page and chunk diagnostics for owner-labeled financial evidence.

This tests text co-occurrence only. It does NOT establish whether a number
belongs to the correct table row, metric, reporting period or currency.
"""
from __future__ import annotations

import unicodedata
from collections.abc import Sequence

from nexus_ai.documents.types import ExtractedPage, SourceChunk

_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_ARABIC_ALEF = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا"})
_ARABIC_DIACRITICS = frozenset((
    *range(0x0610, 0x061B),
    *range(0x064B, 0x0660),
    0x0670,
    *range(0x06D6, 0x06EE),
))


def normalize_anchor(value: str) -> str:
    """Normalize Arabic display variants for diagnostics, not fact extraction.

    Strip tatweel and Arabic vowel marks and fold alef-hamza variants;
    preserve amounts, punctuation, word order, currencies and source text.
    """
    value = unicodedata.normalize("NFKC", value).translate(_DIGITS)
    value = "".join(ch for ch in value if ch != "ـ" and ord(ch) not in _ARABIC_DIACRITICS)
    return " ".join(value.translate(_ARABIC_ALEF).casefold().split())


def inspect_page_anchors(
    *,
    pages: Sequence[ExtractedPage],
    chunks: Sequence[SourceChunk],
    page_number: int,
    anchors: Sequence[str],
    line_radius: int = 2,
) -> dict[str, object]:
    """Return source-line and chunk diagnostics without raw text or anchor values."""
    if type(page_number) is not int or page_number < 1:
        raise ValueError("page_number must be positive")
    if (isinstance(anchors, (str, bytes)) or not 2 <= len(anchors) <= 8
            or any(not isinstance(a, str) or not a.strip() or len(a) > 80 for a in anchors)):
        raise ValueError("provide 2-8 bounded anchors")
    if type(line_radius) is not int or not 0 <= line_radius <= 5:
        raise ValueError("line_radius must be between 0 and 5")
    normalized = [normalize_anchor(a) for a in anchors]
    if len(set(normalized)) != len(normalized):
        raise ValueError("anchors must differ after normalization")

    page = next((row for row in pages if row.page_number == page_number), None)
    if page is None:
        raise ValueError("requested page is absent")
    lines = page.text.splitlines()
    positions = [
        [i + 1 for i, line in enumerate(lines) if needle in normalize_anchor(line)]
        for needle in normalized
    ]
    candidates = [row for row in chunks if row.page_number == page_number]
    # Chunk texts must come from the same page/source offset where reliable.
    for row in candidates:
        if row.offsets_reliable and (
            row.start_char is None or row.end_char is None
            or page.text[row.start_char:row.end_char] != row.text
        ):
            raise ValueError("chunk source offsets do not match extracted page")
    chunk_hits = [
        [i + 1 for i, row in enumerate(candidates) if needle in normalize_anchor(row.text)]
        for needle in normalized
    ]
    common_chunks = sorted(set.intersection(*(set(items) for items in chunk_hits)))
    common_line_windows: list[tuple[int, int]] = []
    if all(positions):
        for start in range(len(lines)):
            end = min(len(lines), start + 2 * line_radius + 1)
            if all(any(start <= line_number - 1 < end for line_number in hits) for hits in positions):
                common_line_windows.append((start + 1, end))
                if len(common_line_windows) >= 20:
                    break

    return {
        "page_number": page_number,
        "anchor_count": len(anchors),
        "line_radius": line_radius,
        "line_count": len(lines),
        "chunk_count": len(candidates),
        "anchors": [
            {
                "anchor_index": index + 1,
                "found_on_page": bool(positions[index]),
                "line_numbers": positions[index][:30],
                "line_hits_truncated": len(positions[index]) > 30,
                "chunk_ordinals": chunk_hits[index][:30],
                "chunk_hits_truncated": len(chunk_hits[index]) > 30,
            } for index in range(len(anchors))
        ],
        "all_anchors_present_on_page": all(positions),
        "all_anchors_share_chunk": bool(common_chunks),
        "shared_chunk_ordinals": common_chunks[:30],
        "all_anchors_within_line_window": bool(common_line_windows),
        "matching_line_windows": [
            {"start_line": start, "end_line": end}
            for start, end in common_line_windows[:10]
        ],
        "interpretation": (
            "Anchor co-occurrence is diagnostic only; not a verified financial-table fact."
        ),
    }
