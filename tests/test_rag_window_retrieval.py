import unittest

from experiments.rag_prototype import Chunk
from experiments.rag_prototype.evaluation import load_fixture, run_evaluation
from experiments.rag_prototype.window_retrieval import (
    WindowHit,
    build_window_retriever,
    expand_chunk_window,
)


def _chunks():
    return (
        Chunk("doc.md", "doc", "v1", "c0", 0, 5, 1, 1, (), "alpha"),
        Chunk("doc.md", "doc", "v1", "c1", 5, 10, 2, 2, (), "middle"),
        Chunk("doc.md", "doc", "v1", "c2", 10, 15, 3, 3, (), "omega"),
        Chunk("other.md", "other", "v1", "other0", 0, 5, 1, 1, (), "alpha"),
    )


class WindowRetrievalTests(unittest.TestCase):
    def test_expansion_includes_anchor_and_bounded_neighbors(self):
        hits=build_window_retriever(_chunks(),window_radius=1).retrieve("alpha",2)
        first=next(hit for hit in hits if hit.chunk.chunk_id=="c0")
        self.assertEqual([chunk.chunk_id for chunk in first.window_chunks],["c0","c1"])

    def test_expansion_never_crosses_document_or_version_boundaries(self):
        chunks=(*_chunks(),Chunk("doc.md","doc","v2","new",15,19,4,4,(),"newer"))
        window=expand_chunk_window(chunks[2],chunks,radius=5)
        self.assertEqual([chunk.chunk_id for chunk in window],["c0","c1","c2"])
        self.assertTrue(all(chunk.document_id=="doc" and chunk.version_id=="v1" for chunk in window))

    def test_zero_radius_returns_only_anchor(self):
        hit=build_window_retriever(_chunks(),window_radius=0).retrieve("omega",1)[0]
        self.assertEqual(hit.window_chunks,(hit.chunk,))

    def test_radius_is_bounded_and_rejects_boolean(self):
        for radius in (-1,6,True,1.5):
            with self.subTest(radius=radius), self.assertRaises(ValueError):
                build_window_retriever(_chunks(),window_radius=radius)

    def test_anchor_must_be_unique_in_its_document_version(self):
        duplicated=(*_chunks(),_chunks()[0])
        with self.assertRaisesRegex(ValueError,"duplicate chunk IDs"):
            build_window_retriever(duplicated)
        missing=Chunk("doc.md","doc","v1","missing",50,54,8,8,(),"none")
        with self.assertRaisesRegex(ValueError,"exactly once"):
            expand_chunk_window(missing,_chunks())

    def test_equal_bm25_scores_are_tied_by_chunk_id(self):
        tied=(
            Chunk("z.md","z","v1","z",0,5,1,1,(),"needle"),
            Chunk("a.md","a","v1","a",0,5,1,1,(),"needle"),
        )
        ids=[hit.chunk.chunk_id for hit in build_window_retriever(tied).retrieve("needle",2)]
        self.assertEqual(ids,["a","z"])

    def test_window_hits_keep_the_anchor_as_the_metric_unit(self):
        from pathlib import Path
        fixture=load_fixture(Path(__file__).parents[1]/"benchmarks"/"rag_eval_synthetic_dev_v2.json")
        chunks=tuple(
            Chunk(row["source"],row["document_id"],row["version_id"],row["chunk_id"],
                  0,len(row["text"]),1,1,(),row["text"])
            for row in fixture["chunks"]
        )
        retriever=build_window_retriever(chunks,window_radius=1)
        report=run_evaluation(fixture,retrievers={"window":retriever},k=1)
        strategy=report["strategies"]["window"]
        self.assertEqual(strategy["metrics"]["overall"]["query_count"],5)
        ranked=next(iter(strategy["query_results"].values()))["ranked_chunks"]
        self.assertEqual(len(ranked),1)
        self.assertEqual(ranked[0]["window_chunk_ids"],[ranked[0]["chunk_id"]])

    def test_window_provenance_includes_source_versions_and_offsets(self):
        from pathlib import Path
        fixture=load_fixture(Path(__file__).parents[1]/"benchmarks"/"rag_eval_synthetic_dev_v2.json")
        chunks=tuple(
            Chunk(row["source"],row["document_id"],row["version_id"],row["chunk_id"],
                  0,len(row["text"]),1,1,(),row["text"])
            for row in fixture["chunks"]
        )
        report=run_evaluation(fixture,retrievers={"window":build_window_retriever(chunks)},k=1)
        provenance=next(iter(report["strategies"]["window"]["query_results"].values()))["ranked_chunks"][0]["window_provenance"][0]
        self.assertEqual(provenance["document_version_id"],"v1")
        self.assertEqual(provenance["start_char"],0)
        self.assertGreater(provenance["end_char"],0)

    def test_threshold_can_abstain_without_fabricating_hits(self):
        from pathlib import Path
        fixture=load_fixture(Path(__file__).parents[1]/"benchmarks"/"rag_eval_synthetic_dev_v2.json")
        chunks=tuple(
            Chunk(row["source"],row["document_id"],row["version_id"],row["chunk_id"],
                  0,len(row["text"]),1,1,(),row["text"])
            for row in fixture["chunks"]
        )
        spec=build_window_retriever(chunks,minimum_score=100.0)
        self.assertEqual(spec.minimum_score,100.0)
        report=run_evaluation(fixture,retrievers={"abstaining-window":spec},k=2)
        self.assertEqual(report["strategies"]["abstaining-window"]["answerable_coverage"]["retrieved_relevant_at_k"],0)
        self.assertEqual(report["strategies"]["abstaining-window"]["no_answer"]["false_positive_queries"],0)

    def test_arabic_normalized_window_retriever_is_opt_in(self):
        from pathlib import Path
        fixture=load_fixture(Path(__file__).parents[1]/"benchmarks"/"rag_eval_synthetic_dev_v2.json")
        chunks=tuple(
            Chunk(row["source"],row["document_id"],row["version_id"],row["chunk_id"],
                  0,len(row["text"]),1,1,(),row["text"])
            for row in fixture["chunks"]
        )
        raw=build_window_retriever(chunks).retrieve("ايرادات",3)
        normalized=build_window_retriever(chunks,normalize_arabic=True).retrieve("ايرادات",3)
        self.assertFalse(raw)
        self.assertTrue(normalized)
        self.assertEqual(normalized[0].chunk.chunk_id,"chunk-dev-ar-revenue")

    def test_minimum_score_rejects_non_numeric_and_non_finite_values(self):
        for threshold in (True,"0.2",float("inf"),float("nan")):
            with self.subTest(threshold=threshold), self.assertRaises(ValueError):
                build_window_retriever(_chunks(),minimum_score=threshold)


class FakeMultilingualEncoder:
    model_id = "fake/multilingual-e5"
    revision = "0123456789abcdef0123456789abcdef01234567"

    def encode(self, texts, *, kind):
        rows = []
        for text in texts:
            if kind == "query":
                rows.append((0.0, 1.0) if "apple" in text else ((1.0, 0.0) if any("\u0600" <= c <= "\u06ff" for c in text) else (0.0, 1.0)))
            else:
                rows.append((0.0, 1.0) if "banana" in text or "English" in text else (1.0, 0.0))
        return tuple(rows)


class ActualWindowedE5Tests(unittest.TestCase):
    def test_windows_are_bounded_overlapping_deterministic_and_offset_exact(self):
        from experiments.rag_prototype.window_retrieval import split_text_windows
        chunk = Chunk("source", "doc", "v2", "page-4", 100, 120, 1, 1, (), "abcdefghijklmnopqrst")
        first = split_text_windows((chunk,), window_chars=10, overlap_chars=3)
        second = split_text_windows((chunk,), window_chars=10, overlap_chars=3)
        self.assertEqual(first, second)
        self.assertEqual([(row.start_char, row.end_char, row.text) for row in first], [
            (100, 110, "abcdefghij"), (107, 117, "hijklmnopq"), (114, 120, "opqrst")
        ])
        self.assertTrue(all(row.chunk_id == "page-4" and row.document_version_id == "v2" for row in first))

    def test_arabic_and_english_queries_rank_semantic_windows_and_deduplicate_pages(self):
        from experiments.rag_prototype.window_retrieval import build_windowed_e5_retrievers
        chunks = (
            Chunk("ar.pdf", "ar-doc", "v7", "ar-page", 40, 40 + len("معلومات عربية " * 8), 1, 1, (), "معلومات عربية " * 8),
            Chunk("en.pdf", "en-doc", "v3", "en-page", 0, len("English evidence " * 8), 1, 1, (), "English evidence " * 8),
        )
        specs = build_windowed_e5_retrievers(chunks, FakeMultilingualEncoder(), window_chars=20, overlap_chars=5)
        ar_hits = specs["windowed_e5"].retrieve("سؤال عربي", 2)
        en_hits = specs["windowed_e5"].retrieve("English question", 2)
        self.assertEqual(ar_hits[0].chunk.chunk_id, "ar-page")
        self.assertEqual(en_hits[0].chunk.chunk_id, "en-page")
        self.assertEqual(len({hit.chunk.chunk_id for hit in ar_hits}), len(ar_hits))
        matched = ar_hits[0].matched_window
        self.assertEqual(matched.window.document_version_id, "v7")
        self.assertEqual(matched.window.source, "ar.pdf")
        self.assertGreaterEqual(matched.window.start_char, matched.window.chunk_start_char)
        self.assertLessEqual(matched.window.end_char, matched.window.chunk_end_char)

    def test_weighted_rrf_changes_hybrid_order_and_reports_weights(self):
        from experiments.rag_prototype.window_retrieval import build_windowed_e5_retrievers
        chunks = (
            Chunk("a", "a", "v1", "a", 0, 5, 1, 1, (), "apple"),
            Chunk("b", "b", "v1", "b", 0, 6, 1, 1, (), "banana"),
        )
        encoder = FakeMultilingualEncoder()
        dense_wins = build_windowed_e5_retrievers(chunks, encoder, window_chars=8, overlap_chars=2,
                                                   dense_weight=0.9, rrf_constant=1)["windowed_hybrid"]
        lexical_wins = build_windowed_e5_retrievers(chunks, encoder, window_chars=8, overlap_chars=2,
                                                     dense_weight=0.1, rrf_constant=1)["windowed_hybrid"]
        self.assertEqual(dense_wins.retrieve("apple", 2)[0].chunk.chunk_id, "b")
        self.assertEqual(lexical_wins.retrieve("apple", 2)[0].chunk.chunk_id, "a")
        self.assertEqual(dense_wins.metadata["dense_rrf_weight"], 0.9)
        self.assertAlmostEqual(dense_wins.metadata["lexical_rrf_weight"], 0.1)

    def test_zero_fusion_weight_does_not_inject_irrelevant_candidates(self):
        from experiments.rag_prototype.window_retrieval import weighted_reciprocal_rank_fusion
        ranked = weighted_reciprocal_rank_fusion([("dense-only",), ()], [1.0, 0.0], top_k=3)
        self.assertEqual([row.item_id for row in ranked], ["dense-only"])
        self.assertEqual(weighted_reciprocal_rank_fusion([("unused",), ()], [0.0, 1.0], top_k=3), ())

    def test_windowed_provenance_survives_evaluation_reporting(self):
        from pathlib import Path
        from experiments.rag_prototype.window_retrieval import build_windowed_e5_retrievers
        fixture = load_fixture(Path(__file__).parents[1] / "benchmarks" / "rag_eval_synthetic_dev_v2.json")
        chunks = tuple(
            Chunk(row["source"], row["document_id"], row["version_id"], row["chunk_id"],
                  0, len(row["text"]), 1, 1, (), row["text"])
            for row in fixture["chunks"]
        )
        spec = build_windowed_e5_retrievers(chunks, FakeMultilingualEncoder())["windowed_e5"]
        result = run_evaluation(fixture, retrievers={"windowed": spec}, k=2)
        ranked = next(iter(result["strategies"]["windowed"]["query_results"].values()))["ranked_chunks"]
        item = ranked[0]
        matched = item["matched_subwindow"]
        self.assertEqual(matched["document_version_id"], item["document_version_id"])
        self.assertEqual(matched["chunk_id"], item["chunk_id"])
        self.assertGreaterEqual(matched["start_char"], matched["chunk_start_char"])
        self.assertLessEqual(matched["end_char"], matched["chunk_end_char"])


if __name__ == "__main__":
    unittest.main()
