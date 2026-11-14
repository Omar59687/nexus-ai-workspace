"""Conservative Arabic financial-table text diagnostics.

These are *lexical signals*, not table-row classification. pypdf may break,
reorder or reverse Arabic glyphs. We therefore report separately whether the
complete extracted page contains known metric/unit tokens and whether the
positioned fragments contain those tokens. No inferred metric, year, unit,
source citation or financial fact is returned by this module.
"""
from __future__ import annotations

import re
import unicodedata

from nexus_ai.data_analytics import AnalyticsInputError


def normalize_arabic(text: str) -> str:
    """Normalize only orthographic glyph variants, never infer word order."""
    if not isinstance(text, str):
        raise AnalyticsInputError("invalid Arabic diagnostic input")
    normalized = unicodedata.normalize("NFKC", text)
    normalized = "".join(
        c for c in normalized
        if not (unicodedata.category(c) in ("Mn", "Cf") or c == "\u0640")
    )
    normalized = normalized.translate(str.maketrans({
        "أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ى": "ي",
        "٠": "0", "١": "1", "٢": "2", "٣": "3", "٤": "4",
        "٥": "5", "٦": "6", "٧": "7", "٨": "8", "٩": "9",
        "۰": "0", "۱": "1", "۲": "2", "۳": "3", "۴": "4",
        "۵": "5", "۶": "6", "۷": "7", "۸": "8", "۹": "9",
    }))
    return re.sub(r"\s+", " ", normalized).strip().casefold()


# No unit may be inferred from a single isolated currency word. Explicit
# unit hints are *diagnostic only*, not trustworthy currency/unit declarations.
_PATTERNS = {
    "revenue_word": re.compile(r"(?:الايرادات|ايرادات|الايراد|ايراد|revenue)", re.I),
    "total_word": re.compile(r"(?:اجمالي|مجموع|total)", re.I),
    "thousand_word": re.compile(r"(?:بالالاف|الاف|الالف|الف|thousand)", re.I),
    "million_word": re.compile(r"(?:بالملايين|ملايين|مليون|million)", re.I),
    "saudi_riyals": re.compile(r"(?:ريال|ريالات|sar|saudi\s+riyal)", re.I),
}


def financial_signal_counts(text: str) -> dict[str, int]:
    """Return bounded counts, not raw sensitive content or guessed facts."""
    normalized = normalize_arabic(text)
    return {name: min(len(pattern.findall(normalized)), 1000)
            for name, pattern in _PATTERNS.items()}


def financial_signal_diagnostics(
    page_text: str, anchored_fragments: tuple[str, ...],
) -> dict[str, object]:
    if not isinstance(anchored_fragments, tuple) or len(anchored_fragments) > 3000:
        raise AnalyticsInputError("invalid anchored fragment inventory")
    if len(page_text) > 2_000_000:
        raise AnalyticsInputError("page text exceeds safe bounds")
    if any(not isinstance(fragment, str) or len(fragment) > 400
           for fragment in anchored_fragments):
        raise AnalyticsInputError("invalid anchored fragment text")
    return {
        "page_text_lexical_hints": financial_signal_counts(page_text),
        "positioned_fragment_lexical_hints": financial_signal_counts(
            " ".join(anchored_fragments)
        ),
        "interpretation": "DIAGNOSTIC_ONLY_NO_ROW_OR_UNIT_INFERENCE",
    }
