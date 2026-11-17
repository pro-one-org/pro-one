"""Typed, versioned records for the development matter ledger."""
from datetime import date, datetime
from typing import Annotated, Literal, get_args
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StrictBool, StrictInt, model_validator

from app.procedural_models import Fact as ProceduralFact, Key, Scope

Text = Annotated[str, Field(min_length=1, max_length=320)]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
EvidenceKind = Literal[
    "document", "photo", "video", "message", "email", "medical_record", "contract",
    "receipt", "incident_report", "witness", "corporate_record", "court_filing",
    "government_record", "proof_of_service", "legal_authority", "other",
]
PartyRole = Literal["user", "business_involved", "potential_defendant", "owner", "operator", "witness", "insurer", "other"]
EntityType = Literal["individual", "business", "government", "insurer", "unknown"]
FieldName = Literal[
    "jurisdiction", "matter_type", "goal", "brand", "legal_name", "alias", "property_owner",
    "operator", "registry_id", "entity_type", "registered_agent", "self_name", "hazard", "warning_sign", "injury", "employee_notice",
    "hazard_duration", "visit_purpose", "condition_visibility", "hazard_origin", "fall_mechanism",
    "contract_obligation", "contract_performance", "contract_loss",
    "medical_expenses", "lost_wages", "future_treatment", "surveillance", "incident_report",
    "date", "location", "street", "allegation", "possible_legal_issue", "forum",
] | ProceduralFact
FIELD_NAMES = tuple(name for group in get_args(FieldName) for name in get_args(group))
EventKind = Literal[
    "incident", "medical_visit", "conversation", "notice", "payment", "demand", "filing",
    "service", "court_event", "document_received", "deadline_trigger", "judgment", "agency_decision",
    "hearing", "order", "mailing", "publication",
]


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True,
                              revalidate_instances="always")


class Temporal(Record):
    precision: Literal["exact", "approximate", "range", "unknown"]
    original: Text
    start: date | AwareDatetime | None = None
    end: date | AwareDatetime | None = None
    timezone: Text | None = None
    reference: AwareDatetime | None = None
    derivation: Text | None = None

    @model_validator(mode="after")
    def validate_interval(self):
        if self.precision == "unknown":
            valid = self.start is None and self.end is None
        elif self.precision == "exact":
            valid = self.start is not None and self.end is None
        else:
            valid = (self.start is not None and self.end is not None
                     and type(self.start) is type(self.end) and self.start <= self.end)
        if not valid or bool(self.reference) != bool(self.derivation):
            raise ValueError("invalid temporal precision or derivation")
        if self.timezone:
            try:
                zone = ZoneInfo(self.timezone)
            except ZoneInfoNotFoundError:
                raise ValueError("invalid timezone") from None
            for bound in (self.start, self.end):
                if isinstance(bound, datetime) and bound.utcoffset() != bound.astimezone(zone).utcoffset():
                    raise ValueError("timezone contradicts timestamp")
        return self


FactValue = Text | StrictBool | StrictInt | Temporal


class Target(Record):
    field: FieldName
    subject: UUID | None = None


class Message(Record):
    id: UUID
    text: str = Field(min_length=1, max_length=2000)
    received_at: AwareDatetime


class UserSource(Record):
    kind: Literal["user_statement"] = "user_statement"
    message_id: UUID


class DocumentSource(Record):
    kind: Literal["document"] = "document"
    evidence_id: UUID
    excerpt: Text
    offset: int = Field(ge=0, lt=16000)
    page: int | None = Field(default=None, ge=1, le=20)


class ExternalSource(Record):
    kind: Literal["external_record"] = "external_record"
    evidence_id: UUID
    excerpt: Text
    offset: int = Field(ge=0, lt=16000)


class InferenceSource(Record):
    kind: Literal["model_inference"] = "model_inference"
    message_id: UUID
    provider: Key
    model: Text


Source = Annotated[UserSource | DocumentSource | ExternalSource | InferenceSource, Field(discriminator="kind")]


class ExternalRecord(Record):
    provider: Key
    record_id: Text
    retrieved_at: AwareDatetime
    current_as_of: date | None = None
    locator: Text
    link_evidence_hash: Digest | None = None
    subject_label: Text | None = None

    @model_validator(mode="after")
    def link_scope(self):
        if bool(self.link_evidence_hash) != bool(self.subject_label):
            raise ValueError("incomplete external identity link scope")
        return self


class Evidence(Record):
    id: UUID
    kind: EvidenceKind
    origin: Literal["user_upload", "user_inventory", "external_record"]
    received_at: AwareDatetime
    content_hash: Digest | None = None
    extracted_text: str | None = Field(default=None, max_length=16000, repr=False)
    extraction: Literal["supplied", "extracted", "metadata_only"]
    limitations: tuple[Text, ...] = ()
    custody: Text | None = None
    label: Text | None = None
    external: ExternalRecord | None = None
    # Offsets match the parser's extracted text, including page separators.
    page_offsets: tuple[int, ...] = ()

    @model_validator(mode="after")
    def validate_evidence(self):
        if bool(self.external) != (self.origin == "external_record"):
            raise ValueError("external evidence requires record identity")
        if (self.extraction == "extracted") != bool(self.extracted_text):
            raise ValueError("extraction state does not match content")
        if self.extracted_text and not self.content_hash:
            raise ValueError("extraction requires stable content identity")
        if self.origin == "user_inventory" and self.extraction != "metadata_only":
            raise ValueError("inventory requires metadata-only evidence")
        if self.page_offsets and (
            self.origin != "user_upload" or not self.extracted_text or self.page_offsets[0] != 0
            or self.page_offsets != tuple(sorted(set(self.page_offsets)))
            or self.page_offsets[-1] >= len(self.extracted_text) or len(self.page_offsets) > 20
        ):
            raise ValueError("invalid page locators")
        if self.external and (self.external.retrieved_at > self.received_at or
                              self.external.current_as_of and self.external.current_as_of > self.external.retrieved_at.date()):
            raise ValueError("invalid external record dates")
        return self


class Party(Record):
    id: UUID
    role: PartyRole
    origin: UUID  # attributed brand or name assertion


class IdentityCandidate(Record):
    party: UUID
    assertion: UUID
    relationship: Literal["legal_name", "owner", "operator", "registered_agent"] = "legal_name"
    corroborates: UUID | None = None


class Event(Record):
    id: UUID
    kind: EventKind
    origin: UUID
    participants: tuple[UUID, ...] = ()
    evidence: tuple[UUID, ...] = ()


class Assertion(Record):
    id: UUID
    target: Target
    value: FactValue
    source: Source
    status: Literal["asserted", "documented", "externally_verified", "inferred", "alleged"]
    received_at: AwareDatetime
    locator: Text | None = None


class Gap(Record):
    target: Target
    status: Literal["unknown", "unresolved"]
    question: Text


class Correction(Record):
    previous: UUID
    replacement: UUID
    message: UserSource
    received_at: AwareDatetime


class Dispute(Record):
    assertion: UUID
    message: UserSource
    received_at: AwareDatetime


class Choice(Record):
    path: Key
    jurisdiction: Scope
    forum: Key | None = None
    catalog_version: Text
    reference_date: date
    stage: Key | None = None
    procedural_status: Key
    based_on_revision: int = Field(ge=0)
    message: UserSource
    received_at: AwareDatetime


class Suggestion(Record):
    field: FieldName
    quote: Text


class Matter(Record):
    schema_version: Literal["1.0.0"] = "1.0.0"
    id: UUID
    revision: int = Field(ge=0)
    created_at: AwareDatetime
    updated_at: AwareDatetime
    messages: tuple[Message, ...] = ()
    evidence: tuple[Evidence, ...] = ()
    parties: tuple[Party, ...] = ()
    identities: tuple[IdentityCandidate, ...] = ()
    events: tuple[Event, ...] = ()
    assertions: tuple[Assertion, ...] = ()
    gaps: tuple[Gap, ...] = ()
    corrections: tuple[Correction, ...] = ()
    disputes: tuple[Dispute, ...] = ()
    choices: tuple[Choice, ...] = ()
