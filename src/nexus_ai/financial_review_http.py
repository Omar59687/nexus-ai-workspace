"""Opt-in, workspace-bound HTTP review router.

NOT mounted by the default Nexus application. The host must provide a
verified, request-scoped authentication resolver and explicit authorization
policy. A request header, cookie, or body is never treated as a principal by
this module. The router has no workspace selector to prevent tenant switching.
"""
from __future__ import annotations

from typing import Callable

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr

from nexus_ai.data_analytics import AnalyticsInputError
from nexus_ai.financial_review_adapter import (
    AuthorizedFinancialReviewAdapter, ReviewPrincipal,
)
from nexus_ai.financial_review_workflow import ReviewDecision, ReviewSelection, _require_text
from nexus_ai.financial_review_pdf import make_review_pdf_attachment
from nexus_ai.financial_review_ui import review_page_response


class NumericCitationPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    workspace_id: StrictStr
    document_id: StrictStr
    version_id: StrictStr
    source_sha256: StrictStr
    source_path: StrictStr
    page_number: StrictInt = Field(ge=1, le=500)
    chunk_id: StrictStr
    start_char: StrictInt = Field(ge=0)
    end_char: StrictInt = Field(gt=0)


class ReviewSubmissionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    citation: NumericCitationPayload
    value: StrictStr = Field(min_length=1, max_length=100)


class ReviewDecisionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    company: StrictStr = Field(min_length=1, max_length=160)
    year: StrictInt = Field(ge=1900, le=2100)
    metric: StrictStr
    currency: StrictStr
    unit: StrictStr
    source_page_visually_checked: StrictBool
    metric_year_unit_visually_confirmed: StrictBool


class FinancialAnalysisPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    company: StrictStr = Field(min_length=1, max_length=160)
    metric: StrictStr
    currency: StrictStr
    unit: StrictStr
    start_year: StrictInt = Field(ge=1900, le=2100)
    end_year: StrictInt = Field(ge=1900, le=2100)


def create_financial_review_router(
    *,
    workspace_id: str,
    ledger_factory: Callable[[], object],
    authenticate_request: Callable[[Request], ReviewPrincipal],
    authorize: Callable[[ReviewPrincipal, str, str], bool],
    pdf_bytes_provider: Callable[[ReviewPrincipal, str, str, str], bytes] | None = None,
    enable_review_page: bool = False,
) -> APIRouter:
    """Construct routes only after a trusted host explicitly configures them.

    Authentication is run at request time. The trusted host supplies a
    verified session resolver and tenant policy. A ledger must be scoped to
    the exact configured workspace. No untrusted request supplies a ledger,
    principal, or workspace ID.
    """
    workspace_id = _require_text(workspace_id, "workspace", 128)
    if not all(callable(value) for value in (
        ledger_factory, authenticate_request, authorize,
    )):
        raise ValueError("trusted ledger, authentication and policy required")

    router = APIRouter(prefix="/financial-reviews", tags=["financial-review"])

    def get_adapter(request: Request) -> AuthorizedFinancialReviewAdapter:
        try:
            principal = authenticate_request(request)
            if not isinstance(principal, ReviewPrincipal):
                raise PermissionError("invalid principal")
            # Do not create a ledger for unauthenticated requests.
            _require_text(principal.subject, "principal", 128)
        except Exception as exc:
            raise HTTPException(status_code=401, detail="Authentication required") from exc
        try:
            ledger = ledger_factory()
            if ledger.workspace_id != workspace_id:
                raise PermissionError("ledger workspace mismatch")
            return AuthorizedFinancialReviewAdapter(
                ledger=ledger,
                resolve_principal=lambda: principal,
                authorize=authorize,
            )
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Review service unavailable") from exc

    def protected(adapter: AuthorizedFinancialReviewAdapter, action: Callable):
        try:
            return action()
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail="Review access denied") from exc
        except AnalyticsInputError as exc:
            # Avoid exposing document paths, indexed text, or user input in errors.
            raise HTTPException(status_code=422, detail="Invalid financial review input or source") from exc

    if enable_review_page is True:
        @router.get("/reviewer", include_in_schema=False)
        def reviewer_workbench():
            return review_page_response()

    @router.get("/selections")
    def list_pending(limit: int = Query(default=50, ge=1, le=100), adapter=Depends(get_adapter)):
        return {"items": protected(adapter, lambda: adapter.pending(limit=limit))}

    @router.get("/selections/{item_id}/evidence")
    def get_evidence(item_id: int, adapter=Depends(get_adapter)):
        return protected(adapter, lambda: adapter.evidence(item_id))

    if pdf_bytes_provider is not None:
        if not callable(pdf_bytes_provider):
            raise ValueError("trusted PDF bytes provider required")

        @router.get("/selections/{item_id}/original-pdf")
        def original_pdf(item_id: int, adapter=Depends(get_adapter)):
            # This permission is independent from queue and indexed-text
            # access. A trusted provider must enforce document-level grants.
            source = protected(adapter, lambda: adapter.authorize_pdf(item_id))
            principal = protected(adapter, lambda: adapter._check("view_pdf"))
            try:
                contents = pdf_bytes_provider(
                    principal, workspace_id, source["document_id"],
                    source["version_id"],
                )
                # Revalidate active source after accessing original bytes.
                current = protected(adapter, lambda: adapter.authorize_pdf(item_id))
                if current["citation"] != source["citation"]:
                    raise AnalyticsInputError("source version changed")
                return make_review_pdf_attachment(
                    indexed_evidence=current, pdf_bytes=contents,
                )
            except PermissionError as exc:
                raise HTTPException(
                    status_code=403, detail="Original PDF access denied",
                ) from exc
            except AnalyticsInputError as exc:
                raise HTTPException(
                    status_code=422, detail="Original PDF evidence unavailable",
                ) from exc
            except HTTPException:
                raise
            except Exception as exc:
                raise HTTPException(
                    status_code=503, detail="Original PDF provider unavailable",
                ) from exc

    @router.post("/selections", status_code=201)
    def submit(payload: ReviewSubmissionPayload, adapter=Depends(get_adapter)):
        citation = payload.citation.model_dump()
        if citation["workspace_id"] != workspace_id:
            raise HTTPException(status_code=403, detail="Review access denied")
        item_id = protected(adapter, lambda: adapter.submit(
            ReviewSelection(citation, payload.value),
        ))
        return {"id": item_id}

    @router.post("/selections/{item_id}/approve", status_code=204)
    def approve(item_id: int, payload: ReviewDecisionPayload,
                adapter=Depends(get_adapter)):
        # The trusted authenticated subject, never the request body, is reviewer_id.
        principal = protected(adapter, lambda: adapter._check("approve"))
        decision = ReviewDecision(
            reviewer_id=principal.subject,
            **payload.model_dump(),
        )
        protected(adapter, lambda: adapter.approve(item_id, decision))

    @router.post("/selections/{item_id}/reject", status_code=204)
    def reject(item_id: int, adapter=Depends(get_adapter)):
        protected(adapter, lambda: adapter.reject(item_id))

    @router.get("/status")
    def status(adapter=Depends(get_adapter)):
        return protected(adapter, adapter.status)

    @router.post("/analyze")
    def analyze(payload: FinancialAnalysisPayload, adapter=Depends(get_adapter)):
        return protected(adapter, lambda: adapter.analyze(**payload.model_dump()))

    return router
