"""Citation identity lookup is separate from proposition/quotation verification."""

import os
import re
from pydantic import BaseModel, ConfigDict, Field
from app.authority import AuthorityUnavailable
from app.courtlistener_authority import CourtListenerCitationVerifier, normalize_name
from app.corpus_store import CORPUS_STORAGE_ERRORS, SQLiteCorpusStore
from app.courtlistener_client import CourtListenerClient, CourtListenerError


class CitationResearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    citation: str = Field(min_length=1, max_length=100)
    state: str = Field(min_length=1, max_length=80)
    expected_name: str = Field(default="", max_length=1000)


def lookup_configured_citation(request, settings):
    token = os.environ.get("COURTLISTENER_API_TOKEN") if settings.courtlistener_enabled else None
    if not settings.corpus_path and not token:
        return {"status": "unavailable", "reason": "courtlistener_unconfigured"}
    try:
        with SQLiteCorpusStore(settings.corpus_path or ".local/courtlistener.sqlite3") as store:
            client = CourtListenerClient(token, store=store) if token else None
            return resolve_citation(request, store, client)
    except CORPUS_STORAGE_ERRORS:
        return {"status": "unavailable", "reason": "corpus_storage_unavailable"}


def resolve_citation(request, store, client=None):
    if not re.fullmatch(r"[0-9]{1,5} [A-Za-z.0-9 ]{1,35} [0-9]{1,6}", request.citation):
        return {"status": "citation_unverified", "reason": "base_citation_required_no_pin_cite"}
    try:
        value = store.verification(request.citation) or store.bulk_citation_identity(request.citation)
        if value is None and client:
            value = client.lookup(request.citation)
            store.save_verification(value)
        if not value:
            return {"status": "unavailable", "reason": "citation_lookup_unconfigured_or_unresolved"}
        if request.expected_name and normalize_name(request.expected_name) != normalize_name(value["name"]):
            return {"status": "citation_unverified", "reason": "case_name_citation_mismatch"}
        bundle = store.case(value["cluster"])
        if bundle is None and client:
            bundle = client.hydrate(value["cluster"])
            store.ingest(bundle)
        if not bundle or bundle.court.state != request.state or bundle.court.sovereign != "state":
            return {"status": "citation_unverified", "reason": "jurisdiction_mismatch_or_missing_case"}
        verification = CourtListenerCitationVerifier(store, client).verify(request.citation, bundle.cluster.id, bundle.cluster.name)
        return {"status": "identity_verified", "name": bundle.cluster.name, "citation": request.citation,
                "court": bundle.court.name, "date": bundle.cluster.date, "cluster": bundle.cluster.id,
                "url": f"https://www.courtlistener.com/opinion/{bundle.cluster.id}/", "publication": bundle.cluster.publication,
                "opinion_roles": [o.role for o in bundle.opinions], "verification": verification,
                "limitations": ["Base citation identity only. Quotations, pin cites, substantive support, controlling force and currentness are not verified."]}
    except (AuthorityUnavailable, CourtListenerError):
        return {"status": "citation_unverified", "reason": "citation_lookup_failed"}


def render_citation_identity(value):
    if value.get("status") != "identity_verified":
        return None
    limits = value["limitations"] + value["verification"]["limitations"]
    return {"sections": [{"heading": "Case identity", "text": value["name"] + "; " + value["citation"] + ". " + value["court"] + "; " + (value["date"] or "Date unknown"),
                          "citation_numbers": [1], "user_provided": False}],
            "sources": [{"number": 1, "title": value["name"], "citation": value["citation"], "issuing_authority": value["court"],
                         "case_metadata": {"court": value["court"], "decision_date": value["date"],
                             "opinion_role": value["opinion_roles"][0] if len(value["opinion_roles"]) == 1 else "mixed",
                             "publication_status": value["publication"].lower() if value["publication"] in {"Published", "Unpublished"} else "unknown",
                             "precedential_status": "unknown", "subsequent_treatment": "unknown"},
                         "url": value["url"], "locator": "Base citation identity", "source_type": "court_opinion", "currentness": "unresolved", "limitations": limits}],
            "notices": [], "warnings": limits, "limitations": limits, "publicly_approved": False, "status_label": "Development citation identity"}
