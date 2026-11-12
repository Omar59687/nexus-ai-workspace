"""Bounded, offline embedding-provider contract and pinned E5 adapter."""
from __future__ import annotations

import math
import re
import hashlib
from dataclasses import dataclass
from typing import Any, Protocol, Sequence

from experiments.rag_prototype.dense_retrieval import (
    DenseRuntimeUnavailable,
    E5_MODEL_ID,
    E5_MODEL_REVISION,
    LocalE5Encoder,
)
from nexus_ai.documents.types import IndexedWindow, SourceChunk


MAX_EMBEDDING_DIMENSIONS = 4_096
DEFAULT_BATCH_SIZE = 32
DEFAULT_WINDOW_CHARS = 500
DEFAULT_WINDOW_OVERLAP = 100
MAX_INDEX_WINDOWS = 20_000


class EmbeddingUnavailableError(RuntimeError):
    """The configured local embedding provider cannot run in this environment."""


class EmbeddingProvider(Protocol):
    model_id: str
    revision: str

    def embed(self, texts: Sequence[str], *, input_type: str) -> tuple[tuple[float, ...], ...]: ...


class E5EmbeddingProvider:
    """Adapter for the existing pinned multilingual E5 encoder; never downloads."""

    preprocessing_id = "e5-query-passage-prefix-mean-pooling-l2-v1"
    embedding_dimensions = 384

    def __init__(
        self,
        *,
        encoder: Any | None = None,
        revision: str = E5_MODEL_REVISION,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> None:
        if not re.fullmatch(r"[0-9a-f]{40}", revision):
            raise ValueError("embedding revision must be an immutable 40-character commit SHA")
        _positive_integer(batch_size, "batch_size")
        try:
            self._encoder = encoder if encoder is not None else LocalE5Encoder(revision=revision)
        except DenseRuntimeUnavailable as exc:
            raise EmbeddingUnavailableError(str(exc)) from exc
        self.model_id = getattr(self._encoder, "model_id", E5_MODEL_ID)
        self.revision = getattr(self._encoder, "revision", revision)
        self.batch_size = batch_size

    def embed(self, texts: Sequence[str], *, input_type: str) -> tuple[tuple[float, ...], ...]:
        if input_type not in ("query", "passage"):
            raise ValueError("input_type must be query or passage")
        if any(not isinstance(text, str) or not text.strip() for text in texts):
            raise ValueError("embedding texts must be non-empty strings")
        rows: list[tuple[float, ...]] = []
        dimensions: int | None = None
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start:start + self.batch_size]
            encoded = self._encoder.encode(batch, kind=input_type)
            if len(encoded) != len(batch):
                raise ValueError("embedding provider returned the wrong number of vectors")
            for vector in encoded:
                clean = validate_vector(vector, dimensions=dimensions)
                dimensions = dimensions or len(clean)
                rows.append(clean)
        return tuple(rows)


def validate_vector(vector: Any, *, dimensions: int | None = None) -> tuple[float, ...]:
    if isinstance(vector, (str, bytes)):
        raise ValueError("embedding must be a numeric vector")
    try:
        values = tuple(vector)
    except TypeError as exc:
        raise ValueError("embedding must be a numeric vector") from exc
    if not values or len(values) > MAX_EMBEDDING_DIMENSIONS:
        raise ValueError("embedding dimensions must be between 1 and 4096")
    if dimensions is not None and len(values) != dimensions:
        raise ValueError("embedding dimensions do not match")
    result = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("embedding coordinates must be finite numbers")
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("embedding coordinates must be finite numbers") from exc
        if not math.isfinite(number):
            raise ValueError("embedding coordinates must be finite numbers")
        result.append(number)
    if not any(result):
        raise ValueError("embedding vector must have a non-zero norm")
    return tuple(result)


@dataclass(frozen=True)
class WindowDraft:
    window_id: str
    chunk_id: str
    page_number: int | None
    start_char: int | None
    end_char: int | None
    local_start: int
    local_end: int
    text: str


def create_text_windows(
    chunks: Sequence[SourceChunk],
    *,
    window_chars: int = DEFAULT_WINDOW_CHARS,
    overlap_chars: int = DEFAULT_WINDOW_OVERLAP,
    max_windows: int = MAX_INDEX_WINDOWS,
) -> tuple[WindowDraft, ...]:
    if type(window_chars) is not int or not 1 <= window_chars <= 4_096:
        raise ValueError("window_chars must be between 1 and 4096")
    if type(overlap_chars) is not int or not 0 <= overlap_chars < window_chars:
        raise ValueError("overlap_chars must be less than window_chars")
    _positive_integer(max_windows, "max_windows")
    windows = []
    seen = set()
    for chunk in sorted(chunks, key=lambda c: (c.document_id, c.version_id, c.page_number or 0, c.chunk_id)):
        if chunk.chunk_id in seen:
            raise ValueError("duplicate chunk IDs are not allowed")
        seen.add(chunk.chunk_id)
        if not chunk.text:
            raise ValueError("cannot embed an empty chunk")
        local_start = 0
        while local_start < len(chunk.text):
            local_end = min(local_start + window_chars, len(chunk.text))
            text = chunk.text[local_start:local_end]
            source_start = chunk.start_char + local_start if chunk.offsets_reliable and chunk.start_char is not None else None
            source_end = chunk.start_char + local_end if chunk.offsets_reliable and chunk.start_char is not None else None
            material = "\0".join((chunk.chunk_id, str(local_start), str(local_end), text))
            window_id = hashlib.sha256(material.encode("utf-8")).hexdigest()
            windows.append(WindowDraft(window_id, chunk.chunk_id, chunk.page_number, source_start, source_end,
                                       local_start, local_end, text))
            if len(windows) > max_windows:
                raise ValueError("index exceeds max_windows before embedding")
            if local_end == len(chunk.text):
                break
            local_start = local_end - overlap_chars
    return tuple(windows)


def embed_windows(
    drafts: Sequence[WindowDraft],
    provider: EmbeddingProvider,
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
    max_vector_coordinates: int | None = None,
) -> tuple[tuple[float, ...], ...]:
    _positive_integer(batch_size, "batch_size")
    if max_vector_coordinates is not None:
        _positive_integer(max_vector_coordinates, "max_vector_coordinates")
    vectors: list[tuple[float, ...]] = []
    dimensions: int | None = None
    coordinates = 0
    for start in range(0, len(drafts), batch_size):
        batch = drafts[start:start + batch_size]
        encoded = provider.embed([row.text for row in batch], input_type="passage")
        if len(encoded) != len(batch):
            raise ValueError("embedding provider returned the wrong number of vectors")
        for vector in encoded:
            clean = validate_vector(vector, dimensions=dimensions)
            dimensions = dimensions or len(clean)
            coordinates += len(clean)
            if max_vector_coordinates is not None and coordinates > max_vector_coordinates:
                raise ValueError("index exceeds max_vector_coordinates during embedding")
            vectors.append(clean)
    return tuple(vectors)


def _positive_integer(value: int, name: str) -> None:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
