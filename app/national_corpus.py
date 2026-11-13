"""Provider-neutral models and bounded persistence contract for legal authority."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from hashlib import sha256
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.corpus_store import encode


AuthorityType = Literal[
    "statute", "regulation", "opinion", "constitution", "court_rule",
    "administrative_decision", "attorney_general_opinion", "agency_guidance",
    "executive_material", "session_law", "recap_filing", "register_document",
]
Currentness = Literal["unresolved", "current", "historical", "repealed", "superseded", "proposed"]
OpinionRole = Literal[
    "lead", "majority", "unanimous", "plurality", "concurrence", "concurrence_in_part", "dissent",
    "mixed", "addendum", "remittitur", "rehearing", "on_the_merits", "motion", "trial_document", "unknown",
]


def fingerprint(value: bytes) -> str:
    return sha256(value).hexdigest()


def identity(*parts: str) -> str:
    return fingerprint(encode(parts).encode())


class CorpusError(ValueError):
    """A stable, safe error code for a failed corpus operation."""


class AuthorityVersion(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    jurisdiction: str = Field(pattern=r"^US(?:-[A-Z]{2})?$")
    sovereign: Literal["federal", "state"]
    authority_type: AuthorityType
    # Namespace and key identify a legal unit independent of its representation.
    # Adapters without independently checked identity must use their own namespace.
    identity_namespace: str = Field(min_length=1, max_length=80)
    identity_key: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=1000)
    citation: str = Field(min_length=1, max_length=200)
    alternate_citations: tuple[str, ...] = ()
    edition: str = Field(min_length=1, max_length=100)
    text: str = Field(min_length=1, max_length=500_000)
    hierarchy: tuple[str, ...] = ()
    institution: str | None = None
    court: str | None = None
    agency: str | None = None
    legislature: str | None = None
    enacted_on: date | None = None
    effective_from: date | None = None
    effective_until: date | None = None
    published_on: date | None = None
    amended_on: date | None = None
    repealed_on: date | None = None
    currentness: Currentness = "unresolved"
    current_as_of: date | None = None
    currentness_basis: str | None = None
    opinion_role: OpinionRole | None = None
    precedential_status: str | None = None
    procedural_posture: str | None = None
    document_kind: Literal["proposed_rule", "final_rule", "notice", "other"] | None = None
    limitations: tuple[str, ...] = ()
    review_state: Literal["proposed"] = "proposed"

    @model_validator(mode="after")
    def validate_scope(self):
        if (self.jurisdiction == "US") != (self.sovereign == "federal"):
            raise ValueError("authority_jurisdiction_mismatch")
        if self.opinion_role is not None and self.authority_type != "opinion":
            raise ValueError("opinion_role_requires_opinion")
        if self.effective_until and self.effective_from and self.effective_until <= self.effective_from:
            raise ValueError("invalid_effective_period")
        if self.repealed_on and self.currentness != "repealed":
            raise ValueError("repeal_requires_repealed_status")
        if self.document_kind is not None and self.authority_type != "register_document":
            raise ValueError("register_kind_requires_register_document")
        if self.document_kind == "proposed_rule" and self.currentness != "proposed":
            raise ValueError("proposed_rule_requires_proposed_status")
        if self.currentness == "current":
            if not self.current_as_of or not self.currentness_basis or self.authority_type not in {"statute", "regulation"}:
                raise ValueError("current_status_requires_as_of_evidence")
            if ((self.effective_from and self.effective_from > self.current_as_of)
                    or (self.effective_until and self.effective_until <= self.current_as_of)):
                raise ValueError("current_status_outside_effective_period")
        elif self.current_as_of is not None or self.currentness_basis is not None:
            raise ValueError("current_evidence_requires_current_status")
        return self

    @property
    def authority_id(self) -> str:
        return identity(self.jurisdiction, self.authority_type, self.identity_namespace, self.identity_key)

    @property
    def normalized_hash(self) -> str:
        return fingerprint(self.text.encode())

    @property
    def version_id(self) -> str:
        payload = self.model_dump(mode="json")
        for field in ("document_kind", "current_as_of", "currentness_basis"):
            if payload[field] is None:
                del payload[field]
        return identity(self.authority_id, encode(payload))


@dataclass(frozen=True)
class SourceRelationship:
    kind: Literal["cites", "opinion_of", "docket_of", "part_of", "references_cfr", "part_authority_citation"]
    target_native_id: str


@dataclass(frozen=True)
class Observation:
    version: AuthorityVersion
    native_id: str
    locator: str
    original_citation: str
    relationships: tuple[SourceRelationship, ...] = ()


@dataclass(frozen=True)
class Source:
    name: str
    host: str
    authority_type: AuthorityType
    jurisdictions: tuple[str, ...]
    official_publisher: bool
    rendition: str
    endpoint: str
    format: str
    update: str
    rights: str
    attribution: str
    currentness_method: str
    parser_revision: str
    acceptance: str = "proposed"
    authentication: str = "none"
    pagination: str = "none"
    max_bytes: int = 8 * 1024 * 1024
    max_requests: int = 1


@dataclass(frozen=True)
class FetchedSource:
    raw: bytes
    requests: int


class CorpusProvider(Protocol):
    source: Source

    def source_url(self, selector: str) -> str: ...
    def fetch(self, selector: str) -> FetchedSource: ...
    def normalize(self, selector: str, raw: bytes) -> Iterable[Observation]: ...


@dataclass(frozen=True)
class CorpusQuery:
    jurisdiction: str
    authority_type: AuthorityType
    citation: str = ""
    text: str = ""
    edition: str = ""
    provider: str = ""
    currentness: Currentness = "unresolved"
    as_of: date | None = None
    opinion_roles: tuple[str, ...] = ()
    court: str = ""
    agency: str = ""
    legislature: str = ""
    published_from: date | None = None
    published_through: date | None = None
    limit: int = 12


class NormalizedCorpusStore(Protocol):
    def ingest(self, provider: CorpusProvider, selector: str, raw: bytes) -> dict: ...
    def search(self, query: CorpusQuery) -> list[dict]: ...
    def snapshot_bytes(self, content_hash: str) -> bytes | None: ...
    def stats(self) -> dict[str, int]: ...
