"""Deterministic evidence topics and constraints, never a legal answer generator."""

from copy import deepcopy
from datetime import date
from typing import Any, Callable, TypedDict
from time import perf_counter

from pydantic import Field

from app.execution import ExecutionContextService
from app.grounding import GroundingEligibilityService, utc_today
from app.intake import IntakeRequest
from app.repository import RecordRepository
from app.retrieval import PassageRetrievalService, RetrievalRequest
from app.routing import MatterRequest, MatterRoutingService


class ResponseAssemblyRequest(IntakeRequest):
    retrieval: RetrievalRequest = Field(default_factory=RetrievalRequest)
    matter: MatterRequest | None = None


class ResponseAssemblyResult(TypedDict):
    workflow_id: str
    mode: str
    development_package: dict[str, Any]
    user_context: dict[str, Any]
    intake: dict[str, Any]
    risks: dict[str, Any]
    privacy: dict[str, Any]
    routing: list[str]
    grounding: dict[str, Any]
    response_plan: dict[str, Any]
    public_execution: dict[str, Any]
    scope_resolution: dict[str, Any]


class AssemblyIntegrityError(ValueError):
    """Composed services must agree on workflow identity."""


class ResponseAssemblyService:
    def __init__(self, repository: RecordRepository, today: Callable[[], date] = utc_today) -> None:
        self.repository = repository
        self.execution_service = ExecutionContextService(repository)
        self.retrieval_service = PassageRetrievalService(repository)
        self.grounding_service = GroundingEligibilityService(repository, today)

    def assemble(self, workflow_id: str, request: ResponseAssemblyRequest, metrics: dict | None = None) -> ResponseAssemblyResult | None:
        execution = self.execution_service.build(workflow_id, request.answers, request.risk_ids)
        if execution is None:
            return None
        started = perf_counter()
        retrieval = self.retrieval_service.retrieve(workflow_id, request.retrieval)
        if metrics is not None:
            metrics["retrieval"] = round((perf_counter() - started) * 1000, 2)
        if retrieval is None or execution["workflow_id"] != workflow_id or retrieval["workflow_id"] != workflow_id:
            raise AssemblyIntegrityError("package_workflow_mismatch")
        eligibility = self.grounding_service.evaluate(
            workflow_id, [p["id"] for p in retrieval["passages"]],
            risk_ids=[r["id"] for r in execution["risks"]["recognized"]],
        )
        material = eligibility["records"]
        passages, sources = material["passages"], material["sources"]
        rules, steps, patterns = material["legal_rules"], material["process_steps"], material["response_patterns"]
        workflow = self.repository.get_workflow(workflow_id)
        context = execution["execution"]["context"]

        gaps = []
        withheld = set()
        for configured in workflow.get("response_constraints", {}).get("support_gaps", []):
            gap = deepcopy(configured)
            gap["evidence_passage_ids"] = sorted(
                p["id"] for p in passages if set(p["propositions"]).intersection(gap["propositions"])
            )
            gaps.append(gap)
            if gap["withhold_claims"]:
                withheld.update(gap["propositions"] or [topic for p in passages for topic in p["propositions"]])
        if not eligibility["development_grounding"]["available"]:
            gaps.append({
                "code": "grounding_unavailable", "description": "No eligible evidence package is available; no substantive claims are assembled.",
                "propositions": [], "evidence_passage_ids": [],
                "withhold_claims": True, "blocks_public_grounding": True,
                "prohibited_conclusions": ["Do not fill missing evidence with an inferred legal conclusion."],
            })
        if context is None:
            gaps.append({
                "code": "execution_context_unavailable", "description": "Execution package integrity is unresolved.",
                "propositions": [], "evidence_passage_ids": [], "withhold_claims": True,
                "blocks_public_grounding": True, "prohibited_conclusions": [],
            })

        source_map = {s["id"]: s for s in sources}
        citations = []
        for passage in passages:
            source = source_map[passage["source_id"]]
            citations.append({
                "citation_id": "citation." + passage["id"],
                "passage_id": passage["id"], "source_id": source["id"],
                "source_title": source["title"], "official_url": source["url"],
                "locator": passage["locator"], "preferred_citation": source["citation"]["preferred_citation"],
                "source_citation": source["citation"], "verification": passage["verification"],
                "source_dates": source["dates"], "source_provenance": source["provenance"],
                "passage_status": passage["status"], "passage_review": passage["review"],
                "source_status": source["status"], "source_review": source["review"],
                "source_currentness": source.get("public_currentness", {"status": "unresolved"}),
                "passage_currentness": passage.get("public_currentness", {"status": "unresolved"}),
                "rights": source["rights"],
                "limitations": sorted(set(passage["limitations"] + source["workflow_fit"].get("limitations", []))),
            })

        sections = [set(p["response_structure"]["required_sections"] + p["response_structure"]["optional_sections"]) for p in patterns]
        allowed_sections = set.intersection(*sections) if sections else set()
        required_sections = {s for p in patterns for s in p["response_structure"]["required_sections"]}
        section_conflict = bool(required_sections - allowed_sections)
        if execution["privacy"]["redaction_prompt_required"]:
            allowed_sections.add("redaction_prompt")
            required_sections.add("redaction_prompt")
        if execution["privacy"]["privacy_notice_required"]:
            allowed_sections.add("privacy_prompt")
            required_sections.add("privacy_prompt")
        if execution["risks"]["recognized"]:
            allowed_sections.add("risk_notice")
            required_sections.add("risk_notice")
        if section_conflict:
            gaps.append({
                "code": "response_section_constraints_conflict", "description": "Response patterns have incompatible section requirements.",
                "propositions": [], "evidence_passage_ids": [], "withhold_claims": True,
                "blocks_public_grounding": True, "prohibited_conclusions": [],
            })

        claims = []
        if context is not None and not section_conflict:
            topics = sorted({topic for p in passages for topic in p["propositions"]} - withheld)
            for topic in topics:
                evidence = [p for p in passages if topic in p["propositions"]]
                claims.append({
                    "claim_id": "claim." + topic, "claim_type": "legal_information_topic",
                    "topic": topic, "workflow_id": workflow_id,
                    "supported_by_passage_ids": [p["id"] for p in evidence],
                    "source_ids": sorted({p["source_id"] for p in evidence}),
                    "citation_ids": ["citation." + p["id"] for p in evidence],
                    "legal_rule_ids": sorted({i for p in evidence for i in p["legal_rule_ids"]}),
                    "process_step_ids": sorted({i for p in evidence for i in p["process_step_ids"]}),
                    "user_fact_ids": [], "status": "development_only",
                    "support_scope": "tagged_proposition_only_not_entire_record_or_action",
                    "limitations": sorted(
                        {limit for p in evidence for limit in p["limitations"]}
                        | {gap["description"] for gap in gaps if topic in gap["propositions"]}
                    ),
                })
        if not patterns:
            gaps.append({
                "code": "response_pattern_not_configured", "description": "No eligible response pattern defines sections for this package.",
                "propositions": [], "evidence_passage_ids": [], "withhold_claims": False,
                "blocks_public_grounding": True, "prohibited_conclusions": [],
            })
        package_integrity = context is not None and eligibility["development_grounding"]["available"] and not section_conflict and bool(patterns)
        public_allowed = (
            execution["execution"]["input_eligible"] and execution["public_execution"]["allowed"]
            and eligibility["public_grounding"]["allowed"] and package_integrity and bool(claims)
        )
        for claim in claims:
            if public_allowed:
                claim["status"] = "public_eligible"
        return deepcopy({
            "workflow_id": workflow_id, "mode": "development_inspection",
            "scope_resolution": MatterRoutingService(self.repository).scope(workflow_id, request.matter, context["user_facts"] if context else {}),
            "development_package": {"available": context is not None, "package_integrity": package_integrity},
            "user_context": {
                "facts": context["user_facts"] if context else {},
                "missing_information": execution["intake"]["missing_required_inputs"],
                "jurisdiction_scope": workflow["jurisdiction"],
                "jurisdiction_confirmed_from_user_facts": False,
            },
            "intake": execution["intake"], "risks": execution["risks"],
            "privacy": execution["privacy"], "routing": execution["routing"],
            "grounding": {
                **material, "eligibility": {k: v for k, v in eligibility.items() if k != "records"},
                "retrieval": retrieval["retrieval"], "filters": retrieval["filters"],
            },
            "response_plan": {
                "available": package_integrity,
                "claims": claims, "citations": citations, "support_gaps": sorted(gaps, key=lambda g: g["code"]),
                "allowed_sections": sorted(allowed_sections), "required_sections": sorted(required_sections),
                "prohibited_conclusions": sorted({c for gap in gaps for c in gap["prohibited_conclusions"]}),
                "prohibited_actions": sorted(set(
                    workflow["scope"]["excludes"]
                    + [a for p in patterns for a in p["prohibited_content"]["prohibited_actions"]]
                    + [a for step in steps for a in step["actions"]["prohibited_actions"]]
                    + [a for risk in execution["risks"]["recognized"] for a in risk["prohibited_support"]["prohibited_actions"]]
                )),
                "constraints": {
                    "workflow_outputs": workflow["outputs"], "workflow_scope": workflow["scope"],
                    "intake_outputs": context["output_constraints"]["intake"] if context else {},
                    "response_patterns": patterns,
                    "legal_rule_support": {rule["id"]: {"rule_statement": rule["rule_statement"], "user_support": rule["user_support"], "source_support": rule["source_support"]} for rule in rules},
                },
                "required_disclosures": sorted(set(
                    workflow["safety"]["required_warnings"]
                    + [s for p in patterns for s in p["user_message"]["required_phrases"]]
                    + [s for p in patterns for s in p["source_use"]["source_limitation_language"]]
                )),
                "limitations": sorted(set(retrieval["limitations"] + [g["description"] for g in gaps])),
                "legal_answer_generated": False,
            },
            "public_execution": {
                "allowed": bool(public_allowed), "input_eligible": execution["execution"]["input_eligible"],
                "input_blockers": execution["execution"]["blockers"],
                "workflow_readiness": eligibility["workflow_readiness"],
                "grounding_allowed": eligibility["public_grounding"]["allowed"],
                "package_integrity": package_integrity,
            },
        })
