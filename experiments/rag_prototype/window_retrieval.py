"""Deterministic local retrieval with bounded same-document context windows.

The ranked item remains the chunk that matched the query. Neighboring chunks
are attached only as citation-ready context; evaluation metrics continue to
score the anchor chunk and never count expanded context as extra retrievals.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Sequence

from experiments.rag_prototype import BM25Index, Chunk
from experiments.rag_prototype.evaluation import RetrieverSpec


MAX_WINDOW_RADIUS = 5


@dataclass(frozen=True)
class WindowHit:
    """An anchor hit plus bounded neighboring source chunks."""

    chunk: Chunk
    score: float
    window_chunks: tuple[Chunk, ...]


def expand_chunk_window(
    anchor: Chunk,
    chunks: Sequence[Chunk],
    *,
    radius: int = 1,
) -> tuple[Chunk, ...]:
    """Return an anchor-centered window within one document version."""
    _validate_radius(radius)
    matching = [
        chunk for chunk in chunks
        if (chunk.document_id, chunk.version_id) == (anchor.document_id, anchor.version_id)
    ]
    matching.sort(key=lambda chunk: (chunk.start_char, chunk.end_char, chunk.chunk_id))
    positions = [i for i, chunk in enumerate(matching) if chunk.chunk_id == anchor.chunk_id]
    if len(positions) != 1:
        raise ValueError("anchor must occur exactly once in its document version")
    position = positions[0]
    return tuple(matching[max(0, position - radius):position + radius + 1])


def build_window_retriever(
    chunks: Sequence[Chunk],
    *,
    window_radius: int = 1,
    normalize_arabic: bool = False,
    minimum_score: float | None = None,
) -> RetrieverSpec:
    """Build BM25 ranking with deterministic, provenance-bounded context windows."""
    _validate_radius(window_radius)
    if not chunks:
        raise ValueError("chunks must not be empty")
    if minimum_score is not None and (
        isinstance(minimum_score, bool)
        or not isinstance(minimum_score, (int, float))
        or not isfinite(float(minimum_score))
    ):
        raise ValueError("minimum_score must be a finite number")
    by_id = {chunk.chunk_id: chunk for chunk in chunks}
    if len(by_id) != len(chunks):
        raise ValueError("duplicate chunk IDs are not allowed")
    index = BM25Index(chunks, normalize_arabic=normalize_arabic)

    def retrieve(query: str, k: int) -> tuple[WindowHit, ...]:
        hits = index.search(query, top_k=k)
        return tuple(
            WindowHit(
                chunk=hit.chunk,
                score=hit.score,
                window_chunks=expand_chunk_window(hit.chunk, chunks, radius=window_radius),
            )
            for hit in hits
        )

    strategy = "arabic-normalized BM25" if normalize_arabic else "raw BM25"
    return RetrieverSpec(
        retrieve=retrieve,
        tie_policy="score descending, chunk ID ascending",
        minimum_score=minimum_score,
        metadata={
            "strategy": f"{strategy} with bounded context windows",
            "window_radius": window_radius,
            "window_max_chunks": 2 * window_radius + 1,
            "metrics_score_anchor_only": True,
            "cross_document_expansion": False,
        },
    )


def _validate_radius(radius: int) -> None:
    if type(radius) is not int or not 0 <= radius <= MAX_WINDOW_RADIUS:
        raise ValueError(f"window radius must be an integer from 0 to {MAX_WINDOW_RADIUS}")
