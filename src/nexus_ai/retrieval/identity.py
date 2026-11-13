"""Deterministic identities for source versions, processing, and index generations."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import PurePosixPath
from typing import Any


def stable_identity(*, kind: str, values: dict[str, Any]) -> str:
    payload = json.dumps(
        {"kind": kind, "values": values},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def stable_source_version_id(document_id: str, content_sha256: str) -> str:
    return stable_identity(kind="source-version-v1", values={
        "document_id": document_id,
        "content_sha256": content_sha256,
    })


def stable_document_id(workspace_id: str, source_path: str) -> str:
    """Stable workspace-scoped identity for one canonical relative source path."""
    normalized = os.path.normcase(PurePosixPath(source_path).as_posix())
    return hashlib.sha256(f"document-v1\0{workspace_id}\0{normalized}".encode("utf-8")).hexdigest()


def stable_processing_id(
    *,
    extractor_name: str,
    extractor_version: str,
    media_type: str,
    offsets_reliable: bool,
    chunker_fingerprint: str,
) -> str:
    return stable_identity(kind="document-processing-v1", values={
        "extractor_name": extractor_name,
        "extractor_version": extractor_version,
        "media_type": media_type,
        "offsets_reliable": offsets_reliable,
        "chunker_fingerprint": chunker_fingerprint,
    })


def stable_index_generation_id(
    *,
    document_id: str,
    source_version_id: str,
    processing_id: str,
    embedding_model_id: str,
    embedding_revision: str,
    embedding_dimensions: int,
    chunker_fingerprint: str,
    window_chars: int,
    window_overlap_chars: int,
    preprocessing_id: str,
) -> str:
    return stable_identity(kind="index-generation-v1", values={
        "document_id": document_id,
        "source_version_id": source_version_id,
        "processing_id": processing_id,
        "embedding_model_id": embedding_model_id,
        "embedding_revision": embedding_revision,
        "embedding_dimensions": embedding_dimensions,
        "chunker_fingerprint": chunker_fingerprint,
        "window_chars": window_chars,
        "window_overlap_chars": window_overlap_chars,
        "preprocessing_id": preprocessing_id,
    })
