"""Optional, local-only multilingual dense/hybrid retrieval experiments.

Ordinary tests use injected encoders and never import or download ML runtimes.
The E5 adapter loads only an already cached model at an immutable revision.
"""

from __future__ import annotations

import math
import re
import time
from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from experiments.rag_prototype import BM25Index, Chunk, ChunkHit, RankedItem, exact_cosine, reciprocal_rank_fusion
from experiments.rag_prototype.evaluation import RetrieverSpec


E5_MODEL_ID = "intfloat/multilingual-e5-small"
E5_MODEL_REVISION = "614241f622f53c4eeff9890bdc4f31cfecc418b3"


class TextEncoder(Protocol):
    model_id: str
    revision: str

    def encode(self, texts: Sequence[str], *, kind: str) -> Sequence[Sequence[float]]: ...


class DenseRuntimeUnavailable(RuntimeError):
    """Raised if the optional embedding runtime or local weights are unavailable."""


def _validated_vector(vector: Any, *, label: str, dimensions: int | None = None) -> tuple[float, ...]:
    if isinstance(vector, (str, bytes)):
        raise ValueError(f"{label} must be a numeric vector")
    try:
        values = tuple(vector)
    except TypeError as exc:
        raise ValueError(f"{label} must be a numeric vector") from exc
    if not values or len(values) > 4_096:
        raise ValueError(f"{label} dimensions must be between 1 and 4096")
    if dimensions is not None and len(values) != dimensions:
        raise ValueError(f"{label} dimension does not match passage embeddings")
    if any(
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        for value in values
    ):
        raise ValueError(f"{label} must contain only finite numeric values")
    converted = tuple(float(value) for value in values)
    if not any(value != 0.0 for value in converted):
        raise ValueError(f"{label} must not be a zero vector")
    return converted


class LocalE5Encoder:
    """Pinned E5-small adapter with local-files-only loading and required prefixes."""

    model_id = E5_MODEL_ID

    def __init__(self, *, revision: str = E5_MODEL_REVISION, device: str = "cpu") -> None:
        if not re.fullmatch(r"[0-9a-f]{40}", revision):
            raise ValueError("model revision must be a full immutable commit SHA")
        self.revision = revision
        started = time.perf_counter()
        try:
            import torch
            import torch.nn.functional as functional
            import transformers
            from transformers import AutoModel, AutoTokenizer
        except ImportError as exc:
            raise DenseRuntimeUnavailable(
                "dense retrieval requires optional torch and transformers packages"
            ) from exc
        try:
            self._torch = torch
            self._functional = functional
            self._tokenizer = AutoTokenizer.from_pretrained(
                self.model_id, revision=revision, local_files_only=True, trust_remote_code=False
            )
            self._model = AutoModel.from_pretrained(
                self.model_id, revision=revision, local_files_only=True, trust_remote_code=False
            ).to(device)
            self._model.eval()
            self.device = device
            self.runtime_metadata = {
                "device": device,
                "torch_version": torch.__version__,
                "transformers_version": transformers.__version__,
                "model_load_seconds": time.perf_counter() - started,
            }
        except Exception as exc:
            raise DenseRuntimeUnavailable(
                f"pinned E5 revision {revision} is not available in the local model cache"
            ) from exc

    def encode(self, texts: Sequence[str], *, kind: str, batch_size: int = 32) -> tuple[tuple[float, ...], ...]:
        if kind not in ("query", "passage"):
            raise ValueError("kind must be query or passage")
        if type(batch_size) is not int or batch_size <= 0:
            raise ValueError("batch_size must be a positive integer")
        if any(not isinstance(text, str) or not text.strip() for text in texts):
            raise ValueError("texts must contain non-empty strings")
        result = []
        for start in range(0, len(texts), batch_size):
            prefixed = [f"{kind}: {text}" for text in texts[start:start + batch_size]]
            batch = self._tokenizer(
                prefixed, max_length=512, padding=True, truncation=True, return_tensors="pt"
            ).to(self.device)
            with self._torch.inference_mode():
                outputs = self._model(**batch)
                mask = batch["attention_mask"][..., None].to(outputs.last_hidden_state.dtype)
                pooled = (outputs.last_hidden_state * mask).sum(dim=1) / mask.sum(dim=1).clamp(min=1)
                normalized = self._functional.normalize(pooled, p=2, dim=1)
            result.extend(tuple(float(value) for value in row) for row in normalized.cpu().tolist())
        return tuple(result)


def build_dense_hybrid_retrievers(
    chunks: Sequence[Chunk],
    encoder: TextEncoder,
    *,
    rrf_constant: int = 60,
    minimum_score: float | None = None,
    hybrid_minimum_score: float | None = None,
    batch_size: int = 32,
    max_dense_chunks: int = 20_000,
) -> dict[str, RetrieverSpec]:
    """Build E5 and raw-BM25+E5 RRF strategies over the same chunk set."""
    if not chunks:
        raise ValueError("chunks must not be empty")
    if type(rrf_constant) is not int or rrf_constant <= 0:
        raise ValueError("rrf_constant must be a positive integer")
    if type(batch_size) is not int or batch_size <= 0:
        raise ValueError("batch_size must be a positive integer")
    if type(max_dense_chunks) is not int or max_dense_chunks <= 0:
        raise ValueError("max_dense_chunks must be a positive integer")
    if len(chunks) > max_dense_chunks:
        raise ValueError("dense corpus exceeds max_dense_chunks before embedding")
    if len({chunk.chunk_id for chunk in chunks}) != len(chunks):
        raise ValueError("duplicate chunk IDs are not allowed")
    for name, value in (
        ("minimum_score", minimum_score),
        ("hybrid_minimum_score", hybrid_minimum_score),
    ):
        if value is not None and (
            isinstance(value, bool)
            or not isinstance(value, (float, int))
            or not math.isfinite(value)
        ):
            raise ValueError(f"{name} must be a finite number")
    embedding_started = time.perf_counter()
    passage_vectors_list = []
    for start in range(0, len(chunks), batch_size):
        passage_vectors_list.extend(
            encoder.encode([chunk.text for chunk in chunks[start:start + batch_size]], kind="passage")
        )
    if len(passage_vectors_list) != len(chunks):
        raise ValueError("encoder returned the wrong number of passage embeddings")
    first = _validated_vector(passage_vectors_list[0], label="passage embedding")
    passage_vectors = (first, *(
        _validated_vector(vector, label="passage embedding", dimensions=len(first))
        for vector in passage_vectors_list[1:]
    ))
    embedding_seconds = time.perf_counter() - embedding_started
    vectors = {chunk.chunk_id: vector for chunk, vector in zip(chunks, passage_vectors)}
    chunk_by_id = {chunk.chunk_id: chunk for chunk in chunks}
    lexical = BM25Index(chunks)
    metadata = {
        "model_id": encoder.model_id,
        "model_revision": encoder.revision,
        "query_prefix": "query: ",
        "passage_prefix": "passage: ",
        "embedding_count": len(chunks),
        "embedding_batch_size": batch_size,
        "passage_embedding_seconds": embedding_seconds,
        "rrf_constant": rrf_constant,
        **getattr(encoder, "runtime_metadata", {}),
    }

    def dense(query: str, k: int) -> tuple[ChunkHit, ...]:
        encoded = encoder.encode([query], kind="query")
        if len(encoded) != 1:
            raise ValueError("encoder returned the wrong number of query embeddings")
        query_vector = _validated_vector(encoded[0], label="query embedding", dimensions=len(first))
        ranked = exact_cosine(query_vector, vectors, top_k=k)
        return tuple(ChunkHit(chunk_by_id[item.item_id], item.score) for item in ranked)

    def hybrid(query: str, k: int) -> tuple[ChunkHit, ...]:
        candidate_depth = min(len(chunks), max(20, k))
        encoded = encoder.encode([query], kind="query")
        if len(encoded) != 1:
            raise ValueError("encoder returned the wrong number of query embeddings")
        query_vector = _validated_vector(encoded[0], label="query embedding", dimensions=len(first))
        dense_ids = [item.item_id for item in exact_cosine(query_vector, vectors, top_k=candidate_depth)]
        lexical_ids = [hit.chunk.chunk_id for hit in lexical.search(query, top_k=candidate_depth)]
        fused = reciprocal_rank_fusion([lexical_ids, dense_ids], top_k=k, rank_constant=rrf_constant)
        return tuple(ChunkHit(chunk_by_id[item.item_id], item.score) for item in fused)

    return {
        "dense_e5_small": RetrieverSpec(
            dense,
            "cosine descending, chunk ID ascending",
            minimum_score,
            {**metadata, "strategy": "dense cosine"},
        ),
        "hybrid_bm25_e5_rrf": RetrieverSpec(
            hybrid,
            "RRF score descending, chunk ID ascending",
            hybrid_minimum_score,
            {
                **metadata,
                "strategy": "raw BM25 + dense RRF",
                "hybrid_minimum_rrf_score": hybrid_minimum_score,
            },
        ),
    }
