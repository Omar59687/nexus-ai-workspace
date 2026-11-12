"""Deterministic local retrieval with bounded same-document context windows.

The ranked item remains the chunk that matched the query. Neighboring chunks
are attached only as citation-ready context; evaluation metrics continue to
score the anchor chunk and never count expanded context as extra retrievals.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from math import isfinite
from time import perf_counter
from typing import Sequence

from experiments.rag_prototype import BM25Index, Chunk, RankedItem, exact_cosine
from experiments.rag_prototype.evaluation import RetrieverSpec


MAX_WINDOW_RADIUS = 5
DEFAULT_TEXT_WINDOW_CHARS = 500
DEFAULT_TEXT_WINDOW_OVERLAP = 100
MAX_TEXT_WINDOW_CHARS = 4_096
MAX_SEMANTIC_WINDOWS = 20_000


@dataclass(frozen=True)
class WindowHit:
    """An anchor hit plus bounded neighboring source chunks."""

    chunk: Chunk
    score: float
    window_chunks: tuple[Chunk, ...]


@dataclass(frozen=True)
class TextWindow:
    """A deterministic overlapping slice mapped back to its source chunk."""

    window_id: str
    source: str
    document_id: str
    document_version_id: str
    chunk_id: str
    chunk_start_char: int
    chunk_end_char: int
    start_char: int
    end_char: int
    text: str


@dataclass(frozen=True)
class MatchedTextWindow:
    """The best semantic window that caused an original chunk to be ranked."""

    window: TextWindow
    cosine_similarity: float


@dataclass(frozen=True)
class WindowedChunkHit:
    """A page/chunk-level result with its best matching subwindow provenance."""

    chunk: Chunk
    score: float
    matched_window: MatchedTextWindow | None


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


def split_text_windows(
    chunks: Sequence[Chunk],
    *,
    window_chars: int = DEFAULT_TEXT_WINDOW_CHARS,
    overlap_chars: int = DEFAULT_TEXT_WINDOW_OVERLAP,
    max_windows: int = MAX_SEMANTIC_WINDOWS,
) -> tuple[TextWindow, ...]:
    """Split original chunks into bounded overlapping windows with source offsets.

    Character offsets are Python Unicode string offsets, matching the original
    chunk contract. The window end is exclusive, exactly like chunk offsets.
    """
    _validate_text_window_config(window_chars, overlap_chars, max_windows)
    seen: set[str] = set()
    windows: list[TextWindow] = []
    for chunk in sorted(chunks, key=lambda row: (row.document_id, row.version_id, row.start_char, row.chunk_id)):
        if chunk.chunk_id in seen:
            raise ValueError(f"duplicate chunk ID: {chunk.chunk_id}")
        seen.add(chunk.chunk_id)
        if not isinstance(chunk.text, str) or not chunk.text:
            raise ValueError(f"chunk {chunk.chunk_id} must contain non-empty text")
        if chunk.end_char - chunk.start_char != len(chunk.text):
            raise ValueError(f"chunk {chunk.chunk_id} offsets do not match its text length")
        local_start = 0
        while local_start < len(chunk.text):
            local_end = min(local_start + window_chars, len(chunk.text))
            text = chunk.text[local_start:local_end]
            source_start = chunk.start_char + local_start
            source_end = chunk.start_char + local_end
            digest_input = (
                f"{chunk.document_id}\0{chunk.version_id}\0{chunk.chunk_id}\0"
                f"{source_start}\0{source_end}\0{text}"
            ).encode("utf-8")
            windows.append(
                TextWindow(
                    window_id=sha256(digest_input).hexdigest(),
                    source=chunk.source,
                    document_id=chunk.document_id,
                    document_version_id=chunk.version_id,
                    chunk_id=chunk.chunk_id,
                    chunk_start_char=chunk.start_char,
                    chunk_end_char=chunk.end_char,
                    start_char=source_start,
                    end_char=source_end,
                    text=text,
                )
            )
            if len(windows) > max_windows:
                raise ValueError("semantic corpus exceeds max_windows before embedding")
            if local_end == len(chunk.text):
                break
            local_start = local_end - overlap_chars
    return tuple(windows)


def weighted_reciprocal_rank_fusion(
    rankings: Sequence[Sequence[str]],
    weights: Sequence[float],
    *,
    top_k: int,
    rank_constant: int = 60,
) -> tuple[RankedItem, ...]:
    """Fuse ordered ID rankings with explicit non-negative per-source weights."""
    if type(top_k) is not int or top_k < 0:
        raise ValueError("top_k must be a non-negative integer")
    if type(rank_constant) is not int or rank_constant <= 0:
        raise ValueError("rank_constant must be a positive integer")
    if len(rankings) != len(weights) or not rankings:
        raise ValueError("rankings and weights must have the same non-zero length")
    clean_weights = []
    for weight in weights:
        if isinstance(weight, bool) or not isinstance(weight, (int, float)):
            raise ValueError("weights must be finite non-negative numbers")
        try:
            converted = float(weight)
        except (OverflowError, TypeError, ValueError) as exc:
            raise ValueError("weights must be finite non-negative numbers") from exc
        if not isfinite(converted) or converted < 0:
            raise ValueError("weights must be finite non-negative numbers")
        clean_weights.append(converted)
    if not any(clean_weights):
        raise ValueError("at least one fusion weight must be positive")
    scores: dict[str, float] = {}
    for ranking, weight in zip(rankings, clean_weights):
        if weight == 0.0:
            continue
        if len(ranking) != len(set(ranking)):
            raise ValueError("each ranking must contain unique IDs")
        for rank, item_id in enumerate(ranking, start=1):
            if not isinstance(item_id, str) or not item_id:
                raise ValueError("ranked IDs must be non-empty strings")
            scores[item_id] = scores.get(item_id, 0.0) + weight / (rank_constant + rank)
    ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))[:top_k]
    return tuple(RankedItem(item_id, score) for item_id, score in ranked)


def build_windowed_e5_retrievers(
    chunks: Sequence[Chunk],
    encoder: object,
    *,
    window_chars: int = DEFAULT_TEXT_WINDOW_CHARS,
    overlap_chars: int = DEFAULT_TEXT_WINDOW_OVERLAP,
    dense_weight: float = 0.75,
    rrf_constant: int = 60,
    batch_size: int = 32,
    max_windows: int = MAX_SEMANTIC_WINDOWS,
    minimum_score: float | None = None,
    hybrid_minimum_score: float | None = None,
) -> dict[str, RetrieverSpec]:
    """Build opt-in E5 window ranking and dense-weighted window/BM25 hybrid.

    E5 retrieves the bounded subwindows. The score for each source chunk is the
    maximum cosine score among its windows, with the earliest deterministic
    window winning exact ties. Metrics and citations remain at original chunk
    granularity. Hybrid combines the full dense chunk ranking and lexical BM25
    ranking with weighted RRF; `dense_weight` is actually applied per rank.
    """
    if not chunks:
        raise ValueError("chunks must not be empty")
    if isinstance(dense_weight, bool) or not isinstance(dense_weight, (int, float)):
        raise ValueError("dense_weight must be a finite number from 0 to 1")
    try:
        dense_weight = float(dense_weight)
    except (OverflowError, TypeError, ValueError) as exc:
        raise ValueError("dense_weight must be a finite number from 0 to 1") from exc
    if not isfinite(dense_weight) or not 0 <= dense_weight <= 1:
        raise ValueError("dense_weight must be a finite number from 0 to 1")
    if type(batch_size) is not int or batch_size <= 0:
        raise ValueError("batch_size must be a positive integer")
    if type(rrf_constant) is not int or rrf_constant <= 0:
        raise ValueError("rrf_constant must be a positive integer")
    for field, threshold in (("minimum_score", minimum_score), ("hybrid_minimum_score", hybrid_minimum_score)):
        if threshold is not None and (
            isinstance(threshold, bool)
            or not isinstance(threshold, (int, float))
            or not isfinite(float(threshold))
        ):
            raise ValueError(f"{field} must be a finite number")

    windows = split_text_windows(
        chunks,
        window_chars=window_chars,
        overlap_chars=overlap_chars,
        max_windows=max_windows,
    )
    model_id = getattr(encoder, "model_id", None)
    revision = getattr(encoder, "revision", None)
    if not isinstance(model_id, str) or not model_id.strip():
        raise ValueError("encoder must declare a non-empty model_id")
    if not isinstance(revision, str) or not revision.strip():
        raise ValueError("encoder must declare an immutable revision")
    embedding_started = perf_counter()
    window_vectors: list[tuple[float, ...]] = []
    for start in range(0, len(windows), batch_size):
        batch = windows[start:start + batch_size]
        encoded = encoder.encode([window.text for window in batch], kind="passage")
        if len(encoded) != len(batch):
            raise ValueError("encoder returned the wrong number of window embeddings")
        window_vectors.extend(_checked_vector(vector) for vector in encoded)
    if len(window_vectors) != len(windows):
        raise ValueError("encoder returned the wrong number of window embeddings")
    dimensions = len(window_vectors[0])
    if any(len(vector) != dimensions for vector in window_vectors):
        raise ValueError("window embedding dimensions do not match")
    passage_embedding_seconds = perf_counter() - embedding_started

    vector_by_window = {window.window_id: vector for window, vector in zip(windows, window_vectors)}
    window_by_id = {window.window_id: window for window in windows}
    chunk_by_id = {chunk.chunk_id: chunk for chunk in chunks}
    lexical = BM25Index(chunks)
    lexical_weight = 1.0 - dense_weight
    metadata_base = {
        "model_id": model_id,
        "model_revision": revision,
        "query_prefix": "query: ",
        "passage_prefix": "passage: ",
        "window_chars": window_chars,
        "window_overlap_chars": overlap_chars,
        "window_count": len(windows),
        "original_chunk_count": len(chunks),
        "window_aggregation": "maximum cosine per original chunk",
        "rrf_constant": rrf_constant,
        "embedding_batch_size": batch_size,
        "passage_embedding_seconds": passage_embedding_seconds,
        **getattr(encoder, "runtime_metadata", {}),
    }

    def dense_rows(query: str) -> tuple[tuple[Chunk, float, MatchedTextWindow], ...]:
        query_vectors = encoder.encode([query], kind="query")
        if len(query_vectors) != 1:
            raise ValueError("encoder returned the wrong number of query embeddings")
        query_vector = _checked_vector(query_vectors[0])
        if len(query_vector) != dimensions:
            raise ValueError("query embedding dimension does not match window embeddings")
        window_ranking = exact_cosine(
            query_vector,
            vector_by_window,
            top_k=len(windows),
            max_vectors=max_windows,
        )
        best_by_chunk: dict[str, tuple[float, TextWindow]] = {}
        for item in window_ranking:
            window = window_by_id[item.item_id]
            current = best_by_chunk.get(window.chunk_id)
            if current is None or item.score > current[0]:
                best_by_chunk[window.chunk_id] = (item.score, window)
        rows = [
            (chunk_by_id[chunk_id], score, MatchedTextWindow(window, score))
            for chunk_id, (score, window) in best_by_chunk.items()
        ]
        rows.sort(key=lambda row: (-row[1], row[0].chunk_id))
        return tuple(rows)

    def windowed_e5(query: str, k: int) -> tuple[WindowedChunkHit, ...]:
        if type(k) is not int or k < 0:
            raise ValueError("top_k must be a non-negative integer")
        rows = dense_rows(query)[:k]
        return tuple(WindowedChunkHit(chunk, score, matched) for chunk, score, matched in rows)

    def windowed_hybrid(query: str, k: int) -> tuple[WindowedChunkHit, ...]:
        dense = dense_rows(query)
        dense_ids = [row[0].chunk_id for row in dense]
        dense_matched = {row[0].chunk_id: row[2] for row in dense}
        lexical_hits = lexical.search(query, top_k=len(chunks))
        lexical_ids = [hit.chunk.chunk_id for hit in lexical_hits]
        fused = weighted_reciprocal_rank_fusion(
            [dense_ids, lexical_ids],
            [dense_weight, lexical_weight],
            top_k=k,
            rank_constant=rrf_constant,
        )
        return tuple(
            WindowedChunkHit(chunk_by_id[item.item_id], item.score, dense_matched.get(item.item_id))
            for item in fused
        )

    return {
        "windowed_e5": RetrieverSpec(
            windowed_e5,
            "cosine descending, chunk ID ascending",
            minimum_score,
            {**metadata_base, "strategy": "E5 over overlapping text windows; max-score aggregation"},
        ),
        "windowed_hybrid": RetrieverSpec(
            windowed_hybrid,
            "weighted RRF score descending, chunk ID ascending",
            hybrid_minimum_score,
            {
                **metadata_base,
                "strategy": "E5 text windows + original-chunk BM25; weighted RRF",
                "dense_rrf_weight": dense_weight,
                "lexical_rrf_weight": lexical_weight,
                "hybrid_minimum_score": hybrid_minimum_score,
            },
        ),
    }


def _checked_vector(vector: Sequence[float]) -> tuple[float, ...]:
    if isinstance(vector, (str, bytes)):
        raise ValueError("embedding must be a numeric vector")
    values = tuple(vector)
    if not values or len(values) > 4_096:
        raise ValueError("embedding dimensions must be between 1 and 4096")
    converted_values = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("embedding must contain finite numeric values")
        try:
            number = float(value)
        except (OverflowError, TypeError, ValueError) as exc:
            raise ValueError("embedding must contain finite numeric values") from exc
        if not isfinite(number):
            raise ValueError("embedding must contain finite numeric values")
        converted_values.append(number)
    converted = tuple(converted_values)
    if not any(value != 0.0 for value in converted):
        raise ValueError("embedding must not be a zero vector")
    return converted


def _validate_text_window_config(window_chars: int, overlap_chars: int, max_windows: int) -> None:
    if type(window_chars) is not int or not 1 <= window_chars <= MAX_TEXT_WINDOW_CHARS:
        raise ValueError(f"window_chars must be an integer from 1 to {MAX_TEXT_WINDOW_CHARS}")
    if type(overlap_chars) is not int or not 0 <= overlap_chars < window_chars:
        raise ValueError("overlap_chars must be an integer from zero to less than window_chars")
    if type(max_windows) is not int or max_windows <= 0:
        raise ValueError("max_windows must be a positive integer")


def _validate_radius(radius: int) -> None:
    if type(radius) is not int or not 0 <= radius <= MAX_WINDOW_RADIUS:
        raise ValueError(f"window radius must be an integer from 0 to {MAX_WINDOW_RADIUS}")
