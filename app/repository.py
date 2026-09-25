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
