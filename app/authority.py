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


# Only these spans of the combined official Austin PDF are attributed to the majority.
AUSTIN_NOTICE_SNAPSHOT = {
    "pdf_sha256": "d415a280c200d3196b6ab7eaa63170277a03726de15d4a984806b064ed7d601d",
    "passages": (
        (7, 1162, 1486, "sha256:51195d4f9464590e63afa4223cbc59c160aac2317a6956e01b3a0c995686d223"),
        (8, 16, 244, "sha256:a00e669cbbb2d543ad3921352005880daf33a39101cef9230c35ec0151a1f2d5"),
    ),
    "opinion_role": "lead",
    "procedural_posture": "Appeal from a renewed motion to strike. Reversed and remanded.",
    "limitation": "The majority's constructive-knowledge analysis depends on a reasonable inference that the property owner created the condition. The court did not determine liability.",
    "topics": ["notice"],
}


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
        "checked_snapshot": {
            "pdf_sha256": "40bff5eb96358580eaefc518b0a082eaa2ee1fff1daec4d6344ad9773cf1b816",
            "passages": ((9, 843, 1096, "sha256:afddb80549438da3563d592c96394d1b4f66d273d203ad7685db84bb257312d0"),),
            "opinion_role": "majority",
            "procedural_posture": "The court affirmed the judgment, including the ruling striking the contract evidence.",
            "limitation": "The excerpt lists claim elements. The court resolved the contract claim on proof of damages and left other issues unresolved.",
        },
    },
    "va-rascher-friend": {
        "url": "https://www.vacourts.gov/static/opinions/opnscvwp/1090193.pdf",
        "title": "Rascher v. Friend", "citation": "279 Va. 370", "date": "2010-02-25",
        "area": "torts", "topics": ["contributory_negligence", "traffic_contributory_negligence"],
        "checked_snapshot": {
            "pdf_sha256": "5aa9b45270cde61889d1b60d0fcff00ed68b871898ac009ed53dc0bc49b0872b",
            "passages": (
                (5, 964, 1259, "sha256:667e1e5fc15154b1dbd3d12bd06a8abad63f7a1951b51b0d1ebcd14a8340f13c"),
                (6, 0, 464, "sha256:f7ce1388f32d6eba0762dad9d7faee6f2563c971652879703828ff7fa58d80b6"),
            ),
            "opinion_role": "majority",
            "procedural_posture": "Appeal from a ruling striking evidence in a traffic collision case. Reversed and remanded for a new trial.",
            "limitation": "The opinion addresses the factfinder's role and proof of negligence and proximate causation. It leaves the collision's outcome for trial.",
        },
    },
    "va-sales-kecoughtan": {
        "url": "https://www.vacourts.gov/static/opinions/opnscvwp/1090143.pdf",
        "title": "Sales v. Kecoughtan Housing Co., Ltd.", "citation": "279 Va. 475", "date": "2010-02-25",
        "area": "landlord_tenant", "topics": ["landlord_repairs"],
        "checked_snapshot": {
            "pdf_sha256": "b8d40ede372158a492a7235f45370d482f3aecc4dba291cf7983487a283a75e8",
            "passages": ((5, 1173, 1301, "sha256:37d28e1312b765222dfd7de6a7176024eb0d8a0b714304db19cca1afaa0fc2bc"),),
            "opinion_role": "majority",
            "procedural_posture": "Appeal from a demurrer. The court reversed and remanded on the pleadings.",
            "limitation": "The excerpt concerns common-law care in repairs actually undertaken. The court addressed the sufficiency of the allegations.",
        },
    },
    "va-albritton-commonwealth": {
        "url": "https://www.vacourts.gov/static/opinions/opnscvwp/1191030.pdf",
        "title": "AlBritton v. Commonwealth", "citation": "299 Va. 392 (2021)", "date": "2021-02-04",
        "area": "civil_procedure", "topics": ["summary_judgment"],
        "checked_snapshot": {
            "pdf_sha256": "11ff92022814a26eb509d737b8c5431c9e377ed917d5e94f4f3a8a80e8557af6",
            "passages": ((7, 41, 184, "sha256:37a26fb14391d56397c4723b2ba531bc10c34ef5e57a8aae2cecd30936d79744"),),
            "opinion_role": "majority",
            "procedural_posture": "Appeal from summary judgment. The court reversed and remanded.",
            "limitation": "The excerpt addresses which factual disputes affect summary judgment. Read the full opinion and rule for other requirements.",
        },
    },
}
OFFICIAL_CATALOG.update({sid: (case["url"], "pdf") for sid, case in OFFICIAL_APPELLATE_CASES.items()})
OFFICIAL_STATUTE_SECTIONS = {
    "va-residential-landlord-maintenance": {
        "url": "https://law.lis.virginia.gov/vacode/title55.1/chapter12/section55.1-1220/",
        "title": "§ 55.1-1220. Landlord to maintain fit premises.",
        "citation": "Va. Code § 55.1-1220",
        "area": "landlord_tenant",
        "topics": ["landlord_repairs"],
        "paragraphs": (
            ("A 2", "2. Make all repairs", "sha256:fc68f5dbbacfded2a8841d7beaaf421484292ea3092e85e7af380913afd7d4bd"),
            ("B", "B. The landlord shall perform", "sha256:6ca1fbdace35a8faa62e3bf088b356a7ce964d4c77393745ca3c95eac7afdb98"),
        ),
    },
}
OFFICIAL_CATALOG.update({sid: (section["url"], "html") for sid, section in OFFICIAL_STATUTE_SECTIONS.items()})
VIRGINIA_RULE_SOURCE = "va-rule-3-20"
VIRGINIA_RULES_URL = "https://www.vacourts.gov/static/courts/scv/rulesofcourt.pdf"
VIRGINIA_RULE_PAGE = 202
VIRGINIA_RULE_EXCERPT = "Summary judgment may not be entered if any material fact is genuinely in dispute."
OFFICIAL_CATALOG[VIRGINIA_RULE_SOURCE] = (VIRGINIA_RULES_URL, "pdf")


class OfficialSectionParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.skip = [], 0
        self.paragraphs = []
        self.paragraph = None

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.skip += 1
        elif tag == "p" and not self.skip:
            self.paragraph = []

    def handle_endtag(self, tag):
        if tag in {"script", "style"} and self.skip:
            self.skip -= 1
        elif tag == "p" and self.paragraph is not None and not self.skip:
            self.paragraphs.append(normalized_source(" ".join(self.paragraph)))
            self.paragraph = None

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)
            if self.paragraph is not None:
                self.paragraph.append(data)


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
        statute = OFFICIAL_STATUTE_SECTIONS.get(source_id)
        if statute:
            source = deepcopy(self.repository.get("sources", "va-personal-injury-limitations"))
            source.update(id=source_id, title=statute["title"], url=statute["url"],
                          legal_areas=[statute["area"]], status="proposed", review=proposed_review(),
                          last_modified=date.today().isoformat())
            source.pop("enactment_metadata", None)
            source.pop("public_currentness", None)
            source["dates"] = dict.fromkeys(source["dates"])
            source["authority"]["authority_notes"] = "Official Code publication. Effective dates and applicability require review."
            source["provenance"] = {"source_content_version": "pending_official_fetch", "content_hash": None,
                                    "superseded_by_source_id": None}
            source["citation"] = {"preferred_citation": statute["citation"], "retrieved_at": None}
            source["workflow_fit"] = {"topics": statute["topics"], "workflow_ids": [], "risk_level": "high",
                                      "limitations": ["Coverage of the tenancy and statutory exceptions require review."]}
            return source
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
        if source_id == "va-austin-shoneys":
            snapshot = AUSTIN_NOTICE_SNAPSHOT
        statute = OFFICIAL_STATUTE_SECTIONS.get(source_id)
        checked_opinion_passages = []
        checked_paragraphs = []
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
                    if snapshot:
                        for page, start, end, fingerprint in snapshot["passages"]:
                            page_text = pages[page - 1]
                            excerpt = page_text[start:end]
                            if not 0 <= start < end <= len(page_text) or digest(excerpt) != fingerprint:
                                raise ValueError()
                            checked_opinion_passages.append((page, excerpt))
                    text = normalized_source(" ".join(pages))
            else:
                if media != "text/html":
                    raise ValueError()
                parser = OfficialSectionParser()
                parser.feed(body.decode("utf-8"))
                text = normalized_source(" ".join(parser.parts))
                if statute:
                    # The linked section number and its period can be separate HTML text nodes.
                    if statute["title"] not in text.replace(" .", "."):
                        raise ValueError()
                    for locator, prefix, fingerprint in statute["paragraphs"]:
                        matches = [paragraph for paragraph in parser.paragraphs if paragraph.startswith(prefix)]
                        if len(matches) != 1 or digest(matches[0]) != fingerprint:
                            raise ValueError()
                        checked_paragraphs.append((locator, matches[0]))
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
            for index, (page, excerpt) in enumerate(checked_opinion_passages, 1):
                passage = evidence_passage(source, excerpt, f"PDF page {page}", snapshot.get("topics", source["workflow_fit"]["topics"]),
                                           suffix="excerpt" if index == 1 else f"excerpt-{index}")
                passage["limitations"].append(snapshot["limitation"])
                passages.append(passage)
        for locator, paragraph in checked_paragraphs:
            passage = evidence_passage(source, paragraph, f"{statute['citation']} {locator}", statute["topics"],
                                       suffix="paragraph-" + locator.lower().replace(" ", "-"))
            passage["limitations"].extend(source["workflow_fit"]["limitations"])
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
