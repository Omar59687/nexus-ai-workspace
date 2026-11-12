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


if __name__ == "__main__":
    unittest.main()
