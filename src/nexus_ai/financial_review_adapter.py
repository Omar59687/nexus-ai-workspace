"""Fail-closed application boundary for the durable financial review ledger.

The host MUST supply a trusted authenticated-principal resolver and tenant
authorization policy. This module does not authenticate HTTP requests or
grant permissions from caller-provided reviewer/workspace strings.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from nexus_ai.financial_review_workflow import ReviewDecision, ReviewSelection, _require_text


@dataclass(frozen=True)
class ReviewPrincipal:
    """Identity returned by trusted authentication middleware, not a request body."""
    subject: str
    session_token_sha256: str | None = None


class AuthorizedFinancialReviewAdapter:
    """Authorizes every operation before accessing the workspace-scoped ledger.

    construct one instance per request or a request-scoped principal resolver.
    The policy receives (principal, workspace_id, action) and must return
    literal True; false, None, or an exception fails closed.
    """

    def __init__(
        self, *, ledger, resolve_principal: Callable[[], ReviewPrincipal],
        authorize: Callable[[ReviewPrincipal, str, str], bool],
    ):
        if not callable(resolve_principal) or not callable(authorize):
            raise ValueError("trusted identity resolver and policy required")
        self._ledger = ledger
        self._resolve = resolve_principal
        self._authorize = authorize
        self._workspace_id = _require_text(ledger.workspace_id, "workspace", 128)

    def _check(self, action: str) -> ReviewPrincipal:
        try:
            principal = self._resolve()
            if not isinstance(principal, ReviewPrincipal):
                raise PermissionError("unauthenticated financial review")
            _require_text(principal.subject, "principal", 128)
            if self._authorize(principal, self._workspace_id, action) is not True:
                raise PermissionError("financial review access denied")
        except Exception as exc:
            raise PermissionError("financial review access denied") from exc
        return principal

    def submit(self, selection: ReviewSelection) -> int:
        self._check("submit")
        return self._ledger.submit(selection)

    def approve(self, item_id: int, decision: ReviewDecision) -> None:
        principal = self._check("approve")
        if not isinstance(decision, ReviewDecision) or decision.reviewer_id != principal.subject:
            raise PermissionError("reviewer identity mismatch")
        self._ledger.approve(item_id, decision)

    def reject(self, item_id: int) -> None:
        principal = self._check("reject")
        self._ledger.reject(item_id, reviewer_id=principal.subject)

    def pending(self, *, limit: int = 50) -> list[dict[str, object]]:
        self._check("list")
        return self._ledger.pending(limit=limit)

    def evidence(self, item_id: int) -> dict[str, object]:
        self._check("view_evidence")
        return self._ledger.evidence(item_id)

    def authorize_pdf(self, item_id: int) -> dict[str, object]:
        self._check("view_pdf")
        return self._ledger.evidence(item_id)

    def status(self) -> dict[str, object]:
        self._check("status")
        return self._ledger.status()

    def analyze(self, *, company: str, metric: str, currency: str,
                unit: str, start_year: int, end_year: int) -> dict[str, object]:
        self._check("analyze")
        return self._ledger.analyze(
            company=company, metric=metric, currency=currency,
            unit=unit, start_year=start_year, end_year=end_year,
        )
