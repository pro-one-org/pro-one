import json
import shutil
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app, repository
from app.repository import RecordRepository, RepositoryLoadError


ROOT = Path(__file__).resolve().parents[1]


class RuntimeRepositoryTests(unittest.TestCase):
    def test_repository_loads_all_current_records(self) -> None:
        self.assertEqual(86, repository.count_records())
        self.assertEqual(9, len(repository.records))

    def test_known_workflow_can_be_retrieved(self) -> None:
        workflow = repository.get_workflow("name_change_information")

        self.assertIsNotNone(workflow)
        self.assertEqual("name_change_information", workflow["id"])
        self.assertEqual("Name Change Information", workflow["title"])
    def test_malformed_record_fails_schema_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            data_dir = temp_root / "data"
            schema_dir = temp_root / "schemas"

            shutil.copytree(ROOT / "data", data_dir)
            shutil.copytree(ROOT / "schemas", schema_dir)

            workflows_path = data_dir / "sample-workflows.json"
            workflows = json.loads(
                workflows_path.read_text(encoding="utf-8")
            )

            del workflows[0]["title"]

            workflows_path.write_text(
                json.dumps(workflows, indent=2) + "\n",
                encoding="utf-8",
            )

            with self.assertRaises(RepositoryLoadError) as context:
                RecordRepository(
                    data_dir=data_dir,
                    schema_dir=schema_dir,
                )

            message = str(context.exception)

            self.assertIn("failed schema validation", message)
            self.assertIn("title", message)


    def test_unknown_workflow_returns_none(self) -> None:
        self.assertIsNone(repository.get_workflow("does_not_exist"))

    def test_name_change_workflow_resolves_expected_record_counts(self) -> None:
        resolved = repository.resolve_workflow("name_change_information")

        self.assertIsNotNone(resolved)
        self.assertEqual(
            {
                "sources": 1,
                "process_steps": 4,
                "legal_documents": 1,
                "intakes": 1,
                "legal_rules": 1,
                "risks": 2,
                "responses": 0,
                "evaluation_fixtures": 0,
            },
            resolved["counts"],
        )

    def test_name_change_workflow_resolves_expected_records(self) -> None:
        resolved = repository.resolve_workflow("name_change_information")

        self.assertIsNotNone(resolved)

        related = resolved["related"]

        self.assertEqual(
            {"example-state-court-name-change-guide"},
            {record["id"] for record in related["sources"]},
        )

        self.assertEqual(
            {
                "example-name-change-review-instructions",
                "example-name-change-complete-forms",
                "example-name-change-file-with-court",
                "example-name-change-attend-hearing",
            },
            {record["id"] for record in related["process_steps"]},
        )

        self.assertEqual(
            {"example-name-change-petition"},
            {record["id"] for record in related["legal_documents"]},
        )

        self.assertEqual(
            {"example-name-change-intake"},
            {record["id"] for record in related["intakes"]},
        )

        self.assertEqual(
            {"example-name-change-filing-instructions-rule"},
            {record["id"] for record in related["legal_rules"]},
        )

        self.assertEqual(
            {
                "example-imminent-deadline-risk",
                "example-evidence-integrity-unsafe-request-risk",
            },
            {record["id"] for record in related["risks"]},
        )

        self.assertEqual([], related["responses"])
        self.assertEqual([], related["evaluation_fixtures"])

    def test_resolved_counts_match_returned_records(self) -> None:
        resolved = repository.resolve_workflow("name_change_information")

        self.assertIsNotNone(resolved)

        for domain, count in resolved["counts"].items():
            self.assertEqual(
                count,
                len(resolved["related"][domain]),
            )

    def test_unknown_workflow_cannot_be_resolved(self) -> None:
        self.assertIsNone(
            repository.resolve_workflow("does_not_exist")
        )


class RuntimeApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)

    def test_health_endpoint(self) -> None:
        response = self.client.get("/health")

        self.assertEqual(200, response.status_code)
        self.assertEqual(
            {
                "status": "ok",
                "service": "pro-one",
                "version": "0.1.0",
                "records_loaded": 86,
                "domains_loaded": 9,
            },
            response.json(),
        )

    def test_workflow_endpoint(self) -> None:
        response = self.client.get(
            "/workflows/name_change_information"
        )

        self.assertEqual(200, response.status_code)
        self.assertEqual(
            "name_change_information",
            response.json()["id"],
        )

    def test_unknown_workflow_returns_404(self) -> None:
        response = self.client.get(
            "/workflows/does_not_exist"
        )

        self.assertEqual(404, response.status_code)
        self.assertEqual(
            {
                "detail": "Workflow 'does_not_exist' was not found."
            },
            response.json(),
        )

    def test_resolved_workflow_endpoint(self) -> None:
        response = self.client.get(
            "/workflows/name_change_information/resolved"
        )

        self.assertEqual(200, response.status_code)

        body = response.json()

        self.assertEqual(
            "name_change_information",
            body["workflow"]["id"],
        )
        self.assertEqual(1, body["counts"]["sources"])
        self.assertEqual(4, body["counts"]["process_steps"])
        self.assertEqual(1, body["counts"]["legal_rules"])
        self.assertEqual(2, body["counts"]["risks"])

    def test_unknown_resolved_workflow_returns_404(self) -> None:
        response = self.client.get(
            "/workflows/does_not_exist/resolved"
        )

        self.assertEqual(404, response.status_code)
        self.assertEqual(
            {
                "detail": "Workflow 'does_not_exist' was not found."
            },
            response.json(),
        )


if __name__ == "__main__":
    unittest.main()
