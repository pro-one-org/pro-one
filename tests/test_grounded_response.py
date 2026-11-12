import copy
import hashlib
import json
import logging
import socket
import subprocess
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from app.grounding import GroundingEligibilityService
from app.main import app
from app.readiness import WorkflowReadinessService
from app.repository import RecordRepository
from app.response_assembly import AssemblyIntegrityError, ResponseAssemblyRequest, ResponseAssemblyService
from app.retrieval import RetrievalFilterError, RetrievalRequest
from app.review_policy import SUPPORTED_REVIEW_SCOPES
from test_intake_execution import ANSWERS, CHOICE_RISK, RETURN_RISK
from test_readiness import EVALUATION_FIXTURE_ID, WORKFLOW_ID as SYNTHETIC_WORKFLOW, make_ready_repository
from test_repository_foundation import repository_validator


WORKFLOW = "va-small-claims-warrant-in-debt-information"
PREFIX = "va-small-claims-passage-"
CODE = "va-small-claims-procedure-code"
TODAY = date(2026, 10, 30)
FIXTURE_PASSAGE = "synthetic-grounding-passage"
FIXTURE_PATTERN = "synthetic-grounding-response"


def codes(result, public=True):
    key = "public_grounding" if public else "development_grounding"
    return {b["code"] for b in result[key]["blockers"]}


def approve(record, kind):
    """Synthetic in-memory provenance only; never applied to on-disk records."""
    record["status"] = "supported"
    record["review"] = {
        "status": "approved", "reviewed_by": "synthetic-test-only",
        "reviewer_role": "technical_reviewer", "review_scope": sorted(SUPPORTED_REVIEW_SCOPES[kind]),
        "reviewed_on": TODAY.isoformat(), "reviewed_record_version": record["record_version"],
    }


def certify(record, version):
    record["public_currentness"] = {
        "status": "certified", "record_version": record["record_version"],
        "source_content_version": version, "verified_on": TODAY.isoformat(),
        "valid_through": (TODAY + timedelta(days=30)).isoformat(), "unresolved_issues": [],
    }


def synthetic_repository():
    """Fully controlled fictional positive path, with no Virginia promotions."""
    repo = make_ready_repository()
    workflow = repo.get_workflow(SYNTHETIC_WORKFLOW)
    approve(workflow, "workflow")
    workflow["review"]["review_scope"].append("privacy")
    source_id = workflow["sources"]["required_source_ids"][0]
    step_id = workflow["process"]["process_step_ids"][0]
    rule_id = repo.resolve_workflow(SYNTHETIC_WORKFLOW)["related"]["legal_rules"][0]["id"]
    source, step, rule = repo.get("sources", source_id), repo.get("process_steps", step_id), repo.get("legal_rules", rule_id)
    source["dates"]["last_verified"] = TODAY.isoformat()
    source["citation"]["retrieved_at"] = TODAY.isoformat()
    source["provenance"]["source_content_version"] = "synthetic-version"
    source["rights"]["reuse_status"] = "public_domain"
    approve(source, "source")
    certify(source, "synthetic-version")
    approve(step, "process_step")
    approve(rule, "legal_rule")
    rule["jurisdiction"].update({key: source["jurisdiction"].get(key) for key in ("country", "state", "locality", "court", "agency")})
    rule["rule_statement"]["user_facing_allowed"] = True
    pattern = copy.deepcopy(repo.get("responses", "va-small-claims-information-response"))
    pattern["id"] = FIXTURE_PATTERN
    for field in pattern["related_records"]:
        pattern["related_records"][field] = []
    pattern["related_records"]["workflow_ids"] = [SYNTHETIC_WORKFLOW]
    pattern["related_records"]["source_ids"] = [source_id]
    pattern["source_use"]["allowed_source_review_statuses"] = ["approved"]
    pattern["source_use"]["allowed_source_authority_levels"] = [source["authority"]["level"]]
    approve(pattern, "response")
    for record in (step, rule, pattern):
        record["evaluation"]["required_evaluation_fixture_ids"] = [EVALUATION_FIXTURE_ID]
    repo.records["responses"][pattern["id"]] = pattern
    passage = copy.deepcopy(repo.get("source_passages", PREFIX + "division"))
    passage.update({
        "id": FIXTURE_PASSAGE, "workflow_ids": [SYNTHETIC_WORKFLOW], "source_id": source_id,
        "jurisdiction": copy.deepcopy(source["jurisdiction"]), "title": "Synthetic grounded topic",
        "text": "Synthetic test excerpt.", "propositions": ["synthetic-grounded-topic"],
        "legal_rule_ids": [rule_id], "process_step_ids": [step_id],
        "limitations": ["Synthetic evidence only; not an actual legal review."],
    })
    passage["verification"].update({
        "source_version": "synthetic-version", "verified_on": TODAY.isoformat(),
        "retrieved_on": TODAY.isoformat(),
        "excerpt_hash": "sha256:" + hashlib.sha256(passage["text"].encode()).hexdigest(),
    })
    approve(passage, "source_passage")
    certify(passage, "synthetic-version")
    repo.records["source_passages"][passage["id"]] = passage
    return repo


class GroundingEligibilityTests(unittest.TestCase):
    def setUp(self):
        self.repo = RecordRepository()
        self.service = GroundingEligibilityService(self.repo, lambda: TODAY)

    def evaluate(self, suffix="first-return-date", **kwargs):
        return self.service.evaluate(WORKFLOW, [PREFIX + suffix], **kwargs)

    def test_unknown_workflow_returns_none(self):
        self.assertIsNone(self.service.evaluate("unknown", []))

    def test_proposed_virginia_material_is_development_only(self):
        result = self.evaluate()
        self.assertTrue(result["development_grounding"]["available"])
        self.assertFalse(result["public_grounding"]["allowed"])
        for code in ("passage_status_not_supported", "passage_review_not_approved", "source_status_not_supported", "process_step_status_not_supported", "response_pattern_status_not_supported", "workflow_not_ready"):
            self.assertIn(code, codes(result))

    def test_linked_legal_rule_is_checked_even_if_caller_omits_it(self):
        result = self.evaluate("pleading-categories", legal_rule_ids=[])
        self.assertIn("legal_rule_status_not_supported", codes(result))
        self.assertIn("legal_rule_user_facing_not_allowed", codes(result))

    def test_rejected_deprecated_passage_and_reviews_fail_development(self):
        passage = self.repo.get("source_passages", PREFIX + "first-return-date")
        for key, status in (("status", "rejected"), ("status", "deprecated"), ("review", "rejected"), ("review", "deprecated")):
            original = copy.deepcopy(passage)
            if key == "review": passage["review"]["status"] = status
            else: passage["status"] = status
            result = self.evaluate()
            self.assertFalse(result["development_grounding"]["available"])
            self.assertEqual([], result["records"]["passages"])
            passage.clear()
            passage.update(original)

    def test_rejected_or_superseded_source_fails_development(self):
        source = self.repo.get("sources", CODE)
        for mode in ("rejected", "superseded"):
            original = copy.deepcopy(source)
            if mode == "rejected": source["review"]["status"] = "rejected"
            else: source["provenance"]["superseded_by_source_id"] = "va-small-claims-self-help"
            self.assertFalse(self.evaluate()["development_grounding"]["available"])
            source.clear()
            source.update(original)

    def test_missing_and_outside_workflow_references_fail_closed(self):
        cases = (("unknown", "grounding_reference_not_found"), (PREFIX + "division", "grounding_reference_not_in_workflow"))
        for passage_id, code in cases:
            workflow_id = WORKFLOW if passage_id == "unknown" else SYNTHETIC_WORKFLOW
            result = self.service.evaluate(workflow_id, [passage_id])
            self.assertIn(code, codes(result, False))
            self.assertFalse(result["public_grounding"]["allowed"])

    def test_invalid_source_link_and_hash_fail_closed(self):
        passage = self.repo.get("source_passages", PREFIX + "first-return-date")
        original = copy.deepcopy(passage)
        for change in ({"source_id": "unknown"}, {"text": "Changed excerpt"}):
            passage.update(change)
            self.assertIn("grounding_relationship_invalid", codes(self.evaluate(), False))
            passage.clear()
            passage.update(original)

    def test_unrelated_rule_or_step_is_not_imported(self):
        for kwargs in ({"legal_rule_ids": ["example-name-change-filing-instructions-rule"]}, {"process_step_ids": ["example-name-change-review-instructions"]}):
            self.assertIn("grounding_reference_not_in_workflow", codes(self.evaluate(**kwargs), False))

    def test_related_rule_without_selected_passage_support_fails(self):
        result = self.evaluate(legal_rule_ids=["va-small-claims-warrant-and-answer-rule"])
        self.assertIn("grounding_record_passage_support_missing", codes(result, False))

    def test_no_passages_is_explicitly_unavailable(self):
        result = self.service.evaluate(WORKFLOW, [])
        self.assertIn("grounding_passages_missing", codes(result, False))

    def test_actual_instruction_currentness_remains_unresolved(self):
        result = self.evaluate("grounds-of-defense-order")
        self.assertTrue(result["development_grounding"]["available"])
        self.assertIn("passage_freshness_unresolved", codes(result))
        self.assertIn("source_freshness_unresolved", codes(result))
        self.assertIn("grounding_proposition_unresolved", codes(result))
        self.assertIn("September 2008", json.dumps(result["records"]))

    def test_workflow_readiness_is_reused(self):
        self.assertEqual(WorkflowReadinessService(self.repo).evaluate(WORKFLOW), self.evaluate()["workflow_readiness"])

    def test_active_risk_constraints_require_approval(self):
        result = self.evaluate(risk_ids=[RETURN_RISK])
        self.assertIn("risk_status_not_supported", codes(result))


class GroundingPublicPolicyTests(unittest.TestCase):
    def setUp(self):
        self.repo = synthetic_repository()
        self.service = GroundingEligibilityService(self.repo, lambda: TODAY)

    def evaluate(self):
        return self.service.evaluate(SYNTHETIC_WORKFLOW, [FIXTURE_PASSAGE])

    def test_fully_certified_fictional_positive_path(self):
        result = self.evaluate()
        self.assertTrue(result["development_grounding"]["available"])
        self.assertEqual([], result["public_grounding"]["blockers"])
        self.assertTrue(result["public_grounding"]["allowed"])

    def test_all_selected_record_types_require_existing_review_scopes(self):
        cases = (("source_passages", FIXTURE_PASSAGE, "passage"), ("responses", FIXTURE_PATTERN, "response_pattern"))
        positive = self.evaluate()
        cases += tuple((domain, positive["records"][domain][0]["id"], label) for domain, label in (("sources", "source"), ("legal_rules", "legal_rule"), ("process_steps", "process_step")))
        for domain, record_id, label in cases:
            record = self.repo.get(domain, record_id)
            scopes = record["review"]["review_scope"]
            record["review"]["review_scope"] = []
            self.assertIn(label + "_review_scopes_missing", codes(self.evaluate()))
            record["review"]["review_scope"] = scopes

    def test_review_policy_is_shared_with_validator(self):
        self.assertIs(SUPPORTED_REVIEW_SCOPES, repository_validator.SUPPORTED_REVIEW_SCOPES)

    def test_supported_state_schema_gates_are_also_required(self):
        step_id = self.evaluate()["records"]["process_steps"][0]["id"]
        self.repo.get("process_steps", step_id)["evaluation"]["required_evaluation_fixture_ids"] = []
        self.assertIn("process_step_schema_invalid", codes(self.evaluate()))

    def test_package_wide_blocking_gap_cannot_be_ignored(self):
        self.repo.get_workflow(SYNTHETIC_WORKFLOW)["response_constraints"] = {"support_gaps": [{
            "code": "synthetic_unresolved_gap", "description": "Synthetic unresolved package condition.",
            "propositions": [], "withhold_claims": True, "blocks_public_grounding": True,
            "prohibited_conclusions": [],
        }]}
        self.assertIn("grounding_proposition_unresolved", codes(self.evaluate()))

    def test_certification_absence_expiry_version_and_open_issues_fail(self):
        passage = self.repo.get("source_passages", FIXTURE_PASSAGE)
        original = copy.deepcopy(passage["public_currentness"])
        cases = ({"status": "unresolved"}, {**original, "valid_through": "2026-10-29"}, {**original, "record_version": "9.9.9"}, {**original, "source_content_version": "other"}, {**original, "unresolved_issues": ["uncertain"]}, {**original, "verified_on": "2026-11-01"})
        for certification in cases:
            passage["public_currentness"] = certification
            self.assertFalse(self.evaluate()["public_grounding"]["allowed"])
        passage.pop("public_currentness")
        self.assertIn("passage_freshness_unresolved", codes(self.evaluate()))

    def test_source_certification_and_effective_period_are_independent(self):
        source = self.evaluate()["records"]["sources"][0]
        actual = self.repo.get("sources", source["id"])
        actual["source_type"] = "statute"
        actual["dates"]["effective_from"] = None
        self.assertIn("source_effective_period_unresolved", codes(self.evaluate()))
        actual["dates"]["effective_from"] = "2026-01-01"
        actual["dates"]["effective_through"] = "2026-10-29"
        self.assertIn("source_outside_effective_period", codes(self.evaluate()))

    def test_review_version_and_future_review_date_fail(self):
        passage = self.repo.get("source_passages", FIXTURE_PASSAGE)
        passage["review"]["reviewed_record_version"] = "9.9.9"
        self.assertIn("passage_review_provenance_invalid", codes(self.evaluate()))
        passage["review"]["reviewed_record_version"] = passage["record_version"]
        passage["review"]["reviewed_on"] = "2026-11-01"
        self.assertIn("passage_review_provenance_invalid", codes(self.evaluate()))

    def test_unknown_reuse_and_pattern_source_restrictions_block(self):
        source_id = self.evaluate()["records"]["sources"][0]["id"]
        source = self.repo.get("sources", source_id)
        source["rights"]["reuse_status"] = "unknown"
        self.assertIn("source_reuse_unresolved", codes(self.evaluate()))
        source["rights"]["reuse_status"] = "public_domain"
        self.repo.get("responses", FIXTURE_PATTERN)["source_use"]["allowed_source_authority_levels"] = ["unknown"]
        self.assertIn("response_pattern_source_constraints_unsatisfied", codes(self.evaluate()))

    def test_workflow_approval_cannot_be_bypassed_by_approved_evidence(self):
        self.repo.get_workflow(SYNTHETIC_WORKFLOW)["status"] = "proposed"
        result = self.evaluate()
        self.assertEqual({"workflow_not_ready"}, codes(result))

    def test_public_currentness_schema_and_startup_contract(self):
        schema = self.repo.schemas["source-passage.schema.json"]
        validator = Draft202012Validator(schema, registry=self.repo.registry)
        passage = self.repo.get("source_passages", FIXTURE_PASSAGE)
        self.assertEqual([], list(validator.iter_errors(passage)))
        passage["public_currentness"].pop("record_version")
        self.assertTrue(list(validator.iter_errors(passage)))


class ResponseAssemblyTests(unittest.TestCase):
    def setUp(self):
        self.repo = RecordRepository()
        self.service = ResponseAssemblyService(self.repo, lambda: TODAY)

    def assemble(self, query="return date", answers=None, risks=None, **filters):
        return self.service.assemble(WORKFLOW, ResponseAssemblyRequest(
            answers=dict(ANSWERS) if answers is None else answers,
            risk_ids=risks or [], retrieval=RetrievalRequest(query=query, **filters),
        ))

    def test_complete_intake_creates_development_plan_but_no_public_execution(self):
        result = self.assemble()
        self.assertTrue(result["development_package"]["available"])
        self.assertTrue(result["response_plan"]["available"])
        self.assertTrue(result["intake"]["complete"])
        self.assertFalse(result["public_execution"]["allowed"])
        self.assertFalse(result["response_plan"]["legal_answer_generated"])

    def test_return_date_claim_is_only_a_supported_topic_reference(self):
        claim = next(c for c in self.assemble()["response_plan"]["claims"] if c["topic"] == "va-small-claims-first-return-date")
        self.assertEqual([PREFIX + "first-return-date"], claim["supported_by_passage_ids"])
        self.assertEqual("legal_information_topic", claim["claim_type"])
        self.assertNotIn("text", claim)
        self.assertEqual([], claim["user_fact_ids"])

    def test_removal_appears_only_when_its_evidence_is_selected(self):
        self.assertNotIn("va-small-claims-removal-right", [c["topic"] for c in self.assemble()["response_plan"]["claims"]])
        result = self.assemble("removal")
        self.assertEqual(["va-small-claims-removal-right"], [c["topic"] for c in result["response_plan"]["claims"]])

    def test_grounds_of_defense_keeps_conditional_and_freshness_limitations(self):
        result = self.assemble("grounds defense", proposition_ids=["va-small-claims-grounds-of-defense-order"])
        claim = result["response_plan"]["claims"][0]
        self.assertEqual("va-small-claims-grounds-of-defense-order", claim["topic"])
        self.assertIn("judge", json.dumps(claim["limitations"]))
        self.assertIn("September 2008", json.dumps(claim["limitations"]))

    def test_appearance_is_gap_not_resolved_claim(self):
        result = self.assemble("appearance")
        self.assertNotIn("va-small-claims-appearance-wording", [c["topic"] for c in result["response_plan"]["claims"]])
        gap = next(g for g in result["response_plan"]["support_gaps"] if g["code"] == "appearance_wording_unresolved")
        self.assertEqual(2, len(gap["evidence_passage_ids"]))

    def test_answer_requirement_and_deadline_are_only_support_gaps(self):
        result = self.assemble("written answer deadline")
        topics = {c["topic"] for c in result["response_plan"]["claims"]}
        self.assertNotIn("va-small-claims-universal-written-answer-deadline", topics)
        self.assertNotIn("va-small-claims-universal-written-answer-requirement", topics)
        gaps = {g["code"] for g in result["response_plan"]["support_gaps"]}
        self.assertIn("universal_written_answer_deadline_unestablished", gaps)
        self.assertIn("universal_written_answer_requirement_unestablished", gaps)
        self.assertTrue(result["response_plan"]["prohibited_conclusions"])

    def test_every_claim_has_canonical_evidence_citations_and_workflow_identity(self):
        result = self.assemble(None, limit=20)
        citation_map = {c["citation_id"]: c for c in result["response_plan"]["citations"]}
        for claim in result["response_plan"]["claims"]:
            self.assertEqual(WORKFLOW, claim["workflow_id"])
            self.assertTrue(claim["supported_by_passage_ids"])
            self.assertTrue(claim["source_ids"])
            for citation_id in claim["citation_ids"]:
                citation = citation_map[citation_id]
                self.assertIn(citation["passage_id"], claim["supported_by_passage_ids"])
                source = self.repo.get("sources", citation["source_id"])
                self.assertEqual(source["citation"]["preferred_citation"], citation["preferred_citation"])
                self.assertEqual(source["url"], citation["official_url"])
                self.assertTrue(citation["locator"])
                self.assertEqual("proposed", citation["passage_review"]["status"])

    def test_no_result_is_explicit_gap_with_no_claims(self):
        result = self.assemble("xyzzzz")
        self.assertEqual([], result["response_plan"]["claims"])
        self.assertFalse(result["response_plan"]["available"])
        self.assertFalse(result["grounding"]["eligibility"]["development_grounding"]["available"])
        self.assertIn("grounding_unavailable", {g["code"] for g in result["response_plan"]["support_gaps"]})

    def test_only_selected_workflow_material_enters_grounding(self):
        for domain, records in self.assemble()["grounding"].items():
            if isinstance(records, list):
                self.assertTrue(all(r["id"].startswith("va-") for r in records))

    def test_unrelated_filters_remain_rejected(self):
        with self.assertRaises(RetrievalFilterError):
            self.assemble(source_ids=["example-state-court-name-change-guide"])

    def test_multiple_risks_and_privacy_controls_are_preserved(self):
        result = self.assemble(risks=[RETURN_RISK, CHOICE_RISK])
        self.assertEqual(["avoid_final_decision", "continue_with_urgent_support"], result["routing"])
        self.assertEqual(2, len(result["risks"]["recognized"]))
        self.assertIn("risk_notice", result["response_plan"]["required_sections"])
        self.assertIn("redaction_prompt", result["response_plan"]["required_sections"])

    def test_missing_facts_remain_missing_and_admitted_values_keep_provenance(self):
        result = self.assemble(answers={"user_goal": " Uncertain? "})
        self.assertEqual({"user_goal": {"value": " Uncertain? ", "provenance": "user_provided"}}, result["user_context"]["facts"])
        self.assertIn("state", result["user_context"]["missing_information"])
        self.assertFalse(result["public_execution"]["input_eligible"])

    def test_excluded_values_are_not_echoed_anywhere(self):
        result = self.assemble(answers={**ANSWERS, "social_security_number": "SENSITIVE_SENTINEL"})
        self.assertNotIn("SENSITIVE_SENTINEL", json.dumps(result))
        self.assertFalse(result["public_execution"]["allowed"])

    def test_response_pattern_and_rule_constraints_are_preserved(self):
        result = self.assemble("pleading categories", legal_rule_ids=["va-small-claims-warrant-and-answer-rule"])
        plan = result["response_plan"]
        self.assertTrue(plan["constraints"]["workflow_outputs"]["prohibited_outputs"])
        self.assertTrue(plan["prohibited_actions"])
        self.assertTrue(plan["required_disclosures"])
        support = plan["constraints"]["legal_rule_support"]["va-small-claims-warrant-and-answer-rule"]
        self.assertFalse(support["source_support"]["source_quotes_allowed"])
        self.assertFalse(support["rule_statement"]["user_facing_allowed"])

    def test_deterministic_detached_and_nonmutating(self):
        before = copy.deepcopy(self.repo.records)
        first = self.assemble(risks=[RETURN_RISK, CHOICE_RISK])
        self.assertEqual(first, self.assemble(risks=[CHOICE_RISK, RETURN_RISK]))
        first["grounding"]["passages"][0]["text"] = "changed"
        first["response_plan"]["citations"][0]["source_review"]["status"] = "changed"
        self.assertEqual(before, self.repo.records)

    def test_no_network_file_io_processes_or_value_logging(self):
        with (
            patch.object(socket, "socket", side_effect=AssertionError("Network")),
            patch.object(socket, "create_connection", side_effect=AssertionError("Network")),
            patch("builtins.open", side_effect=AssertionError("File I/O")),
            patch.object(Path, "open", side_effect=AssertionError("File I/O")),
            patch.object(subprocess, "Popen", side_effect=AssertionError("Process")),
            patch.object(logging.Logger, "_log") as log,
        ):
            result = self.assemble()
        log.assert_not_called()
        self.assertFalse(result["response_plan"]["legal_answer_generated"])

    def test_requests_do_not_reuse_facts_or_risks(self):
        self.assemble(risks=[RETURN_RISK])
        result = self.assemble(answers={})
        self.assertEqual({}, result["user_context"]["facts"])
        self.assertEqual([], result["risks"]["recognized"])

    def test_service_workflow_mismatch_fails_closed(self):
        retrieval = self.service.retrieval_service.retrieve(WORKFLOW, RetrievalRequest())
        retrieval["workflow_id"] = "other"
        with patch.object(self.service.retrieval_service, "retrieve", return_value=retrieval):
            with self.assertRaises(AssemblyIntegrityError):
                self.assemble()

    def test_public_conjunction_has_a_fictional_positive_path_and_input_veto(self):
        repo = synthetic_repository()
        service = ResponseAssemblyService(repo, lambda: TODAY)
        answers = {key: "explicit synthetic fact" for key in repo.get_workflow(SYNTHETIC_WORKFLOW)["intake"]["required_inputs"]}
        complete = service.assemble(SYNTHETIC_WORKFLOW, ResponseAssemblyRequest(answers=answers))
        self.assertTrue(complete["public_execution"]["allowed"])
        incomplete = service.assemble(SYNTHETIC_WORKFLOW, ResponseAssemblyRequest(answers={}))
        self.assertTrue(incomplete["public_execution"]["grounding_allowed"])
        self.assertFalse(incomplete["public_execution"]["allowed"])

    def test_all_actual_virginia_records_stay_proposed_and_uncertified(self):
        self.assemble(None, limit=20)
        records = [r for group in self.repo.records.values() for r in group.values() if r["id"].startswith(("va-small-claims", "va-dc402"))]
        self.assertEqual(35, len(records))
        for record in records:
            self.assertEqual("proposed", record["status"])
            self.assertEqual("proposed", record["review"]["status"])
            self.assertNotIn("public_currentness", record)


class ResponseAssemblyApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.url = f"/workflows/{WORKFLOW}/response/assemble"

    def test_complete_request_and_no_result_contract(self):
        for query in ("return date", "xyzzzz"):
            response = self.client.post(self.url, json={"answers": ANSWERS, "retrieval": {"query": query}})
            self.assertEqual(200, response.status_code)
            body = response.json()
            self.assertIn("response_plan", body)
            self.assertFalse(body["public_execution"]["allowed"])
            self.assertFalse(body["response_plan"]["legal_answer_generated"])

    def test_unknown_workflow_is_404(self):
        self.assertEqual(404, self.client.post("/workflows/unknown/response/assemble", json={"answers": {}}).status_code)

    def test_malformed_and_unrelated_filters_are_422(self):
        for payload in ({}, {"answers": []}, {"answers": {}, "retrieval": {"limit": 0}}, {"answers": {}, "retrieval": {"limit": True}}, {"answers": {}, "risk_ids": "risk"}, {"answers": {}, "extra": 1}, {"answers": {}, "retrieval": {"source_ids": ["unrelated"]}}):
            self.assertEqual(422, self.client.post(self.url, json=payload).status_code)

    def test_intake_conflict_and_corpus_integrity_preserve_409(self):
        for conflict in ("intake", "corpus"):
            repo = RecordRepository()
            if conflict == "intake": repo.records["intakes"].clear()
            else: repo.get("source_passages", PREFIX + "first-return-date")["text"] = "changed"
            with patch("app.main.response_assembly_service", ResponseAssemblyService(repo, lambda: TODAY)):
                response = self.client.post(self.url, json={"answers": {}})
            self.assertEqual(409, response.status_code)
            self.assertEqual("intake_not_found" if conflict == "intake" else "corpus_integrity_error", response.json()["detail"]["code"])

    def test_openapi_reuses_retrieval_request(self):
        schema = self.client.get("/openapi.json").json()
        request = schema["components"]["schemas"]["ResponseAssemblyRequest"]
        self.assertEqual("#/components/schemas/RetrievalRequest", request["properties"]["retrieval"]["$ref"])


if __name__ == "__main__":
    unittest.main()
