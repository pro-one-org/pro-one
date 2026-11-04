"""Exact structured matching: workflow specification fit, never legal jurisdiction."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.readiness import WorkflowReadinessService
from app.repository import RecordRepository


def key(value: str) -> str:
    return " ".join(value.casefold().replace("—", "-").split())


class MatterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    country: str = Field(default="US", max_length=80)
    state: str = Field(default="", max_length=80)
    user_type: Literal["self_represented_individual", "small_business_owner"]
    matter_type: str = Field(default="", max_length=120)
    court: str = Field(default="", max_length=150)
    document_title: str = Field(default="", max_length=150)
    form_number: str = Field(default="", max_length=80)
    role: str = Field(default="", max_length=80)
    user_goal: str = Field(default="", max_length=2000)


class WorkflowCatalogService:
    def __init__(self, repository: RecordRepository) -> None:
        self.repository = repository
        self.readiness = WorkflowReadinessService(repository)

    def catalog(self, user_type: str | None = None) -> list[dict]:
        result = []
        for workflow in sorted(self.repository.records["workflows"].values(), key=lambda w: w["id"]):
            routing = workflow.get("routing")
            if not routing or (user_type and user_type not in workflow["user_types"]):
                continue  # Fictional examples are not product capabilities.
            result.append({
                "workflow_id": workflow["id"], "title": workflow["title"],
                "purpose": workflow["scope"]["purpose"], "user_types": workflow["user_types"],
                "legal_area": workflow["legal_area"], "jurisdiction": {k: workflow["jurisdiction"][k] for k in ("country", "state", "court", "agency")},
                "routing": routing, "maturity": workflow["status"],
                "development_available": workflow["status"] not in {"rejected", "deprecated"} and workflow["review"]["status"] not in {"rejected", "deprecated"},
                "workflow_ready": self.readiness.evaluate(workflow["id"])["ready_for_public_use"],
                "public_available": False,  # Public generation/release remains disabled.
                "scope_limits": workflow["scope"]["excludes"],
                "intake_fields": workflow["intake"]["required_inputs"],
                "risk_options": [{"id": r["id"], "type": r["risk_type"]} for r in self.repository.records["risks"].values()
                                 if workflow["id"] in r["related_records"]["workflow_ids"]],
            })
        return result


class MatterRoutingService:
    def __init__(self, repository: RecordRepository) -> None:
        self.repository = repository
        self.catalog = WorkflowCatalogService(repository)

    def scope(self, workflow_id: str, matter: MatterRequest | None, facts: dict | None = None) -> dict:
        workflow = self.repository.get_workflow(workflow_id)
        if (workflow is None or not workflow.get("routing") or workflow["status"] in {"rejected", "deprecated"}
                or workflow["review"]["status"] in {"rejected", "deprecated"}):
            return {"state": "outside_workflow", "reasons": ["workflow_not_in_product_catalog"], "missing_fields": []}
        if matter is None:
            return {"state": "insufficient_information", "reasons": ["structured_matter_required"], "missing_fields": workflow["routing"]["required_fields"]}
        values = matter.model_dump()
        missing, conflicts = [], []
        expected = {"country": [workflow["jurisdiction"]["country"]], "state": [workflow["jurisdiction"]["state"]],
                    "user_type": workflow["user_types"], **workflow["routing"]["selectors"]}
        for field, allowed in expected.items():
            value = values[field]
            if value and key(value) not in {key(x) for x in allowed}:
                conflicts.append(field)
        for field in sorted(set(["country", "state", "user_type", *workflow["routing"]["required_fields"]])):
            if not values[field].strip():
                missing.append(field)
        # Structured routing and sanitized intake must not contradict each other.
        if facts is not None:
            bindings = {field: field for field in expected}
            bindings.update(workflow["routing"].get("intake_bindings", {}))
            for field, matter_field in bindings.items():
                if field in facts:
                    value = facts[field]["value"]
                    if not isinstance(value, str) or key(value) != key(values[matter_field]):
                        conflicts.append("intake:" + field)
        state = "outside_workflow" if conflicts else "insufficient_information" if missing else "confirmed_for_workflow"
        return {"state": state, "reasons": ["conflicting_structured_fields"] if conflicts else ["missing_distinguishing_fields"] if missing else ["exact_workflow_specification_match"],
                "missing_fields": sorted(missing), "conflicting_fields": sorted(set(conflicts)),
                "legal_jurisdiction_determined": False}

    def evaluate(self, matter: MatterRequest) -> dict:
        candidates, exact = [], []
        for item in self.catalog.catalog(matter.user_type):
            if not item["development_available"]:
                continue
            scope = self.scope(item["workflow_id"], matter)
            if scope["state"] == "confirmed_for_workflow":
                exact.append(item["workflow_id"])
            elif scope["state"] == "insufficient_information":
                candidates.append({"workflow_id": item["workflow_id"], "missing_fields": scope["missing_fields"]})
        if len(exact) == 1:
            return {"state": "exact_match", "workflow_ids": exact, "missing_fields": [], "reasons": ["exact_structured_match"]}
        if len(exact) > 1:
            return {"state": "ambiguous", "workflow_ids": exact, "missing_fields": [], "reasons": ["multiple_exact_matches_no_automatic_selection"]}
        if candidates:
            return {"state": "candidate_match" if len(candidates) == 1 else "insufficient_information",
                    "workflow_ids": [c["workflow_id"] for c in candidates],
                    "missing_fields": sorted({f for c in candidates for f in c["missing_fields"]}), "reasons": ["confirm_missing_structured_information"]}
        return {"state": "unsupported", "workflow_ids": [], "missing_fields": [], "reasons": ["no_matching_development_workflow"],
                "official_resources": sorted({s["url"] for s in self.repository.records["sources"].values()
                                             if s["jurisdiction"].get("state") == matter.state and s["authority"]["level"].startswith("official")})}
