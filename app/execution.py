"""Assemble development metadata contexts without generating legal answers."""

from copy import deepcopy
from typing import Any, TypedDict

from app.intake import AnswerValue, IntakeAssessmentService, IntakeSummary, RiskSummary
from app.readiness import WorkflowReadinessService
from app.repository import RecordRepository


class ExecutionState(TypedDict):
    context_available: bool
    next_runtime_state: str
    input_eligible: bool
    blockers: list[str]
    reference_issues: list[dict[str, str]]
    context: dict[str, Any] | None


class PublicExecution(TypedDict):
    allowed: bool
    readiness: dict[str, Any]


class ExecutionResult(TypedDict):
    workflow_id: str
    intake_id: str
    intake: IntakeSummary
    risks: RiskSummary
    privacy: dict[str, Any]
    routing: list[str]
    execution: ExecutionState
    public_execution: PublicExecution


def required_reference_issues(resolved: dict[str, Any]) -> list[dict[str, str]]:
    """Check package integrity, without loading or adding any related records.

    A required dependency must be in the resolver's selected workflow package.
    This also detects an existing dependency with a missing workflow backlink.
    """
    related = resolved["related"]
    linked_ids = {
        domain: {record["id"] for record in records}
        for domain, records in related.items()
    }
    required_fields = {
        "required_source_ids": "sources",
        "required_rule_ids": "legal_rules",
        "required_evaluation_fixture_ids": "evaluation_fixtures",
    }
    issues: list[dict[str, str]] = []

    def check(record_id: str, field: str, ids: list[str], domain: str) -> None:
        for target_id in sorted(set(ids) - linked_ids[domain]):
            issues.append({
                "code": "required_reference_not_in_workflow_package",
                "record_id": record_id,
                "field": field,
                "target_domain": domain,
                "target_id": target_id,
            })

    def walk(record_id: str, value: Any) -> None:
        if isinstance(value, dict):
            for key, child in sorted(value.items()):
                if key in required_fields:
                    check(record_id, key, child, required_fields[key])
                else:
                    walk(record_id, child)

    workflow = resolved["workflow"]
    check(
        workflow["id"], "process_step_ids",
        workflow["process"]["process_step_ids"], "process_steps",
    )
    records = [workflow, *(record for group in related.values() for record in group)]
    for record in sorted(records, key=lambda record: record["id"]):
        walk(record["id"], record)
    return issues


class ExecutionContextService:
    def __init__(self, repository: RecordRepository) -> None:
        self.intake_service = IntakeAssessmentService(repository)
        self.readiness_service = WorkflowReadinessService(repository)

    def build(
        self,
        workflow_id: str,
        answers: dict[str, AnswerValue],
        risk_ids: list[str],
    ) -> ExecutionResult | None:
        assessment = self.intake_service.evaluate(workflow_id, answers, risk_ids)
        if assessment is None:
            return None
        readiness = self.readiness_service.evaluate(workflow_id)
        issues = required_reference_issues(assessment.resolved)
        blockers = list(assessment.blockers)
        if issues:
            blockers.append("unresolved_required_references")
        eligible = not blockers and readiness["ready_for_public_use"]
        workflow = assessment.resolved["workflow"]
        related = assessment.resolved["related"]
        routes = set(assessment.routing)
        if issues:
            routes.discard("none")
            routes.add("pause_for_missing_information")
        routing = sorted(routes)

        context = None
        if not issues:
            context = {
                "purpose": "development_inspection",
                "workflow": workflow,
                # Repository scope metadata is not a confirmed user jurisdiction.
                "jurisdiction": workflow["jurisdiction"],
                "intake_definition": assessment.definition,
                "user_facts": assessment.user_facts,
                "missing_information": assessment.intake["missing_required_inputs"],
                "records": {
                    domain: sorted(related[domain], key=lambda record: record["id"])
                    for domain in (
                        "process_steps", "sources", "legal_rules", "risks",
                        "legal_documents", "responses",
                    )
                },
                "active_risk_ids": [
                    record["id"] for record in assessment.risks["recognized"]
                ],
                # Preserve each record's output vocabulary; do not imply that
                # a union of allowed outputs overrides another record's limits.
                "output_constraints": {
                    "workflow": workflow["outputs"],
                    "intake": assessment.definition["outputs"],
                },
                "limitations": {
                    "scope": workflow["scope"],
                    "safety": workflow["safety"],
                    "privacy": {
                        "data_limits": assessment.definition["data_limits"],
                        "sensitive_data": assessment.definition["sensitive_data"],
                        **assessment.privacy,
                    },
                    "fact_interpretation": "user_provided_values_unverified",
                    "source_content": "repository_metadata_only",
                    "legal_answer_generated": False,
                },
                "routing": routing,
                "readiness": readiness,
                "public_execution_allowed": eligible,
            }

        if issues:
            state = "context_unavailable"
        elif blockers:
            state = "input_action_required"
        elif not eligible:
            state = "development_context_only"
        else:
            state = "public_execution_eligible"
        # Detach all returned metadata so callers cannot mutate repository state.
        return deepcopy({
            "workflow_id": workflow_id,
            "intake_id": assessment.definition["id"],
            "intake": assessment.intake,
            "risks": assessment.risks,
            "privacy": assessment.privacy,
            "routing": routing,
            "execution": {
                "context_available": context is not None,
                "next_runtime_state": state,
                "input_eligible": not assessment.blockers,
                "blockers": blockers,
                "reference_issues": issues,
                "context": context,
            },
            "public_execution": {"allowed": eligible, "readiness": readiness},
        })
