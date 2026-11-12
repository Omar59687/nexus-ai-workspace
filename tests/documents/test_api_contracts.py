import unittest

from nexus_ai.documents.api_contracts import (
    AnsweringUnavailableError,
    AuthorizedWorkspaceContext,
    DocumentBackendAdapter,
    DocumentIdRequest,
    DocumentListRequest,
    DocumentPathRequest,
    EvidenceLookupRequest,
    GroundedAnswerRequest,
    GroundedAnswerResult,
    IngestionTriggerRequest,
    SearchRequest,
    WorkspacePermissionError,
)
from nexus_ai.documents.types import (
    DocumentVersion,
    ExtractedPage,
    IndexedDocument,
    IngestionResult,
)
from nexus_ai.retrieval.schemas import RetrievalResponse


class FakeRepository:
    def __init__(self):
        self.rows = {}
        self.workspace_calls = []

    def list_active(self, workspace_id, filters=None):
        self.workspace_calls.append(("list", workspace_id))
        return tuple(self.rows.get(workspace_id, ()))

    def iter_active(self, workspace_id, filters=None):
        self.workspace_calls.append(("iter", workspace_id))
        yield from self.rows.get(workspace_id, ())

    def get_active(self, workspace_id, document_id):
        self.workspace_calls.append(("get", workspace_id))
        return next((row for row in self.rows.get(workspace_id, ())
                     if row.document.document_id == document_id), None)

    def delete(self, workspace_id, document_id):
        self.workspace_calls.append(("delete", workspace_id))
        old = list(self.rows.get(workspace_id, ()))
        remaining = [row for row in old if row.document.document_id != document_id]
        self.rows[workspace_id] = remaining
        return len(old) != len(remaining)


class FakeIngestion:
    def __init__(self):
        self.calls = []

    def ingest(self, workspace_id, relative_path):
        self.calls.append((workspace_id, relative_path))
        return IngestionResult("doc-1", "version-1", "a" * 64, 2, 3,
                               activated=True, idempotent=False, warnings=())


class FakeRetrieval:
    def __init__(self, response=None):
        self.calls = []
        self.response = response or RetrievalResponse(
            workspace_id="workspace-a", strategy="windowed_e5", status="empty", results=[]
        )

    def retrieve(self, query, *, workspace_id, top_k=5, strategy="windowed_e5", filters=None):
        self.calls.append((query, workspace_id, top_k, strategy, filters))
        return self.response


class FakeAnswerer:
    def __init__(self):
        self.calls = []

    def answer(self, query, evidence, *, language):
        self.calls.append((query, evidence, language))
        if not evidence:
            resolved = "ar" if language == "ar" or (language == "auto" and "؟" in query) else "en"
            localized = "لا تتوفر أدلة كافية للإجابة." if resolved == "ar" else "I don't have enough evidence to answer."
            return GroundedAnswerResult(answer=localized, abstained=True, citations=(), language=resolved)
        return GroundedAnswerResult(answer="supported", abstained=False, citations=evidence, language="en")


def context(workspace="workspace-a", permissions=frozenset({"documents:read", "documents:write", "documents:delete"})):
    return AuthorizedWorkspaceContext("subject-1", workspace, permissions)


def indexed_document(workspace="workspace-a", document_id="doc-1"):
    document = DocumentVersion(
        workspace_id=workspace, document_id=document_id, version_id="v1",
        processing_id="processing-1",
        source_path="report.pdf", content_sha256="a" * 64, media_type="application/pdf",
        extractor_name="fake", extractor_version="1", chunker_version="c1",
        pages=(ExtractedPage(1, "source"),), warnings=(), offsets_reliable=True,
    )
    return IndexedDocument(document, (), (), "fake/model", "revision", 2,
                           "generation-1", 500, 100, "preprocessing-1")


class ContractValidationTests(unittest.TestCase):
    def test_requests_reject_extra_workspace_fields_and_bad_paths(self):
        for model, payload in (
            (DocumentPathRequest, {"relative_path": "a.txt", "workspace_id": "other"}),
            (DocumentIdRequest, {"document_id": "doc-1", "workspace_id": "other"}),
            (SearchRequest, {"query": "question", "workspace_id": "other"}),
        ):
            with self.subTest(model=model), self.assertRaises(ValueError):
                model(**payload)
        for value in ("../secret.txt", "/outside.txt", r"folder\..\secret.md", "C:/secret.pdf", "folder//x.txt"):
            with self.subTest(path=value), self.assertRaises(ValueError):
                DocumentPathRequest(relative_path=value)
        for value in ("image.png", "  "):
            with self.subTest(path=value), self.assertRaises(ValueError):
                DocumentPathRequest(relative_path=value)

    def test_request_bounds_and_unknown_fields_are_enforced(self):
        self.assertEqual(DocumentListRequest().limit, 50)
        with self.assertRaises(ValueError):
            DocumentListRequest(limit=201)
        with self.assertRaises(ValueError):
            SearchRequest(query=" \n ")
        with self.assertRaises(ValueError):
            GroundedAnswerRequest(query="question", debug=True)
        with self.assertRaises(ValueError):
            EvidenceLookupRequest(query="q", document_id="d", page_number=0)


class BackendAdapterTests(unittest.TestCase):
    def setUp(self):
        self.repo = FakeRepository()
        self.ingestion = FakeIngestion()
        self.retrieval = FakeRetrieval()
        self.adapter = DocumentBackendAdapter(
            ingestion=self.ingestion, repository=self.repo, retrieval=self.retrieval,
        )

    def test_register_derives_workspace_from_authorized_context(self):
        result = self.adapter.register(context(), DocumentPathRequest(relative_path="team/report.md"))
        self.assertEqual(self.ingestion.calls, [("workspace-a", "team/report.md")])
        self.assertEqual(result.document_id, "doc-1")
        self.assertEqual(result.window_count, 3)

    def test_trigger_uses_registered_document_and_replays_idempotency_key(self):
        self.repo.rows["workspace-a"] = [indexed_document()]
        request = IngestionTriggerRequest(document_id="doc-1", idempotency_key="retry-1")
        first = self.adapter.trigger_ingestion(context(), request)
        replay = self.adapter.trigger_ingestion(context(), request)
        self.assertEqual(first, replay)
        self.assertEqual(self.ingestion.calls, [("workspace-a", "report.pdf")])
        self.assertEqual(self.repo.workspace_calls, [("get", "workspace-a")])
        with self.assertRaisesRegex(ValueError, "already associated"):
            self.adapter.trigger_ingestion(
                context(), IngestionTriggerRequest(document_id="doc-other", idempotency_key="retry-1"),
            )

    def test_trigger_rejects_unregistered_document_and_blank_idempotency_key(self):
        with self.assertRaisesRegex(KeyError, "not registered"):
            self.adapter.trigger_ingestion(context(), IngestionTriggerRequest(document_id="missing"))
        with self.assertRaises(ValueError):
            IngestionTriggerRequest(document_id="doc-1", idempotency_key="   ")
        self.assertEqual(self.ingestion.calls, [])

    def test_idempotency_cache_has_a_fixed_capacity(self):
        self.repo.rows["workspace-a"] = [indexed_document()]
        self.adapter._MAX_TRIGGER_RESULTS = 2
        for key in ("first", "second", "third"):
            self.adapter.trigger_ingestion(
                context(), IngestionTriggerRequest(document_id="doc-1", idempotency_key=key),
            )
        self.assertEqual(len(self.adapter._trigger_results), 2)
        self.assertNotIn(("workspace-a", "first"), self.adapter._trigger_results)

    def test_missing_permission_fails_before_touching_services(self):
        denied = context("workspace-a", frozenset({"documents:read"}))
        with self.assertRaises(WorkspacePermissionError):
            self.adapter.register(denied, DocumentPathRequest(relative_path="report.txt"))
        self.assertEqual(self.ingestion.calls, [])
        with self.assertRaises(WorkspacePermissionError):
            self.adapter.delete_document(denied, DocumentIdRequest(document_id="doc-1"))
        self.assertEqual(self.repo.workspace_calls, [])

    def test_list_status_and_delete_are_scoped_to_context_workspace(self):
        self.repo.rows["workspace-a"] = [indexed_document()]
        self.repo.rows["workspace-b"] = [indexed_document("workspace-b", "doc-1")]
        rows = self.adapter.list_documents(context("workspace-a"), DocumentListRequest(limit=1))
        self.assertEqual([row.document_id for row in rows.items], ["doc-1"])
        self.assertFalse(rows.has_more)
        state = self.adapter.ingestion_status(context("workspace-a"), DocumentIdRequest(document_id="doc-1"))
        self.assertEqual(state.status, "indexed")
        removed = self.adapter.delete_document(context("workspace-a"), DocumentIdRequest(document_id="doc-1"))
        self.assertTrue(removed.deleted)
        self.assertEqual(len(self.repo.rows["workspace-b"]), 1)
        self.assertIn(("iter", "workspace-a"), self.repo.workspace_calls)
        self.assertEqual({call[1] for call in self.repo.workspace_calls}, {"workspace-a"})

    def test_search_and_evidence_use_context_workspace_and_explicit_filters(self):
        self.adapter.search(context("workspace-z"), SearchRequest(query="what?", top_k=3))
        self.adapter.evidence(
            context("workspace-z"), EvidenceLookupRequest(
                query="what?", document_id="doc-9", page_number=2,
            ),
        )
        self.assertEqual(self.retrieval.calls[0][1], "workspace-z")
        self.assertEqual(self.retrieval.calls[1][1], "workspace-z")
        self.assertEqual(self.retrieval.calls[1][4].document_id, "doc-9")
        self.assertEqual(self.retrieval.calls[1][4].page_number, 2)

    def test_answer_is_unavailable_by_default_and_abstains_without_evidence(self):
        with self.assertRaises(AnsweringUnavailableError):
            self.adapter.grounded_answer(context(), GroundedAnswerRequest(query="question"))
        answerer = FakeAnswerer()
        self.adapter.answerer = answerer
        result = self.adapter.grounded_answer(context(), GroundedAnswerRequest(query="question"))
        self.assertTrue(result.abstained)
        self.assertEqual(len(answerer.calls), 1)
        self.assertEqual(answerer.calls[0][1], ())
        self.assertEqual(result.language, "en")

    def test_answer_adapter_passes_only_retrieved_citations(self):
        citation = {
            "workspace_id": "workspace-a", "document_id": "doc-1", "document_version_id": "v1",
            "source_path": "report.txt", "source_sha256": "a" * 64, "page_number": None,
            "chunk_id": "chunk-1", "start_char": 0, "end_char": 6,
            "matched_window_id": "window-1", "matched_window_start_char": 0,
            "matched_window_end_char": 6, "offsets_reliable": True, "exact_text": "source",
        }
        from nexus_ai.retrieval.schemas import EvidenceCitation, RetrievedEvidence
        found = RetrievalResponse(
            workspace_id="workspace-a", strategy="windowed_e5", status="ok",
            results=[RetrievedEvidence(score=0.9, score_type="cosine_similarity",
                                       strategy="windowed_e5", citation=EvidenceCitation(**citation))],
        )
        self.retrieval.response = found
        answerer = FakeAnswerer()
        self.adapter.answerer = answerer
        result = self.adapter.grounded_answer(
            context(), GroundedAnswerRequest(query="question", language="en"),
        )
        self.assertEqual(result.answer, "supported")
        self.assertEqual(answerer.calls[0][1], (found.results[0].citation,))
        self.assertEqual(answerer.calls[0][2], "en")


if __name__ == "__main__":
    unittest.main()
