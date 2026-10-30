"""Structured intake assessment; answer text is never classified or interpreted."""

from dataclasses import dataclass
from typing import Any, TypedDict

from pydantic import BaseModel, ConfigDict, Field

from app.repository import RecordRepository


AnswerValue = str | bool | int | float | None


class IntakeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

    answers: dict[str, AnswerValue]
    risk_ids: list[str] = Field(default_factory=list)


class IntakeSummary(TypedDict):
    complete: bool
    required_inputs: list[str]
    provided_required_inputs: list[str]
    missing_required_inputs: list[str]
    optional_inputs_provided: list[str]
    excluded_inputs_provided: list[str]
    restricted_inputs_provided: list[str]
    unrecognized_inputs: list[str]


class RiskSummary(TypedDict):
    recognized: list[dict[str, Any]]
    unknown: list[str]
    not_applicable: list[str]
    routing: list[str]


class IntakeResolutionError(ValueError):
    def __init__(self, code: str, candidate_ids: list[str]) -> None:
        super().__init__(code)
        self.code = code
        self.candidate_ids = candidate_ids


@dataclass
class IntakeAssessment:
    resolved: dict[str, Any]
    definition: dict[str, Any]
    intake: IntakeSummary
    risks: RiskSummary
    privacy: dict[str, Any]
    routing: list[str]
    user_facts: dict[str, dict[str, Any]]
    blockers: list[str]


def category_key(label: str) -> str:
    """Technical matching only: case folding and space/underscore equivalence."""
    return "_".join(label.casefold().replace("_", " ").split())


def has_value(value: AnswerValue) -> bool:
    # False and zero are explicit values. Empty/null is missing, not a legal fact.
    return value is not None and (not isinstance(value, str) or bool(value.strip()))


class IntakeAssessmentService:
    def __init__(self, repository: RecordRepository) -> None:
        self.repository = repository

    def evaluate(
        self,
        workflow_id: str,
        answers: dict[str, AnswerValue],
        risk_ids: list[str],
    ) -> IntakeAssessment | None:
        resolved = self.repository.resolve_workflow(workflow_id)
        if resolved is None:
            return None

        candidates = resolved["related"]["intakes"]
        if len(candidates) != 1:
            raise IntakeResolutionError(
                "intake_not_found" if not candidates else "intake_ambiguous",
                sorted(record["id"] for record in candidates),
            )
        definition = candidates[0]
        fields = resolved["workflow"]["intake"]
        required = sorted(set(fields["required_inputs"]))
        optional = set(fields["optional_inputs"])
        present = {key for key, value in answers.items() if has_value(value)}

        linked_risks = {
            record["id"]: record for record in resolved["related"]["risks"]
        }
        recognized: list[dict[str, Any]] = []
        unknown: list[str] = []
        not_applicable: list[str] = []
        for risk_id in sorted(set(risk_ids)):
            if risk_id in linked_risks:
                recognized.append(linked_risks[risk_id])
            elif self.repository.get("risks", risk_id) is None:
                unknown.append(risk_id)
            else:
                not_applicable.append(risk_id)
        risk_routes = sorted({
            risk["support_routing"]["default_response_strategy"]
            for risk in recognized
        })

        # Categories are metadata labels, not instructions to inspect prose values.
        privacy_records = [
            definition["data_limits"],
            *(risk["privacy"] for risk in recognized),
        ]
        excluded_categories = {category_key(key) for key in fields["excluded_inputs"]}
        restricted_categories: set[str] = set()
        for record in privacy_records:
            excluded_categories.update(
                category_key(key) for key in record["prohibited_data_categories"]
            )
            restricted_categories.update(
                category_key(key) for key in record["restricted_data_categories"]
            )
        # Report supplied keys even when their value is null/empty; never echo values.
        excluded = sorted(
            key for key in answers if category_key(key) in excluded_categories
        )
        restricted = sorted(
            key for key in answers
            if category_key(key) in restricted_categories and key not in excluded
        )
        unrecognized = sorted(
            set(answers) - set(required) - optional - set(excluded) - set(restricted)
        )
        missing = sorted(set(required) - present)
        summary: IntakeSummary = {
            "complete": not missing,
            "required_inputs": required,
            "provided_required_inputs": sorted(set(required) & present),
            "missing_required_inputs": missing,
            "optional_inputs_provided": sorted(optional & present),
            "excluded_inputs_provided": excluded,
            "restricted_inputs_provided": restricted,
            "unrecognized_inputs": unrecognized,
        }
        blockers = [
            code for condition, code in (
                (missing, "missing_required_inputs"),
                (excluded, "excluded_inputs_supplied"),
                (restricted, "restricted_inputs_supplied"),
                (unrecognized, "unrecognized_inputs_supplied"),
                (unknown, "unknown_risk_ids"),
                (not_applicable, "not_applicable_risk_ids"),
            ) if condition
        ]
        routing = set(risk_routes)
        if missing:
            routing.add("pause_for_missing_information")
        if excluded or restricted or unrecognized:
            routing.add("narrow_then_continue")
        if unknown or not_applicable:
            routing.add("pause_for_missing_information")

        privacy = {
            **definition["privacy"],
            "redaction_prompt_required": (
                definition["sensitive_data"]["redaction_prompt_required"]
                or any(risk["privacy"]["redaction_prompt_required"] for risk in recognized)
            ),
            "data_minimization_required": (
                definition["privacy"]["data_minimization_required"]
                or definition["data_limits"]["minimum_necessary_only"]
                or any(risk["privacy"]["data_minimization_required"] for risk in recognized)
            ),
            "sensitive_data_handling": (
                definition["sensitive_data"]["sensitive_data_handling"]
            ),
            "withheld_inputs": sorted(set(excluded + restricted + unrecognized)),
        }
        admitted = (set(required) | optional) & present
        admitted -= set(excluded + restricted + unrecognized)
        return IntakeAssessment(
            resolved=resolved,
            definition=definition,
            intake=summary,
            risks={
                "recognized": recognized,
                "unknown": unknown,
                "not_applicable": not_applicable,
                "routing": risk_routes,
            },
            privacy=privacy,
            routing=sorted(routing) or ["none"],
            user_facts={
                key: {"value": answers[key], "provenance": "user_provided"}
                for key in sorted(admitted)
            },
            blockers=blockers,
        )
