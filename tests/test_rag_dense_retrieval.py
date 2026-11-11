import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from experiments.rag_prototype import Chunk
from experiments.rag_prototype import dense_retrieval
from experiments.rag_prototype.dense_retrieval import (
    E5_MODEL_REVISION,
    LocalE5Encoder,
    DenseRuntimeUnavailable,
    build_dense_hybrid_retrievers,
)
from experiments.rag_prototype.evaluation import _chunks, load_fixture, run_evaluation
from scripts import run_rag_eval


class FakeEncoder:
    model_id = "fake/e5"
    revision = "0123456789abcdef0123456789abcdef01234567"

    def __init__(self):
        self.max_passage_batch = 0
        self.passage_count = 0

    def encode(self, texts, *, kind):
        if kind == "passage":
            self.max_passage_batch=max(self.max_passage_batch,len(texts))
            self.passage_count+=len(texts)
            return tuple((0.0, 1.0) if "beta" in text else (1.0, 0.0) for text in texts)
        return tuple((1.0, 0.0) for _ in texts)


def _two_chunks():
    return (
        Chunk("a.txt","a","v1","a",0,5,1,1,(),"alpha"),
        Chunk("b.txt","b","v1","b",0,4,1,1,(),"beta"),
    )


class DenseRetrievalTests(unittest.TestCase):
    def test_dense_and_hybrid_use_same_chunks_and_explicit_metadata(self):
        encoder=FakeEncoder()
        retrievers=build_dense_hybrid_retrievers(_two_chunks(),encoder,batch_size=1)
        self.assertEqual(set(retrievers),{"dense_e5_small","hybrid_bm25_e5_rrf"})
        self.assertEqual(retrievers["dense_e5_small"].tie_policy,"cosine descending, chunk ID ascending")
        hits=retrievers["dense_e5_small"].retrieve("alpha",1)
        self.assertEqual([hit.chunk.chunk_id for hit in hits],["a"])
        self.assertEqual(retrievers["hybrid_bm25_e5_rrf"].metadata["rrf_constant"],60)
        self.assertNotIn("hybrid_minimum_rrf_score", retrievers["dense_e5_small"].metadata)
        self.assertIsNone(retrievers["hybrid_bm25_e5_rrf"].metadata["hybrid_minimum_rrf_score"])
        self.assertEqual(encoder.max_passage_batch,1)
        self.assertEqual(encoder.passage_count,2)
        self.assertEqual(retrievers["dense_e5_small"].metadata["embedding_batch_size"],1)

    def test_dense_corpus_limit_fails_before_encoder_is_called(self):
        encoder=FakeEncoder()
        with self.assertRaisesRegex(ValueError,"before embedding"):
            build_dense_hybrid_retrievers(_two_chunks(),encoder,max_dense_chunks=1)
        self.assertEqual(encoder.passage_count,0)

    def test_score_threshold_can_produce_an_explicit_abstention(self):
        fixture=load_fixture(Path(__file__).parents[1]/"benchmarks"/"rag_eval_synthetic_dev_v2.json")
        retriever=build_dense_hybrid_retrievers(_chunks(fixture,"dev"),FakeEncoder(),minimum_score=1.1)["dense_e5_small"]
        report=run_evaluation(fixture,retrievers={"dense_abstain":retriever})
        result=report["strategies"]["dense_abstain"]
        self.assertEqual(result["answerable_coverage"]["retrieved_relevant_at_k"],0)
        self.assertEqual(result["no_answer"]["abstained_queries"],1)

    def test_hybrid_rrf_threshold_is_reported_and_can_abstain(self):
        fixture=load_fixture(Path(__file__).parents[1]/"benchmarks"/"rag_eval_synthetic_dev_v2.json")
        retriever=build_dense_hybrid_retrievers(
            _chunks(fixture,"dev"), FakeEncoder(), hybrid_minimum_score=1.0
        )["hybrid_bm25_e5_rrf"]
        self.assertEqual(retriever.minimum_score,1.0)
        self.assertEqual(retriever.metadata["hybrid_minimum_rrf_score"],1.0)
        report=run_evaluation(fixture,retrievers={"hybrid_abstain":retriever})
        result=report["strategies"]["hybrid_abstain"]
        self.assertEqual(result["no_answer"]["abstained_queries"],1)
        self.assertEqual(result["answerable_coverage"]["retrieved_relevant_at_k"],0)

    def test_hybrid_rrf_threshold_rejects_non_finite_and_boolean_values(self):
        for invalid in (float("inf"), float("nan"), True, "0.1"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    build_dense_hybrid_retrievers(
                        _two_chunks(), FakeEncoder(), hybrid_minimum_score=invalid
                    )

    def test_cli_forwards_hybrid_threshold_to_json_report(self):
        with tempfile.TemporaryDirectory(dir=run_rag_eval.REPOSITORY_ROOT) as directory:
            report_path=Path(directory)/"report.json"
            argv=[
                "run_rag_eval.py", "--with-e5", "--hybrid-minimum-rrf-score", "1.0",
                "--fixture", "benchmarks/rag_eval_synthetic_dev_v2.json",
                "--json-out", str(report_path.relative_to(run_rag_eval.REPOSITORY_ROOT)),
            ]
            with patch.object(sys,"argv",argv), patch.object(
                dense_retrieval,"LocalE5Encoder",FakeEncoder
            ):
                self.assertEqual(run_rag_eval.main(),0)
            report=json.loads(report_path.read_text(encoding="utf-8"))
            dense=report["strategies"]["dense_e5_small"]["diagnostics"]
            hybrid=report["strategies"]["hybrid_bm25_e5_rrf"]["diagnostics"]
            self.assertIsNone(dense["minimum_score"])
            self.assertNotIn("hybrid_minimum_rrf_score",dense["metadata"])
            self.assertEqual(hybrid["minimum_score"],1.0)
            self.assertEqual(hybrid["metadata"]["hybrid_minimum_rrf_score"],1.0)

    def test_cli_rejects_threshold_without_with_e5(self):
        stderr=io.StringIO()
        with patch.object(sys,"argv",["run_rag_eval.py","--hybrid-minimum-rrf-score","0.1"]), \
             contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit) as raised:
            run_rag_eval.main()
        self.assertEqual(raised.exception.code,2)
        self.assertIn("thresholds require --with-e5",stderr.getvalue())

    def test_pinned_adapter_rejects_floating_model_revisions(self):
        self.assertEqual(len(E5_MODEL_REVISION),40)
        with self.assertRaisesRegex(ValueError,"immutable"):
            LocalE5Encoder(revision="main")

    def test_missing_optional_runtime_fails_without_downloading(self):
        try:
            import torch  # noqa: F401
            from transformers import AutoModel  # noqa: F401
        except ImportError:
            with self.assertRaises(DenseRuntimeUnavailable):
                LocalE5Encoder()


if __name__=="__main__":
    unittest.main()
