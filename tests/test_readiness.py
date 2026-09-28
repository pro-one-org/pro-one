import unittest

from fastapi.testclient import TestClient

from app.main import app
from app.readiness import WORKFLOW_REVIEW_SCOPES, WorkflowReadinessService
from app.repository import RecordRepository


WORKFLOW_ID = "name_change_information"
EVALUATION_FIXTURE_ID = "runtime-readiness-evaluation"


def make_ready_repository() -> RecordRepository:
    repository = RecordRepository()
    workflow = repository.get_workflow(WORKFLOW_ID)

    workflow["status"] = "supported"
    workflow["review"]["status"] = "approved"
    workflow["review"]["review_scope"] = [
        *WORKFLOW_REVIEW_SCOPES,
        "privacy",
    ]
    workflow["evaluation"]["required_evaluation_fixture_ids"] = [
        EVALUATION_FIXTURE_ID
    ]

    for source_id in workflow["sources"]["required_source_ids"]:
        source = repository.get("sources", source_id)
        source["status"] = "supported"
        source["review"]["status"] = "approved"

    for step_id in workflow["process"]["process_step_ids"]:
        step = repository.get("process_steps", step_id)
        step["status"] = "supported"
        step["review"]["status"] = "approved"

    repository.records["evaluation_fixtures"][EVALUATION_FIXTURE_ID] = {
        "id": EVALUATION_FIXTURE_ID,
        "status": "supported",
        "review": {"status": "approved"},
        "related_records": {"workflow_ids": [WORKFLOW_ID]},
    }

    return repository


def blocker_codes(result: dict) -> set[str]:
    return {blocker["code"] for blocker in result["blockers"]}


class WorkflowReadinessServiceTests(unittest.TestCase):
    def test_current_name_change_workflow_is_not_ready(self) -> None:
        service = WorkflowReadinessService(RecordRepository())

        result = service.evaluate(WORKFLOW_ID)

        self.assertIsNotNone(result)
        self.assertFalse(result["ready_for_public_use"])
        self.assertEqual([], result["warnings"])
        self.assertEqual(
            {
                "workflow_status_not_supported",
                "workflow_review_not_approved",
                "workflow_review_scopes_missing",
                "required_source_not_supported",
                "required_source_review_not_approved",
                "required_process_step_not_supported",
                "required_process_step_review_not_approved",
                "required_evaluation_fixtures_not_configured",
            },
            blocker_codes(result),
        )

        scope_blocker = next(
            blocker
            for blocker in result["blockers"]
            if blocker["code"] == "workflow_review_scopes_missing"
        )
        self.assertEqual(
            [*WORKFLOW_REVIEW_SCOPES, "privacy"],
            scope_blocker["missing_scopes"],
        )

        blocked_step_ids = {
            blocker["record_id"]
            for blocker in result["blockers"]
            if blocker["code"] == "required_process_step_not_supported"
        }
        self.assertEqual(
            {
                "example-name-change-review-instructions",
                "example-name-change-complete-forms",
                "example-name-change-file-with-court",
                "example-name-change-attend-hearing",
            },
            blocked_step_ids,
        )

    def test_fully_eligible_workflow_is_ready(self) -> None:
        service = WorkflowReadinessService(make_ready_repository())

        result = service.evaluate(WORKFLOW_ID)

        self.assertEqual(
            {
                "workflow_id": WORKFLOW_ID,
                "ready_for_public_use": True,
                "blockers": [],
                "warnings": [],
            },
            result,
        )

    def test_sensitive_workflow_requires_privacy_review(self) -> None:
        repository = make_ready_repository()
        workflow = repository.get_workflow(WORKFLOW_ID)
        workflow["review"]["review_scope"].remove("privacy")

        result = WorkflowReadinessService(repository).evaluate(WORKFLOW_ID)

        self.assertFalse(result["ready_for_public_use"])
        self.assertEqual(
            ["privacy"],
            next(
                blocker["missing_scopes"]
                for blocker in result["blockers"]
                if blocker["code"] == "workflow_review_scopes_missing"
            ),
        )

    def test_unresolved_required_dependencies_block_readiness(self) -> None:
        cases = (
            (
                "sources",
                "sources",
                "required_source_ids",
                "missing-source",
                "required_source_not_found",
            ),
            (
                "process_steps",
                "process",
                "process_step_ids",
                "missing-step",
                "required_process_step_not_found",
            ),
            (
                "evaluation_fixtures",
                "evaluation",
                "required_evaluation_fixture_ids",
                "missing-evaluation",
                "required_evaluation_fixture_not_found",
            ),
        )

        for domain, section, field, missing_id, expected_code in cases:
            with self.subTest(domain=domain):
                repository = make_ready_repository()
                workflow = repository.get_workflow(WORKFLOW_ID)
                workflow[section][field] = [missing_id]

                result = WorkflowReadinessService(repository).evaluate(
                    WORKFLOW_ID
                )

                self.assertFalse(result["ready_for_public_use"])
                self.assertIn(expected_code, blocker_codes(result))

    def test_dependency_status_and_review_both_gate_readiness(self) -> None:
        cases = (
            (
                "sources",
                "example-state-court-name-change-guide",
                "required_source_not_supported",
                "required_source_review_not_approved",
            ),
            (
                "process_steps",
                "example-name-change-review-instructions",
                "required_process_step_not_supported",
                "required_process_step_review_not_approved",
            ),
            (
                "evaluation_fixtures",
                EVALUATION_FIXTURE_ID,
                "required_evaluation_fixture_not_supported",
                "required_evaluation_fixture_review_not_approved",
            ),
        )

        for domain, record_id, status_code, review_code in cases:
            with self.subTest(domain=domain):
                repository = make_ready_repository()
                record = repository.get(domain, record_id)
                record["status"] = "proposed"
                record["review"]["status"] = "proposed"

                result = WorkflowReadinessService(repository).evaluate(
                    WORKFLOW_ID
                )

                self.assertFalse(result["ready_for_public_use"])
                self.assertIn(status_code, blocker_codes(result))
                self.assertIn(review_code, blocker_codes(result))

    def test_unknown_workflow_has_no_readiness_result(self) -> None:
        service = WorkflowReadinessService(RecordRepository())

        self.assertIsNone(service.evaluate("does_not_exist"))


class WorkflowReadinessApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)

    def test_name_change_readiness_endpoint_exposes_blockers(self) -> None:
        response = self.client.get(
            "/workflows/name_change_information/readiness"
        )

        self.assertEqual(200, response.status_code)

        body = response.json()

        self.assertEqual(WORKFLOW_ID, body["workflow_id"])
        self.assertFalse(body["ready_for_public_use"])
        self.assertIn(
            "required_evaluation_fixtures_not_configured",
            blocker_codes(body),
        )

    def test_unknown_workflow_readiness_returns_404(self) -> None:
        response = self.client.get(
            "/workflows/does_not_exist/readiness"
        )

        self.assertEqual(404, response.status_code)
        self.assertEqual(
            {"detail": "Workflow 'does_not_exist' was not found."},
            response.json(),
        )


if __name__ == "__main__":
    unittest.main()
