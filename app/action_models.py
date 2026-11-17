"""Versioned development action policies and exact-artifact request contracts."""
from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.matter_models import Digest, EvidenceKind, EventKind, FactValue, FieldName, PartyRole, Record, Text
from app.procedural_models import Key, Scope

Dimension = Literal["legal", "procedural", "party_identity", "jurisdiction", "venue", "facts", "evidence",
                    "claim_analysis", "prerequisites", "deadlines", "documents", "authorization", "review"]
Status = Literal["satisfied", "partially_satisfied", "unknown", "conflicting", "unsupported", "stale",
                 "not_applicable", "requires_review", "blocked"]
Severity = Literal["blocking_requirement", "warning", "informational_gap", "review_required"]
ArtifactKind = Literal["readiness", "deadline", "document", "review", "workspace"]


class FactRequirement(Record):
    field: FieldName
    scope: Literal["matter", "event", "party", "user"] = "matter"
    sources: tuple[Literal["asserted", "documented", "externally_verified"], ...] = Field(min_length=1)
    evidence_kinds: tuple[EvidenceKind, ...] = ()
    equals: FactValue | None = None
    minimum: int | None = None
    exact_date: bool = False
    format: Literal["text", "name", "observation"] | None = None
    allowed_text: tuple[Text, ...] = ()
    same_as: Key | None = None
    claim_element: Key | None = None
    claim_relation: Literal["supporting", "context"] | None = None

    @model_validator(mode="after")
    def check_constraints(self):
        if bool(self.claim_element) != bool(self.claim_relation):
            raise ValueError("claim evidence needs both element and relationship")
        if sum((self.equals is not None, self.minimum is not None, self.exact_date, self.format is not None)) > 1:
            raise ValueError("fact constraints are mutually exclusive")
        return self


class Requirement(Record):
    id: Key
    dimension: Dimension
    severity: Severity
    check: Literal["fact", "choice", "claim", "claim_currentness", "procedure_currentness",
                   "deadline", "review", "future_authorization", "assess_remedies"]
    message: Text
    origin: Literal["legal_authority", "procedural_authority", "document_template", "system_safety", "user_authorization"]
    refs: tuple[Key, ...]
    fact: FactRequirement | None = None

    @model_validator(mode="after")
    def fact_shape(self):
        if (self.check == "fact") != bool(self.fact):
            raise ValueError("invalid action requirement operand")
        if self.origin in {"procedural_authority", "legal_authority", "document_template"} and not self.refs:
            raise ValueError("requirement source needed")
        return self


class ActionDefinition(Record):
    id: Key
    version: Key
    action_type: Literal["demand", "claim", "complaint", "response", "motion", "service", "administrative", "appeal"]
    label: Text
    jurisdiction: Scope
    forum: Key | None = None
    path: Key
    stage: Key | None = None
    event_kind: EventKind | None = None
    allowed_party_roles: tuple[PartyRole, ...] = ()
    theories: tuple[Key, ...] = ()
    requirements: tuple[Requirement, ...] = Field(min_length=1)
    procedure_refs: tuple[Key, ...] = ()
    deadline_rules: tuple[Key, ...] = ()
    template: Key
    coverage: Literal["bounded_reference", "synthetic"] = "bounded_reference"
    review_status: Literal["development_reference"] = "development_reference"


class DocumentField(Record):
    id: Key
    title: Text
    source: Key
    required: bool = True


class Section(Record):
    title: Text
    number_paragraphs: bool = False
    fields: tuple[DocumentField, ...] = Field(min_length=1)


class DocumentTemplate(Record):
    id: Key
    version: Key
    action: Key
    document_type: Key
    title: Text
    sections: tuple[Section, ...] = Field(min_length=1)
    procedure_refs: tuple[Key, ...] = ()
    attachment_kinds: tuple[EvidenceKind, ...] = ()
    include_caption: bool = False
    unsigned_signature_block: bool = False
    review_status: Literal["development_reference"] = "development_reference"


class DeadlinePolicy(Record):
    id: Key
    version: Key
    jurisdiction: Scope
    path: Key
    forum: Key
    event_kind: EventKind
    procedure_ref: Key | None = None
    theory_ref: Key | None = None
    trigger_evidence: tuple[EvidenceKind, ...] = ()
    message: Text

    @model_validator(mode="after")
    def rule_source(self):
        if bool(self.procedure_ref) == bool(self.theory_ref) or (self.procedure_ref and not self.trigger_evidence):
            raise ValueError("deadline needs a procedural rule or an unresolved substantive reference")
        return self


class CalendarDay(Record):
    state: Literal["open", "federal_holiday", "jurisdiction_holiday", "court_closure", "weekend"]
    source: Text


class CourtCalendar(Record):
    id: Key
    version: Key
    forum: Key
    jurisdiction: Scope
    reviewed_by: Text
    days: dict[date, CalendarDay] = Field(min_length=1, max_length=800)


class ActionCatalogData(Record):
    schema_version: Literal["1.0.0"]
    actions: tuple[ActionDefinition, ...]
    templates: tuple[DocumentTemplate, ...]
    deadlines: tuple[DeadlinePolicy, ...]


class RevisionRequest(Record):
    revision: int = Field(ge=0, le=199)


class EvaluateAction(RevisionRequest):
    action_id: Key
    claim_analysis_id: Digest | None = None
    event_id: UUID | None = None
    party_id: UUID | None = None
    user_party_id: UUID | None = None


class EvaluateDeadline(RevisionRequest):
    rule_id: Key
    event_id: UUID | None = None


class AssembleDocument(RevisionRequest):
    readiness_id: Digest


class ReviewDocument(RevisionRequest):
    package_id: Digest
    displayed_digest: Digest
    reviewed: Literal[True]
