"""Authority retrieval is independent of model vendors and never accepts URLs.

Adapters return actual evidence, not search snippets. The official adapter uses
a small source catalog rather than pretending to offer nationwide discovery.
"""

from copy import deepcopy
from dataclasses import dataclass
from datetime import date
import hashlib
from html.parser import HTMLParser
from io import BytesIO
from typing import Protocol
from urllib.request import Request, build_opener, ProxyHandler

from app.capabilities import ResearchMatter, same_jurisdiction
from app.models.http_transport import NoRedirect
from app.retrieval import eligible_record, lexical_score, tokens


class AuthorityUnavailable(ValueError):
    pass


@dataclass(frozen=True)
class AuthorityDocument:
    source: dict
    passages: tuple[dict, ...]
    # Full normalized text is for compiler linkage checks, never a model tool.
    text: str


class LegalAuthorityProvider(Protocol):
    name: str
    def search(self, matter: ResearchMatter, limit: int = 3) -> list[str]: ...
    def fetch(self, source_id: str) -> AuthorityDocument: ...


def authority_rank(source):
    """Relevance preference only, never a rule resolving controlling authority."""
    level = 0 if source["authority"]["level"] == "official_primary" else 1
    case = source.get("case_metadata", {})
    court = case.get("court", "").casefold()
    hierarchy = (0 if "supreme court" in court else 1 if "court of appeals" in court else 2) if case else 0
    return level, hierarchy


def digest(text):
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalized_source(text):
    return " ".join(text.split())


def evidence_passage(source, text, locator, topics, suffix="excerpt", method="bounded_official_source_fetch"):
    today = date.today().isoformat()
    return {"id": source["id"] + "-" + suffix, "schema_version": "1.0.0", "record_version": "0.1.0",
            "last_modified": today, "title": source["title"], "status": "proposed", "review": proposed_review(),
            "source_id": source["id"], "workflow_ids": [], "jurisdiction": deepcopy(source["jurisdiction"]),
            "locator": locator, "propositions": topics, "text": text,
            "verification": {"retrieved_on": today, "verified_on": today,
                             "source_version": source["provenance"]["source_content_version"],
                             "excerpt_hash": digest(text), "method": method},
            "limitations": ["An excerpt is source context, not a conclusion about your facts.",
                            "Currentness and subsequent case treatment have not been certified."],
            "legal_rule_ids": [], "process_step_ids": []}


def proposed_review():
    return {"status": "proposed", "reviewed_by": None, "reviewer_role": None, "review_scope": [],
            "reviewed_on": None, "reviewed_record_version": None}


class RepositoryAuthorityProvider:
    """Offline authoritative corpus discovery, independent of capability/workflow IDs."""
    name = "repository"

    def __init__(self, repository):
        self.repository = repository

    def search(self, matter, limit=3):
        matches = []
        for source in self.repository.records["sources"].values():
            topics = set(source["workflow_fit"]["topics"])
            if (eligible_record(source) and same_jurisdiction(source["jurisdiction"], matter.model_dump())
                    and matter.legal_area in source.get("legal_areas", [])
                    and source["authority"]["level"] in {"official_primary", "official_secondary"}
                    and source["provenance"]["superseded_by_source_id"] is None
                    and set(matter.topics) & topics):
                passages = [p for p in self.repository.records["source_passages"].values() if p["source_id"] == source["id"] and eligible_record(p)]
                score = sum(lexical_score(tokens(" ".join(matter.topics)), p) for p in passages)
                if passages:
                    matches.append((score, source["id"]))
        return [i for _, i in sorted(matches, key=lambda p: (authority_rank(self.repository.get("sources", p[1])), -p[0], p[1]))[:min(limit, 3)]]

    def fetch(self, source_id):
        source = self.repository.get("sources", source_id)
        if not source or not eligible_record(source) or source["authority"]["level"] not in {"official_primary", "official_secondary"}:
            raise AuthorityUnavailable("source_unavailable")
        passages = tuple(deepcopy(p) for p in self.repository.records["source_passages"].values() if p["source_id"] == source_id and eligible_record(p))
        return AuthorityDocument(deepcopy(source), passages, " ".join(p["text"] for p in passages))


# Server-owned registry. No API, user input, model output or redirect can expand it.
# Catalog subjects describe source collections, never per-question workflows.
OFFICIAL_CATALOG = {
    "va-fultz-delhaize": ("https://www.vacourts.gov/static/opinions/opnscvwp/1080782.pdf", "pdf"),
    "va-austin-shoneys": ("https://www.vacourts.gov/static/opinions/opnscvwp/1961236.pdf", "pdf"),
    "va-personal-injury-limitations": ("https://law.lis.virginia.gov/vacode/title8.01/section8.01-243/", "html"),
}


class OfficialSectionParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.skip += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style"} and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


class BoundedAuthorityTransport:
    MAX_BYTES = 2 * 1024 * 1024

    def get(self, url):
        if url not in {item[0] for item in OFFICIAL_CATALOG.values()}:
            raise AuthorityUnavailable("endpoint_not_allowed")
        try:
            # Disable ambient proxies, redirects, compression and credential headers.
            with build_opener(ProxyHandler({}), NoRedirect()).open(
                Request(url, headers={"User-Agent": "Pro-One-Research/0.2", "Accept-Encoding": "identity"}), timeout=8
            ) as response:
                if response.status != 200 or response.headers.get("Content-Encoding", "identity") != "identity":
                    raise AuthorityUnavailable("unexpected_authority_response")
                body = response.read(self.MAX_BYTES + 1)
                kind = response.headers.get_content_type()
            if len(body) > self.MAX_BYTES:
                raise AuthorityUnavailable("authority_response_limit")
            return body, kind
        except Exception:
            raise AuthorityUnavailable("authority_fetch_failed") from None


class VirginiaOfficialProvider:
    name = "virginia_official"

    def __init__(self, repository, transport=None):
        self.repository = repository
        self.isolated = transport is None
        self.transport = transport or BoundedAuthorityTransport()

    def search(self, matter, limit=3):
        if matter.country != "US" or matter.state != "Virginia" or matter.sovereign != "state":
            return []
        return [sid for sid in OFFICIAL_CATALOG if matter.legal_area in self.repository.get("sources", sid).get("legal_areas", [])
                and set(matter.topics) & set(self.repository.get("sources", sid)["workflow_fit"]["topics"])][:min(limit, 3)]

    def fetch(self, source_id):
        if source_id not in OFFICIAL_CATALOG:
            raise AuthorityUnavailable("source_not_allowlisted")
        if self.isolated:
            import json
            import subprocess
            import sys
            try:
                result = subprocess.run([sys.executable, "-B", "-m", "app.authority_worker", source_id],
                                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=12, check=False)
                if result.returncode or len(result.stdout) > 512000:
                    raise ValueError()
                value = json.loads(result.stdout)
                return AuthorityDocument(value["source"], tuple(value["passages"]), value["text"])
            except Exception:
                raise AuthorityUnavailable("authority_fetch_failed") from None
        url, kind = OFFICIAL_CATALOG[source_id]
        body, media = self.transport.get(url)
        source = deepcopy(self.repository.get("sources", source_id))
        if not source or source["url"] != url:
            raise AuthorityUnavailable("catalog_integrity_error")
        try:
            if kind == "pdf":
                if media != "application/pdf" or not body.startswith(b"%PDF-"):
                    raise ValueError()
                from pypdf import PdfReader
                reader = PdfReader(BytesIO(body))
                if reader.is_encrypted or len(reader.pages) > 20:
                    raise ValueError()
                text = normalized_source(" ".join(p.extract_text() or "" for p in reader.pages))
            else:
                if media != "text/html":
                    raise ValueError()
                parser = OfficialSectionParser()
                parser.feed(body.decode("utf-8"))
                text = normalized_source(" ".join(parser.parts))
            if not text or len(text) > 200000:
                raise ValueError()
        except Exception:
            raise AuthorityUnavailable("authority_parse_failed") from None
        source["status"], source["review"] = "proposed", proposed_review()
        source.pop("public_currentness", None)
        source["provenance"]["content_hash"] = digest(text)
        source["provenance"]["source_content_version"] = digest(text)
        source["citation"]["retrieved_at"] = date.today().isoformat()
        # Verified minimal excerpts are checked against the newly fetched text.
        # Changed/missing wording is a gap, never silently substituted as law.
        passages = []
        for existing in self.repository.records["source_passages"].values():
            if existing["source_id"] == source_id and normalized_source(existing["text"]) in text:
                passage = deepcopy(existing)
                passage["status"], passage["review"] = "proposed", proposed_review()
                passage.pop("public_currentness", None)
                passage["verification"].update(retrieved_on=date.today().isoformat(), verified_on=date.today().isoformat(),
                                                source_version=digest(text), method="bounded_official_source_fetch")
                passages.append(passage)
        return AuthorityDocument(source, tuple(passages), text)


def configured_authority_providers(repository, network_provider="", corpus_path=""):
    providers = [RepositoryAuthorityProvider(repository)]
    if network_provider == "virginia_official":
        providers.append(VirginiaOfficialProvider(repository))
    elif network_provider not in {"", "courtlistener"}:
        raise ValueError("unknown_authority_provider")
    if corpus_path or network_provider == "courtlistener":
        import os
        from app.corpus_store import SQLiteCorpusStore
        from app.courtlistener_authority import LocalCorpusAuthorityProvider, CourtListenerAuthorityProvider
        from app.courtlistener_client import CourtListenerClient
        store = SQLiteCorpusStore(corpus_path or ".local/courtlistener.sqlite3")
        token = os.environ.get("COURTLISTENER_API_TOKEN") if network_provider == "courtlistener" else None
        provider = CourtListenerAuthorityProvider(store, CourtListenerClient(token, store=store)) if token else LocalCorpusAuthorityProvider(store)
        provider.owned_store = True
        provider.network_requested_unconfigured = network_provider == "courtlistener" and not token
        providers.append(provider)
    return providers
