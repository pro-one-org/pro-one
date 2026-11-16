"""Versioned procedural knowledge layered over normalized authority versions."""

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.national_corpus import AuthorityVersion, AuthorityType


Key = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
Scope = Annotated[str, Field(pattern=r"^US(?:-[A-Z]{2})?$")]
Hash = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Text = Annotated[str, Field(min_length=1, max_length=1800)]
Fact = Literal["incident_locality", "defendant_identity", "defendant_type", "defendant_location",
               "amount_sought", "complaint_filed", "summons_issued", "document_type", "service_date",
               "service_mode", "extension_status", "local_rules_checked", "order_entered"]
Classification = Literal["objective_procedural_fact", "conditional_procedural_requirement",
                         "available_user_option", "strategy_legal_judgment", "reserved_legal_act"]
PathKind = Literal["claim", "demand", "negotiation", "administrative", "civil_litigation", "defense",
                   "appeal", "post_judgment"]
Inquiry = Literal["compensation", "response", "service"]


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class Authority(Record):
    artifact: Key
    artifact_hash: Hash
    captured_on: date
    locator: Text
    native_id: Text
    version: AuthorityVersion
    status_artifact: Key | None = None
    status_hash: Hash | None = None

    @model_validator(mode="after")
    def status_proof(self):
        dated = self.version.evidence_status == "current_as_of"
        if dated != bool(self.status_artifact) or dated != bool(self.status_hash):
            raise ValueError("dated authority requires a pinned status source")
        if self.version.current_as_of and self.version.current_as_of > self.captured_on:
            raise ValueError("review date follows capture date")
        return self


class Reference(Record):
    authority: Key
    authority_type: AuthorityType


class Jurisdiction(Record):
    name: Text
    state_name: Text | None = None


class Forum(Record):
    jurisdiction: Scope
    parent: Key | None = None
    level: Literal["limited_trial", "general_trial", "appellate", "highest", "agency"]
    name: Text
    geography: tuple[Text, ...] = ()
    subject_matter: tuple[Text, ...] = ()
    venue_facts: tuple[Fact, ...] = ()
    court_id: Text
    clerk_reference: Reference | None = None
    filing_systems: tuple[Key, ...] = ()
    evidence: tuple[Reference, ...] = Field(min_length=1)


class Filing(Record):
    method: Literal["unspecified", "paper", "electronic", "in_person"]
    destination: Text
    system: Key | None = None
    eligibility: Text
    components: tuple[Text, ...] = ()
    formatting: Text | None = None
    signature: Text | None = None
    page_limit: int | None = Field(default=None, gt=0)
    exceptions: tuple[Text, ...] = ()


class Fee(Record):
    currency: Literal["USD"] = "USD"
    amount_cents: int | None = Field(default=None, ge=0)
    variable_by: tuple[Text, ...] = ()
    payment_event: Text | None = None

    @model_validator(mode="after")
    def amount_or_variables(self):
        if self.amount_cents is not None and self.variable_by:
            raise ValueError("a fixed fee cannot vary")
        if self.amount_cents is None and not (self.variable_by or self.payment_event):
            raise ValueError("fee requires an amount, variables or a payment event")
        return self


class Service(Record):
    recipient: Text
    documents: tuple[Text, ...] = ()
    methods: tuple[Text, ...] = Field(min_length=1)
    actor: Text | None = None
    trigger: Text
    proof: Text | None = None
    entity_type: Text | None = None
    exceptions: tuple[Text, ...] = ()


class Deadline(Record):
    trigger: Literal["service_of_summons_and_complaint", "filing_of_complaint", "entry_of_final_judgment"]
    period: int = Field(gt=0, le=365)
    unit: Literal["calendar_days"]
    counting: Literal["exclude_trigger_include_last"]
    last_day: Literal["next_open_business_day"]
    service_effects: Text
    extensions: Text
    counting_authority: Reference


class Stage(Record):
    label: Text
    prerequisite_facts: tuple[Fact, ...] = ()
    completion_facts: tuple[Fact, ...] = ()
    transitions: tuple[Key, ...] = ()


class Path(Record):
    jurisdiction: Scope
    inquiry: Inquiry
    legal_area: Key
    proceeding: Key
    kind: PathKind
    label: Text
    description: Text
    evidence: tuple[Reference, ...] = Field(min_length=1)
    forums: tuple[Key, ...] = ()
    entry_facts: tuple[Fact, ...] = ()
    entry_stage: Key | None = None
    stages: dict[Key, Stage] = Field(default_factory=dict)
    user_choice_required: Literal[True] = True


class Requirement(Record):
    path: Key
    stage: Key
    forum: Key | None = None
    classification: Classification
    action: Literal["required", "optional", "informational"]
    trigger: Text
    facts: tuple[Fact, ...] = ()
    conditions: tuple[Text, ...] = ()
    text: Text
    evidence: tuple[Reference, ...] = Field(min_length=1, max_length=4)
    filing: Filing | None = None
    fee: Fee | None = None
    service: Service | None = None
    deadline: Deadline | None = None
    local: bool = False


class Catalog(Record):
    schema_version: Literal["1.0.0"]
    record_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    review: Literal["development_only"]
    reference_date: date
    jurisdictions: dict[Scope, Jurisdiction]
    authorities: dict[Key, Authority]
    forums: dict[Key, Forum]
    paths: dict[Key, Path]
    requirements: dict[Key, Requirement]

    def checked_authority(self, ref, jurisdiction, forum=None):
        authority = self.authorities.get(ref.authority)
        if (not authority or authority.version.jurisdiction != jurisdiction
                or authority.version.authority_type != ref.authority_type
                or (authority.version.court is not None and authority.version.court != forum)):
            raise ValueError(f"invalid procedure evidence reference {ref.authority}")
        return authority

    @model_validator(mode="after")
    def validate_graph(self):
        if any((key == "US") == bool(scope.state_name) for key, scope in self.jurisdictions.items()):
            raise ValueError("invalid procedural jurisdiction name")
        for key, authority in self.authorities.items():
            scope = authority.version.jurisdiction
            forum = authority.version.court
            if (scope not in self.jurisdictions
                    or (forum and (forum not in self.forums or self.forums[forum].jurisdiction != scope))):
                raise ValueError(f"invalid authority jurisdiction or forum {key}")
        for key, forum in self.forums.items():
            if forum.jurisdiction not in self.jurisdictions:
                raise ValueError(f"invalid forum jurisdiction {key}")
            ancestry = {key}
            parent_id = forum.parent
            while parent_id:
                parent = self.forums.get(parent_id)
                if not parent or parent.jurisdiction != forum.jurisdiction or parent_id in ancestry:
                    raise ValueError(f"invalid forum parent {key}")
                ancestry.add(parent_id)
                parent_id = parent.parent
            refs = forum.evidence + ((forum.clerk_reference,) if forum.clerk_reference else ())
            for ref in refs:
                self.checked_authority(ref, forum.jurisdiction, key)
        for key, path in self.paths.items():
            if path.jurisdiction not in self.jurisdictions:
                raise ValueError(f"invalid path jurisdiction {key}")
            for ref in path.evidence:
                self.checked_authority(ref, path.jurisdiction)
            if any(fid not in self.forums or self.forums[fid].jurisdiction != path.jurisdiction for fid in path.forums):
                raise ValueError(f"invalid path forum {key}")
            if bool(path.stages) != bool(path.entry_stage) or (path.entry_stage and path.entry_stage not in path.stages):
                raise ValueError(f"invalid entry stage {key}")
            visited = set()

            def visit(stage_id, ancestors):
                if stage_id not in path.stages or stage_id in ancestors:
                    raise ValueError(f"invalid stage transition {key}/{stage_id}")
                if stage_id in visited:
                    return
                for target in path.stages[stage_id].transitions:
                    visit(target, ancestors | {stage_id})
                visited.add(stage_id)

            if path.entry_stage:
                visit(path.entry_stage, set())
            if visited != set(path.stages):
                raise ValueError(f"unreachable stage {key}")
        for key, requirement in self.requirements.items():
            path = self.paths.get(requirement.path)
            if (not path or requirement.stage not in path.stages
                    or (requirement.forum and requirement.forum not in path.forums)
                    or (requirement.local and not requirement.forum)):
                raise ValueError(f"invalid requirement scope {key}")
            refs = requirement.evidence
            if requirement.deadline:
                refs += (requirement.deadline.counting_authority,)
            evidence = [self.checked_authority(ref, path.jurisdiction, requirement.forum) for ref in refs]
            if requirement.local and not any(item.version.court == requirement.forum for item in evidence):
                raise ValueError(f"missing local authority {key}")
            if requirement.filing and requirement.filing.system:
                forum = self.forums.get(requirement.forum)
                if not forum or requirement.filing.system not in forum.filing_systems:
                    raise ValueError(f"unregistered filing system {key}")
        return self
