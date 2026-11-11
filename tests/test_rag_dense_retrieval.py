import unittest

from experiments.rag_prototype import Chunk
from experiments.rag_prototype.dense_retrieval import (
    E5_MODEL_REVISION,
    LocalE5Encoder,
    DenseRuntimeUnavailable,
    build_dense_hybrid_retrievers,
)
from experiments.rag_prototype.evaluation import _chunks, load_fixture, run_evaluation
from pathlib import Path


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
