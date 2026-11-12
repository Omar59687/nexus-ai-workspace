"""Typed request and response contracts prepared for a later API route."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr


class RetrievalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: StrictStr = Field(min_length=1, max_length=128)
    query: StrictStr = Field(min_length=1, max_length=8_000)
    top_k: StrictInt = Field(default=5, ge=1, le=20)
    strategy: Literal["windowed_e5", "bm25_raw"] = "windowed_e5"
    document_id: StrictStr | None = Field(default=None, min_length=1, max_length=128)
    page_number: StrictInt | None = Field(default=None, ge=1)


class EvidenceCitation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: StrictStr
    document_id: StrictStr
    document_version_id: StrictStr
    source_path: StrictStr
    source_sha256: StrictStr
    page_number: StrictInt | None
    chunk_id: StrictStr
    start_char: StrictInt | None
    end_char: StrictInt | None
    matched_window_id: StrictStr | None
    matched_window_start_char: StrictInt | None
    matched_window_end_char: StrictInt | None
    offsets_reliable: bool
    exact_text: StrictStr


class RetrievedEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    score: float
    score_type: Literal["cosine_similarity", "bm25"]
    strategy: Literal["windowed_e5", "bm25_raw"]
    citation: EvidenceCitation


class RetrievalResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: StrictStr
    strategy: Literal["windowed_e5", "bm25_raw"]
    status: Literal["ok", "empty"]
    results: list[RetrievedEvidence]
