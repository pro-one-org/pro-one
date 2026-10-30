import copy
import json
import logging
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.execution import ExecutionContextService
from app.intake import IntakeResolutionError
from app.main import app
from app.readiness import WorkflowReadinessService
from app.repository import RecordRepository
from test_readiness import WORKFLOW_ID as READY_WORKFLOW_ID, make_ready_repository


WORKFLOW_ID = "va-small-claims-warrant-in-debt-information"
RETURN_RISK = "va-small-claims-return-date-risk"
CHOICE_RISK = "va-small-claims-response-choice-risk"
ANSWERS = {
    "state": "Virginia",
    "court_name_or_locality": "Augusta County",
    "document_title_or_form_number": "DC-402",
    "return_date_and_time_if_shown": "2026-11-10 09:00",
    "user_goal": "Understand what this document is",
}


class IntakeExecutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = RecordRepository()
        self.service = ExecutionContextService(self.repository)

    def build(self, answers=None, risk_ids=None):
        return self.service.build(
            WORKFLOW_ID, dict(ANSWERS) if answers is None else answers,
            [] if risk_ids is None else risk_ids,
        )

    def test_unknown_workflow_has_no_result(self) -> None:
        self.assertIsNone(self.service.build("unknown", {}, []))

    def test_empty_answers_report_every_required_input(self) -> None:
        result = self.build({})
        self.assertFalse(result["intake"]["complete"])
        self.assertEqual(sorted(ANSWERS), result["intake"]["missing_required_inputs"])
        self.assertEqual([], result["intake"]["provided_required_inputs"])
        self.assertFalse(result["public_execution"]["allowed"])

    def test_partial_answers_report_only_actual_missing_fields(self) -> None:
        result = self.build({"state": "Virginia", "user_goal": "Read form"})
        self.assertEqual(
            sorted(set(ANSWERS) - {"state", "user_goal"}),
            result["intake"]["missing_required_inputs"],
        )

    def test_complete_intake_produces_only_development_eligibility(self) -> None:
        result = self.build()
        self.assertTrue(result["intake"]["complete"])
        self.assertTrue(result["execution"]["context_available"])
        self.assertTrue(result["execution"]["input_eligible"])
        self.assertEqual("development_context_only", result["execution"]["next_runtime_state"])
        self.assertFalse(result["public_execution"]["allowed"])
        self.assertFalse(result["execution"]["context"]["public_execution_allowed"])

    def test_optional_input_detection(self) -> None:
        result = self.build({**ANSWERS, "redacted_document_summary": "Short summary"})
        self.assertEqual(["redacted_document_summary"], result["intake"]["optional_inputs_provided"])
        self.assertIn("redacted_document_summary", result["execution"]["context"]["user_facts"])

    def test_excluded_and_intake_prohibited_values_are_withheld(self) -> None:
        for key in ("social_security_number", "bank_account_numbers", "privileged_communications"):
            with self.subTest(key=key):
                result = self.build({**ANSWERS, key: "SENSITIVE_SENTINEL"})
                self.assertEqual([key], result["intake"]["excluded_inputs_provided"])
                self.assertNotIn("SENSITIVE_SENTINEL", json.dumps(result))
                self.assertFalse(result["execution"]["input_eligible"])
                self.assertIn("narrow_then_continue", result["routing"])

    def test_restricted_category_matches_technical_field_spelling(self) -> None:
        for key in ("case_number", "case number", "PARTY_ADDRESSES"):
            with self.subTest(key=key):
                result = self.build({**ANSWERS, key: "SENSITIVE_SENTINEL"})
                self.assertEqual([key], result["intake"]["restricted_inputs_provided"])
                self.assertNotIn("SENSITIVE_SENTINEL", json.dumps(result))
                self.assertFalse(result["execution"]["input_eligible"])

    def test_prohibition_wins_over_required_optional_and_restricted(self) -> None:
        intake = self.repository.records["intakes"]["va-small-claims-defendant-intake"]
        intake["data_limits"]["prohibited_data_categories"].append("state")
        intake["data_limits"]["restricted_data_categories"].append("state")
        result = self.build()
        self.assertTrue(result["intake"]["complete"])
        self.assertEqual(["state"], result["intake"]["excluded_inputs_provided"])
        self.assertNotIn("state", result["execution"]["context"]["user_facts"])

    def test_unknown_input_values_are_withheld_and_block_input_eligibility(self) -> None:
        result = self.build({**ANSWERS, "unconfigured_field": "SENSITIVE_SENTINEL"})
        self.assertEqual(["unconfigured_field"], result["intake"]["unrecognized_inputs"])
        self.assertNotIn("SENSITIVE_SENTINEL", json.dumps(result))
        self.assertIn("unrecognized_inputs_supplied", result["execution"]["blockers"])

    def test_null_and_blank_values_are_missing_but_zero_and_false_are_explicit(self) -> None:
        result = self.build({
            **ANSWERS, "state": None, "user_goal": " \t ",
            "court_name_or_locality": False, "document_title_or_form_number": 0,
        })
        self.assertEqual(["state", "user_goal"], result["intake"]["missing_required_inputs"])
        facts = result["execution"]["context"]["user_facts"]
        self.assertIs(False, facts["court_name_or_locality"]["value"])
        self.assertEqual(0, facts["document_title_or_form_number"]["value"])
        self.assertNotIn("state", facts)

    def test_excluded_empty_values_are_still_reported(self) -> None:
        result = self.build({**ANSWERS, "social_security_number": None})
        self.assertEqual(["social_security_number"], result["intake"]["excluded_inputs_provided"])

    def test_values_are_preserved_exactly_with_user_provenance(self) -> None:
        answers = {**ANSWERS, "state": " Virginia? ", "user_goal": "Unsure\nwhat this is"}
        result = self.build(answers)
        self.assertEqual({
            key: {"value": value, "provenance": "user_provided"}
            for key, value in answers.items()
        }, result["execution"]["context"]["user_facts"])

    def test_missing_values_are_not_invented(self) -> None:
        result = self.build({"user_goal": "Read document"})
        context = result["execution"]["context"]
        self.assertEqual(["user_goal"], list(context["user_facts"]))
        self.assertEqual(sorted(set(ANSWERS) - {"user_goal"}), context["missing_information"])
        self.assertEqual("user_provided_values_unverified", context["limitations"]["fact_interpretation"])

    def test_return_date_risk_uses_configured_urgent_route(self) -> None:
        result = self.build(risk_ids=[RETURN_RISK])
        self.assertEqual([RETURN_RISK], [r["id"] for r in result["risks"]["recognized"]])
        self.assertEqual(["continue_with_urgent_support"], result["risks"]["routing"])
        self.assertEqual(
            self.repository.get("risks", RETURN_RISK), result["risks"]["recognized"][0],
        )

    def test_response_choice_risk_preserves_distinct_route(self) -> None:
        result = self.build(risk_ids=[CHOICE_RISK])
        self.assertEqual(["avoid_final_decision"], result["risks"]["routing"])

    def test_unknown_risks_are_reported_and_block_input_eligibility(self) -> None:
        result = self.build(risk_ids=["unknown-risk"])
        self.assertEqual(["unknown-risk"], result["risks"]["unknown"])
        self.assertEqual([], result["risks"]["recognized"])
        self.assertIn("unknown_risk_ids", result["execution"]["blockers"])

    def test_unrelated_risks_are_reported_and_never_activated(self) -> None:
        unrelated = "example-imminent-deadline-risk"
        result = self.build(risk_ids=[unrelated])
        self.assertEqual([unrelated], result["risks"]["not_applicable"])
        self.assertEqual([], result["risks"]["recognized"])
        self.assertEqual([], result["execution"]["context"]["active_risk_ids"])
        self.assertIn("not_applicable_risk_ids", result["execution"]["blockers"])

    def test_multiple_risks_are_sorted_deduplicated_and_all_preserved(self) -> None:
        result = self.build(risk_ids=[RETURN_RISK, CHOICE_RISK, RETURN_RISK])
        self.assertEqual(sorted([RETURN_RISK, CHOICE_RISK]), result["execution"]["context"]["active_risk_ids"])
        self.assertEqual(["avoid_final_decision", "continue_with_urgent_support"], result["routing"])
        self.assertEqual(result, self.build(risk_ids=[CHOICE_RISK, RETURN_RISK]))

    def test_risk_privacy_categories_are_applied_only_when_explicitly_active(self) -> None:
        result = self.build({**ANSWERS, "addresses": "SENSITIVE_SENTINEL"}, [RETURN_RISK])
        self.assertEqual(["addresses"], result["intake"]["restricted_inputs_provided"])
        self.assertNotIn("SENSITIVE_SENTINEL", json.dumps(result))

    def test_privacy_prompt_metadata_is_preserved(self) -> None:
        privacy = self.build()["privacy"]
        for key in ("redaction_prompt_required", "data_minimization_required", "privacy_notice_required", "retention_warning_required"):
            self.assertTrue(privacy[key])
        self.assertEqual("ask_for_redacted_information", privacy["sensitive_data_handling"])

    def test_context_contains_exactly_resolver_selected_metadata(self) -> None:
        result = self.build()
        context = result["execution"]["context"]
        resolved = self.repository.resolve_workflow(WORKFLOW_ID)
        self.assertEqual(resolved["workflow"], context["workflow"])
        self.assertEqual(resolved["related"]["intakes"][0], context["intake_definition"])
        for domain, records in context["records"].items():
            self.assertEqual(sorted(resolved["related"][domain], key=lambda r: r["id"]), records)
            self.assertTrue(all(record["id"].startswith("va-") for record in records))
        self.assertNotIn("evaluation_fixtures", context["records"])

    def test_resolution_and_readiness_are_reused(self) -> None:
        with patch.object(self.repository, "resolve_workflow", wraps=self.repository.resolve_workflow) as resolve:
            result = self.build()
        # Intake resolves its package; existing readiness resolves its own package.
        self.assertEqual(2, resolve.call_count)
        self.assertEqual(
            WorkflowReadinessService(self.repository).evaluate(WORKFLOW_ID),
            result["public_execution"]["readiness"],
        )

    def test_incomplete_context_behavior_and_routing_are_explicit(self) -> None:
        result = self.build({}, [RETURN_RISK])
        self.assertTrue(result["execution"]["context_available"])
        self.assertFalse(result["execution"]["input_eligible"])
        self.assertEqual("input_action_required", result["execution"]["next_runtime_state"])
        self.assertEqual(["continue_with_urgent_support", "pause_for_missing_information"], result["routing"])

    def test_no_applicable_intake_fails_clearly(self) -> None:
        self.repository.records["intakes"].clear()
        with self.assertRaises(IntakeResolutionError) as caught:
            self.build()
        self.assertEqual("intake_not_found", caught.exception.code)

    def test_multiple_intakes_fail_without_arbitrary_selection(self) -> None:
        duplicate = copy.deepcopy(self.repository.get("intakes", "va-small-claims-defendant-intake"))
        duplicate["id"] = "duplicate-intake"
        self.repository.records["intakes"][duplicate["id"]] = duplicate
        with self.assertRaises(IntakeResolutionError) as caught:
            self.build()
        self.assertEqual("intake_ambiguous", caught.exception.code)
        self.assertEqual(["duplicate-intake", "va-small-claims-defendant-intake"], caught.exception.candidate_ids)

    def test_missing_required_dependencies_prevent_context_assembly(self) -> None:
        cases = (
            ("sources", "va-small-claims-procedure-code"),
            ("process_steps", "va-small-claims-identify-warrant"),
            ("evaluation_fixtures", "va-small-claims-ordinary-user-fixture"),
            ("legal_rules", "va-small-claims-warrant-and-answer-rule"),
        )
        for domain, record_id in cases:
            with self.subTest(domain=domain):
                record = self.repository.records[domain].pop(record_id)
                result = self.build()
                self.assertFalse(result["execution"]["context_available"])
                self.assertIsNone(result["execution"]["context"])
                self.assertIn(record_id, [issue["target_id"] for issue in result["execution"]["reference_issues"]])
                self.assertFalse(result["public_execution"]["allowed"])
                self.repository.records[domain][record_id] = record

    def test_existing_required_record_without_workflow_link_is_not_imported(self) -> None:
        source = self.repository.get("sources", "va-small-claims-procedure-code")
        source["workflow_fit"]["workflow_ids"] = []
        result = self.build()
        self.assertFalse(result["execution"]["context_available"])
        self.assertIn(source["id"], [issue["target_id"] for issue in result["execution"]["reference_issues"]])

    def test_no_repository_or_request_mutation_and_results_are_detached(self) -> None:
        before = copy.deepcopy(self.repository.records)
        answers = dict(ANSWERS)
        risks = [RETURN_RISK]
        result = self.build(answers, risks)
        result["execution"]["context"]["workflow"]["title"] = "changed"
        result["risks"]["recognized"][0]["title"] = "changed"
        self.assertEqual(before, self.repository.records)
        self.assertEqual(ANSWERS, answers)
        self.assertEqual([RETURN_RISK], risks)

    def test_repeatable_with_reordered_input_and_repository_metadata(self) -> None:
        first = self.build()
        for domain, records in self.repository.records.items():
            self.repository.records[domain] = dict(reversed(list(records.items())))
        self.assertEqual(first, self.build(dict(reversed(list(ANSWERS.items())))))

    def test_runtime_performs_no_file_io_or_value_logging(self) -> None:
        with (
            patch("builtins.open", side_effect=AssertionError("Unexpected file I/O")),
            patch.object(Path, "open", side_effect=AssertionError("Unexpected path I/O")),
            patch.object(logging.Logger, "_log") as log,
        ):
            result = self.build({**ANSWERS, "social_security_number": "SENSITIVE_SENTINEL"})
        log.assert_not_called()
        self.assertNotIn("SENSITIVE_SENTINEL", json.dumps(result))
        self.assertFalse(hasattr(self.service, "answers"))

    def test_requests_do_not_reuse_prior_facts_or_risks(self) -> None:
        self.build(risk_ids=[RETURN_RISK])
        result = self.build({})
        self.assertEqual({}, result["execution"]["context"]["user_facts"])
        self.assertEqual([], result["risks"]["recognized"])
        self.assertEqual(["pause_for_missing_information"], result["routing"])

    def test_context_is_metadata_without_a_generated_answer_or_document(self) -> None:
        result = self.build()
        context = result["execution"]["context"]
        self.assertFalse(context["limitations"]["legal_answer_generated"])
        self.assertEqual("repository_metadata_only", context["limitations"]["source_content"])
        self.assertEqual({"context_available", "next_runtime_state", "input_eligible", "blockers", "reference_issues", "context"}, set(result["execution"]))
        self.assertEqual(self.repository.get_workflow(WORKFLOW_ID)["outputs"], context["output_constraints"]["workflow"])

    def test_virginia_records_and_reviews_remain_proposed(self) -> None:
        self.build()
        records = [record for group in self.repository.records.values() for record in group.values() if record["id"].startswith("va-")]
        self.assertEqual(50, len(records))
        for record in records:
            self.assertEqual("proposed", record["status"])
            self.assertEqual("proposed", record["review"]["status"])

    def test_readiness_is_necessary_even_when_input_is_eligible(self) -> None:
        result = self.build()
        self.assertEqual([], result["execution"]["blockers"])
        self.assertFalse(result["public_execution"]["allowed"])
        self.assertIn("workflow_status_not_supported", [b["code"] for b in result["public_execution"]["readiness"]["blockers"]])

    def test_input_blockers_remain_effective_even_when_readiness_is_true(self) -> None:
        # Existing synthetic readiness helper changes only an in-memory fictional workflow.
        repository = make_ready_repository()
        service = ExecutionContextService(repository)
        workflow = repository.get_workflow(READY_WORKFLOW_ID)
        answers = {key: "explicit value" for key in workflow["intake"]["required_inputs"]}
        complete = service.build(READY_WORKFLOW_ID, answers, [])
        self.assertTrue(complete["public_execution"]["allowed"])
        incomplete = service.build(READY_WORKFLOW_ID, {}, [])
        self.assertTrue(incomplete["public_execution"]["readiness"]["ready_for_public_use"])
        self.assertFalse(incomplete["public_execution"]["allowed"])
        invalid = service.build(READY_WORKFLOW_ID, answers, ["unknown"])
        self.assertFalse(invalid["public_execution"]["allowed"])


class IntakeExecutionApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)
        cls.url = f"/workflows/{WORKFLOW_ID}/intake/evaluate"

    def test_unknown_workflow_returns_404(self) -> None:
        response = self.client.post("/workflows/unknown/intake/evaluate", json={"answers": {}})
        self.assertEqual(404, response.status_code)

    def test_empty_partial_and_complete_requests(self) -> None:
        for answers, complete in (({}, False), ({"state": "Virginia"}, False), (ANSWERS, True)):
            with self.subTest(answers=answers):
                response = self.client.post(self.url, json={"answers": answers})
                self.assertEqual(200, response.status_code)
                body = response.json()
                self.assertEqual(complete, body["intake"]["complete"])
                self.assertTrue(body["execution"]["context_available"])
                self.assertFalse(body["public_execution"]["allowed"])

    def test_explicit_risk_and_safety_contract(self) -> None:
        response = self.client.post(self.url, json={
            "answers": {**ANSWERS, "case_number": "SENSITIVE_SENTINEL"},
            "risk_ids": [CHOICE_RISK, RETURN_RISK, "unknown"],
        })
        self.assertEqual(200, response.status_code)
        body = response.json()
        self.assertEqual(["unknown"], body["risks"]["unknown"])
        self.assertEqual(["avoid_final_decision", "continue_with_urgent_support"], body["risks"]["routing"])
        self.assertNotIn("SENSITIVE_SENTINEL", response.text)

    def test_malformed_payloads_use_fastapi_validation(self) -> None:
        for payload in (
            {}, {"answers": []}, {"answers": None}, {"answers": {"state": {"value": "VA"}}},
            {"answers": {"state": []}}, {"answers": {}, "risk_ids": "risk"},
            {"answers": {}, "risk_ids": [12]}, {"answers": {}, "extra": True},
        ):
            with self.subTest(payload=payload):
                self.assertEqual(422, self.client.post(self.url, json=payload).status_code)

    def test_missing_or_ambiguous_intakes_return_409(self) -> None:
        for ambiguous in (False, True):
            repository = RecordRepository()
            if ambiguous:
                record = copy.deepcopy(repository.get("intakes", "va-small-claims-defendant-intake"))
                record["id"] = "second-intake"
                repository.records["intakes"][record["id"]] = record
            else:
                repository.records["intakes"].clear()
            with patch("app.main.execution_service", ExecutionContextService(repository)):
                response = self.client.post(self.url, json={"answers": {}})
            self.assertEqual(409, response.status_code)
            self.assertEqual("intake_ambiguous" if ambiguous else "intake_not_found", response.json()["detail"]["code"])

    def test_readiness_matches_existing_endpoint(self) -> None:
        body = self.client.post(self.url, json={"answers": ANSWERS}).json()
        readiness = self.client.get(f"/workflows/{WORKFLOW_ID}/readiness").json()
        self.assertEqual(readiness, body["public_execution"]["readiness"])

    def test_scalar_values_retain_types_and_provenance_through_the_api(self) -> None:
        answers = {
            **ANSWERS, "state": " Virginia? ", "user_goal": False,
            "court_name_or_locality": 0, "claim_amount_as_shown": 12.5,
        }
        response = self.client.post(self.url, json={"answers": answers})
        self.assertEqual(200, response.status_code)
        facts = response.json()["execution"]["context"]["user_facts"]
        self.assertEqual({
            key: {"value": value, "provenance": "user_provided"}
            for key, value in answers.items()
        }, facts)
        self.assertIs(False, facts["user_goal"]["value"])


if __name__ == "__main__":
    unittest.main()
