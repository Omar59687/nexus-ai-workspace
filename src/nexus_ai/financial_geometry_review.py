"""A bounded, explicitly unreviewed geometry and citation inventory.

The PDF geometry worker provides document-digest-bound coordinates, but
its Arabic words may not exist in the separate plain-text index. Numeric
entries are independently backed by an active indexed source chunk.
These two evidence classes are deliberately kept in separate arrays.
No cross-class association, metric attribution or reviewed observation
is inferred. A human can use the inventory to navigate to a source page.
"""
from __future__ import annotations

from nexus_ai.data_analytics import AnalyticsInputError
from nexus_ai.financial_arabic_signals import normalize_arabic
from nexus_ai.financial_evidence_analytics import _evidence_contains_amount
from nexus_ai.financial_pdf_layout_diagnostics import _match_layout_phrase
from nexus_ai.financial_positioned_tables import PositionedText, _coordinate
from nexus_ai.financial_table_candidates import _parse_amount


def build_financial_review_inventory(
    boxes: tuple[PositionedText, ...], *,
    repository, workspace_id: str, document_id: str, page_number: int,
    max_numeric: int = 120, max_label_bands: int = 40,
) -> dict[str, object]:
    """Retrieve verified numbers and separately untrusted spatial label hints.

    Never return this as a machine-approved financial table. Source generation
    is checked before and after processing; callers must separately authorize
    the tenant and ensure PDF geometry was generated from this very digest.
    """
    if (not isinstance(boxes, tuple) or len(boxes) > 3000
            or type(page_number) is not int or not 1 <= page_number <= 500
            or type(max_numeric) is not int or not 1 <= max_numeric <= 120
            or type(max_label_bands) is not int or not 1 <= max_label_bands <= 40):
        raise AnalyticsInputError("invalid review inventory budget")
    indexed = repository.get_active(workspace_id, document_id)
    if (indexed is None or indexed.document.workspace_id != workspace_id
            or indexed.document.document_id != document_id):
        raise AnalyticsInputError("source not active in authorized scope")
    doc = indexed.document
    page = next((p for p in doc.pages if p.page_number == page_number), None)
    if page is None:
        raise AnalyticsInputError("page missing from indexed document")
    validated = []
    for box in boxes:
        if not isinstance(box, PositionedText) or box.page_number != page_number:
            raise AnalyticsInputError("geometry page mismatch")
        x, y = _coordinate(box.x), _coordinate(box.y)
        if not isinstance(box.text, str) or not box.text.strip() or len(box.text) > 400:
            raise AnalyticsInputError("invalid positioned text")
        validated.append((x, y, box.text.strip()))

    source_chunks = []
    for c in indexed.chunks:
        if c.page_number != page_number:
            continue
        if (c.document_id != doc.document_id or c.version_id != doc.version_id
                or c.source_path != doc.source_path or c.source_sha256 != doc.content_sha256):
            raise AnalyticsInputError("indexed chunk provenance mismatch")
        if (c.offsets_reliable and c.start_char is not None and c.end_char is not None
                and page.text[c.start_char:c.end_char] == c.text):
            source_chunks.append(c)

    numeric = []
    seen_numeric = set()
    numeric_without_citation = 0
    for x, y, text in validated:
        value = _parse_amount(text)
        # Ignore short numbers and years in this *inventory*; not a
        # completeness guarantee for small financial cells.
        if value is None or len(value.lstrip("-").split(".")[0]) < 5:
            continue
        evidence = next((c for c in source_chunks if _evidence_contains_amount(c.text, value)), None)
        if evidence is None:
            numeric_without_citation += 1
            continue
        identity = (x, y, value, evidence.chunk_id)
        if identity in seen_numeric:
            continue
        seen_numeric.add(identity)
        if len(numeric) >= max_numeric:
            raise AnalyticsInputError("numeric inventory limit exceeded")
        numeric.append({
            "value": value, "x": x, "y": y,
            "citation": {
                "workspace_id": workspace_id, "document_id": document_id,
                "version_id": doc.version_id, "source_sha256": doc.content_sha256,
                "source_path": doc.source_path, "page_number": page_number,
                "chunk_id": evidence.chunk_id, "start_char": evidence.start_char,
                "end_char": evidence.end_char,
            },
            "status": "SOURCE_NUMERIC_TOKEN_ONLY",
        })

    # The heading geometry here is PDF digest-bound, NOT proven by the
    # plain-text indexed chunk. Keep it entirely separate from numeric.
    bands: dict[int, list[tuple[float, str]]] = {}
    for x, y, text in validated:
        bands.setdefault(int(round(y / 3)), []).append((x, text))
    label_bands = []
    for band, parts in sorted(bands.items()):
        if len(parts) > 100:
            continue
        asc = " ".join(text for _, text in sorted(parts))
        desc = " ".join(text for _, text in sorted(parts, reverse=True))
        a = _match_layout_phrase(normalize_arabic(asc))
        b = _match_layout_phrase(normalize_arabic(desc))
        if not (any(a) or any(b)):
            continue
        if len(label_bands) >= max_label_bands:
            raise AnalyticsInputError("geometry heading inventory limit exceeded")
        label_bands.append({
            "approx_y": round(sum(int(round(band * 3)) for _ in parts) / len(parts), 1),
            "revenue_hint": bool(a[0] or b[0]),
            "currency_unit_hint": bool(a[1] or b[1]),
            "reading_order_ambiguous": a != b or (len(parts) > 1 and asc != desc),
            "status": "DIGEST_BOUND_GEOMETRY_HINT_NOT_INDEX_CITATION",
        })
    after = repository.get_active(workspace_id, document_id)
    if (after is None or after.document.version_id != doc.version_id
            or after.document.content_sha256 != doc.content_sha256
            or after.document.source_path != doc.source_path
            or after.document.workspace_id != workspace_id):
        raise AnalyticsInputError("source changed during review inventory")
    return {
        "status": "REVIEW_INVENTORY_NOT_FINANCIAL_FACTS",
        "page_number": page_number,
        "numeric_citation_count": len(numeric),
        "uncited_numeric_fragments_skipped": numeric_without_citation,
        "geometry_label_band_count": len(label_bands),
        "numeric_citations": numeric,
        "geometry_label_bands": label_bands,
        "cross_evidence_associations": 0,
        "automatically_verified_financial_facts": 0,
        "requires_explicit_human_review": True,
    }
