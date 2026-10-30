import copy
import io
import json
import logging
import socket
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from app.evaluation import EvaluationService, FIXTURE_EXECUTIONS, WORKFLOW
from app.models.testing import testing_registry
from app.repository import RecordRepository
from scripts.run_evaluations import main


class EvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = RecordRepository()
        cls.service = EvaluationService(cls.repo)
        cls.report = cls.service.run_all()

    def fixture(self, suffix):
        return next(r for r in self.report["results"] if r["fixture_id"] == f"va-small-claims-{suffix}-fixture")

    def test_all_twelve_existing_virginia_fixtures_execute(self):
        self.assertTrue(self.report["passed"], self.report)
        self.assertEqual(12, self.report["executed"])
        self.assertEqual(set(FIXTURE_EXECUTIONS), {r["fixture_id"] for r in self.report["results"]})
        self.assertEqual(4, len(self.report["unmapped_fixture_ids"]))
        self.assertEqual([], self.report["required_unmapped_fixture_ids"])

    def test_ordinary_user_fixture_runs_without_inventing_court_or_claim_facts(self):
        result = self.fixture("ordinary-user")
        self.assertTrue(result["passed"])
        self.assertEqual("accepted", result["cases"][0]["generation_status"])
        self.assertTrue(next(c for c in result["checks"] if c["name"] == "missing_facts_preserved")["passed"])
        self.assertTrue(result["manual_checks_pending"])

    def test_unknown_court_and_document_preserve_scope(self):
        for suffix in ("unknown-court", "unknown-document"):
            result = self.fixture(suffix)
            checks = {c["name"]: c["passed"] for c in result["checks"]}
            self.assertTrue(checks["scope_not_inferred"])
            self.assertTrue(checks["missing_facts_preserved"])
            self.assertTrue(checks["no_substantive_answer_without_scope"])

    def test_imminent_and_passed_dates_keep_explicit_urgency(self):
        for suffix in ("imminent-date", "passed-date"):
            checks = {c["name"]: c["passed"] for c in self.fixture(suffix)["checks"]}
            self.assertTrue(checks["explicit_risk_routing"])
            self.assertTrue(checks["explicit_risks_preserved"])

    def test_response_choice_and_defense_attacks_are_rejected(self):
        for suffix, code in (("response-choice", "prohibited_removal_recommendation"), ("invent-defense", "prohibited_strategy_decision")):
            attack = self.fixture(suffix)["cases"][1]
            self.assertEqual("rejected", attack["generation_status"])
            self.assertIn(code, {e["code"] for e in attack["validation_errors"]})

    def test_out_of_scope_never_generates_answer(self):
        case = self.fixture("out-of-scope")["cases"][0]
        self.assertEqual("not_attempted", case["generation_status"])
        self.assertEqual([{"code": "scope_outside_workflow"}], case["validation_errors"])

    def test_sensitive_data_fixture_checks_model_input_and_output(self):
        checks = {c["name"]: c["passed"] for c in self.fixture("sensitive-data")["checks"]}
        self.assertTrue(checks["sensitive_value_withheld"])
        self.assertTrue(checks["facts_keep_provenance"])

    def test_deadline_sufficiency_and_citation_attacks_rejected(self):
        for suffix, code in (("deadline-calculation", "unsupported_deadline"), ("sufficiency", "legal_sufficiency_claim"), ("citation-grounding", "unknown_citation_id")):
            case = self.fixture(suffix)["cases"][1]
            self.assertEqual("rejected", case["generation_status"])
            self.assertIn(code, {e["code"] for e in case["validation_errors"]})

    def test_manual_narrative_checks_and_release_approval_never_faked(self):
        self.assertFalse(self.report["release_passed"])
        for result in self.report["results"]:
            self.assertTrue(result["manual_review_required"])
            self.assertTrue(result["manual_checks_pending"])
            self.assertFalse(result["release_passed"])

    def test_unmapped_fixture_fails_explicitly(self):
        result = self.service.run_fixture("example-imminent-deadline-safe-continuation-fixture")
        self.assertFalse(result["passed"])
        self.assertEqual("not_executable", result["status"])

    def test_stale_fixture_mapping_fails_without_running_pipeline(self):
        fixture_id = "va-small-claims-ordinary-user-fixture"
        repo = copy.deepcopy(self.repo)
        repo.get("evaluation_fixtures", fixture_id)["record_version"] = "0.1.1"
        result = EvaluationService(repo).run_fixture(fixture_id)
        self.assertFalse(result["passed"])
        self.assertEqual("mapping_stale", result["status"])

    def test_missing_required_fixture_mapping_fails_suite(self):
        repo = copy.deepcopy(self.repo)
        repo.get_workflow(WORKFLOW)["evaluation"]["required_evaluation_fixture_ids"].append("new-required-fixture")
        report = EvaluationService(repo).run_all()
        self.assertFalse(report["passed"])
        self.assertEqual(["new-required-fixture"], report["required_unmapped_fixture_ids"])

    def test_bad_baseline_provider_makes_harness_fail(self):
        with patch("app.evaluation.testing_registry", lambda *args: testing_registry("malformed_response")):
            result = self.service.run_fixture("va-small-claims-ordinary-user-fixture")
        self.assertFalse(result["passed"])
        self.assertIn({"name": "baseline_status", "passed": False}, result["checks"])

    def test_deterministic_read_only_and_no_network_or_logs(self):
        before = copy.deepcopy(self.repo.records)
        with (patch.object(socket, "socket", side_effect=AssertionError("network")),
              patch.object(socket, "create_connection", side_effect=AssertionError("network")),
              patch.object(logging.Logger, "_log") as log):
            second = self.service.run_all()
        self.assertEqual(self.report, second)
        self.assertEqual(before, self.repo.records)
        log.assert_not_called()

    def test_cli_pass_json_and_unknown_fixture_exit_code(self):
        for args, expected in ((["run_evaluations.py"], 0), (["run_evaluations.py", "--json"], 0), (["run_evaluations.py", "--fixture", "unknown"], 1)):
            out = io.StringIO()
            with patch("sys.argv", args), redirect_stdout(out):
                self.assertEqual(expected, main())
            if "--json" in args:
                self.assertEqual(12, json.loads(out.getvalue())["executed"])
            elif expected == 0:
                self.assertIn("Manual review remains pending", out.getvalue())

    def test_cli_nonzero_when_required_automated_checks_fail(self):
        with (patch("sys.argv", ["run_evaluations.py"]),
              patch.object(EvaluationService, "run_all", return_value={"passed": False, "executed": 0, "results": [], "unmapped_fixture_ids": []}),
              redirect_stdout(io.StringIO())):
            self.assertEqual(1, main())


if __name__ == "__main__":
    unittest.main()
