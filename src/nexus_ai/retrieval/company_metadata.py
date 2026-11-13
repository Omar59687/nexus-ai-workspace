"""Validated, model-independent company/year metadata for indexed collections.

The registry is an in-process reference implementation. Collection records bind
metadata to an immutable document version and source digest; durable persistence
can implement the same interface without changing retrieval semantics.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from itertools import islice
from pathlib import PurePosixPath
from threading import RLock
from typing import Iterable, Mapping

from nexus_ai.documents.types import IndexedDocument

_COMPANY_ID = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
MAX_COLLECTION_DOCUMENTS = 150


class MetadataIntegrityError(RuntimeError):
    """Collection metadata is absent, incomplete, or stale for active sources."""


@dataclass(frozen=True)
class CompanyYearDocument:
    workspace_id: str
    collection_id: str
    document_id: str
    document_version_id: str
    source_path: str
    source_sha256: str
    company_id: str
    financial_year: int
    duplicate_of_document_id: str | None = None


@dataclass(frozen=True)
class CompanyYearFilter:
    collection_id: str
    company: str | None = None
    financial_year: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.collection_id, str) or not self.collection_id.strip() or len(self.collection_id) > 128:
            raise ValueError("collection_id must be non-empty and at most 128 characters")
        if self.company is None and self.financial_year is None:
            raise ValueError("at least one company or financial_year filter is required")
        if self.company is not None:
            _validate_company_name(self.company)
        if self.financial_year is not None:
            _validate_year(self.financial_year)


@dataclass(frozen=True)
class CollectionMetadataSnapshot:
    workspace_id: str
    collection_id: str
    revision_id: str
    company_names: tuple[tuple[str, tuple[str, ...]], ...]
    documents: tuple[CompanyYearDocument, ...]

    def company_id_for_name(self, value: str) -> str:
        key = normalize_company_name(value)
        for company_id, names in self.company_names:
            if key == company_id or key in {normalize_company_name(name) for name in names}:
                return company_id
        raise ValueError("company filter does not match a registered company name")


class CompanyYearMetadataCatalog:
    """Atomic in-memory collection metadata registry for model-free filtering.

    Replacing metadata produces a deterministic new revision. Each member must
    be explicitly rebound to its current immutable source version and digest.
    """

    def __init__(self, *, max_documents: int = MAX_COLLECTION_DOCUMENTS) -> None:
        if type(max_documents) is not int or not 1 <= max_documents <= MAX_COLLECTION_DOCUMENTS:
            raise ValueError(f"max_documents must be between 1 and {MAX_COLLECTION_DOCUMENTS}")
        self.max_documents = max_documents
        self._snapshots: dict[tuple[str, str], CollectionMetadataSnapshot] = {}
        self._lock = RLock()

    def replace_collection(
        self,
        *,
        workspace_id: str,
        collection_id: str,
        companies: Mapping[str, Iterable[str]],
        documents: Iterable[CompanyYearDocument],
    ) -> CollectionMetadataSnapshot:
        _validate_scope(workspace_id, collection_id)
        if not isinstance(companies, Mapping) or not companies:
            raise ValueError("companies must map stable company IDs to explicit aliases")
        if len(companies) > self.max_documents:
            raise ValueError("company catalog exceeds the collection document bound")
        alias_rows: list[tuple[str, tuple[str, ...]]] = []
        aliases: dict[str, str] = {}
        for company_id, raw_names in companies.items():
            if not isinstance(company_id, str) or not _COMPANY_ID.fullmatch(company_id):
                raise ValueError("company IDs must be stable lowercase ASCII identifiers")
            id_key = normalize_company_name(company_id)
            if id_key in aliases and aliases[id_key] != company_id:
                raise ValueError("company ID conflicts with another company's alias")
            aliases[id_key] = company_id
            if isinstance(raw_names, (str, bytes)):
                raise ValueError("company aliases must be a sequence of names")
            names = tuple(islice(raw_names, 21))
            if not names or len(names) > 20:
                raise ValueError("each company needs between 1 and 20 explicit names")
            normalized_names: set[str] = set()
            for name in names:
                _validate_company_name(name)
                key = normalize_company_name(name)
                if key in normalized_names:
                    raise ValueError("duplicate company alias")
                normalized_names.add(key)
                if key in aliases and aliases[key] != company_id:
                    raise ValueError("company alias is ambiguous")
                aliases[key] = company_id
            alias_rows.append((company_id, names))
        alias_rows.sort(key=lambda row: row[0])

        rows = tuple(islice(documents, self.max_documents + 1))
        if not rows or len(rows) > self.max_documents:
            raise ValueError(f"collection must contain between 1 and {self.max_documents} documents")
        seen_ids: set[str] = set()
        seen_paths: set[str] = set()
        for row in rows:
            if not isinstance(row, CompanyYearDocument):
                raise ValueError("documents must be CompanyYearDocument records")
            if (row.workspace_id, row.collection_id) != (workspace_id, collection_id):
                raise ValueError("document metadata scope does not match its collection")
            _validate_identity(row)
            if row.company_id not in companies:
                raise ValueError("document references an unknown company ID")
            if row.document_id in seen_ids:
                raise ValueError("a document may occur only once in a collection")
            path_key = row.source_path.casefold()
            if path_key in seen_paths:
                raise ValueError("source paths must be unique within a collection")
            seen_ids.add(row.document_id)
            seen_paths.add(path_key)
        by_id = {row.document_id: row for row in rows}
        by_digest: dict[str, list[CompanyYearDocument]] = {}
        for row in rows:
            by_digest.setdefault(row.source_sha256, []).append(row)
        for digest_rows in by_digest.values():
            if len(digest_rows) == 1:
                if digest_rows[0].duplicate_of_document_id is not None:
                    raise ValueError("duplicate_of_document_id must refer to a duplicate source in this collection")
                continue
            roots = [row for row in digest_rows if row.duplicate_of_document_id is None]
            if len(roots) != 1:
                raise ValueError("duplicate source content needs exactly one canonical document")
            root = roots[0]
            for duplicate in digest_rows:
                if duplicate is root:
                    continue
                target = by_id.get(duplicate.duplicate_of_document_id or "")
                if (target is not root or target.source_sha256 != duplicate.source_sha256
                        or target.company_id != duplicate.company_id
                        or target.financial_year != duplicate.financial_year):
                    raise ValueError("duplicate source must link to its canonical document with matching metadata")
        rows = tuple(sorted(rows, key=lambda row: row.document_id))
        body = {
            "workspace_id": workspace_id,
            "collection_id": collection_id,
            "companies": alias_rows,
            "documents": [row.__dict__ for row in rows],
        }
        revision_id = hashlib.sha256(json.dumps(
            body, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")).hexdigest()
        snapshot = CollectionMetadataSnapshot(
            workspace_id=workspace_id,
            collection_id=collection_id,
            revision_id=revision_id,
            company_names=tuple(alias_rows),
            documents=rows,
        )
        # One reference assignment is the update boundary for concurrent readers.
        with self._lock:
            self._snapshots[(workspace_id, collection_id)] = snapshot
        return snapshot

    def get(self, workspace_id: str, collection_id: str) -> CollectionMetadataSnapshot:
        _validate_scope(workspace_id, collection_id)
        with self._lock:
            try:
                return self._snapshots[(workspace_id, collection_id)]
            except KeyError as exc:
                raise MetadataIntegrityError("collection metadata is not registered for this workspace") from exc

    def resolve(
        self,
        repository,
        *,
        workspace_id: str,
        query_filter: CompanyYearFilter,
    ) -> tuple[CollectionMetadataSnapshot, tuple[CompanyYearDocument, ...]]:
        snapshot = self.get(workspace_id, query_filter.collection_id)
        company_id = snapshot.company_id_for_name(query_filter.company) if query_filter.company is not None else None

        # Validate the whole declared collection. Returning a partial subset when
        # one member was deleted, replaced, or moved could make a filter appear
        # valid while the manifest's scope is no longer true.
        for metadata in snapshot.documents:
            indexed = repository.get_active(workspace_id, metadata.document_id)
            if not _matches_active(metadata, indexed):
                raise MetadataIntegrityError("collection metadata is stale or incomplete; refresh the collection snapshot")

        selected = tuple(
            row for row in snapshot.documents
            if (company_id is None or row.company_id == company_id)
            and (query_filter.financial_year is None or row.financial_year == query_filter.financial_year)
        )
        return snapshot, selected


def normalize_company_name(value: str) -> str:
    """Normalize only Unicode compatibility, case, and whitespace; no fuzzy matching."""
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _validate_company_name(value: object) -> None:
    if (not isinstance(value, str) or not value.strip() or len(value) > 160
            or any(unicodedata.category(ch).startswith("C") for ch in value)):
        raise ValueError("company names must be non-empty, bounded plain text")


def _validate_year(value: object) -> None:
    if type(value) is not int or not 1900 <= value <= 2100:
        raise ValueError("financial_year must be an integer between 1900 and 2100")


def _validate_scope(workspace_id: str, collection_id: str) -> None:
    if not isinstance(workspace_id, str) or not workspace_id.strip() or len(workspace_id) > 128:
        raise ValueError("workspace_id must be non-empty and at most 128 characters")
    if not isinstance(collection_id, str) or not collection_id.strip() or len(collection_id) > 128:
        raise ValueError("collection_id must be non-empty and at most 128 characters")


def _validate_identity(row: CompanyYearDocument) -> None:
    if any(not isinstance(value, str) or not value.strip() or len(value) > limit for value, limit in (
        (row.document_id, 128), (row.document_version_id, 128), (row.source_path, 512), (row.company_id, 64)
    )):
        raise ValueError("document metadata identity fields are invalid")
    if not _SHA256.fullmatch(row.document_version_id):
        raise ValueError("document_version_id must be a lowercase SHA-256 identity")
    path = PurePosixPath(row.source_path)
    if path.is_absolute() or ".." in path.parts or "\\" in row.source_path or str(path) != row.source_path:
        raise ValueError("source_path must be a normalized workspace-relative POSIX path")
    if not _SHA256.fullmatch(row.source_sha256):
        raise ValueError("source_sha256 must be a lowercase SHA-256 digest")
    _validate_year(row.financial_year)


def _matches_active(metadata: CompanyYearDocument, indexed: IndexedDocument | None) -> bool:
    return bool(indexed is not None and (
        indexed.document.workspace_id == metadata.workspace_id
        and indexed.document.document_id == metadata.document_id
        and indexed.document.version_id == metadata.document_version_id
        and indexed.document.source_path == metadata.source_path
        and indexed.document.content_sha256 == metadata.source_sha256
    ))
