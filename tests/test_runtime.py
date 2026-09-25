import unittest

from fastapi.testclient import TestClient

from app.main import app, repository


class RuntimeRepositoryTests(unittest.TestCase):
    def test_repository_loads_all_current_records(self) -> None:
        self.assertEqual(61, repository.count_records())
        self.assertEqual(9, len(repository.records))

    def test_known_workflow_can_be_retrieved(self) -> None:
        workflow = repository.get_workflow("name_change_information")

        self.assertIsNotNone(workflow)
        self.assertEqual("name_change_information", workflow["id"])
        self.assertEqual("Name Change Information", workflow["title"])

    def test_unknown_workflow_returns_none(self) -> None:
        self.assertIsNone(repository.get_workflow("does_not_exist"))


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
                "records_loaded": 61,
                "domains_loaded": 9,
            },
            response.json(),
        )

    def test_workflow_endpoint(self) -> None:
        response = self.client.get("/workflows/name_change_information")

        self.assertEqual(200, response.status_code)
        self.assertEqual(
            "name_change_information",
            response.json()["id"],
        )

    def test_unknown_workflow_returns_404(self) -> None:
        response = self.client.get("/workflows/does_not_exist")

        self.assertEqual(404, response.status_code)
        self.assertEqual(
            {
                "detail": "Workflow 'does_not_exist' was not found."
            },
            response.json(),
        )


if __name__ == "__main__":
    unittest.main()
