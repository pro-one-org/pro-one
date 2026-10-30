import copy
import hashlib
import json
import logging
import shutil
import socket
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.corpus import passage_relationship_errors
from app.execution import ExecutionContextService
from app.main import app
from app.readiness import WorkflowReadinessService
from app.repository import RecordRepository, RepositoryLoadError
from app.retrieval import PassageRetrievalService, RetrievalFilterError, RetrievalRequest
from test_readiness import WORKFLOW_ID as READY_WORKFLOW_ID, make_ready_repository
from test_repository_foundation import repository_validator


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = "va-small-claims-warrant-in-debt-information"
CODE = "va-small-claims-procedure-code"
FORM = "va-dc402-warrant-in-debt-small-claims-form"
INSTRUCTIONS = "va-dc402-warrant-in-debt-instructions"
RULE = "va-small-claims-warrant-and-answer-rule"
STEP = "va-small-claims-identify-warrant"
PREFIX = "va-small-claims-passage-"


class CorpusIntegrityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repository = RecordRepository()

    def load_changed(self, edit=None, *, remove=False):
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory) / "data"
            shutil.copytree(ROOT / "data", data)
            path = data / "source-passages.json"
            if remove:
                path.unlink()
            else:
                passages = json.loads(path.read_text(encoding="utf-8"))
                edit(passages)
                path.write_text(json.dumps(passages), encoding="utf-8")
            return RecordRepository(data_dir=data)

    def test_corpus_loads_and_resolves_through_existing_repository(self) -> None:
        self.assertEqual(13, len(self.repository.records["source_passages"]))
        self.assertEqual(9, self.repository.resolve_workflow(WORKFLOW)["counts"]["source_passages"])

    def test_missing_corpus_fails_startup(self) -> None:
        with self.assertRaisesRegex(RepositoryLoadError, "Required data file is missing"):
            self.load_changed(remove=True)

    def test_duplicate_ids_fail_startup(self) -> None:
        with self.assertRaisesRegex(RepositoryLoadError, "Duplicate id"):
            self.load_changed(lambda records: records.append(copy.deepcopy(records[0])))

    def test_unknown_record_relationships_fail_startup(self) -> None:
        for field, value in (
            ("source_id", "unknown-source"), ("workflow_ids", ["unknown-workflow"]),
            ("legal_rule_ids", ["unknown-rule"]), ("process_step_ids", ["unknown-step"]),
        ):
            with self.subTest(field=field), self.assertRaises(RepositoryLoadError):
                self.load_changed(lambda records: records[0].update({field: value}))

    def test_existing_but_unrelated_source_rule_and_step_fail_startup(self) -> None:
        for field, value in (
            ("source_id", "example-state-court-name-change-guide"),
            ("legal_rule_ids", ["example-name-change-filing-instructions-rule"]),
            ("process_step_ids", ["example-name-change-review-instructions"]),
        ):
            with self.subTest(field=field), self.assertRaises(RepositoryLoadError):
                self.load_changed(lambda records: records[0].update({field: value}))

    def test_source_must_support_linked_rule_or_step(self) -> None:
        # The instruction source is workflow-linked, but not named by this rule.
        with self.assertRaisesRegex(RepositoryLoadError, "source_not_linked_to_record"):
            self.load_changed(lambda records: records[-2].update({"legal_rule_ids": [RULE]}))

    def test_jurisdiction_mismatch_fails_startup(self) -> None:
        with self.assertRaisesRegex(RepositoryLoadError, "jurisdiction_mismatch"):
            self.load_changed(lambda records: records[0]["jurisdiction"].update({"state": "Maryland"}))

    def test_linked_rule_jurisdiction_must_match_passage(self) -> None:
        records = copy.deepcopy(self.repository.records)
        records["legal_rules"][RULE]["jurisdiction"]["state"] = "Maryland"
        passage = records["source_passages"][PREFIX + "pleading-categories"]
        errors = passage_relationship_errors(
            passage, sources=records["sources"], workflows=records["workflows"],
            legal_rules=records["legal_rules"], process_steps=records["process_steps"],
        )
        self.assertIn(f"jurisdiction_mismatch:{RULE}", errors)

    def test_hash_mismatch_fails_startup(self) -> None:
        with self.assertRaisesRegex(RepositoryLoadError, "excerpt_hash_mismatch"):
            self.load_changed(lambda records: records[0].update({"text": "Altered text"}))

    def test_invalid_verification_order_fails_startup(self) -> None:
        with self.assertRaisesRegex(RepositoryLoadError, "verification_precedes_retrieval"):
            self.load_changed(lambda records: records[0]["verification"].update({"verified_on": "2020-01-01"}))

    def test_schema_rejects_missing_text_invalid_dates_and_extra_properties(self) -> None:
        edits = (
            lambda r: r[0].pop("text"),
            lambda r: r[0]["verification"].update({"verified_on": "not-a-date"}),
            lambda r: r[0].update({"arbitrary": True}),
            lambda r: r[0].update({"workflow_ids": []}),
        )
        for edit in edits:
            with self.subTest(edit=edit), self.assertRaisesRegex(RepositoryLoadError, "schema validation"):
                self.load_changed(edit)

    def test_all_virginia_records_and_reviews_remain_proposed(self) -> None:
        records = [r for group in self.repository.records.values() for r in group.values() if r["id"].startswith("va-")]
        self.assertEqual(50, len(records))
        for record in records:
            self.assertEqual("proposed", record["status"])
            self.assertEqual("proposed", record["review"]["status"])

    def test_excerpt_hashes_are_actual_text_hashes(self) -> None:
        for passage in self.repository.records["source_passages"].values():
            self.assertEqual(
                "sha256:" + hashlib.sha256(passage["text"].encode("utf-8")).hexdigest(),
                passage["verification"]["excerpt_hash"],
            )

    def test_repository_validator_and_runtime_share_corpus_semantics(self) -> None:
        self.assertIs(passage_relationship_errors, repository_validator.passage_relationship_errors)

    def test_validator_checks_typed_source_reference_and_supported_dependency(self) -> None:
        passage = copy.deepcopy(next(iter(self.repository.records["source_passages"].values())))
        for supported in (False, True):
            passage["status"] = "supported" if supported else "proposed"
            if supported:
                passage["review"]["status"] = "approved"
                passage["review"]["review_scope"] = sorted(repository_validator.SUPPORTED_REVIEW_SCOPES["source_passage"])
            records = {"source_passage": {passage["id"]: passage}}
            locations = {("source_passage", passage["id"]): "test:passage"}
            if supported:
                source = self.repository.get("sources", passage["source_id"])
                records["source"] = {source["id"]: source}
                locations[("source", source["id"])] = "test:source"
            report = repository_validator.ValidationReport()
            repository_validator.validate_cross_record_references(records, locations, report)
            self.assertTrue(any("ineligible supporting source" in error if supported else "unknown source id" in error for error in report.errors))


class PassageRetrievalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = RecordRepository()
        self.service = PassageRetrievalService(self.repository)

    def retrieve(self, workflow=WORKFLOW, **kwargs):
        return self.service.retrieve(workflow, RetrievalRequest(**kwargs))

    def test_workflow_scoping_includes_only_resolver_selected_passages(self) -> None:
        result = self.retrieve(limit=20)
        expected = self.repository.resolve_workflow(WORKFLOW)["related"]["source_passages"]
        self.assertEqual(sorted(r["id"] for r in expected), [p["id"] for p in result["passages"]])
        self.assertTrue(all(p["workflow_ids"] == [WORKFLOW] for p in result["passages"]))

    def test_example_workflow_has_no_corpus_and_no_global_fallback(self) -> None:
        result = self.retrieve("name_change_information", query="return date")
        self.assertEqual([], result["passages"])
        self.assertEqual("no_eligible_passages", result["retrieval"]["status"])

    def test_unknown_workflow_returns_none(self) -> None:
        self.assertIsNone(self.retrieve("unknown"))

    def test_unrelated_or_unknown_filters_fail_without_scope_expansion(self) -> None:
        for field, value in (
            ("source_ids", "example-state-court-name-change-guide"),
            ("legal_rule_ids", "example-name-change-filing-instructions-rule"),
            ("process_step_ids", "example-name-change-review-instructions"),
            ("proposition_ids", "unknown-proposition"),
        ):
            with self.subTest(field=field), self.assertRaises(RetrievalFilterError) as caught:
                self.retrieve(**{field: [value]})
            self.assertEqual({field: [value]}, caught.exception.invalid_filters)

    def test_valid_relationship_filters_narrow_candidates(self) -> None:
        for field, values in (
            ("source_ids", [FORM]), ("legal_rule_ids", [RULE]),
            ("process_step_ids", [STEP]),
            ("proposition_ids", ["va-small-claims-removal-right"]),
        ):
            with self.subTest(field=field):
                passages = self.retrieve(**{field: values})["passages"]
                self.assertTrue(passages)
                for passage in passages:
                    actual = [passage["source_id"]] if field == "source_ids" else passage["propositions"] if field == "proposition_ids" else passage[field]
                    self.assertTrue(set(values) & set(actual))

    def test_filter_types_intersect_and_values_within_type_union(self) -> None:
        union = self.retrieve(source_ids=[CODE, FORM], limit=20)
        self.assertEqual(7, len(union["passages"]))
        intersection = self.retrieve(source_ids=[FORM], legal_rule_ids=[RULE])
        self.assertEqual([], intersection["passages"])

    def test_return_date_query_ranks_first_return_date_passage(self) -> None:
        self.assertEqual(PREFIX + "first-return-date", self.retrieve(query="return date")["passages"][0]["id"])

    def test_removal_query_ranks_removal_passage(self) -> None:
        self.assertEqual(PREFIX + "removal", self.retrieve(query="removal")["passages"][0]["id"])

    def test_grounds_of_defense_query_preserves_freshness_warning(self) -> None:
        passage = self.retrieve(query="Grounds of Defense")["passages"][0]
        self.assertEqual(INSTRUCTIONS, passage["source_id"])
        self.assertIn("September 2008", json.dumps(passage["limitations"]))
        self.assertFalse(passage["freshness"]["currentness_certified"])
        self.assertEqual("2026-10-30", passage["verification"]["verified_on"])
        self.assertEqual("2026-09-28", passage["freshness"]["source_dates"]["last_verified"])

    def test_written_answer_deadline_query_preserves_support_gap(self) -> None:
        result = self.retrieve(query="universal written answer deadline")
        self.assertTrue(result["passages"])
        self.assertIn("does not establish a universal written-answer", " ".join(result["limitations"]))
        self.assertEqual(PREFIX + "pleading-categories", result["passages"][0]["id"])
        for passage in result["passages"]:
            self.assertEqual(self.repository.get("source_passages", passage["id"])["text"], passage["text"])

    def test_appearance_query_preserves_both_wordings_and_uncertainty(self) -> None:
        result = self.retrieve(query="appearance")
        self.assertEqual({FORM, "va-small-claims-self-help"}, {p["source_id"] for p in result["passages"]})
        self.assertIn("Appearance wording remains unresolved", " ".join(result["limitations"]))

    def test_ranking_and_ties_are_stable_under_input_and_storage_reordering(self) -> None:
        first = self.retrieve(query="appearance", source_ids=[FORM, CODE])
        self.repository.records["source_passages"] = dict(reversed(list(self.repository.records["source_passages"].items())))
        self.assertEqual(first, self.retrieve(query="appearance", source_ids=[CODE, FORM, FORM]))
        ties = self.retrieve(query="appearance")["passages"]
        self.assertEqual(ties[0]["retrieval_score"], ties[1]["retrieval_score"])
        self.assertEqual(sorted(p["id"] for p in ties), [p["id"] for p in ties])

    def test_limit_and_counts_are_explicit(self) -> None:
        result = self.retrieve(limit=2)
        self.assertEqual(9, result["retrieval"]["candidate_count"])
        self.assertEqual(9, result["retrieval"]["matched_count"])
        self.assertEqual(2, result["retrieval"]["returned_count"])

    def test_empty_no_match_and_omitted_queries_are_distinct(self) -> None:
        for query, status in ((" \t ", "empty_query"), ("xyzzzz", "no_matching_passages")):
            result = self.retrieve(query=query)
            self.assertEqual([], result["passages"])
            self.assertEqual(status, result["retrieval"]["status"])
        self.assertTrue(self.retrieve()["passages"])
        self.assertEqual("relationship_selection_v1", self.retrieve()["retrieval"]["algorithm"])

    def test_every_passage_has_citation_provenance_and_both_review_states(self) -> None:
        for passage in self.retrieve(limit=20)["passages"]:
            source = self.repository.get("sources", passage["source_id"])
            self.assertEqual(source["title"], passage["source_title"])
            self.assertEqual(source["url"], passage["source_url"])
            self.assertEqual(source["citation"], passage["citation"])
            self.assertTrue(passage["locator"])
            self.assertTrue(passage["propositions"])
            self.assertEqual("proposed", passage["status"])
            self.assertEqual("proposed", passage["review"]["status"])
            self.assertEqual("proposed", passage["source_review"]["status"])
            self.assertEqual("unknown", passage["rights"]["reuse_status"])
            self.assertTrue(passage["freshness"])
            self.assertTrue(passage["limitations"])

    def test_deprecated_rejected_superseded_and_nonofficial_sources_are_excluded(self) -> None:
        for mutation in ("deprecated", "rejected_review", "superseded", "nonofficial"):
            with self.subTest(mutation=mutation):
                source = self.repository.get("sources", FORM)
                original = copy.deepcopy(source)
                if mutation == "deprecated": source["status"] = "deprecated"
                if mutation == "rejected_review": source["review"]["status"] = "rejected"
                if mutation == "superseded": source["provenance"]["superseded_by_source_id"] = CODE
                if mutation == "nonofficial": source["authority"]["level"] = "unknown"
                self.assertNotIn(FORM, {p["source_id"] for p in self.retrieve(limit=20)["passages"]})
                source.clear()
                source.update(original)

    def test_rejected_passage_is_not_ranked(self) -> None:
        self.repository.get("source_passages", PREFIX + "removal")["status"] = "rejected"
        self.assertEqual([], self.retrieve(query="removal")["passages"])

    def test_corrupt_relationship_after_startup_fails_closed(self) -> None:
        self.repository.get("sources", FORM)["workflow_fit"]["workflow_ids"] = []
        with self.assertRaises(RepositoryLoadError):
            self.retrieve()

    def test_no_candidates_short_circuits_lexical_ranking(self) -> None:
        with patch("app.retrieval.lexical_score", side_effect=AssertionError("Global ranking")):
            self.assertEqual([], self.retrieve("name_change_information", query="debt")["passages"])

    def test_readiness_is_reused_and_high_score_cannot_change_it(self) -> None:
        expected = WorkflowReadinessService(self.repository).evaluate(WORKFLOW)
        with patch.object(self.repository, "resolve_workflow", wraps=self.repository.resolve_workflow) as resolve:
            result = self.retrieve(query="return date")
        self.assertEqual(2, resolve.call_count)
        self.assertEqual(expected, result["public_execution"]["readiness"])
        self.assertFalse(result["public_execution"]["allowed"])
        self.assertFalse(expected["ready_for_public_use"])

    def test_development_retrieval_never_grants_execution_even_for_ready_workflow(self) -> None:
        service = PassageRetrievalService(make_ready_repository())
        result = service.retrieve(READY_WORKFLOW_ID, RetrievalRequest())
        self.assertTrue(result["public_execution"]["readiness"]["ready_for_public_use"])
        self.assertFalse(result["public_execution"]["allowed"])

    def test_no_network_file_io_processes_or_query_logging_during_retrieval(self) -> None:
        with (
            patch.object(socket, "socket", side_effect=AssertionError("Network")),
            patch.object(socket, "create_connection", side_effect=AssertionError("Network")),
            patch("builtins.open", side_effect=AssertionError("File I/O")),
            patch.object(Path, "open", side_effect=AssertionError("Path I/O")),
            patch.object(subprocess, "Popen", side_effect=AssertionError("Process")),
            patch.object(logging.Logger, "_log") as log,
        ):
            result = self.retrieve(query="return date")
        self.assertTrue(result["passages"])
        log.assert_not_called()

    def test_no_repository_mutation_and_returned_records_are_detached(self) -> None:
        before = copy.deepcopy(self.repository.records)
        result = self.retrieve()
        result["passages"][0]["text"] = "changed"
        result["passages"][0]["citation"]["preferred_citation"] = "changed"
        self.assertEqual(before, self.repository.records)

    def test_requests_are_stateless_and_compatible_with_execution_context(self) -> None:
        first = self.retrieve(query="removal")
        self.retrieve(query="return date", source_ids=[CODE])
        self.assertEqual(first, self.retrieve(query="removal"))
        context = ExecutionContextService(self.repository).build(WORKFLOW, {}, [])
        self.assertEqual(context["workflow_id"], first["workflow_id"])
        self.assertEqual(context["public_execution"]["readiness"], first["public_execution"]["readiness"])
        self.assertFalse(context["public_execution"]["allowed"])


class RetrievalApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)
        cls.url = f"/workflows/{WORKFLOW}/retrieval"

    def test_retrieval_response_contract(self) -> None:
        response = self.client.post(self.url, json={"query": "removal", "limit": 2})
        self.assertEqual(200, response.status_code)
        body = response.json()
        self.assertEqual({"workflow_id", "mode", "query", "filters", "passages", "retrieval", "limitations", "public_execution"}, set(body))
        self.assertEqual(PREFIX + "removal", body["passages"][0]["id"])
        self.assertFalse(body["public_execution"]["allowed"])

    def test_unknown_workflow_is_404(self) -> None:
        self.assertEqual(404, self.client.post("/workflows/unknown/retrieval", json={}).status_code)

    def test_malformed_payloads_and_limits_are_422(self) -> None:
        for payload in ({"limit": 0}, {"limit": 21}, {"limit": True}, {"limit": "5"}, {"query": 1}, {"source_ids": "source"}, {"source_ids": [1]}, {"extra": True}, {"query": "x" * 2001}):
            with self.subTest(payload=payload):
                self.assertEqual(422, self.client.post(self.url, json=payload).status_code)

    def test_invalid_filters_are_explicit_and_sorted(self) -> None:
        response = self.client.post(self.url, json={"source_ids": ["zzz", "aaa", "zzz"]})
        self.assertEqual(422, response.status_code)
        self.assertEqual({"code": "filters_not_in_workflow_package", "invalid_filters": {"source_ids": ["aaa", "zzz"]}}, response.json()["detail"])

    def test_empty_result_is_explicit(self) -> None:
        response = self.client.post(self.url, json={"query": "xyzzzz"})
        self.assertEqual(200, response.status_code)
        self.assertEqual([], response.json()["passages"])
        self.assertEqual("no_matching_passages", response.json()["retrieval"]["status"])

    def test_runtime_integrity_failure_is_409(self) -> None:
        repository = RecordRepository()
        repository.get("source_passages", PREFIX + "removal")["source_id"] = "missing"
        with patch("app.main.retrieval_service", PassageRetrievalService(repository)):
            response = self.client.post(self.url, json={})
        self.assertEqual(409, response.status_code)
        self.assertEqual({"code": "corpus_integrity_error"}, response.json()["detail"])

    def test_openapi_describes_typed_request(self) -> None:
        schema = self.client.get("/openapi.json").json()
        self.assertIn("RetrievalRequest", schema["components"]["schemas"])
        self.assertIn("/workflows/{workflow_id}/retrieval", schema["paths"])


if __name__ == "__main__":
    unittest.main()
