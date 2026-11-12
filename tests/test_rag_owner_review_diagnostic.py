import copy
import hashlib
import unittest

from experiments.rag_prototype import Chunk, ChunkHit
from experiments.rag_prototype.evaluation import FixtureError, RetrieverSpec
from experiments.rag_prototype.owner_review_diagnostic import (
    PROVISIONAL_LABEL,
    run_owner_dev_diagnostic,
    validate_owner_dev_manifest,
)


def _manifest():
    docs = [
        {"document_id": "d-ar", "version_id": "v1", "split": "dev", "language": "ar",
         "source_ref": "source/ar.pdf", "text": "دليل عربي للمشروع"},
        {"document_id": "d-en", "version_id": "v1", "split": "dev", "language": "en",
         "source_ref": "source/en.pdf", "text": "English project evidence"},
    ]
    for doc in docs:
        doc["content_sha256"] = hashlib.sha256(doc["text"].encode()).hexdigest()
    chunks = []
    for doc in docs:
        chunks.append({"chunk_id": f"c-{doc['document_id']}", "document_id": doc["document_id"],
                       "version_id": doc["version_id"], "split": "dev", "start_char": 0,
                       "end_char": len(doc["text"]), "text": doc["text"],
                       "content_sha256": doc["content_sha256"]})
    queries = [
        {"question_id": qid, "text": f"question {qid}", "query_language": qlang,
         "evidence_language": elang, "split": "dev", "answerable": True}
        for qid, qlang, elang in (("q-aa", "ar", "ar"), ("q-ee", "en", "en"),
                                  ("q-ae", "ar", "en"), ("q-ea", "en", "ar"))
    ]
    queries.append({"question_id": "q-none", "text": "not in corpus", "query_language": "en",
                    "evidence_language": None, "split": "dev", "answerable": False})
    manifest = {
        "schema_version": 2, "dataset_id": "provisional-demo", "dataset_version": "1", "split": "dev",
        "synthetic": False,
        "provenance": {"source_name": "local owner corpus", "source_version": "v1", "license": "private",
                       "retrieved_at": "2026-11-12", "source_sha256": "a" * 64},
        "documents": docs, "chunks": chunks, "queries": queries, "review_records": [],
    }
    for query in queries:
        qid = query["question_id"]
        manifest["review_records"].append({"question_id": qid, "target_kind": "answerability",
                                            "target_id": qid, "reviewer_id": "reviewer-a",
                                            "relevance": 3 if query["answerable"] else 0,
                                            "rationale": "submitted owner decision", "status": "submitted"})
        for chunk in chunks:
            doc = next(item for item in docs if item["document_id"] == chunk["document_id"])
            grade = 2 if query["answerable"] and doc["language"] == query["evidence_language"] else 0
            manifest["review_records"].append({"question_id": qid, "target_kind": "chunk",
                                                "target_id": chunk["chunk_id"], "reviewer_id": "reviewer-a",
                                                "relevance": grade, "rationale": "submitted owner decision",
                                                "status": "submitted"})
    return manifest


class OwnerReviewDiagnosticTests(unittest.TestCase):
    def test_provisional_report_keeps_submitted_labels_explicit_and_reports_all_directions(self):
        manifest = _manifest()
        checked = validate_owner_dev_manifest(manifest, reviewer_id="reviewer-a")
        chunks = [Chunk("source/ar.pdf", "d-ar", "v1", "c-d-ar", 0, len("دليل عربي للمشروع"), 1, 1, (), "دليل عربي للمشروع"),
                  Chunk("source/en.pdf", "d-en", "v1", "c-d-en", 0, len("English project evidence"), 1, 1, (), "English project evidence")]
        by_id = {chunk.chunk_id: chunk for chunk in chunks}
        spec = RetrieverSpec(lambda query, k: (ChunkHit(by_id["c-d-ar"], 1.0),),
                             "score descending, chunk ID ascending")
        report = run_owner_dev_diagnostic(checked, {"fake": spec}, k=3)
        self.assertIn("not independently adjudicated", report["evaluation_status"])
        self.assertEqual(report["label_status"], PROVISIONAL_LABEL)
        self.assertEqual(set(report["strategies"]["fake"]["by_direction"]),
                         {"ar->ar", "ar->en", "en->ar", "en->en"})
        self.assertEqual(report["strategies"]["fake"]["no_answer"]["false_positive_queries"], 1)
        self.assertNotIn("question q-aa", str(report))
        self.assertNotIn("دليل عربي", str(report))

    def test_holdout_and_explicit_holdout_artifacts_are_rejected(self):
        manifest = _manifest()
        manifest["split"] = "holdout"
        with self.assertRaisesRegex(FixtureError, "accept dev split only"):
            validate_owner_dev_manifest(manifest, reviewer_id="reviewer-a")
        manifest = _manifest()
        manifest["holdout_manifest"] = {"path": "do-not-open"}
        with self.assertRaisesRegex(FixtureError, "holdout fields"):
            validate_owner_dev_manifest(manifest, reviewer_id="reviewer-a")

    def test_missing_review_unsupported_reviewer_and_non_submitted_votes_fail(self):
        manifest = _manifest()
        manifest["review_records"].pop()
        with self.assertRaisesRegex(FixtureError, "cover every query and chunk"):
            validate_owner_dev_manifest(manifest, reviewer_id="reviewer-a")
        manifest = _manifest()
        manifest["review_records"][0]["reviewer_id"] = "reviewer-b"
        with self.assertRaisesRegex(FixtureError, "unsupported reviewer identity"):
            validate_owner_dev_manifest(manifest, reviewer_id="reviewer-a")
        with self.assertRaisesRegex(FixtureError, "unsupported reviewer identity"):
            validate_owner_dev_manifest(_manifest(), reviewer_id="reviewer-b")
        manifest = _manifest()
        manifest["review_records"][0]["status"] = "accepted_by_agreement"
        with self.assertRaisesRegex(FixtureError, "must remain submitted"):
            validate_owner_dev_manifest(manifest, reviewer_id="reviewer-a")

    def test_malformed_source_provenance_and_conflicting_labels_fail(self):
        manifest = _manifest()
        manifest["chunks"][0]["version_id"] = "wrong-version"
        with self.assertRaisesRegex(FixtureError, "inconsistent split or version"):
            validate_owner_dev_manifest(manifest, reviewer_id="reviewer-a")
        manifest = _manifest()
        answer = next(row for row in manifest["review_records"]
                      if row["question_id"] == "q-aa" and row["target_kind"] == "answerability")
        answer["relevance"] = 0
        with self.assertRaisesRegex(FixtureError, "conflicts with query"):
            validate_owner_dev_manifest(manifest, reviewer_id="reviewer-a")

    def test_document_level_submitted_judgments_are_covered_and_reported_separately(self):
        manifest = _manifest()
        docs = manifest["documents"]
        for query in manifest["queries"]:
            for doc in docs:
                grade = 2 if query["answerable"] and doc["language"] == query["evidence_language"] else 0
                manifest["review_records"].append({
                    "question_id": query["question_id"], "target_kind": "document",
                    "target_id": doc["document_id"], "reviewer_id": "reviewer-a",
                    "relevance": grade, "rationale": "submitted document vote", "status": "submitted",
                })
        checked = validate_owner_dev_manifest(manifest, reviewer_id="reviewer-a")
        chunks = {"c-d-ar": Chunk("source/ar.pdf", "d-ar", "v1", "c-d-ar", 0, len("دليل عربي للمشروع"), 1, 1, (), "دليل عربي للمشروع"),
                  "c-d-en": Chunk("source/en.pdf", "d-en", "v1", "c-d-en", 0, len("English project evidence"), 1, 1, (), "English project evidence")}
        spec = RetrieverSpec(lambda query, k: [ChunkHit(chunks["c-d-ar"], 1.0),
                                                ChunkHit(chunks["c-d-en"], 0.5)],
                             "score descending, chunk ID ascending")
        report = run_owner_dev_diagnostic(checked, {"strategy": spec}, k=2)
        self.assertIn("document_level_by_direction", report["strategies"]["strategy"])
        self.assertEqual(set(report["strategies"]["strategy"]["document_level_by_direction"]),
                         {"ar->ar", "ar->en", "en->ar", "en->en"})
        manifest["review_records"].pop()
        with self.assertRaisesRegex(FixtureError, "document-level reviews.*cover every"):
            validate_owner_dev_manifest(manifest, reviewer_id="reviewer-a")

    def test_duplicate_or_unknown_retrieval_provenance_fails_closed(self):
        manifest = _manifest()
        duplicate = RetrieverSpec(lambda query, k: [ChunkHit(Chunk("x", "x", "v", "c-d-ar", 0, 1, 1, 1, (), "x"), 1),
                                                    ChunkHit(Chunk("x", "x", "v", "c-d-ar", 0, 1, 1, 1, (), "x"), 0.9)],
                                  "score descending, chunk ID ascending")
        with self.assertRaisesRegex(FixtureError, "duplicate chunk IDs"):
            run_owner_dev_diagnostic(manifest, {"bad": duplicate})

        spoof = RetrieverSpec(lambda query, k: [ChunkHit(
            Chunk("different-source", "d-ar", "v1", "c-d-ar", 0, len("دليل عربي للمشروع"),
                  1, 1, (), "دليل عربي للمشروع"), 1.0
        )], "score descending, chunk ID ascending")
        with self.assertRaisesRegex(FixtureError, "mismatched chunk provenance"):
            run_owner_dev_diagnostic(manifest, {"spoof": spoof})

    def test_provisional_cli_compares_all_four_strategies_with_injected_encoder(self):
        import contextlib
        import io
        import json
        import tempfile
        import sys
        from pathlib import Path
        from unittest.mock import patch
        from scripts import run_provisional_owner_review_diagnostic as cli

        class FakeEncoder:
            model_id = "fake/multilingual-e5"
            revision = "0123456789abcdef0123456789abcdef01234567"
            def encode(self, texts, *, kind):
                def vector(text):
                    if kind == "query":
                        return (1.0, 0.0) if any("\u0600" <= char <= "\u06ff" for char in text) else (0.0, 1.0)
                    return (1.0, 0.0) if any("\u0600" <= char <= "\u06ff" for char in text) else (0.0, 1.0)
                return tuple(vector(text) for text in texts)

        with tempfile.TemporaryDirectory() as directory:
            manifest_path = Path(directory) / "manifest.json"
            output_path = Path(directory) / "report.json"
            manifest_path.write_text(json.dumps(_manifest(), ensure_ascii=False), encoding="utf-8")
            argv = ["run_provisional_owner_review_diagnostic.py", "--manifest", str(manifest_path),
                    "--allow-provisional", "--reviewer", "reviewer-a", "--with-e5",
                    "--with-windowed-e5", "--json-out", str(output_path)]
            with patch.object(sys, "argv", argv), patch.object(cli, "LocalE5Encoder", FakeEncoder), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cli.main(), 0)
            report = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(set(report["strategies"]),
                             {"bm25_raw", "original_e5", "windowed_e5", "windowed_hybrid"})
            self.assertIn("not independently adjudicated", report["evaluation_status"])

    def test_provisional_cli_requires_explicit_opt_in(self):
        import contextlib
        import io
        import sys
        from unittest.mock import patch
        from scripts import run_provisional_owner_review_diagnostic as cli
        stderr = io.StringIO()
        argv = ["run_provisional_owner_review_diagnostic.py", "--manifest", "unused.json",
                "--reviewer", "reviewer-a", "--with-windowed-e5"]
        with patch.object(sys, "argv", argv), contextlib.redirect_stderr(stderr), \
                self.assertRaises(SystemExit) as raised:
            cli.main()
        self.assertEqual(raised.exception.code, 2)
        self.assertIn("--allow-provisional", stderr.getvalue())
