import copy
import csv
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import experiments.rag_prototype.benchmark_dataset as benchmark_dataset

from experiments.rag_prototype.benchmark_dataset import (
    adjudicate_reviews,
    build_corpus_manifest,
    dataset_release_sha256,
    export_review_sheet,
    import_review_sheet,
    resolve_adjudications,
    to_evaluation_fixture,
    validate_dataset,
    validate_split_pair,
)
from experiments.rag_prototype.evaluation import FixtureError, run_evaluation, validate_fixture


def _dataset():
    docs = [
        {"document_id":"d-ar","version_id":"v-ar","split":"dev","language":"ar",
         "source_ref":"source/ar.txt","text":"دليل عربي للمشروع"},
        {"document_id":"d-en","version_id":"v-en","split":"dev","language":"en",
         "source_ref":"source/en.txt","text":"English project evidence"},
    ]
    for doc in docs:
        doc["content_sha256"] = hashlib.sha256(doc["text"].encode()).hexdigest()
    chunks = []
    for doc in docs:
        chunks.append({"chunk_id":f"c-{doc['document_id']}","document_id":doc["document_id"],
                       "version_id":doc["version_id"],"split":"dev","start_char":0,
                       "end_char":len(doc["text"]),"text":doc["text"],
                       "content_sha256":doc["content_sha256"]})
    queries = []
    for qid, qlang, elang in (("q-aa","ar","ar"),("q-ee","en","en"),("q-ae","ar","en"),("q-ea","en","ar")):
        queries.append({"question_id":qid,"text":f"question {qid}","query_language":qlang,
                        "evidence_language":elang,"split":"dev","answerable":True})
    return {
        "schema_version":2,"dataset_id":"review-demo","dataset_version":"1","split":"dev",
        "synthetic":False,
        "provenance":{"source_name":"Owner-provided test corpus","source_version":"1",
                       "license":"test-only","retrieved_at":"2026-11-11",
                       "source_sha256":"a"*64},
        "documents":docs,"chunks":chunks,"queries":queries,"review_records":[],
    }


class BenchmarkDatasetTests(unittest.TestCase):
    def test_corpus_ingestion_manifest_is_bounded_and_unjudged(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/"ar.txt").write_text("دليل عربي",encoding="utf-8")
            (root/"en.md").write_text("English evidence",encoding="utf-8")
            manifest=build_corpus_manifest(
                root,{"ar.txt":{"language":"ar","source_ref":"source/ar"},
                      "en.md":{"language":"en","source_ref":"source/en"}},
                dataset_id="sample",dataset_version="1",split="dev",source_name="local input",
                source_version="sha-1",license_name="test-only",retrieved_at="2026-11-11",
            )
            self.assertEqual(len(manifest["documents"]),2)
            self.assertTrue(all(row["content_sha256"] for row in manifest["chunks"]))
            self.assertEqual(manifest["queries"],[])
            self.assertEqual(manifest["review_records"],[])

    def test_two_reviewers_generate_auditable_accepted_labels(self):
        dataset=_dataset()
        validate_dataset(dataset)
        all_records=[]
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for reviewer in ("reviewer-a","reviewer-b"):
                sheet=root/f"{reviewer}.csv"
                export_review_sheet(dataset,sheet,reviewer_id=reviewer)
                with sheet.open("r",encoding="utf-8",newline="") as stream:
                    reader=csv.DictReader(stream)
                    rows=list(reader); fields=reader.fieldnames
                self.assertTrue(rows[0]["query_text"])
                self.assertEqual(rows[0]["evidence_text"],"")
                self.assertIn("دليل عربي",next(row["evidence_text"] for row in rows if row["target_kind"]=="chunk"))
                for row in rows:
                    if row["target_kind"]=="answerability":
                        row["relevance"]="3"; row["rationale"]="Evidence is present"
                    else:
                        target_lang="ar" if row["document_id"]=="d-ar" else "en"
                        row["relevance"]="2" if target_lang==next(q["evidence_language"] for q in dataset["queries"] if q["question_id"]==row["question_id"]) else "0"
                        row["rationale"]="Supports the answer" if row["relevance"]!="0" else "Does not address the query"
                with sheet.open("w",encoding="utf-8",newline="") as stream:
                    writer=csv.DictWriter(stream,fieldnames=fields); writer.writeheader(); writer.writerows(rows)
                all_records.extend(import_review_sheet(dataset,sheet,expected_reviewer_id=reviewer))
        adjudications=adjudicate_reviews(all_records)
        self.assertTrue(all(row["status"]=="accepted_by_agreement" for row in adjudications))
        review_summary={"dataset_id":dataset["dataset_id"],"dataset_version":dataset["dataset_version"],
                        "split":dataset["split"],"dataset_release_sha256":dataset_release_sha256(dataset),
                        "decisions":adjudications}
        evaluation_fixture=to_evaluation_fixture({**dataset,"review_records":all_records},review_summary)
        validate_fixture(evaluation_fixture)
        report=run_evaluation(evaluation_fixture,k=1)
        self.assertFalse(report["dataset"]["synthetic"])
        self.assertEqual(report["query_count"],4)

        altered=copy.deepcopy(evaluation_fixture)
        altered["human_review"]["records_sha256"]="0"*64
        with self.assertRaisesRegex(FixtureError,"records_sha256"):
            validate_fixture(altered)
        altered=copy.deepcopy(evaluation_fixture)
        altered["documents"][0]["text"] += " altered after adjudication"
        with self.assertRaisesRegex(FixtureError,"fixture_content_sha256"):
            validate_fixture(altered)
        wrong_release={**review_summary,"dataset_version":"2"}
        with self.assertRaisesRegex(FixtureError,"dataset_version"):
            to_evaluation_fixture({**dataset,"review_records":all_records},wrong_release)
        changed=copy.deepcopy(dataset)
        changed["documents"][0]["text"] += " changed"
        changed["documents"][0]["content_sha256"] = hashlib.sha256(changed["documents"][0]["text"].encode()).hexdigest()
        with self.assertRaisesRegex(FixtureError,"dataset_release_sha256"):
            to_evaluation_fixture({**changed,"review_records":all_records},review_summary)

    def test_disagreement_is_never_accepted_automatically(self):
        records=[
            {"question_id":"q","target_kind":"chunk","target_id":"c","reviewer_id":"a","relevance":0},
            {"question_id":"q","target_kind":"chunk","target_id":"c","reviewer_id":"b","relevance":2},
        ]
        result=adjudicate_reviews(records)[0]
        self.assertEqual(result["status"],"needs_adjudication")
        self.assertIsNone(result["relevance"])
        accepted=resolve_adjudications(
            [result],
            [{"question_id":"q","target_kind":"chunk","target_id":"c",
              "adjudicator_id":"independent-adjudicator","relevance":2,"rationale":"Evidence directly supports the claim"}],
        )[0]
        self.assertEqual(accepted["status"],"accepted_by_adjudicator")
        self.assertEqual(accepted["relevance"],2)
        with self.assertRaisesRegex(FixtureError,"independent"):
            resolve_adjudications([result],[{"question_id":"q","target_kind":"chunk","target_id":"c",
                                             "adjudicator_id":"a","relevance":2,"rationale":"reason"}])

    def test_import_rejects_reviewer_identity_changes(self):
        dataset=_dataset()
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"review.csv"
            export_review_sheet(dataset,path,reviewer_id="assigned-reviewer")
            with path.open("r",encoding="utf-8",newline="") as stream:
                reader=csv.DictReader(stream); rows=list(reader); fields=reader.fieldnames
            rows[0]["reviewer_id"]="second-identity"
            with path.open("w",encoding="utf-8",newline="") as stream:
                writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader();writer.writerows(rows)
            with self.assertRaisesRegex(FixtureError,"assigned reviewer"):
                import_review_sheet(dataset,path,expected_reviewer_id="assigned-reviewer")

    def test_review_output_rejects_symlinked_parent_and_changed_evidence(self):
        dataset=_dataset()
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); actual=root/"actual"; actual.mkdir()
            link=root/"link"
            try:
                link.symlink_to(actual,target_is_directory=True)
            except (OSError,NotImplementedError):
                self.skipTest("symlinks unavailable")
            with self.assertRaisesRegex(ValueError,"symlinked parent"):
                export_review_sheet(dataset,link/"review.csv",reviewer_id="reviewer-a")
            sheet=root/"review.csv"
            export_review_sheet(dataset,sheet,reviewer_id="reviewer-a")
            with sheet.open("r",encoding="utf-8",newline="") as stream:
                reader=csv.DictReader(stream);rows=list(reader);fields=reader.fieldnames
            evidence_row=next(row for row in rows if row["target_kind"]=="chunk")
            evidence_row["evidence_text"]="tampered evidence"
            evidence_row["relevance"]="2";evidence_row["rationale"]="supporting text"
            with sheet.open("w",encoding="utf-8",newline="") as stream:
                writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader();writer.writerows(rows)
            with self.assertRaisesRegex(FixtureError,"evidence context"):
                import_review_sheet(dataset,sheet,expected_reviewer_id="reviewer-a")

    def test_import_rejects_document_version_and_provenance_tampering(self):
        dataset=_dataset()
        with tempfile.TemporaryDirectory() as directory:
            sheet=Path(directory)/"review.csv"
            export_review_sheet(dataset,sheet,reviewer_id="reviewer-a")
            with sheet.open("r",encoding="utf-8",newline="") as stream:
                reader=csv.DictReader(stream); fields=reader.fieldnames; rows=list(reader)
            evidence_row=next(row for row in rows if row["target_kind"]=="chunk")
            evidence_row["document_version_id"]="different-version"
            with sheet.open("w",encoding="utf-8",newline="") as stream:
                writer=csv.DictWriter(stream,fieldnames=fields); writer.writeheader(); writer.writerows(rows)
            with self.assertRaisesRegex(FixtureError,"evidence context"):
                import_review_sheet(dataset,sheet,expected_reviewer_id="reviewer-a")
            evidence_row["document_version_id"]="v-ar"
            evidence_row["dataset_provenance_sha256"]="0"*64
            with sheet.open("w",encoding="utf-8",newline="") as stream:
                writer=csv.DictWriter(stream,fieldnames=fields); writer.writeheader(); writer.writerows(rows)
            with self.assertRaisesRegex(FixtureError,"provenance context"):
                import_review_sheet(dataset,sheet,expected_reviewer_id="reviewer-a")

    def test_review_import_rejects_oversized_csv_before_parsing(self):
        dataset=_dataset()
        with tempfile.TemporaryDirectory() as directory:
            sheet=Path(directory)/"review.csv"
            sheet.write_text("dataset_id,dataset_version\n" + "x"*100,encoding="utf-8")
            with patch.object(benchmark_dataset,"MAX_REVIEW_IMPORT_BYTES",32):
                with self.assertRaisesRegex(FixtureError,"safety limit"):
                    import_review_sheet(dataset,sheet,expected_reviewer_id="reviewer-a")

    def test_review_import_accepts_document_evidence_over_default_csv_field_limit(self):
        dataset=_dataset()
        text="x"*150_000
        doc=dataset["documents"][0]
        doc["text"]=text
        doc["content_sha256"]=hashlib.sha256(text.encode()).hexdigest()
        chunk=dataset["chunks"][0]
        chunk_text=text[:4_000]
        chunk.update(start_char=0,end_char=len(chunk_text),text=chunk_text,
                     content_sha256=hashlib.sha256(chunk_text.encode()).hexdigest())
        with tempfile.TemporaryDirectory() as directory:
            sheet=Path(directory)/"large-evidence.csv"
            export_review_sheet(dataset,sheet,reviewer_id="reviewer-a")
            self.assertEqual(import_review_sheet(dataset,sheet,expected_reviewer_id="reviewer-a"),[])

    def test_split_pair_rejects_normalized_content_leakage(self):
        dev=_dataset()
        holdout=copy.deepcopy(dev)
        holdout["split"]="holdout"
        for doc in holdout["documents"]:
            doc["split"]="holdout"; doc["document_id"]="holdout-"+doc["document_id"]
            doc["version_id"]="holdout-"+doc["version_id"]
            doc["source_ref"]="holdout/"+doc["source_ref"]
            doc["text"]="holdout " + doc["text"]
            doc["content_sha256"]=hashlib.sha256(doc["text"].encode()).hexdigest()
        for chunk in holdout["chunks"]:
            chunk["split"]="holdout"; chunk["document_id"]="holdout-"+chunk["document_id"]
            chunk["version_id"]="holdout-"+chunk["version_id"]
            chunk["chunk_id"]="holdout-"+chunk["chunk_id"]
            chunk["text"]="holdout " + chunk["text"]
            chunk["end_char"]=len(chunk["text"])
            chunk["content_sha256"]=hashlib.sha256(chunk["text"].encode()).hexdigest()
        for query in holdout["queries"]:
            query["split"]="holdout"; query["question_id"]="holdout-"+query["question_id"]
        validate_split_pair(dev,holdout)
        holdout["documents"][0]["text"]=dev["documents"][0]["text"]
        holdout["documents"][0]["content_sha256"]=hashlib.sha256(holdout["documents"][0]["text"].encode()).hexdigest()
        holdout["chunks"][0]["text"]=holdout["documents"][0]["text"]
        holdout["chunks"][0]["end_char"]=len(holdout["documents"][0]["text"])
        holdout["chunks"][0]["content_sha256"]=holdout["documents"][0]["content_sha256"]
        with self.assertRaisesRegex(FixtureError,"normalized document text"):
            validate_split_pair(dev,holdout)


if __name__=="__main__":
    unittest.main()
