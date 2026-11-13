"""Deterministic subject discovery, graph integrity, and capability boundaries.

A match establishes relevance only. It never establishes a duty, a cause of
action, jurisdiction over a party, or a favorable outcome.
"""

from copy import deepcopy
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class ResearchMatter(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    country: str | None = Field(default=None, min_length=2, max_length=2)
    state: str | None = Field(default=None, min_length=1, max_length=80)
    sovereign: str = Field(default="state", pattern="^(state|federal|unknown)$")
    legal_area: str | None = Field(default=None, min_length=1, max_length=80)
    topics: list[str] = Field(default_factory=list, max_length=12)
    user_posture: str | None = Field(default=None, max_length=120)
    document_type: str | None = Field(default=None, max_length=120)
    court: str | None = Field(default=None, max_length=120)
    agency: str | None = Field(default=None, max_length=120)
    goal: str = Field(default="", max_length=2000)
    authority_types: list[Literal["statute", "regulation", "opinion", "constitution", "court_rule", "register_document"]] = Field(
        default_factory=list, max_length=6,
    )
    authority_status: Literal["unresolved", "historical", "current", "current_as_of", "proposed", "superseded", "repealed"] = "unresolved"
    authority_as_of: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")


class ResearchComparison(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    matters: list[ResearchMatter] = Field(min_length=2, max_length=2)

    @model_validator(mode="after")
    def distinct_state_scopes(self):
        left, right = self.matters
        if (any(m.country != "US" or m.sovereign != "state" or not m.state for m in self.matters)
                or left.state.casefold() == right.state.casefold()
                or not left.legal_area or not left.topics
                or left.legal_area != right.legal_area or set(left.topics) != set(right.topics)
                or set(left.authority_types) != set(right.authority_types)
                or (left.authority_status, left.authority_as_of) != (right.authority_status, right.authority_as_of)):
            raise ValueError("comparison_requires_distinct_states_and_shared_subject_and_authority_scope")
        return self


REFERENCE_DOMAINS = {
    "source_ids": "sources", "source_passage_ids": "source_passages",
    "legal_rule_ids": "legal_rules", "process_step_ids": "process_steps",
    "risk_ids": "risks", "related_workflow_ids": "workflows",
    "research_evaluation_ids": "research_evaluations",
}


def same_jurisdiction(left, right):
    return all(left.get(k) == right.get(k) for k in ("country", "state"))


def capability_errors(capability, records):
    errors = []
    for field, domain in REFERENCE_DOMAINS.items():
        for record_id in capability[field]:
            if record_id not in records.get(domain, {}):
                errors.append(f"unknown_{field}:{record_id}")
    for passage_id in capability["source_passage_ids"]:
        passage = records.get("source_passages", {}).get(passage_id)
        if not passage:
            continue
        source = records["sources"].get(passage["source_id"])
        if passage["source_id"] not in capability["source_ids"]:
            errors.append(f"passage_source_outside_capability:{passage_id}")
        if not same_jurisdiction(capability["jurisdiction"], passage["jurisdiction"]):
            errors.append(f"passage_jurisdiction_mismatch:{passage_id}")
        if source and not same_jurisdiction(source["jurisdiction"], capability["jurisdiction"]):
            errors.append(f"source_jurisdiction_mismatch:{source['id']}")
    for source_id in capability["source_ids"]:
        source = records.get("sources", {}).get(source_id)
        if source and (not same_jurisdiction(source["jurisdiction"], capability["jurisdiction"])
                       or capability["legal_area"] not in source.get("legal_areas", [])):
            errors.append(f"source_scope_mismatch:{source_id}")
    for rule_id in capability["legal_rule_ids"]:
        rule = records.get("legal_rules", {}).get(rule_id)
        if rule and (not same_jurisdiction(rule["jurisdiction"], capability["jurisdiction"])
                     or not set(rule["source_support"]["required_source_ids"]).issubset(capability["source_ids"])):
            errors.append(f"rule_scope_mismatch:{rule_id}")
        if rule:
            for passage_id in rule.get("source_passage_ids", []):
                passage = records.get("source_passages", {}).get(passage_id)
                if (not passage or passage_id not in capability["source_passage_ids"]
                        or rule_id not in passage["legal_rule_ids"]
                        or passage["source_id"] not in rule["source_support"]["required_source_ids"]
                        or rule["rule_statement"]["canonical_statement"] != passage["text"]):
                    errors.append(f"rule_evidence_mismatch:{rule_id}")
    return errors


class CapabilityResolutionService:
    def __init__(self, repository):
        self.repository = repository

    def resolve(self, matter: ResearchMatter):
        required = ("country", "legal_area", "topics") if matter.sovereign == "federal" else ("country", "state", "legal_area", "topics")
        missing = [k for k in required if not getattr(matter, k)]
        exact, related = [], []
        for capability in self.repository.records["legal_capabilities"].values():
            if capability["status"] in {"rejected", "deprecated"} or capability["review"]["status"] in {"rejected", "deprecated"}:
                continue
            jurisdiction = capability["jurisdiction"]
            if any(getattr(matter, k) and getattr(matter, k) != jurisdiction.get(k) for k in ("country", "state")):
                continue
            if matter.sovereign != capability["sovereign"]:
                continue
            if matter.legal_area and matter.legal_area != capability["legal_area"]:
                continue
            overlap = sorted(set(matter.topics) & set(capability["topics"]))
            if matter.topics and not overlap:
                continue
            covers_topics = bool(matter.topics) and set(matter.topics).issubset(capability["topics"])
            exact_match = not missing and covers_topics
            candidate = {"capability_id": capability["id"], "confidence": "exact_subject_match" if exact_match else "related_subject",
                         "reasons": ["Jurisdiction and legal area match supplied dimensions.", *overlap],
                         "missing_context": missing,
                         "limitations": ["Relevance is not a legal conclusion or approval."]}
            (exact if exact_match else related).append(candidate)
        return {"exact": deepcopy(exact), "related": deepcopy(related), "missing_context": missing,
                "unsupported_areas": [] if exact or related else [matter.legal_area or "unidentified"],
                "confidence_basis": "Exact matches require jurisdiction, sovereign, area and coverage of every supplied topic; no statistical or legal confidence."}
