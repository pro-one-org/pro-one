"""Typed claim catalog, source bindings and mapping records."""
from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.matter_models import FieldName, Record, Target
from app.procedural_models import Key, Scope, Text


class AuthorityRef(Record):
    passage_id: str
    source_id: str
    source_version: str
    excerpt_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    source_type: Literal["court_opinion", "statute", "regulation", "constitution"]
    role: Literal["supports", "qualifies", "conflicts"] = "supports"


class FactLink(Record):
    field: FieldName
    scope: Literal["matter", "event", "party"]
    question: Text
    relation: Literal["context", "supporting", "adverse"] = "context"
    adverse_value: bool | None = None


class LegalElement(Record):
    id: Key
    label: Text
    description: Text
    kind: Literal["requirement", "condition", "exception", "factor"]
    authority: tuple[AuthorityRef, ...] = Field(min_length=1, max_length=8)
    fields: tuple[FactLink, ...] = Field(default=(), max_length=12)
    parent: Key | None = None
    burden: Text | None = None
    standard: Text | None = None

    @model_validator(mode="after")
    def basis(self):
        if not any(ref.role == "supports" for ref in self.authority):
            raise ValueError("element_support_required")
        if len({link.field for link in self.fields}) != len(self.fields):
            raise ValueError("duplicate_element_field")
        return self


class RuleLogic(Record):
    op: Literal["element", "all", "any", "if", "unless"]
    element: Key | None = None
    operands: tuple["RuleLogic", ...] = Field(default=(), max_length=16)

    @model_validator(mode="after")
    def arity(self):
        size = len(self.operands)
        if self.op == "element":
            valid = self.element is not None and size == 0
        else:
            valid = self.element is None and (size >= 2 if self.op in {"all", "any"} else size == 2)
        if not valid:
            raise ValueError("invalid_rule_logic")
        return self

    def references(self):
        if self.element:
            return {self.element}
        return set().union(*(operand.references() for operand in self.operands))


class LegalTheory(Record):
    id: Key
    version: Key
    jurisdiction: Scope
    legal_area: Key
    kind: Literal["claim", "defense", "remedy", "entitlement", "bar"]
    label: Text
    plain_language_label: Text
    review: Literal["proposed", "development_reviewed"] = "proposed"
    capability: str | None = None
    topics: tuple[Key, ...] = Field(min_length=1, max_length=8)
    matter_types: tuple[Key, ...] = Field(min_length=1, max_length=8)
    elements: tuple[LegalElement, ...] = Field(min_length=1, max_length=16)
    logic: RuleLogic
    related_theory: Key | None = None
    procedural_reference: Key | None = None
    limitations: tuple[Text, ...] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def graph(self):
        elements = {element.id: element for element in self.elements}
        if len(elements) != len(self.elements) or not self.logic.references() <= elements.keys():
            raise ValueError("invalid_theory_element_reference")
        for element in self.elements:
            seen = {element.id}
            parent = element.parent
            while parent:
                if parent in seen or parent not in elements:
                    raise ValueError("invalid_element_hierarchy")
                seen.add(parent)
                parent = elements[parent].parent
        return self


class AnalyzeClaim(Record):
    revision: int = Field(ge=0, le=199)
    theory_ids: tuple[Key, ...] = Field(default=(), max_length=8)
    event_id: UUID | None = None
    party_id: UUID | None = None
    law_as_of: date | None = None
    model_assistance: bool = False
    requested_output: Literal["evidence", "strategy", "probability", "readiness", "valuation", "draft", "action"] = "evidence"


class ElementMatterMapping(Record):
    matter_id: UUID
    matter_revision: int
    theory_id: Key
    theory_version: Key
    element_id: Key
    target: Target
    assertion_id: UUID
    evidence_id: UUID | None = None
    relationship: Literal["context", "supporting", "adverse", "conflicting"]


class MappingBatch(Record):
    mappings: tuple[ElementMatterMapping, ...] = Field(max_length=32)


class MappingVerification(Record):
    accepted: tuple[ElementMatterMapping, ...] = Field(max_length=32)
