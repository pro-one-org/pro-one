"""Pinned publisher selectors and normalized procedural evidence projection."""

from dataclasses import dataclass
from functools import lru_cache
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
import re
from textwrap import wrap
from types import MappingProxyType, SimpleNamespace
from urllib.parse import urlsplit

from app.authority import AuthorityDocument, AuthorityUnavailable, evidence_passage, normalized_source
from app.national_corpus import CorpusError, Observation, Source, fingerprint, identity
from app.national_corpus_providers import VirginiaSectionParser
from app.national_corpus_research import NormalizedAuthorityProvider
from app.national_corpus_transport import PublicProvider
from app.procedural_models import Catalog


@dataclass(frozen=True)
class Publication:
    url: str
    publisher: str
    jurisdiction: str
    kind: str
    format: str = "html"
    max_bytes: int = 1024 * 1024


def virginia_code(title, chapter, section):
    return Publication(f"https://law.lis.virginia.gov/vacode/title{title}/chapter{chapter}/section{section}/",
                       "Virginia General Assembly", "US-VA", "statute", "virginia_code")


def virginia_court(host, path, *, kind="court_instruction", format="html", max_bytes=1024 * 1024):
    return Publication(f"https://{host}/{path}", "Virginia Judiciary", "US-VA", kind, format, max_bytes)


PUBLICATIONS = MappingProxyType({
    "venue": virginia_code("8.01", "5", "8.01-262"),
    "district": virginia_code("16.1", "5", "16.1-77"),
    "circuit": virginia_code("17.1", "5", "17.1-513"),
    "service": virginia_code("8.01", "8", "8.01-299"),
    "server": virginia_code("8.01", "8", "8.01-293"),
    "proof": virginia_code("8.01", "8", "8.01-325"),
    "count": virginia_code("1", "2.1", "1-210"),
    "settlement": virginia_code("8.01", "3", "8.01-35.1"),
    "insurance": virginia_code("38.2", "2", "38.2-236"),
    "unrepresented": virginia_code("8.01", "2", "8.01-271.1"),
    "code_updates": Publication("https://law.lis.virginia.gov/vacodeupdates/",
                                "Virginia General Assembly", "US-VA", "statute"),
    "rules": virginia_court("www.vacourts.gov", "static/courts/scv/rulesofcourt.pdf",
                            kind="court_rule", format="pdf", max_bytes=16 * 1024 * 1024),
    "amend": virginia_court("www.vacourts.gov", "courts/scv/amend"),
    "filing": virginia_court("www.vacourts.gov", "online/vjefs/home"),
    "fees": virginia_court("selfhelp.vacourts.gov", "page/14/filing-fees-waivers"),
    "richmond": virginia_court("www.vacourts.gov", "courts/circuit/richmond/home"),
    "local": virginia_court("www.vacourts.gov", "static/courts/circuit/richmond/practices.pdf", format="pdf"),
    "federal": Publication("https://www.uscourts.gov/sites/default/files/document/federal-rules-of-civil-procedure.pdf",
                           "Administrative Office of the U.S. Courts", "US", "court_rule", "pdf"),
    "federal_status": Publication("https://www.uscourts.gov/forms-rules/current-rules-practice-procedure/federal-rules-civil-procedure",
                                  "Administrative Office of the U.S. Courts", "US", "court_instruction"),
    "federal_old": Publication("https://www.uscourts.gov/sites/default/files/2025-02/federal-rules-of-civil-procedure-dec-1-2024_0.pdf",
                               "Administrative Office of the U.S. Courts", "US", "court_rule", "pdf"),
    "florida": Publication("https://www.leg.state.fl.us/Statutes/index.cfm?App_mode=Display_Statute&URL=0000-0099/0048/Sections/0048.031.html",
                           "Florida Legislature", "US-FL", "statute"),
})


@lru_cache(maxsize=1)
def load_catalog():
    path = Path(__file__).resolve().parents[1] / "data" / "procedural-intelligence.json"
    catalog = Catalog.model_validate_json(path.read_bytes())
    for key, authority in catalog.authorities.items():
        publication = PUBLICATIONS.get(authority.artifact)
        if (publication is None or publication.kind != authority.version.authority_type
                or publication.jurisdiction != authority.version.jurisdiction
                or publication.publisher != authority.version.institution
                or (authority.version.court and authority.version.court not in catalog.forums)):
            raise CorpusError(f"procedure_publisher_scope_mismatch:{key}")
        if authority.status_artifact:
            proof = PUBLICATIONS.get(authority.status_artifact)
            if not proof or proof.publisher != publication.publisher or proof.jurisdiction != publication.jurisdiction:
                raise CorpusError(f"procedure_status_publisher_mismatch:{key}")
    return catalog


class PageText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ignored = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in {"style", "script", "template"}:
            self.ignored += 1
        if tag in {"p", "div", "li", "h1", "h2", "h3", "br", "tr"}:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in {"style", "script", "template"} and self.ignored:
            self.ignored -= 1
        if tag in {"p", "div", "li", "h1", "h2", "h3", "tr"}:
            self.parts.append(" ")

    def handle_data(self, data):
        if not self.ignored:
            self.parts.append(data)


def publisher_text(publication, raw, pages=()):
    if not raw or len(raw) > publication.max_bytes:
        raise CorpusError("procedure_artifact_size_invalid")
    if publication.format == "pdf":
        from pypdf import PdfReader

        pdf = PdfReader(BytesIO(raw)).pages
        if not pages or len(pages) > 3 or not all(1 <= page <= min(len(pdf), 1000) for page in pages):
            raise CorpusError("procedure_pdf_page_scope_invalid")
        text = "\n".join(pdf[page - 1].extract_text() for page in pages)
        return normalized_source(re.sub(r"(?<=[A-Za-z])-\s*\n(?=[A-Za-z])", "", text))
    decoded = raw.decode("utf-8-sig")
    parser = VirginiaSectionParser() if publication.format == "virginia_code" else PageText()
    parser.feed(decoded)
    parser.close()
    if publication.format == "virginia_code":
        if parser.headings != 1 or not parser.body_closed:
            raise CorpusError("procedure_statute_identity_invalid")
        return normalized_source("".join(parser.heading_text) + " " + "".join(parser.body_text))
    return normalized_source("".join(parser.parts))


class ProceduralPublicationProvider(PublicProvider):
    """Operator-only artifact acquisition and replay via the existing corpus store."""

    def __init__(self, artifact, catalog):
        if artifact not in PUBLICATIONS:
            raise CorpusError("procedure_publisher_unknown")
        self.artifact = artifact
        self.catalog = catalog
        self.publication = PUBLICATIONS[artifact]
        publication = self.publication
        self.source = Source(
            name=f"procedure_{artifact}", host=urlsplit(publication.url).hostname,
            authority_type=publication.kind, jurisdictions=(publication.jurisdiction,), official_publisher=True,
            rendition="Bounded official publisher selection", endpoint=publication.url, format=publication.format,
            update="Review changed bytes before pinning another version.", rights="Official legal publication.",
            attribution=publication.publisher, currentness_method="Dated publisher evidence where reviewed.",
            parser_revision="1", max_bytes=publication.max_bytes, refresh_mode="pinned_edition",
            refresh_limitation="Publisher amendments and applicable local overlays require separate review.",
        )

    def source_url(self, selector):
        if selector != self.artifact:
            raise CorpusError("procedure_selector_not_allowlisted")
        return self.publication.url

    def normalize(self, selector, raw):
        self.source_url(selector)
        if not raw or len(raw) > self.source.max_bytes:
            raise CorpusError("procedure_artifact_size_invalid")
        raw_hash = fingerprint(raw)
        rows = [a for a in self.catalog.authorities.values() if a.artifact == self.artifact and a.artifact_hash == raw_hash]
        if not rows:
            raise CorpusError("procedure_snapshot_unreviewed")
        texts = {}
        for authority in rows:
            page_match = re.match(r"PDF pages? ([0-9,]+),", authority.locator)
            pages = tuple(map(int, page_match[1].split(","))) if page_match else ()
            if pages not in texts:
                texts[pages] = publisher_text(self.publication, raw, pages)
            if texts[pages].count(authority.version.text) != 1:
                raise CorpusError(f"procedure_excerpt_identity_mismatch:{authority.native_id}")
            yield Observation(authority.version, authority.native_id, authority.locator, authority.version.citation)


class ProceduralAuthorityProvider:
    """Project only the request's prefiltered, pinned normalized evidence."""

    name = "normalized_corpus"

    def __init__(self, matter, authorities, catalog):
        self.matter = matter
        self.documents = {}
        self.passage_ids = {}
        for key, authority in authorities.items():
            version = authority.version
            provider = ProceduralPublicationProvider(authority.artifact, catalog)
            observation = {
                "id": identity(provider.source.name, authority.artifact, authority.artifact_hash, provider.source.parser_revision),
                "hash": authority.artifact_hash, "locator": authority.locator,
                "url": provider.source_url(authority.artifact), "first_retrieved": authority.captured_on.isoformat(),
                "native_id": authority.native_id,
            }
            plan = SimpleNamespace(legal_area=matter.legal_area, issues=matter.topics)
            source = NormalizedAuthorityProvider._source(matter, plan, version, observation, provider.source)
            passages = []
            spans = wrap(version.text, 1000, break_long_words=False, break_on_hyphens=False)
            for index, span in enumerate(spans, 1):
                passage = evidence_passage(source, span, authority.locator, matter.topics, suffix=f"p{index}",
                                           method="provider_exact_text_check")
                passage["verification"]["retrieved_on"] = authority.captured_on.isoformat()
                passage["limitations"].extend(version.limitations)
                passages.append(passage)
            self.documents[source["id"]] = AuthorityDocument(source, tuple(passages), version.text)
            self.passage_ids[key] = tuple(passage["id"] for passage in passages)

    def search(self, matter, limit=6):
        if any(getattr(matter, field) != getattr(self.matter, field)
               for field in ("country", "state", "sovereign", "topics", "legal_area")):
            return []
        return list(self.documents)[:limit]

    def fetch(self, source_id):
        if source_id not in self.documents:
            raise AuthorityUnavailable("procedure_evidence_unavailable")
        return self.documents[source_id]
