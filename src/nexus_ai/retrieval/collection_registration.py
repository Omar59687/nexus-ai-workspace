"""Fail-closed bridge from owner-approved collection manifest to active index metadata.

No file reads, language models, database schema writes or implicit ingestion.
The manifest must be validated separately; registration requires every declared
document to already be active with a matching path, company, and financial year.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping

from nexus_ai.documents.collection_preflight import _manifest_entries
from nexus_ai.documents.service import stable_document_id
from nexus_ai.retrieval.company_metadata import (
    CollectionMetadataSnapshot, CompanyYearDocument, CompanyYearMetadataCatalog,
    MetadataIntegrityError, normalize_company_name,
)
from nexus_ai.retrieval.repository import DocumentIndexRepository


def register_indexed_manifest(
    *,
    catalog: CompanyYearMetadataCatalog,
    repository: DocumentIndexRepository,
    workspace_id: str,
    collection_id: str,
    entries: list[dict[str, object]],
    companies: Mapping[str, Iterable[str]],
) -> CollectionMetadataSnapshot:
    """Atomically register exact manifest/index identities, or change nothing.

    Company labels are owner supplied; each must resolve to one registered
    company ID or exact explicit alias. Never guess identity from filenames.
    """
    checked = _manifest_entries({"documents": entries})
    # Creating this temporary snapshot allows the existing catalog's alias
    # validation logic to reject collisions before any live registration.
    # Instead, resolve company names locally with exact normalized comparisons.
    lookup: dict[str, str] = {}
    for company_id, names in companies.items():
        if isinstance(names, (str, bytes)):
            raise ValueError("company aliases must be explicit sequences")
        values = tuple(names)
        if len(values) > 20:
            raise ValueError("too many aliases")
        for name in (company_id, *values):
            if not isinstance(name, str) or not name.strip():
                raise ValueError("invalid company name")
            key = normalize_company_name(name)
            if key in lookup and lookup[key] != company_id:
                raise ValueError("ambiguous company alias")
            lookup[key] = company_id

    rows = []
    canonical_by_digest: dict[str, CompanyYearDocument] = {}
    for entry in checked:
        path = str(entry["path"])
        document_id = stable_document_id(workspace_id, path)
        active = repository.get_active(workspace_id, document_id)
        if active is None:
            raise MetadataIntegrityError("manifest document is not indexed in the authorized workspace")
        document = active.document
        if (document.workspace_id != workspace_id
                or document.document_id != document_id
                or document.source_path != path):
            raise MetadataIntegrityError("indexed identity does not match manifest path")
        company_id = lookup.get(normalize_company_name(str(entry["company"])))
        if company_id is None:
            raise MetadataIntegrityError("manifest company label is not registered")
        duplicate = canonical_by_digest.get(document.content_sha256)
        if duplicate is not None and (
            duplicate.company_id != company_id
            or duplicate.financial_year != entry["year"]
        ):
            raise MetadataIntegrityError("duplicate source bytes have conflicting company/year metadata")
        row = CompanyYearDocument(
            workspace_id=workspace_id,
            collection_id=collection_id,
            document_id=document_id,
            document_version_id=document.version_id,
            source_path=path,
            source_sha256=document.content_sha256,
            company_id=company_id,
            financial_year=int(entry["year"]),
            duplicate_of_document_id=duplicate.document_id if duplicate else None,
        )
        canonical_by_digest.setdefault(document.content_sha256, row)
        rows.append(row)

    # replace_collection is the only mutation; it performs full validation and
    # publishes one immutable snapshot, never a partially registered collection.
    return catalog.replace_collection(
        workspace_id=workspace_id,
        collection_id=collection_id,
        companies=companies,
        documents=rows,
    )
