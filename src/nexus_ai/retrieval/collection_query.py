"""Collection-scoped retrieval facade with mandatory company or year filtering.

This wrapper is opt-in, intended for application routes that must never issue
unfiltered searches. The caller must obtain workspace_id from authorization,
not from request body. No model selection, ingestion, or database changes.
"""
from __future__ import annotations

from dataclasses import dataclass

from nexus_ai.documents.types import RetrievalFilters
from nexus_ai.retrieval.company_metadata import CompanyYearFilter
from nexus_ai.retrieval.schemas import RetrievalResponse
from nexus_ai.retrieval.service import RetrievalService, RetrievalStrategy


@dataclass(frozen=True)
class AuthorizedCollectionRetriever:
    retrieval: RetrievalService
    workspace_id: str
    collection_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.retrieval, RetrievalService):
            raise TypeError("retrieval must be a RetrievalService")
        # A caller with authorization responsibility supplies workspace_id.
        if not isinstance(self.workspace_id, str) or not self.workspace_id.strip():
            raise ValueError("authorized workspace is required")
        if not isinstance(self.collection_id, str) or not self.collection_id.strip():
            raise ValueError("authorized collection is required")
        if self.retrieval.company_metadata is None:
            raise ValueError("company/year metadata catalog must be configured")

    def retrieve(
        self,
        query: str,
        *,
        company: str | None = None,
        financial_year: int | None = None,
        top_k: int = 5,
        strategy: RetrievalStrategy = "bm25_raw",
        page_number: int | None = None,
    ) -> RetrievalResponse:
        # No unfiltered route: CompanyYearFilter rejects missing selectors.
        selection = CompanyYearFilter(
            collection_id=self.collection_id,
            company=company,
            financial_year=financial_year,
        )
        return self.retrieval.retrieve(
            query,
            workspace_id=self.workspace_id,
            top_k=top_k,
            strategy=strategy,
            filters=RetrievalFilters(page_number=page_number),
            company_year_filter=selection,
        )
