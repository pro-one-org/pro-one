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
Currentness = Literal["unresolved", "historical", "repealed", "superseded"]


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
    opinion_role: Literal["lead", "majority", "concurrence", "dissent", "mixed", "unknown"] | None = None
    precedential_status: str | None = None
    procedural_posture: str | None = None
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
        return self

    @property
    def authority_id(self) -> str:
        return identity(self.jurisdiction, self.authority_type, self.identity_namespace, self.identity_key)

    @property
    def normalized_hash(self) -> str:
        return fingerprint(self.text.encode())

    @property
    def version_id(self) -> str:
        return identity(self.authority_id, encode(self.model_dump(mode="json")))


@dataclass(frozen=True)
class Observation:
    version: AuthorityVersion
    native_id: str
    locator: str
    original_citation: str


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


class CorpusProvider(Protocol):
    source: Source

    def source_url(self, selector: str) -> str: ...
    def fetch(self, selector: str) -> bytes: ...
    def normalize(self, selector: str, raw: bytes) -> Iterable[Observation]: ...


@dataclass(frozen=True)
class CorpusQuery:
    jurisdiction: str
    authority_type: AuthorityType
    citation: str = ""
    text: str = ""
    edition: str = ""
    provider: str = ""
    currentness: Currentness | Literal["current"] = "unresolved"
    opinion_roles: tuple[str, ...] = ()
    limit: int = 12


class NormalizedCorpusStore(Protocol):
    def ingest(self, provider: CorpusProvider, selector: str, raw: bytes) -> dict: ...
    def search(self, query: CorpusQuery) -> list[dict]: ...
    def snapshot_bytes(self, content_hash: str) -> bytes | None: ...
    def stats(self) -> dict[str, int]: ...
