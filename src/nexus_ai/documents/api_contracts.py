"""Experimental backend contracts without HTTP routes or authentication claims.

The application has no authentication/authorization subsystem yet. Callers must
receive ``AuthorizedWorkspaceContext`` from a future trusted auth dependency;
these adapters never accept a workspace ID from a request body.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from threading import RLock
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, field_validator

from nexus_ai.documents.service import DocumentIngestionService
from nexus_ai.documents.types import DocumentVersion, RetrievalFilters
from nexus_ai.retrieval.repository import DocumentIndexRepository
from nexus_ai.retrieval.schemas import EvidenceCitation, RetrievalResponse
from nexus_ai.retrieval.service import CitationValidationError, RetrievalService, validate_citation


class WorkspacePermissionError(PermissionError):
    """The authenticated workspace context lacks the required operation."""


class AnsweringUnavailableError(RuntimeError):
    """No grounded answer service has been configured for this backend."""


class StaleEvidenceError(RuntimeError):
    """Retrieved evidence changed or disappeared before answer delivery."""


@dataclass(frozen=True)
class AuthorizedWorkspaceContext:
    """Context that a future auth layer must construct after authorization.

    This dataclass is not proof of identity. Do not construct it from request
    fields or user-controlled headers. A route must receive it from an actual
    verified identity/workspace authorization dependency before calling here.
    """

    subject_id: str
    workspace_id: str
    permissions: frozenset[str]

    def __post_init__(self) -> None:
        if not self.subject_id.strip() or len(self.subject_id) > 128:
            raise ValueError("subject_id must be non-empty and at most 128 characters")
        if not self.workspace_id.strip() or len(self.workspace_id) > 128:
            raise ValueError("workspace_id must be non-empty and at most 128 characters")

    def require(self, permission: str) -> None:
        if permission not in self.permissions:
            raise WorkspacePermissionError(f"workspace permission required: {permission}")


class WorkspaceContextProvider(Protocol):
    """Future integration contract for an authenticated authorization layer."""

    def for_request(self, request_context: object) -> AuthorizedWorkspaceContext: ...


class DocumentPathRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    relative_path: StrictStr = Field(min_length=1, max_length=512)

    @field_validator("relative_path")
    @classmethod
    def safe_relative_path(cls, value: str) -> str:
        # The ingestion service performs canonical filesystem validation too;
        # this is an early API-shape check, not a replacement for that boundary.
        normalized = value.replace("\\", "/")
        parts = normalized.split("/")
        if (normalized.startswith("/") or ":" in normalized
                or any(part in ("", ".", "..") for part in parts)):
            raise ValueError("relative_path must be a safe workspace-relative path")
        if not normalized.casefold().endswith((".txt", ".md", ".pdf")):
            raise ValueError("relative_path must name a .txt, .md, or .pdf file")
        return normalized


class IngestionTriggerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    document_id: StrictStr = Field(min_length=1, max_length=128)
    idempotency_key: StrictStr | None = Field(default=None, min_length=1, max_length=128)

    @field_validator("idempotency_key")
    @classmethod
    def key_not_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("idempotency_key must contain non-whitespace text")
        return value


class DocumentListRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    limit: StrictInt = Field(default=50, ge=1, le=200)


class DocumentIdRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    document_id: StrictStr = Field(min_length=1, max_length=128)


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    query: StrictStr = Field(min_length=1, max_length=8_000)
    top_k: StrictInt = Field(default=5, ge=1, le=20)
    strategy: Literal["windowed_e5", "bm25_raw"] = "windowed_e5"

    @field_validator("query")
    @classmethod
    def query_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("query must contain non-whitespace text")
        return value


class EvidenceLookupRequest(SearchRequest):
    document_id: StrictStr = Field(min_length=1, max_length=128)
    page_number: StrictInt | None = Field(default=None, ge=1)


class GroundedAnswerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    query: StrictStr = Field(min_length=1, max_length=8_000)
    top_k: StrictInt = Field(default=5, ge=1, le=20)
    language: Literal["ar", "en", "auto"] = "auto"

    @field_validator("query")
    @classmethod
    def query_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("query must contain non-whitespace text")
        return value


class DocumentSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    document_id: StrictStr
    version_id: StrictStr
    source_path: StrictStr
    content_sha256: StrictStr
    media_type: StrictStr
    page_count: StrictInt
    chunk_count: StrictInt
    warning_count: StrictInt


class DocumentRegistrationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    document_id: StrictStr
    version_id: StrictStr
    content_sha256: StrictStr
    activated: StrictBool
    idempotent: StrictBool
    chunk_count: StrictInt
    window_count: StrictInt
    warnings: tuple[StrictStr, ...]


class DocumentListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    items: tuple[DocumentSummary, ...]
    has_more: StrictBool


class IngestionStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    document_id: StrictStr
    status: Literal["indexed", "not_found"]
    active_version_id: StrictStr | None = None


class DocumentDeleteResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    document_id: StrictStr
    deleted: StrictBool


class GroundedAnswerResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    answer: StrictStr
    abstained: StrictBool
    citations: tuple[EvidenceCitation, ...]
    language: Literal["ar", "en", "und"]


class GroundedAnswerer(Protocol):
    def answer(self, query: str, evidence: tuple[EvidenceCitation, ...], *, language: str) -> GroundedAnswerResult: ...


class DocumentBackendAdapter:
    """Thin service adapter. It is not an HTTP router or an auth provider."""

    _MAX_TRIGGER_RESULTS = 1_024

    def __init__(
        self,
        *,
        ingestion: DocumentIngestionService,
        repository: DocumentIndexRepository,
        retrieval: RetrievalService,
        answerer: GroundedAnswerer | None = None,
    ) -> None:
        self.ingestion = ingestion
        self.repository = repository
        self.retrieval = retrieval
        self.answerer = answerer
        self._trigger_lock = RLock()
        # This convenience cache is intentionally process-local, and bounded.
        # It is not durable idempotency; durable job keys belong in a persistent
        # job store before any route is exposed.
        self._trigger_results: OrderedDict[
            tuple[str, str], tuple[str, DocumentRegistrationResponse]
        ] = OrderedDict()

    def register(self, context: AuthorizedWorkspaceContext, request: DocumentPathRequest) -> DocumentRegistrationResponse:
        context.require("documents:write")
        result = self.ingestion.ingest(context.workspace_id, request.relative_path)
        return DocumentRegistrationResponse(
            document_id=result.document_id, version_id=result.version_id,
            content_sha256=result.content_sha256, activated=result.activated,
            idempotent=result.idempotent, chunk_count=result.chunk_count,
            window_count=result.window_count, warnings=result.warnings,
        )

    def trigger_ingestion(
        self, context: AuthorizedWorkspaceContext, request: IngestionTriggerRequest,
    ) -> DocumentRegistrationResponse:
        """Synchronously re-index an already registered active document.

        The optional idempotency cache is process-local only. Durable job
        idempotency belongs to a future persistent job store.
        """
        context.require("documents:write")
        cache_key = ((context.workspace_id, request.idempotency_key)
                     if request.idempotency_key is not None else None)
        with self._trigger_lock:
            if cache_key is not None and cache_key in self._trigger_results:
                prior_document_id, prior_result = self._trigger_results[cache_key]
                if prior_document_id != request.document_id:
                    raise ValueError("idempotency_key is already associated with another document")
                return prior_result
            indexed = self.repository.get_active(context.workspace_id, request.document_id)
            if indexed is None:
                raise KeyError("document is not registered in this workspace")
            result = self.ingestion.ingest(context.workspace_id, indexed.document.source_path)
            response = DocumentRegistrationResponse(
                document_id=result.document_id, version_id=result.version_id,
                content_sha256=result.content_sha256, activated=result.activated,
                idempotent=result.idempotent, chunk_count=result.chunk_count,
                window_count=result.window_count, warnings=result.warnings,
            )
            if cache_key is not None:
                self._trigger_results[cache_key] = (request.document_id, response)
                self._trigger_results.move_to_end(cache_key)
                if len(self._trigger_results) > self._MAX_TRIGGER_RESULTS:
                    self._trigger_results.popitem(last=False)
            return response

    def list_documents(
        self, context: AuthorizedWorkspaceContext, request: DocumentListRequest = DocumentListRequest(),
    ) -> DocumentListResponse:
        context.require("documents:read")
        # Read only one row beyond the requested page. PostgreSQL's materializing
        # list_active() is a convenience API and may load large vector payloads.
        rows = self.repository.iter_active(context.workspace_id)
        selected = []
        try:
            for _ in range(request.limit + 1):
                row = next(rows, None)
                if row is None:
                    break
                selected.append(row)
        finally:
            close = getattr(rows, "close", None)
            if close is not None:
                close()
        return DocumentListResponse(
            items=tuple(_summary(row.document, len(row.chunks)) for row in selected[:request.limit]),
            has_more=len(selected) > request.limit,
        )

    def ingestion_status(
        self, context: AuthorizedWorkspaceContext, request: DocumentIdRequest,
    ) -> IngestionStatusResponse:
        context.require("documents:read")
        indexed = self.repository.get_active(context.workspace_id, request.document_id)
        return IngestionStatusResponse(
            document_id=request.document_id,
            status="indexed" if indexed else "not_found",
            active_version_id=indexed.document.version_id if indexed else None,
        )

    def delete_document(
        self, context: AuthorizedWorkspaceContext, request: DocumentIdRequest,
    ) -> DocumentDeleteResponse:
        context.require("documents:delete")
        return DocumentDeleteResponse(
            document_id=request.document_id,
            deleted=self.repository.delete(context.workspace_id, request.document_id),
        )

    def search(self, context: AuthorizedWorkspaceContext, request: SearchRequest) -> RetrievalResponse:
        context.require("documents:read")
        return self.retrieval.retrieve(
            request.query, workspace_id=context.workspace_id,
            top_k=request.top_k, strategy=request.strategy,
        )

    def evidence(self, context: AuthorizedWorkspaceContext, request: EvidenceLookupRequest) -> RetrievalResponse:
        context.require("documents:read")
        return self.retrieval.retrieve(
            request.query, workspace_id=context.workspace_id, top_k=request.top_k,
            strategy=request.strategy,
            filters=RetrievalFilters(document_id=request.document_id, page_number=request.page_number),
        )

    def grounded_answer(
        self, context: AuthorizedWorkspaceContext, request: GroundedAnswerRequest,
    ) -> GroundedAnswerResult:
        context.require("documents:read")
        if self.answerer is None:
            raise AnsweringUnavailableError("grounded answer generation is not configured")
        found = self.retrieval.retrieve(
            request.query, workspace_id=context.workspace_id, top_k=request.top_k,
        )
        citations = tuple(row.citation for row in found.results)
        answer = self.answerer.answer(request.query, citations, language=request.language)
        for citation in answer.citations:
            if citation not in citations or citation.workspace_id != context.workspace_id:
                raise StaleEvidenceError("answer citations were not part of the authorized retrieval snapshot")
            active = self.repository.get_active(context.workspace_id, citation.document_id)
            if active is None or active.document.version_id != citation.document_version_id:
                raise StaleEvidenceError("source evidence changed before answer delivery")
            chunk = next((row for row in active.chunks if row.chunk_id == citation.chunk_id), None)
            if chunk is None:
                raise StaleEvidenceError("source evidence changed before answer delivery")
            try:
                validate_citation(citation, active.document.pages, chunk, windows=active.windows)
            except CitationValidationError as exc:
                raise StaleEvidenceError("source evidence changed before answer delivery") from exc
        return answer


def _summary(document: DocumentVersion, chunk_count: int) -> DocumentSummary:
    return DocumentSummary(
        document_id=document.document_id, version_id=document.version_id,
        source_path=document.source_path, content_sha256=document.content_sha256,
        media_type=document.media_type, page_count=len(document.pages),
        chunk_count=chunk_count, warning_count=len(document.warnings),
    )
