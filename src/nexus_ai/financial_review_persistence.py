"""Transactional PostgreSQL review ledger for explicitly reviewed financial facts.

Inert schema proposal; no migrations or production connections at import time.
The calling application MUST authenticate and authorize the reviewer and
workspace; reviewer_id strings are not proof of authorization. Source claims
are verified before each write and again during analytics. An index version
change makes stored approval unusable, never silently migrates it.

Tables retain only necessary numeric citation and explicit review decisions.
The ledger is append/transition-only (PENDING -> APPROVED or REJECTED).
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from typing import Callable

from nexus_ai.data_analytics import AnalyticsInputError
from nexus_ai.financial_evidence_analytics import analyze_reviewed_evidence
from nexus_ai.financial_review_workflow import (
    ReviewDecision, ReviewSelection, _require_text, _verify_source,
)
from nexus_ai.financial_analytics import _CURRENCIES, _METRICS, _UNITS


FINANCIAL_REVIEW_SCHEMA_DDL = (
    """CREATE TABLE nexus_financial_reviews (
        id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        workspace_id text NOT NULL CHECK (length(workspace_id) BETWEEN 1 AND 128),
        document_id text NOT NULL,
        version_id text NOT NULL,
        source_sha256 text NOT NULL,
        source_path text NOT NULL,
        page_number integer NOT NULL CHECK (page_number BETWEEN 1 AND 500),
        chunk_id text NOT NULL,
        start_char integer NOT NULL CHECK (start_char >= 0),
        end_char integer NOT NULL CHECK (end_char > start_char),
        amount text NOT NULL,
        state text NOT NULL DEFAULT 'PENDING'
            CHECK (state IN ('PENDING', 'APPROVED', 'REJECTED')),
        reviewer_id text,
        company text,
        financial_year integer CHECK (financial_year BETWEEN 1900 AND 2100),
        metric text,
        currency text,
        unit text,
        visually_checked boolean NOT NULL DEFAULT false,
        relationship_confirmed boolean NOT NULL DEFAULT false,
        created_at timestamptz NOT NULL DEFAULT now(),
        decided_at timestamptz,
        CHECK (
            (state = 'PENDING' AND reviewer_id IS NULL AND
             company IS NULL AND financial_year IS NULL AND metric IS NULL
             AND currency IS NULL AND unit IS NULL AND NOT visually_checked
             AND NOT relationship_confirmed AND decided_at IS NULL)
            OR (state = 'REJECTED' AND reviewer_id IS NOT NULL AND
                company IS NULL AND financial_year IS NULL AND metric IS NULL
                AND currency IS NULL AND unit IS NULL AND NOT visually_checked
                AND NOT relationship_confirmed AND decided_at IS NOT NULL)
            OR (state = 'APPROVED' AND reviewer_id IS NOT NULL AND
                company IS NOT NULL AND financial_year IS NOT NULL
                AND metric IS NOT NULL AND currency IS NOT NULL
                AND unit IS NOT NULL AND visually_checked
                AND relationship_confirmed AND decided_at IS NOT NULL)
        )
    )""",
    "CREATE INDEX nexus_financial_reviews_workspace_state_idx ON nexus_financial_reviews (workspace_id, state, id)",
    "CREATE INDEX nexus_financial_reviews_source_idx ON nexus_financial_reviews (workspace_id, document_id, version_id)",
)


def _selection_from_row(row) -> ReviewSelection:
    return ReviewSelection({
        "workspace_id": row[1], "document_id": row[2],
        "version_id": row[3], "source_sha256": row[4],
        "source_path": row[5], "page_number": row[6],
        "chunk_id": row[7], "start_char": row[8],
        "end_char": row[9],
    }, row[10])


class PostgresFinancialReviewLedger:
    """Explicit durable approvals, with per-operation isolated transactions."""

    def __init__(self, connection_factory: Callable, *, collection_repository,
                 workspace_id: str, max_records: int = 500):
        if not callable(connection_factory):
            raise AnalyticsInputError("connection factory required")
        self.workspace_id = _require_text(workspace_id, "workspace", 128)
        if type(max_records) is not int or not 1 <= max_records <= 500:
            raise AnalyticsInputError("invalid review ledger capacity")
        self._connection_factory = connection_factory
        self._collection = collection_repository
        self._max_records = max_records

    @contextmanager
    def _transaction(self):
        connection = self._connection_factory()
        try:
            if getattr(connection, "autocommit", False):
                raise AnalyticsInputError("review ledger requires transactional connection")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def submit(self, selection: ReviewSelection) -> int:
        if not isinstance(selection, ReviewSelection):
            raise AnalyticsInputError("numeric review selection required")
        original = _verify_source(selection, repository=self._collection,
                                  workspace_id=self.workspace_id)
        with self._transaction() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 29))",
                    (self.workspace_id,),
                )
                cursor.execute(
                    "SELECT COUNT(*) FROM nexus_financial_reviews WHERE workspace_id = %s",
                    (self.workspace_id,),
                )
                if cursor.fetchone()[0] >= self._max_records:
                    raise AnalyticsInputError("review ledger capacity reached")
                # Recheck immediately before the transaction inserts.
                _verify_source(selection, repository=self._collection,
                               workspace_id=self.workspace_id)
                cursor.execute(
                    """INSERT INTO nexus_financial_reviews
                       (workspace_id, document_id, version_id, source_sha256,
                        source_path, page_number, chunk_id, start_char, end_char, amount)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                    (original.workspace_id, original.document_id,
                     original.document_version_id, original.source_sha256,
                     original.source_path, original.page_number,
                     original.chunk_id, original.start_char,
                     original.end_char, original.amount),
                )
                return int(cursor.fetchone()[0])

    def _decide(self, item_id: int, reviewer_id: str,
                decision: ReviewDecision | None) -> None:
        if type(item_id) is not int or item_id < 1:
            raise AnalyticsInputError("invalid review id")
        reviewer_id = _require_text(reviewer_id, "reviewer", 128)
        if decision is not None:
            if not isinstance(decision, ReviewDecision):
                raise AnalyticsInputError("invalid review decision")
            if decision.reviewer_id != reviewer_id:
                raise AnalyticsInputError("reviewer mismatch")
            company = _require_text(decision.company, "company")
            if (decision.source_page_visually_checked is not True
                    or decision.metric_year_unit_visually_confirmed is not True
                    or type(decision.year) is not int
                    or not 1900 <= decision.year <= 2100
                    or decision.metric not in _METRICS
                    or decision.currency not in _CURRENCIES
                    or decision.unit not in _UNITS):
                raise AnalyticsInputError("explicit visual accounting verification required")
        with self._transaction() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """SELECT id, workspace_id, document_id, version_id,
                              source_sha256, source_path, page_number,
                              chunk_id, start_char, end_char, amount
                       FROM nexus_financial_reviews
                       WHERE workspace_id = %s AND id = %s AND state = 'PENDING'
                       FOR UPDATE""",
                    (self.workspace_id, item_id),
                )
                row = cursor.fetchone()
                if row is None:
                    raise AnalyticsInputError("review missing, resolved or outside workspace")
                _verify_source(_selection_from_row(row), repository=self._collection,
                               workspace_id=self.workspace_id)
                if decision is None:
                    cursor.execute(
                        """UPDATE nexus_financial_reviews SET state = 'REJECTED',
                           reviewer_id = %s, decided_at = now()
                           WHERE workspace_id = %s AND id = %s AND state = 'PENDING'""",
                        (reviewer_id, self.workspace_id, item_id),
                    )
                else:
                    cursor.execute(
                        """UPDATE nexus_financial_reviews SET state = 'APPROVED',
                           reviewer_id = %s, company = %s, financial_year = %s,
                           metric = %s, currency = %s, unit = %s,
                           visually_checked = true, relationship_confirmed = true,
                           decided_at = now()
                           WHERE workspace_id = %s AND id = %s AND state = 'PENDING'""",
                        (reviewer_id, company, decision.year, decision.metric,
                         decision.currency, decision.unit, self.workspace_id, item_id),
                    )
                if cursor.rowcount != 1:
                    raise AnalyticsInputError("review decision race detected")

    def approve(self, item_id: int, decision: ReviewDecision) -> None:
        if not isinstance(decision, ReviewDecision):
            raise AnalyticsInputError("review decision required")
        self._decide(item_id, decision.reviewer_id, decision)

    def reject(self, item_id: int, *, reviewer_id: str) -> None:
        self._decide(item_id, reviewer_id, None)

    def pending(self, *, limit: int = 50) -> list[dict[str, object]]:
        """Return bounded, source-checked queue metadata for human review.

        Never infers row, year, unit, or financial meaning from a number.
        An invalidated source fails the entire request closed.
        """
        if type(limit) is not int or not 1 <= limit <= 100:
            raise AnalyticsInputError("invalid pending review limit")
        with self._transaction() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """SELECT id, workspace_id, document_id, version_id,
                              source_sha256, source_path, page_number,
                              chunk_id, start_char, end_char, amount
                       FROM nexus_financial_reviews
                       WHERE workspace_id = %s AND state = 'PENDING'
                       ORDER BY id LIMIT %s""",
                    (self.workspace_id, limit),
                )
                rows = cursor.fetchall()
        output = []
        for row in rows:
            source = _verify_source(
                _selection_from_row(row), repository=self._collection,
                workspace_id=self.workspace_id,
            )
            output.append({
                "id": row[0],
                "document_id": source.document_id,
                "version_id": source.document_version_id,
                "page_number": source.page_number,
                "amount": source.amount,
                "citation": _selection_from_row(row).citation,
                "state": "PENDING",
                "requires_visual_review": True,
                "automatically_verified_financial_fact": False,
            })
        return output

    def evidence(self, item_id: int) -> dict[str, object]:
        """Bounded exact-index-text preview; NOT an original PDF page rendering.

        Only pending records are eligible. No local path is opened and no
        automatic table row, year or unit relationship is inferred.
        """
        if type(item_id) is not int or item_id <= 0:
            raise AnalyticsInputError("invalid review id")
        with self._transaction() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """SELECT id, workspace_id, document_id, version_id,
                              source_sha256, source_path, page_number,
                              chunk_id, start_char, end_char, amount
                       FROM nexus_financial_reviews
                       WHERE workspace_id = %s AND id = %s
                         AND state = 'PENDING'""",
                    (self.workspace_id, item_id),
                )
                row = cursor.fetchone()
        if row is None:
            raise AnalyticsInputError("pending review not found")
        selection = _selection_from_row(row)
        _verify_source(selection, repository=self._collection,
                       workspace_id=self.workspace_id)
        indexed = self._collection.get_active(self.workspace_id, row[2])
        if indexed is None:
            raise AnalyticsInputError("source no longer indexed")
        chunks = [chunk for chunk in indexed.chunks if chunk.chunk_id == row[7]]
        if len(chunks) != 1:
            raise AnalyticsInputError("citation source text mismatch")
        chunk = chunks[0]
        if len(chunk.text) > 8192:
            raise AnalyticsInputError("source preview exceeds bounded limit")
        # Verify again after retrieving text: reject a concurrent replacement
        # detected during source preview preparation.
        _verify_source(selection, repository=self._collection,
                       workspace_id=self.workspace_id)
        return {
            "id": row[0],
            "document_id": row[2],
            "version_id": row[3],
            "page_number": row[6],
            "amount": row[10],
            "indexed_excerpt": chunk.text,
            "citation": dict(selection.citation),
            "evidence_kind": "INDEXED_TEXT_ONLY",
            "original_pdf_visually_checked": False,
            "accounting_row_verified": False,
            "requires_original_document_review": True,
        }

    def status(self) -> dict[str, object]:
        with self._transaction() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """SELECT state, COUNT(*) FROM nexus_financial_reviews
                       WHERE workspace_id = %s GROUP BY state""",
                    (self.workspace_id,),
                )
                counts = dict(cursor.fetchall())
        return {
            "status": "DURABLE_REVIEW_LEDGER",
            "pending": int(counts.get("PENDING", 0)),
            "approved": int(counts.get("APPROVED", 0)),
            "rejected": int(counts.get("REJECTED", 0)),
            "authentication_enforced_by_ledger": False,
            "automatically_verified_financial_facts": 0,
        }

    def analyze(self, *, company: str, metric: str, currency: str,
                unit: str, start_year: int, end_year: int) -> dict[str, object]:
        with self._transaction() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """SELECT id, workspace_id, document_id, version_id,
                              source_sha256, source_path, page_number,
                              chunk_id, start_char, end_char, amount,
                              company, financial_year, metric, currency, unit
                       FROM nexus_financial_reviews
                       WHERE workspace_id = %s AND state = 'APPROVED'
                       ORDER BY id LIMIT %s""",
                    (self.workspace_id, self._max_records + 1),
                )
                rows = cursor.fetchall()
        if not rows or len(rows) > self._max_records:
            raise AnalyticsInputError("no valid bounded approvals")
        observations = []
        for row in rows:
            source = _verify_source(
                _selection_from_row(row), repository=self._collection,
                workspace_id=self.workspace_id,
            )
            observations.append(replace(
                source, company=row[11], year=row[12], metric=row[13],
                currency=row[14], unit=row[15], reviewer_asserted_row=True,
            ))
        result = analyze_reviewed_evidence(
            tuple(observations), repository=self._collection,
            workspace_id=self.workspace_id, company=company, metric=metric,
            currency=currency, unit=unit,
            start_year=start_year, end_year=end_year,
        )
        result["review_workflow"] = "DURABLE_EXPLICIT_HUMAN_APPROVAL"
        result["requires_external_authentication"] = True
        return result
