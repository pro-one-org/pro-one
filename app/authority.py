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
from app.config import authority_networks
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
OFFICIAL_APPELLATE_CASES = {
    "va-filak-george": {
        "url": "https://www.vacourts.gov/static/opinions/opnscvwp/1031407.pdf",
        "title": "Filak v. George", "citation": "267 Va. 612", "date": "2004-04-23",
        "area": "contracts", "topics": ["contract_breach"],
    },
    "va-rascher-friend": {
        "url": "https://www.vacourts.gov/static/opinions/opnscvwp/1090193.pdf",
        "title": "Rascher v. Friend", "citation": "279 Va. 370", "date": "2010-02-25",
        "area": "torts", "topics": ["contributory_negligence"],
    },
    "va-sales-kecoughtan": {
        "url": "https://www.vacourts.gov/static/opinions/opnscvwp/1090143.pdf",
        "title": "Sales v. Kecoughtan Housing Co., Ltd.", "citation": "279 Va. 475", "date": "2010-02-25",
        "area": "landlord_tenant", "topics": ["landlord_repairs"],
    },
    "va-albritton-commonwealth": {
        "url": "https://www.vacourts.gov/static/opinions/opnscvwp/1191030.pdf",
        "title": "AlBritton v. Commonwealth", "citation": "299 Va. 392 (2021)", "date": "2021-02-04",
        "area": "civil_procedure", "topics": ["summary_judgment"],
        "checked_snapshot": {
            "pdf_sha256": "11ff92022814a26eb509d737b8c5431c9e377ed917d5e94f4f3a8a80e8557af6",
            "page": 7,
            "excerpt": "It follows that immaterial facts genuinely in dispute or material facts not genuinely in dispute do not preclude the entry of summary judgment.",
            "opinion_role": "majority",
            "procedural_posture": "Appeal from summary judgment. The court reversed and remanded.",
        },
    },
}
OFFICIAL_CATALOG.update({sid: (case["url"], "pdf") for sid, case in OFFICIAL_APPELLATE_CASES.items()})
VIRGINIA_RULE_SOURCE = "va-rule-3-20"
VIRGINIA_RULES_URL = "https://www.vacourts.gov/static/courts/scv/rulesofcourt.pdf"
VIRGINIA_RULE_PAGE = 202
VIRGINIA_RULE_EXCERPT = "Summary judgment may not be entered if any material fact is genuinely in dispute."
OFFICIAL_CATALOG[VIRGINIA_RULE_SOURCE] = (VIRGINIA_RULES_URL, "pdf")


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
            max_bytes = 16 * 1024 * 1024 if url == VIRGINIA_RULES_URL else self.MAX_BYTES
            # Disable ambient proxies, redirects, compression and credential headers.
            with build_opener(ProxyHandler({}), NoRedirect()).open(
                Request(url, headers={"User-Agent": "Pro-One-Research/0.2", "Accept-Encoding": "identity"}), timeout=8
            ) as response:
                if response.status != 200 or response.headers.get("Content-Encoding", "identity") != "identity":
                    raise AuthorityUnavailable("unexpected_authority_response")
                body = response.read(max_bytes + 1)
                kind = response.headers.get_content_type()
            if len(body) > max_bytes:
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
        return [sid for sid in OFFICIAL_CATALOG if matter.legal_area in self.source_metadata(sid).get("legal_areas", [])
                and set(matter.topics) & set(self.source_metadata(sid)["workflow_fit"]["topics"])][:min(limit, 3)]

    def source_metadata(self, source_id):
        if source_id == VIRGINIA_RULE_SOURCE:
            source = deepcopy(self.repository.get("sources", "va-personal-injury-limitations"))
            source.update(id=source_id, title="Virginia Rule 3:20 — Motion for Summary Judgment",
                          source_type="court_rule", url=VIRGINIA_RULES_URL, legal_areas=["civil_procedure"],
                          status="proposed", review=proposed_review(), last_modified=date.today().isoformat())
            source.pop("enactment_metadata", None)
            source.pop("public_currentness", None)
            source["authority"]["issuing_body"] = "Supreme Court of Virginia"
            source["authority"]["authority_notes"] = "Official Rule 3:20 page from the consolidated rules PDF. Content hash covers the selected normalized page."
            source["dates"] = {"published": None, "effective_from": None, "effective_through": None,
                               "last_updated": None, "last_verified": None}
            source["provenance"] = {"source_content_version": "pending_rule_page_fetch", "content_hash": None,
                                    "superseded_by_source_id": None}
            source["citation"] = {"preferred_citation": "Va. Sup. Ct. R. 3:20", "retrieved_at": None}
            source["workflow_fit"] = {"topics": ["civil_procedure", "summary_judgment"], "workflow_ids": [],
                                      "risk_level": "high", "limitations": ["Applicability and currentness require review."]}
            source["access"]["format"] = "pdf"
            return source
        if source_id not in OFFICIAL_APPELLATE_CASES:
            return deepcopy(self.repository.get("sources", source_id))
        case = OFFICIAL_APPELLATE_CASES[source_id]
        source = deepcopy(self.repository.get("sources", "va-fultz-delhaize"))
        source.update(id=source_id, title=case["title"], url=case["url"],
                      last_modified=date.today().isoformat(), legal_areas=[case["area"]],
                      status="proposed", review=proposed_review())
        source.pop("public_currentness", None)
        source["dates"] = {"published": case["date"], "effective_from": None, "effective_through": None,
                           "last_updated": None, "last_verified": None}
        source["provenance"] = {"source_content_version": "pending_official_fetch", "content_hash": None,
                                "superseded_by_source_id": None}
        source["citation"] = {"preferred_citation": case["citation"], "retrieved_at": None}
        source["workflow_fit"] = {"topics": case["topics"], "workflow_ids": [], "risk_level": "high",
                                  "limitations": ["Compiler input; opinion-role and legal review pending."]}
        source["case_metadata"] = {"court": "Supreme Court of Virginia", "decision_date": case["date"],
                                   "publication_status": "published", "precedential_status": "unknown",
                                   "procedural_posture": None, "subsequent_treatment": "unknown", "opinion_role": "unknown"}
        return source

    def fetch(self, source_id):
        if source_id not in OFFICIAL_CATALOG:
            raise AuthorityUnavailable("source_not_allowlisted")
        if self.isolated:
            import json
            import subprocess
            import sys
            try:
                result = subprocess.run([sys.executable, "-B", "-m", "app.authority_worker", source_id],
                                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                        timeout=30 if source_id == VIRGINIA_RULE_SOURCE else 12, check=False)
                if result.returncode or len(result.stdout) > 512000:
                    raise ValueError()
                value = json.loads(result.stdout)
                return AuthorityDocument(value["source"], tuple(value["passages"]), value["text"])
            except Exception:
                raise AuthorityUnavailable("authority_fetch_failed") from None
        url, kind = OFFICIAL_CATALOG[source_id]
        body, media = self.transport.get(url)
        source = self.source_metadata(source_id)
        if not source or source["url"] != url:
            raise AuthorityUnavailable("catalog_integrity_error")
        snapshot = OFFICIAL_APPELLATE_CASES.get(source_id, {}).get("checked_snapshot")
        try:
            if kind == "pdf":
                if media != "application/pdf" or not body.startswith(b"%PDF-"):
                    raise ValueError()
                if snapshot and hashlib.sha256(body).hexdigest() != snapshot["pdf_sha256"]:
                    raise ValueError()
                from pypdf import PdfReader
                reader = PdfReader(BytesIO(body))
                rule_source = source_id == VIRGINIA_RULE_SOURCE
                if reader.is_encrypted or len(reader.pages) > (800 if rule_source else 20):
                    raise ValueError()
                if rule_source:
                    text = normalized_source(reader.pages[VIRGINIA_RULE_PAGE].extract_text() or "")
                    if ("Rule 3:20." not in text or "Motion for Summary Judgment." not in text
                            or "Rule 3:21." in text or VIRGINIA_RULE_EXCERPT not in text):
                        raise ValueError()
                else:
                    pages = [normalized_source(p.extract_text() or "") for p in reader.pages]
                    if snapshot and snapshot["excerpt"] not in pages[snapshot["page"] - 1]:
                        raise ValueError()
                    text = normalized_source(" ".join(pages))
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
        if snapshot:
            source["case_metadata"].update(opinion_role=snapshot["opinion_role"], precedential_status="reported",
                                           procedural_posture=snapshot["procedural_posture"])
            source["workflow_fit"]["limitations"] = ["Proposed source. Applicability and subsequent treatment require review."]
            passage = evidence_passage(source, snapshot["excerpt"], f"PDF page {snapshot['page']}",
                                       source["workflow_fit"]["topics"])
            passage["limitations"].append("The excerpt addresses which factual disputes affect summary judgment. Read the full opinion and rule for other requirements.")
            passages.append(passage)
        if source_id == VIRGINIA_RULE_SOURCE:
            passage = evidence_passage(source, VIRGINIA_RULE_EXCERPT,
                                       f"Rule 3:20, PDF page {VIRGINIA_RULE_PAGE + 1}",
                                       ["civil_procedure", "summary_judgment"])
            passage["limitations"].append("Read the complete rule for procedure, exceptions and permitted materials. No ruling on the user's motion is made.")
            passages.append(passage)
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
    networks = authority_networks(network_provider)
    providers = [RepositoryAuthorityProvider(repository)]
    if "virginia_official" in networks:
        providers.append(VirginiaOfficialProvider(repository))
    courtlistener_enabled = "courtlistener" in networks
    if corpus_path or courtlistener_enabled:
        import os
        from app.corpus_store import CORPUS_STORAGE_ERRORS, SQLiteCorpusStore
        from app.courtlistener_authority import LocalCorpusAuthorityProvider, CourtListenerAuthorityProvider
        from app.courtlistener_client import CourtListenerClient
        try:
            store = SQLiteCorpusStore(corpus_path or ".local/courtlistener.sqlite3")
        except CORPUS_STORAGE_ERRORS:
            store = None
        token = os.environ.get("COURTLISTENER_API_TOKEN") if courtlistener_enabled else None
        provider = (CourtListenerAuthorityProvider(store, CourtListenerClient(token, store=store))
                    if token and store is not None else LocalCorpusAuthorityProvider(store))
        provider.owned_store = store is not None
        provider.network_requested_unconfigured = courtlistener_enabled and not token
        providers.append(provider)
    return providers
