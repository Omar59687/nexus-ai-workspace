"""Bounded, in-memory, explicitly human-approved financial review workflow.

This is a library-level integration slice, not an authenticated HTTP
endpoint or persistent approval system. The caller MUST authenticate and
authorize reviewer_id/workspace_id outside this module. Merely passing
reviewer_id is not authentication.

Geometry hints are never promoted into financial facts. A human reviewer
must explicitly select each independently source-cited numeric candidate,
declare the accounting row/year/unit, and attest to inspecting the
original document. Active-source identity and exact numeric citation are
rechecked on approval AND on analysis. Review approval is volatile and
becomes invalid if the indexed source version changes.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from threading import RLock

from nexus_ai.data_analytics import AnalyticsInputError, _amount
from nexus_ai.financial_analytics import _CURRENCIES, _METRICS, _UNITS
from nexus_ai.financial_evidence_analytics import (
    ReviewedFinancialObservation, _evidence_contains_amount,
    analyze_reviewed_evidence,
)


@dataclass(frozen=True)
class ReviewSelection:
    """A single reviewer-selected numeric citation, not an extracted row."""
    citation: dict[str, object]
    value: str


@dataclass(frozen=True)
class ReviewDecision:
    reviewer_id: str
    company: str
    year: int
    metric: str
    currency: str
    unit: str
    source_page_visually_checked: bool
    metric_year_unit_visually_confirmed: bool


def _require_text(value: object, field: str, max_length: int = 160) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > max_length:
        raise AnalyticsInputError(f"invalid {field}")
    return value.strip()


def _verify_source(
    selection: ReviewSelection, *, repository, workspace_id: str,
) -> ReviewedFinancialObservation:
    citation = selection.citation
    if not isinstance(citation, dict) or set(citation) != {
        "workspace_id", "document_id", "version_id", "source_sha256",
        "source_path", "page_number", "chunk_id", "start_char", "end_char",
    }:
        raise AnalyticsInputError("invalid numeric citation contract")
    if citation["workspace_id"] != workspace_id:
        raise AnalyticsInputError("cross-workspace review selection")
    doc_id = _require_text(citation["document_id"], "document id")
    indexed = repository.get_active(workspace_id, doc_id)
    if indexed is None:
        raise AnalyticsInputError("source no longer indexed")
    doc = indexed.document
    if (doc.workspace_id != workspace_id or doc.document_id != doc_id
            or doc.version_id != citation["version_id"]
            or doc.content_sha256 != citation["source_sha256"]
            or doc.source_path != citation["source_path"]):
        raise AnalyticsInputError("source generation changed since review")
    page_number, start, end = (
        citation["page_number"], citation["start_char"], citation["end_char"]
    )
    if (type(page_number) is not int or type(start) is not int
            or type(end) is not int or not 1 <= page_number <= 500
            or start < 0 or end <= start):
        raise AnalyticsInputError("invalid citation page or offsets")
    page = next((p for p in doc.pages if p.page_number == page_number), None)
    chunk = next((c for c in indexed.chunks if c.chunk_id == citation["chunk_id"]), None)
    if (page is None or chunk is None or not chunk.offsets_reliable
            or chunk.document_id != doc_id or chunk.version_id != doc.version_id
            or chunk.source_sha256 != doc.content_sha256
            or chunk.source_path != doc.source_path
            or chunk.page_number != page_number
            or chunk.start_char != start or chunk.end_char != end
            or page.text[start:end] != chunk.text):
        raise AnalyticsInputError("citation source text mismatch")
    numeric = _amount(selection.value)
    canonical_amount = format(numeric, "f")
    if canonical_amount != selection.value or not _evidence_contains_amount(chunk.text, canonical_amount):
        raise AnalyticsInputError("numeric claim not contained in exact source citation")
    return ReviewedFinancialObservation(
        workspace_id=workspace_id,
        document_id=doc_id,
        document_version_id=doc.version_id,
        source_sha256=doc.content_sha256,
        source_path=doc.source_path,
        page_number=page_number,
        chunk_id=chunk.chunk_id,
        start_char=start,
        end_char=end,
        company="", year=1900, metric="", amount=canonical_amount,
        currency="", unit="", reviewer_asserted_row=False,
    )


class FinancialReviewSession:
    """Volatile review queue with atomic explicit approval and rejection.

    Nothing is persisted or automatically approved. A web/API adapter
    requires independent authenticated principal-to-workspace checks.
    """

    def __init__(self, *, repository, workspace_id: str, max_pending: int = 120):
        self._repo = repository
        self.workspace_id = _require_text(workspace_id, "workspace", 128)
        if type(max_pending) is not int or not 1 <= max_pending <= 120:
            raise AnalyticsInputError("invalid review queue capacity")
        self._max_pending = max_pending
        self._pending: dict[int, ReviewSelection] = {}
        self._approved: dict[int, ReviewedFinancialObservation] = {}
        self._decisions: dict[int, str] = {}
        self._next_id = 1
        self._lock = RLock()

    def enqueue(self, selection: ReviewSelection) -> int:
        if not isinstance(selection, ReviewSelection):
            raise AnalyticsInputError("review selection required")
        with self._lock:
            if len(self._pending) >= self._max_pending:
                raise AnalyticsInputError("review queue capacity exceeded")
            _verify_source(selection, repository=self._repo, workspace_id=self.workspace_id)
            key = self._next_id
            self._next_id += 1
            # Defensive copy so mutating a caller-owned citation cannot
            # silently alter pending source identity.
            self._pending[key] = ReviewSelection(dict(selection.citation), selection.value)
            return key

    def reject(self, item_id: int, *, reviewer_id: str) -> None:
        _require_text(reviewer_id, "reviewer", 128)
        with self._lock:
            if item_id not in self._pending:
                raise AnalyticsInputError("unknown or resolved review item")
            self._pending.pop(item_id)
            self._decisions[item_id] = "REJECTED"

    def approve(self, item_id: int, decision: ReviewDecision) -> None:
        if not isinstance(decision, ReviewDecision):
            raise AnalyticsInputError("explicit human review decision required")
        _require_text(decision.reviewer_id, "reviewer", 128)
        company = _require_text(decision.company, "company")
        if (decision.source_page_visually_checked is not True
                or decision.metric_year_unit_visually_confirmed is not True):
            raise AnalyticsInputError("visual row/year/unit confirmation required")
        if (type(decision.year) is not int or not 1900 <= decision.year <= 2100
                or decision.metric not in _METRICS
                or decision.currency not in _CURRENCIES
                or decision.unit not in _UNITS):
            raise AnalyticsInputError("invalid reviewed financial fields")
        with self._lock:
            selection = self._pending.get(item_id)
            if selection is None:
                raise AnalyticsInputError("unknown or already resolved review item")
            source = _verify_source(selection, repository=self._repo,
                                    workspace_id=self.workspace_id)
            approved = replace(
                source, company=company, year=decision.year,
                metric=decision.metric, currency=decision.currency,
                unit=decision.unit, reviewer_asserted_row=True,
            )
            self._approved[item_id] = approved
            self._pending.pop(item_id)
            self._decisions[item_id] = "APPROVED"

    def summary(self) -> dict[str, object]:
        with self._lock:
            return {
                "status": "VOLATILE_REVIEW_QUEUE",
                "pending": len(self._pending),
                "approved": len(self._approved),
                "rejected": sum(value == "REJECTED" for value in self._decisions.values()),
                "external_authentication_required": True,
                "durably_persisted": False,
                "automatically_verified_financial_facts": 0,
            }

    def analyze(self, *, company: str, metric: str, currency: str,
                unit: str, start_year: int, end_year: int) -> dict[str, object]:
        with self._lock:
            # The source-backed computation independently checks active
            # generations, duplicate totals, and mixed currency/units.
            observations = tuple(self._approved.values())
            if not observations:
                raise AnalyticsInputError("no explicitly approved source evidence")
            result = analyze_reviewed_evidence(
                observations, repository=self._repo,
                workspace_id=self.workspace_id, company=company,
                metric=metric, currency=currency, unit=unit,
                start_year=start_year, end_year=end_year,
            )
            result["review_workflow"] = "EXPLICIT_VOLATILE_HUMAN_APPROVAL"
            result["requires_external_authentication"] = True
            return result
