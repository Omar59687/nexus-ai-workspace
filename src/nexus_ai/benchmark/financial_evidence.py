"""Deterministic financial-evidence evaluation over the durable collection path.

This runner is for explicitly synthetic fixtures. It uses the existing
collection index, metadata registration, model-free lexical retriever, and
citation contract. It never invokes an LLM, embedding provider, database, or
external service.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import tempfile
import unicodedata
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Mapping

from nexus_ai.documents.collection_index import CollectionIndexService
from nexus_ai.documents.types import ExtractedPage, ExtractionResult
from nexus_ai.retrieval.collection_lexical import CollectionLexicalRetriever
from nexus_ai.retrieval.collection_registration import register_indexed_manifest
from nexus_ai.retrieval.company_metadata import CompanyYearMetadataCatalog, normalize_company_name
from nexus_ai.retrieval.collection_repository import InMemoryCollectionIndexRepository
from nexus_ai.retrieval.service import validate_citation


SCHEMA_VERSION = 1
WORKSPACE_ID = "financial-eval-synthetic-workspace"
COLLECTION_ID = "financial-evidence-fixture"
MAX_FIXTURE_BYTES = 2_000_000
MAX_DOCUMENTS = 150
MAX_CASES = 200
_DIGIT_TRANSLATION = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_CURRENCY_ALIASES = {
    "SAR": ("sar", "ريال سعودي", "ريالات سعودية", "saudi riyal", "saudi riyals"),
    "USD": ("usd", "دولار أمريكي", "دولار امريكي", "us dollar", "us dollars", "united states dollars"),
    "EUR": ("eur", "يورو", "euro", "euros"),
}


class FinancialFixtureError(ValueError):
    """The synthetic financial evaluation fixture is malformed or unsafe."""


class PageDelimitedFixtureExtractor:
    """Test-only page adapter: form-feed-delimited UTF-8 becomes numbered pages."""

    name = "synthetic-page-fixture"
    version = "1"
    media_type = "text/plain"

    def extract(self, content: bytes, *, source_path: str) -> ExtractionResult:
        try:
            text = content.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise FinancialFixtureError("synthetic fixture text is not UTF-8") from exc
        pages = tuple(ExtractedPage(index, page) for index, page in enumerate(text.split("\f"), 1))
        return ExtractionResult(self.name, self.version, self.media_type, pages)


def load_financial_fixture(path: Path) -> dict[str, Any]:
    """Read a small versioned synthetic fixture and verify its canonical hash inputs."""
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise FinancialFixtureError("fixture is unavailable") from exc
    if len(raw) > MAX_FIXTURE_BYTES:
        raise FinancialFixtureError("fixture exceeds the byte limit")
    try:
        fixture = json.loads(raw.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FinancialFixtureError("fixture must be UTF-8 JSON") from exc
    validate_financial_fixture(fixture)
    return fixture


def validate_financial_fixture(fixture: Any) -> dict[str, Any]:
    if not isinstance(fixture, dict) or type(fixture.get("schema_version")) is not int \
            or fixture["schema_version"] != SCHEMA_VERSION:
        raise FinancialFixtureError("fixture schema_version must be 1")
    if not isinstance(fixture.get("dataset_id"), str) or not fixture["dataset_id"].strip():
        raise FinancialFixtureError("dataset_id is required")
    if not isinstance(fixture.get("dataset_version"), str) or not fixture["dataset_version"].strip():
        raise FinancialFixtureError("dataset_version is required")
    if fixture.get("synthetic") is not True:
        raise FinancialFixtureError("this runner accepts only fixtures explicitly marked synthetic=true")
    companies = fixture.get("companies")
    if not isinstance(companies, dict) or not companies:
        raise FinancialFixtureError("companies must be a non-empty alias map")
    if len(companies) > MAX_DOCUMENTS:
        raise FinancialFixtureError("company count exceeds the fixture limit")
    normalized_company_aliases: dict[str, str] = {}
    for company_id, names in companies.items():
        if not isinstance(company_id, str) or not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", company_id):
            raise FinancialFixtureError("company IDs must be lowercase stable identifiers")
        if not isinstance(names, list) or not 1 <= len(names) <= 20:
            raise FinancialFixtureError(f"companies[{company_id}] must have 1 to 20 explicit aliases")
        if any(not _plain_text(name, maximum=160) for name in names):
            raise FinancialFixtureError(f"companies[{company_id}] contains an invalid alias")
        for alias in (company_id, *names):
            normalized = normalize_company_name(alias)
            prior = normalized_company_aliases.get(normalized)
            if prior is not None and prior != company_id:
                raise FinancialFixtureError("company aliases are ambiguous after normalization")
            normalized_company_aliases[normalized] = company_id

    documents = fixture.get("documents")
    cases = fixture.get("cases")
    if not isinstance(documents, list) or not 1 <= len(documents) <= MAX_DOCUMENTS:
        raise FinancialFixtureError(f"documents must contain 1 to {MAX_DOCUMENTS} rows")
    if not isinstance(cases, list) or not 1 <= len(cases) <= MAX_CASES:
        raise FinancialFixtureError(f"cases must contain 1 to {MAX_CASES} rows")
    paths: set[str] = set()
    total_source_chars = 0
    for index, document in enumerate(documents):
        label = f"documents[{index}]"
        if not isinstance(document, dict):
            raise FinancialFixtureError(f"{label} must be an object")
        path = document.get("path")
        if not isinstance(path, str) or not path or len(path) > 500:
            raise FinancialFixtureError(f"{label}.path is invalid")
        posix, windows = PurePosixPath(path), PureWindowsPath(path)
        if (posix.is_absolute() or windows.is_absolute() or windows.drive or windows.root
                or "\\" in path or any(part in ("", ".", "..") for part in path.split("/"))
                or posix.suffix.casefold() != ".txt"):
            raise FinancialFixtureError(f"{label}.path must be a safe relative .txt path")
        path_key = path.casefold()
        if path_key in paths:
            raise FinancialFixtureError("document paths must be unique")
        paths.add(path_key)
        for field in ("company_id", "identity_company_id"):
            if document.get(field) not in companies:
                raise FinancialFixtureError(f"{label}.{field} must reference a registered company")
        _year(document.get("financial_year"), f"{label}.financial_year")
        _year(document.get("identity_year"), f"{label}.identity_year")
        if document.get("language") not in ("ar", "en"):
            raise FinancialFixtureError(f"{label}.language must be ar or en")
        pages = document.get("pages")
        if not isinstance(pages, list) or not 1 <= len(pages) <= 500:
            raise FinancialFixtureError(f"{label}.pages must contain 1 to 500 pages")
        for page_number, text in enumerate(pages, 1):
            if not isinstance(text, str) or not text or len(text) > 100_000:
                raise FinancialFixtureError(f"{label}.pages[{page_number}] must be non-empty bounded text")
            if "\f" in text:
                raise FinancialFixtureError("page text cannot contain a page separator")
            total_source_chars += len(text)
            if total_source_chars > MAX_FIXTURE_BYTES:
                raise FinancialFixtureError("fixture source text exceeds the total character limit")
    case_ids: set[str] = set()
    path_set = {document["path"] for document in documents}
    document_by_path = {document["path"]: document for document in documents}
    directions: set[str] = set()
    for index, case in enumerate(cases):
        label = f"cases[{index}]"
        if not isinstance(case, dict):
            raise FinancialFixtureError(f"{label} must be an object")
        case_id = case.get("case_id")
        if not isinstance(case_id, str) or not case_id.strip() or case_id in case_ids:
            raise FinancialFixtureError(f"{label}.case_id must be unique and non-empty")
        case_ids.add(case_id)
        if not isinstance(case.get("query"), str) or not case["query"].strip() or len(case["query"]) > 8_000:
            raise FinancialFixtureError(f"{label}.query is invalid")
        if case.get("query_language") not in ("ar", "en"):
            raise FinancialFixtureError(f"{label}.query_language must be ar or en")
        if not isinstance(case.get("company"), str) or not case["company"].strip():
            raise FinancialFixtureError(f"{label}.company is required")
        if not any(normalize_company_name(case["company"]) in {
            normalize_company_name(alias) for alias in aliases
        } | {company_id} for company_id, aliases in companies.items()):
            raise FinancialFixtureError(f"{label}.company must exactly match a registered alias or company ID")
        _year(case.get("financial_year"), f"{label}.financial_year")
        evidence = case.get("expected_evidence")
        if not isinstance(evidence, list) or not evidence:
            raise FinancialFixtureError(f"{label}.expected_evidence must be non-empty")
        for target_index, target in enumerate(evidence):
            if not isinstance(target, dict) or target.get("path") not in path_set:
                raise FinancialFixtureError(f"{label}.expected_evidence[{target_index}] has an unknown path")
            directions.add(f"{case['query_language']}->{document_by_path[target['path']]['language']}")
            page = target.get("page_number")
            if type(page) is not int or page < 1:
                raise FinancialFixtureError("expected evidence page_number must be positive")
            _year(target.get("fact_year"), "expected evidence fact_year")
            kind = target.get("kind")
            if kind not in ("value", "absence"):
                raise FinancialFixtureError("expected evidence kind must be value or absence")
            for field in ("metric_aliases",):
                _aliases(target.get(field), field)
            if kind == "value":
                _aliases(target.get("amount_aliases"), "amount_aliases")
                _aliases(target.get("currency_aliases"), "currency_aliases")
            else:
                _aliases(target.get("absence_aliases"), "absence_aliases")
    required_directions = {"ar->ar", "en->en", "ar->en", "en->ar"}
    if directions != required_directions:
        raise FinancialFixtureError("cases must cover Arabic/English query-to-evidence directions")
    return fixture


def run_financial_evaluation(fixture: Mapping[str, Any], *, k_values: tuple[int, ...] = (5, 10)) -> dict[str, Any]:
    """Index the synthetic pages and score deterministic, filtered lexical evidence."""
    validated = validate_financial_fixture(dict(fixture))
    if not isinstance(k_values, tuple) or not k_values or any(type(k) is not int or k <= 0 for k in k_values):
        raise ValueError("k_values must be a non-empty tuple of positive integers")
    if any(k > 10 for k in k_values):
        raise ValueError("k_values cannot exceed the retriever's top-10 limit")
    k_values = tuple(sorted(set((*k_values, 5, 10))))
    company_aliases = validated["companies"]
    report_cases = []
    relevant_count = {k: 0 for k in k_values}
    hit_count = {k: 0 for k in k_values}
    total_citations = 0
    valid_citations = 0
    leaked_citations = 0
    missing_case_count = 0
    explicit_absence_hits = 0
    currency_mismatch_candidates = 0
    cause_counts: dict[str, int] = {
        "extraction": 0,
        "chunking": 0,
        "retrieval": 0,
        "missing_evidence": 0,
        "incorrect_metadata": 0,
        "incorrect_currency": 0,
        "citation_provenance": 0,
    }
    fixture_sha = hashlib.sha256(
        json.dumps(validated, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    with tempfile.TemporaryDirectory(prefix="nexus-financial-eval-") as temp_dir:
        root = Path(temp_dir)
        entries = []
        document_by_path = {row["path"]: row for row in validated["documents"]}
        for document in validated["documents"]:
            destination = root.joinpath(*PurePosixPath(document["path"]).parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes("\f".join(document["pages"]).encode("utf-8"))
            company_label = company_aliases[document["company_id"]][0]
            entries.append({"path": document["path"], "company": company_label,
                            "year": document["financial_year"]})
        repository = InMemoryCollectionIndexRepository()
        indexer = CollectionIndexService(
            approved_root=root,
            repository=repository,
            extractors={".txt": PageDelimitedFixtureExtractor()},
        )
        index_result = indexer.index(WORKSPACE_ID, entries)
        indexed_by_path = {}
        for document in validated["documents"]:
            indexed_by_path[document["path"]] = repository.get_active(
                WORKSPACE_ID,
                _document_id(WORKSPACE_ID, document["path"]),
            )

        metadata_faults = [
            row["path"] for row in validated["documents"]
            if (row["company_id"] != row["identity_company_id"]
                or row["financial_year"] != row["identity_year"])
        ]
        cause_counts["incorrect_metadata"] += len(metadata_faults)
        catalog = CompanyYearMetadataCatalog()
        good_paths = {
            row["path"] for row in index_result["documents"]
            if row["status"] in ("indexed", "unchanged")
        }
        good_entries = [entry for entry in entries if entry["path"] in good_paths]
        registration = None
        if good_entries:
            registration = register_indexed_manifest(
                catalog=catalog,
                repository=repository,
                workspace_id=WORKSPACE_ID,
                collection_id=COLLECTION_ID,
                entries=good_entries,
                companies=company_aliases,
            )
        retriever = CollectionLexicalRetriever(
            repository=repository,
            catalog=catalog,
            workspace_id=WORKSPACE_ID,
            collection_id=COLLECTION_ID,
        )
        for case in validated["cases"]:
            report_cases.append(_evaluate_case(
                case=case,
                docs=document_by_path,
                indexed_by_path=indexed_by_path,
                company_aliases=company_aliases,
                repository=repository,
                retriever=retriever,
                k_values=k_values,
            ))

    for row in report_cases:
        for k in k_values:
            relevant_count[k] += row["relevant_passage_count"]
            hit_count[k] += row["recall_hits"][str(k)]
        total_citations += row["citation_provenance"]["total"]
        valid_citations += row["citation_provenance"]["valid"]
        leaked_citations += row["company_year_leakage"]["count"]
        if row["case_kind"] == "missing_fact":
            missing_case_count += 1
            if row["explicit_absence_retrieved"]:
                explicit_absence_hits += 1
        currency_mismatch_candidates += row["incorrect_currency_candidate_count"]
        for cause in row["failure_causes"]:
            cause_counts[cause] += 1
    for k in k_values:
        if relevant_count[k] == 0:
            raise FinancialFixtureError("fixture has no judged relevant chunks")

    metrics = {
        f"recall_at_{k}": {
            "hits": hit_count[k],
            "relevant": relevant_count[k],
            "value": round(hit_count[k] / relevant_count[k], 6),
        }
        for k in k_values
    }
    metrics.update({
        "citation_provenance_integrity": {
            "valid": valid_citations,
            "total": total_citations,
            "rate": round(valid_citations / total_citations, 6) if total_citations else None,
        },
        "company_year_leakage": {
            "count": leaked_citations,
            "retrieved_citations": total_citations,
            "rate": round(leaked_citations / total_citations, 6) if total_citations else 0.0,
        },
        "missing_evidence": {
            "cases": missing_case_count,
            "explicit_absence_evidence_retrieved": explicit_absence_hits,
            "recall": round(explicit_absence_hits / missing_case_count, 6) if missing_case_count else None,
            "interpretation": "retrieval of explicit absence notes only; no answer generator or abstention is evaluated",
        },
        "incorrect_currency_candidates": currency_mismatch_candidates,
    })
    return {
        "schema_version": 1,
        "dataset": {
            "id": validated["dataset_id"],
            "version": validated["dataset_version"],
            "synthetic": True,
            "fixture_sha256": fixture_sha,
            "document_count": len(validated["documents"]),
            "case_count": len(validated["cases"]),
        },
        "execution": {
            "index_status": index_result["status"],
            "index_blocked_count": index_result["blocked_count"],
            "registration_revision": registration.revision_id if registration is not None else None,
            "retriever": "CollectionLexicalRetriever",
            "model_calls": 0,
            "embedding_calls": 0,
            "database_connections": 0,
        },
        "metrics": metrics,
        "failure_causes": cause_counts,
        "metadata_fault_paths": metadata_faults,
        "cases": report_cases,
        "limitations": [
            "All documents and labels are synthetic fixtures, not real-PDF evidence.",
            "This evaluates retrieval and source provenance, not generated-answer accuracy or financial entailment.",
            "The report does not establish real-world retrieval quality or production acceptance.",
        ],
    }


def _evaluate_case(*, case, docs, indexed_by_path, company_aliases, repository, retriever, k_values):
    expected_chunks: set[str] = set()
    expected_passages = {(fact["path"], fact["page_number"]) for fact in case["expected_evidence"]}
    evidence_diagnostics = []
    stage_causes: set[str] = set()

    def evidence_status(fact, status, relevant_chunk_ids=()):
        result = {
            "path": fact["path"],
            "page_number": fact["page_number"],
            "fact_year": fact["fact_year"],
            "kind": fact["kind"],
            "metric_aliases": fact["metric_aliases"],
            "status": status,
            "relevant_chunk_ids": sorted(relevant_chunk_ids),
        }
        for field in ("amount_aliases", "currency_aliases", "absence_aliases"):
            if field in fact:
                result[field] = fact[field]
        return result

    for fact in case["expected_evidence"]:
        document = docs[fact["path"]]
        indexed = indexed_by_path[fact["path"]]
        if indexed is None:
            stage_causes.add("extraction")
            evidence_diagnostics.append(evidence_status(fact, "source_not_indexed"))
            continue
        source_pages = document["pages"]
        if fact["page_number"] > len(source_pages):
            stage_causes.add("missing_evidence" if fact["kind"] == "absence" else "extraction")
            evidence_diagnostics.append(evidence_status(fact, "expected_page_missing"))
            continue
        source_text = source_pages[fact["page_number"] - 1]
        indexed_page = next((page for page in indexed.document.pages
                             if page.page_number == fact["page_number"]), None)
        if indexed_page is None or indexed_page.text != source_text:
            stage_causes.add("extraction")
            evidence_diagnostics.append(evidence_status(fact, "extracted_page_differs_from_fixture_source"))
            continue
        company_names = company_aliases[document["identity_company_id"]]
        if not _fact_supported(source_text, fact, company_names):
            stage_causes.add("missing_evidence" if fact["kind"] == "absence" else "missing_evidence")
            evidence_diagnostics.append(evidence_status(fact, "expected_fact_not_in_source"))
            continue
        matched_chunks = [chunk for chunk in indexed.chunks
                          if chunk.page_number == fact["page_number"]
                          and _fact_supported(chunk.text, fact, company_names)]
        if not matched_chunks:
            stage_causes.add("chunking")
            evidence_diagnostics.append(evidence_status(fact, "fact_not_contained_in_one_chunk"))
            continue
        expected_chunks.update(chunk.chunk_id for chunk in matched_chunks)
        evidence_diagnostics.append(evidence_status(
            fact, "available", (chunk.chunk_id for chunk in matched_chunks)
        ))

    try:
        response = retriever.retrieve(
            case["query"], company=case["company"], financial_year=case["financial_year"], top_k=10,
        )
    except Exception as exc:
        # Keep the report safe and deterministic; exception text may carry paths.
        response = None
        stage_causes.add("retrieval")
        retrieval_error = type(exc).__name__
    else:
        retrieval_error = None
    retrieved = response.results if response is not None else []
    retrievals = []
    provenance_valid = 0
    leakage = 0
    currency_mismatches = 0
    currency_candidate_ids: list[str] = []
    requested_company_id = _resolve_company(case["company"], company_aliases)
    for item in retrieved:
        citation = item.citation
        source = docs.get(citation.source_path)
        indexed = indexed_by_path.get(citation.source_path)
        chunk = None if indexed is None else next((row for row in indexed.chunks
                                                   if row.chunk_id == citation.chunk_id), None)
        valid = bool(source is not None and indexed is not None and chunk is not None
                     and citation.workspace_id == WORKSPACE_ID
                     and citation.document_id == indexed.document.document_id
                     and citation.document_version_id == indexed.document.version_id
                     and citation.source_path == indexed.document.source_path
                     and citation.source_sha256 == indexed.document.content_sha256
                     and citation.page_number == chunk.page_number
                     and citation.exact_text == chunk.text)
        if valid:
            try:
                validate_citation(citation, indexed.document.pages, chunk)
            except (ValueError, TypeError):
                valid = False
        provenance_valid += int(valid)
        if not valid:
            stage_causes.add("citation_provenance")
        if (source is None or source["company_id"] != requested_company_id
                or source["financial_year"] != case["financial_year"]
                or source["identity_company_id"] != requested_company_id
                or source["identity_year"] != case["financial_year"]):
            leakage += 1
        for fact in case["expected_evidence"]:
            if fact["kind"] != "value":
                continue
            if (_contains_any(citation.exact_text, fact["metric_aliases"])
                    and _contains_any(citation.exact_text, fact["amount_aliases"])
                    and _contains_year(citation.exact_text, fact["fact_year"])
                    and not _contains_any(citation.exact_text, fact["currency_aliases"])
                    and _contains_any(citation.exact_text, _other_currencies(fact["currency_aliases"]))):
                currency_mismatches += 1
                currency_candidate_ids.append(citation.chunk_id)
                break
        retrievals.append({
            "rank": len(retrievals) + 1,
            "score": round(float(item.score), 8),
            "document_id": citation.document_id,
            "document_version_id": citation.document_version_id,
            "source_path": citation.source_path,
            "source_sha256": citation.source_sha256,
            "chunk_id": citation.chunk_id,
            "page_number": citation.page_number,
            "start_char": citation.start_char,
            "end_char": citation.end_char,
            "provenance_valid": valid,
            "exact_text": citation.exact_text,
        })
    def hit_passages(rows):
        hits = set()
        for retrieved_row in rows:
            citation = retrieved_row.citation
            source = docs.get(citation.source_path)
            if source is None:
                continue
            aliases = company_aliases[source["identity_company_id"]]
            for fact in case["expected_evidence"]:
                if (citation.source_path == fact["path"]
                        and citation.page_number == fact["page_number"]
                        and _fact_supported(citation.exact_text, fact, aliases)):
                    hits.add((fact["path"], fact["page_number"]))
        return hits

    recall_hits = {str(k): len(expected_passages & hit_passages(retrieved[:k])) for k in k_values}
    expected_retrieved = expected_passages & hit_passages(retrieved)
    missing_expected = expected_passages - expected_retrieved
    if missing_expected and not ("extraction" in stage_causes or "chunking" in stage_causes
                                 or "missing_evidence" in stage_causes):
        stage_causes.add("retrieval")
    if not expected_chunks and not stage_causes:
        stage_causes.add("missing_evidence")
    if leakage:
        stage_causes.add("incorrect_metadata")
    if currency_mismatches:
        stage_causes.add("incorrect_currency")
    case_kind = "missing_fact" if all(fact["kind"] == "absence" for fact in case["expected_evidence"]) else "value"
    explicit_absence_retrieved = bool(case_kind == "missing_fact" and expected_retrieved)
    return {
        "case_id": case["case_id"],
        "query_language": case["query_language"],
        "company": case["company"],
        "financial_year_filter": case["financial_year"],
        "case_kind": case_kind,
        "expected_evidence": evidence_diagnostics,
        "relevant_passage_count": len(expected_passages),
        "recall_hits": recall_hits,
        "retrieved_expected_passage_count": len(expected_retrieved),
        "explicit_absence_retrieved": explicit_absence_retrieved,
        "citation_provenance": {"valid": provenance_valid, "total": len(retrieved)},
        "company_year_leakage": {"count": leakage, "total": len(retrieved)},
        "incorrect_currency_candidate_count": currency_mismatches,
        "currency_candidate_chunk_ids": currency_candidate_ids,
        "retrieval_error_category": retrieval_error,
        "retrieved": retrievals,
        "failure_causes": sorted(stage_causes),
    }


def _fact_supported(text: str, fact: Mapping[str, Any], company_names: list[str]) -> bool:
    if not _contains_any(text, company_names) or not _contains_year(text, fact["fact_year"]):
        return False
    if not _contains_any(text, fact["metric_aliases"]):
        return False
    if fact["kind"] == "absence":
        return _contains_any(text, fact["absence_aliases"])
    return (_contains_any(text, fact["amount_aliases"])
            and _contains_any(text, fact["currency_aliases"]))


def _normalize(text: str) -> str:
    value = unicodedata.normalize("NFKC", text).translate(_DIGIT_TRANSLATION).casefold()
    return " ".join(value.split())


def _contains_any(text: str, aliases: list[str] | tuple[str, ...]) -> bool:
    normalized = _normalize(text)
    return any(_normalize(alias) in normalized for alias in aliases)


def _contains_year(text: str, year: int) -> bool:
    normalized = _normalize(text)
    return re.search(rf"(?<!\d){year}(?!\d)", normalized) is not None


def _other_currencies(expected_aliases: list[str]) -> tuple[str, ...]:
    expected = {_normalize(alias) for alias in expected_aliases}
    expected_codes = {
        code for code, aliases in _CURRENCY_ALIASES.items()
        if expected & {_normalize(alias) for alias in aliases}
    }
    return tuple(alias for code, aliases in _CURRENCY_ALIASES.items() if code not in expected_codes
                 for alias in aliases)


def _resolve_company(name: str, companies: Mapping[str, list[str]]) -> str:
    normalized = normalize_company_name(name)
    for company_id, aliases in companies.items():
        if normalized == company_id or normalized in {normalize_company_name(alias) for alias in aliases}:
            return company_id
    raise FinancialFixtureError("case references an unknown company")


def _document_id(workspace_id: str, path: str) -> str:
    from nexus_ai.documents.service import stable_document_id
    return stable_document_id(workspace_id, path)


def _year(value: Any, field: str) -> None:
    if type(value) is not int or not 1900 <= value <= 2100:
        raise FinancialFixtureError(f"{field} must be an integer from 1900 to 2100")


def _plain_text(value: Any, *, maximum: int) -> bool:
    return bool(isinstance(value, str) and value.strip() and len(value) <= maximum
                and not any(unicodedata.category(ch).startswith("C") for ch in value))


def _aliases(value: Any, field: str) -> None:
    if not isinstance(value, list) or not 1 <= len(value) <= 20 or any(not _plain_text(item, maximum=160) for item in value):
        raise FinancialFixtureError(f"{field} must contain 1 to 20 explicit text aliases")


def summarize_financial_report(report: Mapping[str, Any]) -> dict[str, Any]:
    """Project full trace data to a concise, stable JSON handoff report."""
    summary_cases = []
    for case in report["cases"]:
        relevant = case["relevant_passage_count"]
        relevant_chunk_ids = {
            chunk_id
            for evidence in case["expected_evidence"]
            for chunk_id in evidence["relevant_chunk_ids"]
        }
        currency_chunk_ids = set(case["currency_candidate_chunk_ids"])

        def cite(row):
            return {
                "rank": row["rank"],
                "document_id": row["document_id"],
                "document_version_id": row["document_version_id"],
                "source_path": row["source_path"],
                "source_sha256": row["source_sha256"],
                "chunk_id": row["chunk_id"],
                "page_number": row["page_number"],
                "start_char": row["start_char"],
                "end_char": row["end_char"],
                "provenance_valid": row["provenance_valid"],
                "text_preview": row["exact_text"][:180],
            }

        summary_cases.append({
            "case_id": case["case_id"],
            "query_language": case["query_language"],
            "company": case["company"],
            "financial_year_filter": case["financial_year_filter"],
            "kind": case["case_kind"],
            "relevant_passages": relevant,
            "recall_at_5": round(case["recall_hits"]["5"] / relevant, 6) if relevant else None,
            "recall_at_10": round(case["recall_hits"]["10"] / relevant, 6) if relevant else None,
            "returned_count": case["citation_provenance"]["total"],
            "expected_evidence": [
                {key: row[key] for key in (
                    "path", "page_number", "fact_year", "kind", "status", "metric_aliases",
                    "amount_aliases", "currency_aliases", "absence_aliases",
                ) if key in row}
                for row in case["expected_evidence"]
            ],
            "relevant_citations": [cite(row) for row in case["retrieved"]
                                   if row["chunk_id"] in relevant_chunk_ids],
            "incorrect_currency_candidates": [cite(row) for row in case["retrieved"]
                                               if row["chunk_id"] in currency_chunk_ids],
            "citation_provenance": case["citation_provenance"],
            "company_year_leakage": case["company_year_leakage"],
            "incorrect_currency_candidate_count": case["incorrect_currency_candidate_count"],
            "explicit_absence_retrieved": case["explicit_absence_retrieved"],
            "failure_causes": case["failure_causes"],
        })
    return {
        "schema_version": report["schema_version"],
        "dataset": report["dataset"],
        "execution": report["execution"],
        "metrics": report["metrics"],
        "failure_causes": report["failure_causes"],
        "metadata_fault_paths": report["metadata_fault_paths"],
        "cases": summary_cases,
        "limitations": report["limitations"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    default_fixture = Path(__file__).resolve().parents[3] / "benchmarks" / "financial_evidence_synthetic_v1.json"
    parser.add_argument("--fixture", type=Path, default=default_fixture)
    args = parser.parse_args(argv)
    report = summarize_financial_report(run_financial_evaluation(load_financial_fixture(args.fixture)))
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
