from typing import Any

from app.repository import RecordRepository


WORKFLOW_REVIEW_SCOPES = (
    "schema",
    "jurisdiction",
    "legal_information_boundary",
    "safety",
    "evaluation",
)


class WorkflowReadinessService:
    """Evaluate whether a resolved workflow may be used publicly."""

    def __init__(self, repository: RecordRepository) -> None:
        self.repository = repository

    def evaluate(self, workflow_id: str) -> dict[str, Any] | None:
        resolved = self.repository.resolve_workflow(workflow_id)

        if resolved is None:
            return None

        workflow = resolved["workflow"]
        blockers: list[dict[str, Any]] = []

        self._check_workflow(workflow, blockers)
        self._check_dependencies(
            blockers=blockers,
            domain="sources",
            dependency_name="source",
            dependency_ids=workflow["sources"]["required_source_ids"],
        )
        self._check_dependencies(
            blockers=blockers,
            domain="process_steps",
            dependency_name="process step",
            dependency_ids=workflow["process"]["process_step_ids"],
        )
        self._check_dependencies(
            blockers=blockers,
            domain="evaluation_fixtures",
            dependency_name="evaluation fixture",
            dependency_ids=(
                workflow["evaluation"]["required_evaluation_fixture_ids"]
            ),
        )

        return {
            "workflow_id": workflow_id,
            "ready_for_public_use": not blockers,
            "blockers": blockers,
            "warnings": [],
        }

    def _check_workflow(
        self,
        workflow: dict[str, Any],
        blockers: list[dict[str, Any]],
    ) -> None:
        if workflow["status"] != "supported":
            blockers.append(
                {
                    "code": "workflow_status_not_supported",
                    "message": "Workflow status must be supported.",
                    "current_status": workflow["status"],
                }
            )

        review = workflow["review"]

        if review["status"] != "approved":
            blockers.append(
                {
                    "code": "workflow_review_not_approved",
                    "message": "Workflow review must be approved.",
                    "current_status": review["status"],
                }
            )

        required_scopes = list(WORKFLOW_REVIEW_SCOPES)

        if workflow["intake"]["collects_sensitive_data"]:
            required_scopes.append("privacy")

        review_scopes = set(review["review_scope"])
        missing_scopes = [
            scope
            for scope in required_scopes
            if scope not in review_scopes
        ]

        if missing_scopes:
            blockers.append(
                {
                    "code": "workflow_review_scopes_missing",
                    "message": (
                        "Workflow review is missing scopes required for "
                        "public use."
                    ),
                    "missing_scopes": missing_scopes,
                }
            )

    def _check_dependencies(
        self,
        *,
        blockers: list[dict[str, Any]],
        domain: str,
        dependency_name: str,
        dependency_ids: list[str],
    ) -> None:
        dependency_code = dependency_name.replace(" ", "_")

        if not dependency_ids:
            blockers.append(
                {
                    "code": f"required_{dependency_code}s_not_configured",
                    "message": (
                        f"Workflow must identify at least one required "
                        f"{dependency_name}."
                    ),
                }
            )
            return

        for dependency_id in sorted(dependency_ids):
            record = self.repository.get(domain, dependency_id)

            if record is None:
                blockers.append(
                    {
                        "code": f"required_{dependency_code}_not_found",
                        "message": (
                            f"Required {dependency_name} was not found."
                        ),
                        "record_id": dependency_id,
                    }
                )
                continue

            if record["status"] != "supported":
                blockers.append(
                    {
                        "code": (
                            f"required_{dependency_code}_not_supported"
                        ),
                        "message": (
                            f"Required {dependency_name} must be supported."
                        ),
                        "record_id": dependency_id,
                        "current_status": record["status"],
                    }
                )

            review_status = record["review"]["status"]

            if review_status != "approved":
                blockers.append(
                    {
                        "code": (
                            f"required_{dependency_code}_review_not_approved"
                        ),
                        "message": (
                            f"Required {dependency_name} review must be "
                            "approved."
                        ),
                        "record_id": dependency_id,
                        "current_status": review_status,
                    }
                )
