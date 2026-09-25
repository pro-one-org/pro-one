import json
from pathlib import Path
from typing import Any


class RepositoryLoadError(RuntimeError):
    """Raised when Pro-One repository data cannot be loaded safely."""


class RecordRepository:
    DOMAIN_FILES = {
        "sources": "sample-sources.json",
        "workflows": "sample-workflows.json",
        "process_steps": "sample-process-steps.json",
        "legal_documents": "sample-legal-documents.json",
        "intakes": "sample-intakes.json",
        "legal_rules": "sample-legal-rules.json",
        "risks": "sample-risks.json",
        "responses": "sample-responses.json",
        "evaluation_fixtures": "sample-evaluation-fixtures.json",
    }

    def __init__(self, data_dir: Path | None = None) -> None:
        project_root = Path(__file__).resolve().parents[1]
        self.data_dir = data_dir or project_root / "data"

        self.records: dict[str, dict[str, dict[str, Any]]] = {}
        self._load()

    def _load(self) -> None:
        for domain, filename in self.DOMAIN_FILES.items():
            path = self.data_dir / filename

            if not path.exists():
                raise RepositoryLoadError(
                    f"Required data file is missing: {path}"
                )

            try:
                with path.open("r", encoding="utf-8") as file:
                    data = json.load(file)
            except (OSError, json.JSONDecodeError) as exc:
                raise RepositoryLoadError(
                    f"Could not load {path}: {exc}"
                ) from exc

            if not isinstance(data, list):
                raise RepositoryLoadError(
                    f"{path} must contain a JSON array."
                )

            domain_records: dict[str, dict[str, Any]] = {}

            for record in data:
                if not isinstance(record, dict):
                    raise RepositoryLoadError(
                        f"{path} contains a record that is not a JSON object."
                    )

                record_id = record.get("id")

                if not isinstance(record_id, str) or not record_id:
                    raise RepositoryLoadError(
                        f"{path} contains a record without a valid id."
                    )

                if record_id in domain_records:
                    raise RepositoryLoadError(
                        f"Duplicate id '{record_id}' in {path}."
                    )

                domain_records[record_id] = record

            self.records[domain] = domain_records

    def get(self, domain: str, record_id: str) -> dict[str, Any] | None:
        return self.records.get(domain, {}).get(record_id)

    def get_workflow(self, workflow_id: str) -> dict[str, Any] | None:
        return self.get("workflows", workflow_id)

    def count_records(self) -> int:
        return sum(len(records) for records in self.records.values())

    def counts_by_domain(self) -> dict[str, int]:
        return {
            domain: len(records)
            for domain, records in self.records.items()
        }

    def _records_for_workflow(
        self,
        domain: str,
        workflow_id: str,
    ) -> list[dict[str, Any]]:
        records = self.records.get(domain, {}).values()
        matches: list[dict[str, Any]] = []

        for record in records:
            workflow_ids: list[str] = []

            if domain == "sources":
                workflow_ids = (
                    record.get("workflow_fit", {}).get("workflow_ids", [])
                )

            elif domain in {
                "process_steps",
                "legal_documents",
                "intakes",
            }:
                workflow_ids = record.get("workflow_ids", [])

            elif domain == "legal_rules":
                workflow_ids = (
                    record.get("workflow_fit", {})
                    .get("supported_workflow_ids", [])
                )

            elif domain in {
                "risks",
                "responses",
                "evaluation_fixtures",
            }:
                workflow_ids = (
                    record.get("related_records", {})
                    .get("workflow_ids", [])
                )

            if workflow_id in workflow_ids:
                matches.append(record)

        return matches

    def resolve_workflow(
        self,
        workflow_id: str,
    ) -> dict[str, Any] | None:
        workflow = self.get_workflow(workflow_id)

        if workflow is None:
            return None

        related: dict[str, list[dict[str, Any]]] = {
            "sources": self._records_for_workflow(
                "sources", workflow_id
            ),
            "process_steps": self._records_for_workflow(
                "process_steps", workflow_id
            ),
            "legal_documents": self._records_for_workflow(
                "legal_documents", workflow_id
            ),
            "intakes": self._records_for_workflow(
                "intakes", workflow_id
            ),
            "legal_rules": self._records_for_workflow(
                "legal_rules", workflow_id
            ),
            "risks": self._records_for_workflow(
                "risks", workflow_id
            ),
            "responses": self._records_for_workflow(
                "responses", workflow_id
            ),
            "evaluation_fixtures": self._records_for_workflow(
                "evaluation_fixtures", workflow_id
            ),
        }

        counts = {
            domain: len(records)
            for domain, records in related.items()
        }

        return {
            "workflow": workflow,
            "related": related,
            "counts": counts,
        }
