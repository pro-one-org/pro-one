"""Server-owned selectors and deterministic parsers for public federal editions."""

from datetime import datetime
from html.parser import HTMLParser
from http.client import HTTPException
from io import BytesIO
from time import monotonic
import re
from types import MappingProxyType
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile

from app.authority import normalized_source
from app.models.http_transport import NoRedirect
from app.national_corpus import AuthorityVersion, CorpusError, FetchedSource, Observation, Source
from app.national_corpus_courtlistener import CourtListenerProvider


USLM = "{http://xml.house.gov/schemas/uslm/1.0}"


class SafeTree(ET.TreeBuilder):
    def doctype(self, name, public_id, system_id):
        raise CorpusError("source_xml_doctype_forbidden")


def xml_root(raw):
    try:
        return ET.fromstring(raw, parser=ET.XMLParser(target=SafeTree()))
    except ET.ParseError as exc:
        raise CorpusError("source_xml_invalid") from exc


def text_of(element):
    return normalized_source("".join(element.itertext())) if element is not None else ""


class PublicProvider:
    def fetch(self, selector):
        url = self.source_url(selector)
        deadline = monotonic() + 30
        opener = build_opener(ProxyHandler({}), NoRedirect())
        request = Request(url, headers={"User-Agent": "Pro-One legal corpus ingestion/1.0", "Accept-Encoding": "identity"})
        raw = bytearray()
        try:
            with opener.open(request, timeout=10) as response:
                if (response.geturl() != url or response.status != 200
                        or response.headers.get("Content-Encoding", "identity") != "identity"):
                    raise CorpusError("source_response_invalid")
                while True:
                    chunk = response.read1(min(65536, self.source.max_bytes + 1 - len(raw)))
                    raw.extend(chunk)
                    if len(raw) > self.source.max_bytes:
                        raise CorpusError("source_size_out_of_bounds")
                    if monotonic() > deadline:
                        raise CorpusError("source_download_deadline")
                    if not chunk:
                        return FetchedSource(bytes(raw), requests=1)
        except HTTPError as exc:
            status = exc.code
            exc.close()
            raise CorpusError(f"source_http_{status}") from None
        except (URLError, OSError, HTTPException):
            raise CorpusError("source_transport_error") from None


class OLRCProvider(PublicProvider):
    source = Source(
        name="olrc", host="uscode.house.gov", authority_type="statute", jurisdictions=("US",),
        official_publisher=True, rendition="OLRC U.S. Code USLM release",
        endpoint="/download/releasepoints/us/pl/{congress}/{law}/xml_usc{title}@{release}.zip",
        format="single-title ZIP containing USLM XML", update="explicit public-law release point",
        rights="Federal codified statutory text. Publisher packaging and annotations preserved for audit.",
        attribution="Office of the Law Revision Counsel, U.S. House of Representatives",
        currentness_method="Matches embedded release identity. Later amendments and effective dates unresolved.",
        parser_revision="1",
    )

    def _selection(self, selector):
        match = re.fullmatch(r"([1-9][0-9]{0,2})-([1-9][0-9]{0,3})/([1-9][0-9]?)", selector)
        if not match:
            raise CorpusError("invalid_olrc_selector")
        congress, law, title = match.groups()
        return congress, law, title, f"{congress}-{law}"

    def source_url(self, selector):
        congress, law, title, release = self._selection(selector)
        path = self.source.endpoint.format(congress=congress, law=law, title=title.zfill(2), release=release)
        return f"https://{self.source.host}{path}"

    def normalize(self, selector, raw):
        _, _, title, release = self._selection(selector)
        member = f"usc{title.zfill(2)}.xml"
        try:
            with ZipFile(BytesIO(raw)) as archive:
                if archive.namelist() != [member] or archive.getinfo(member).file_size > self.source.max_bytes:
                    raise CorpusError("source_zip_member_invalid")
                with archive.open(member) as stream:
                    xml = stream.read(self.source.max_bytes + 1)
        except (BadZipFile, RuntimeError, NotImplementedError, OSError):
            raise CorpusError("source_zip_invalid") from None
        if len(xml) > self.source.max_bytes:
            raise CorpusError("source_size_out_of_bounds")
        root = xml_root(xml)
        title_path = f"/us/usc/t{title}"
        if (root.tag != USLM + "uscDoc" or root.get("identifier") != title_path
                or root.findtext(f"{USLM}meta/{USLM}docNumber") != title
                or root.findtext(f"{USLM}meta/{USLM}docPublicationName") != f"Online@{release}"):
            raise CorpusError("source_edition_identity_mismatch")
        main = root.find(f"{USLM}main/{USLM}title")
        if main is None or main.get("identifier") != title_path:
            raise CorpusError("source_title_identity_mismatch")
        yield from self._sections(main, title, release, member, (title_path,))

    def _sections(self, element, title, release, member, hierarchy, depth=0):
        if depth > 16:
            raise CorpusError("source_hierarchy_limit")
        containers = {USLM + name for name in ("subtitle", "chapter", "subchapter", "part", "subpart", "division")}
        for child in element:
            if child.tag in containers:
                parent = child.get("identifier")
                nested_hierarchy = (*hierarchy, parent) if parent else hierarchy
                yield from self._sections(child, title, release, member, nested_hierarchy, depth + 1)
                continue
            if child.tag != USLM + "section":
                continue
            number = child.find(USLM + "num")
            section = number.get("value", "") if number is not None else ""
            native_id = child.get("identifier", "")
            if not re.fullmatch(r"[0-9][A-Za-z0-9-]*", section) or native_id != f"/us/usc/t{title}/s{section}":
                raise CorpusError("source_section_identity_mismatch")
            status = child.get("status", "")
            # Retain non-operative sections in the raw snapshot.
            if status:
                continue
            body = " ".join(filter(None, (text_of(node) for node in child if node.tag in {
                USLM + name for name in ("content", "subsection", "paragraph", "chapeau", "continuation")
            })))
            if not body:
                continue
            citation = f"{title} U.S.C. § {section}"
            version = AuthorityVersion(
                jurisdiction="US", sovereign="federal", authority_type="statute",
                identity_namespace="usc", identity_key=f"{title}/{section}", citation=citation,
                alternate_citations=(f"{title} USC {section}", f"{title} U.S.C. {section}"),
                title=text_of(child.find(USLM + "heading")) or citation, edition=f"PL {release}",
                text=body, hierarchy=hierarchy, legislature="U.S. Congress",
                limitations=("Release-point text. Effective dates and subsequent legislative changes unresolved.",),
            )
            yield Observation(version, native_id, f"{member}#{native_id}", text_of(number))


class GovInfoCFRProvider(PublicProvider):
    source = Source(
        name="govinfo_cfr", host="www.govinfo.gov", authority_type="regulation", jurisdictions=("US",),
        official_publisher=True, rendition="GovInfo annual CFR XML rendition",
        endpoint="/content/pkg/{package}/xml/{package}.xml",
        format="CFR annual volume XML", update="explicit annual edition and volume",
        rights="Federal regulatory text. Publisher graphics and annotations remain in the original artifact.",
        attribution="U.S. Government Publishing Office and Office of the Federal Register",
        currentness_method="Checks the catalog year and embedded revision date. Annual editions are historical snapshots.",
        parser_revision="1",
    )

    def _selection(self, selector):
        match = re.fullmatch(r"(19[9][6-9]|20[0-9]{2})/([1-9]|[1-4][0-9]|50)/([1-9][0-9]?)", selector)
        if not match:
            raise CorpusError("invalid_cfr_selector")
        return match.groups()

    def source_url(self, selector):
        year, title, volume = self._selection(selector)
        path = self.source.endpoint.format(package=f"CFR-{year}-title{title}-vol{volume}")
        return f"https://{self.source.host}{path}"

    def normalize(self, selector, raw):
        year, title, _ = self._selection(selector)
        root = xml_root(raw)
        page = root.find("./FMTR/TITLEPG")
        if root.tag != "CFRDOC" or page is None or text_of(page.find("TITLENUM")) != f"Title {title}":
            raise CorpusError("source_title_identity_mismatch")
        revised = text_of(page.find("REVISED")).removeprefix("Revised as of ")
        try:
            revision = datetime.strptime(revised, "%B %d, %Y").date()
        except ValueError:
            raise CorpusError("source_edition_identity_mismatch") from None
        if str(revision.year) != year:
            raise CorpusError("source_edition_identity_mismatch")
        for part in root.iter("PART"):
            part_number = re.fullmatch(r"Pt\. ([0-9]+[a-zA-Z]?)", text_of(part.find("EAR")))
            for child in self._operative_sections(part):
                original = text_of(child.find("SECTNO"))
                heading = text_of(child.find("SUBJECT"))
                if child.find("RESERVED") is not None or heading.casefold() == "[reserved]":
                    continue
                section = re.fullmatch(r"§\s*([0-9]+[A-Za-z]?\.[0-9][A-Za-z0-9-]*)", original)
                if not section or not part_number or section[1].split(".")[0] != part_number[1]:
                    raise CorpusError("source_section_identity_mismatch")
                body = " ".join(filter(None, (text_of(node) for node in child if node.tag in {
                    "P", "FP", "EXTRACT", "EXAMPLE", "GPOTABLE",
                })))
                if not body:
                    continue
                citation = f"{title} CFR {section[1]}"
                version = AuthorityVersion(
                    jurisdiction="US", sovereign="federal", authority_type="regulation",
                    identity_namespace="cfr", identity_key=f"{title}/{section[1]}",
                    citation=citation, alternate_citations=(f"{title} C.F.R. § {section[1]}",),
                    title=heading or citation, edition=revision.isoformat(), text=body,
                    hierarchy=(f"{title} CFR", f"{title} CFR part {part_number[1]}"), currentness="historical",
                    limitations=("Annual-edition text. Revision date does not establish section-level effective dates.",),
                )
                yield Observation(version, f"{title}/{section[1]}", f"PART {part_number[1]} / SECTION {section[1]}", original)

    def _operative_sections(self, element, depth=0):
        if depth > 8:
            raise CorpusError("source_hierarchy_limit")
        for child in element:
            if child.tag == "SECTION":
                yield child
            elif child.tag == "SUBPART":
                yield from self._operative_sections(child, depth + 1)


class VirginiaSectionParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.article = False
        self.heading = False
        self.body_depth = 0
        self.body_closed = False
        self.excluded = 0
        self.headings = 0
        self.heading_text = []
        self.body_text = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "article" and attributes.get("id") == "vacode":
            self.article = True
        if not self.article:
            return
        if tag in {"script", "style", "template", "iframe"}:
            self.excluded += 1
        if self.excluded:
            return
        if tag == "h2" and not self.body_depth:
            self.heading = True
            self.headings += 1
        if tag == "section":
            if self.body_depth:
                self.body_depth += 1
            elif attributes.get("data-table") == "CoV" and attributes.get("data-field") == "body":
                if self.body_closed:
                    raise CorpusError("duplicate_statutory_body")
                self.body_depth = 1
        if self.body_depth and tag in {"p", "li", "br", "div", "tr", "td"}:
            self.body_text.append(" ")

    def handle_endtag(self, tag):
        if tag in {"script", "style", "template", "iframe"} and self.excluded:
            self.excluded -= 1
            return
        if self.excluded:
            return
        if tag == "article":
            self.article = False
        if tag == "h2":
            self.heading = False
        if tag == "section" and self.body_depth:
            self.body_depth -= 1
            self.body_closed = not self.body_depth
        if self.body_depth and tag in {"p", "li", "div", "tr", "td"}:
            self.body_text.append(" ")

    def handle_data(self, data):
        if not self.article or self.excluded:
            return
        if self.heading:
            self.heading_text.append(data)
        if self.body_depth:
            self.body_text.append(data)


class VirginiaCodeProvider(PublicProvider):
    source = Source(
        name="virginia_code", host="law.lis.virginia.gov", authority_type="statute", jurisdictions=("US-VA",),
        official_publisher=True, rendition="Virginia General Assembly online Code of Virginia",
        endpoint="/vacode/title{title}/chapter{chapter}/section{section}/",
        format="single official section HTML page", update="explicit chapter and section refresh",
        rights="Virginia statutory text. The official website excludes licensed publisher annotations.",
        attribution="Virginia General Assembly, Division of Legislative Automated Systems",
        currentness_method="Checks the section heading against the requested citation. Effective dates and later changes unresolved.",
        parser_revision="1", max_bytes=1024 * 1024,
    )

    def _selection(self, selector):
        match = re.fullmatch(r"([0-9]{1,2}(?:\.[0-9]{1,2})?)/([0-9]{1,3}(?:\.[0-9]{1,3})?)/([0-9.]{1,5}-[0-9]{1,4}(?:\.[0-9]{1,3})?)", selector)
        if not match or match[3].split("-")[0] != match[1]:
            raise CorpusError("invalid_virginia_code_selector")
        return match.groups()

    def source_url(self, selector):
        title, chapter, section = self._selection(selector)
        path = self.source.endpoint.format(title=title, chapter=chapter, section=section)
        return f"https://{self.source.host}{path}"

    def normalize(self, selector, raw):
        title, chapter, section = self._selection(selector)
        parser = VirginiaSectionParser()
        try:
            parser.feed(raw.decode("utf-8-sig"))
            parser.close()
        except UnicodeError:
            raise CorpusError("source_html_encoding_invalid") from None
        heading = normalized_source("".join(parser.heading_text))
        prefix = f"§ {section}. "
        if parser.headings != 1 or not heading.startswith(prefix) or not parser.body_closed:
            raise CorpusError("source_section_identity_mismatch")
        body = normalized_source("".join(parser.body_text))
        if not body or heading.removeprefix(prefix).casefold().startswith(("repealed", "reserved", "expired")):
            raise CorpusError("source_statutory_text_unavailable")
        citation = f"Va. Code § {section}"
        version = AuthorityVersion(
            jurisdiction="US-VA", sovereign="state", authority_type="statute",
            identity_namespace="va_code", identity_key=section, citation=citation,
            alternate_citations=(f"Va. Code Ann. § {section}",),
            title=heading.removeprefix(prefix), edition="online codification",
            text=body, hierarchy=(f"Title {title}", f"Chapter {chapter}"),
            legislature="Virginia General Assembly",
            limitations=("Effective dates and subsequent legislative changes unresolved.",),
        )
        yield Observation(version, section, "article#vacode section[data-table=CoV][data-field=body]", f"§ {section}")


PROVIDERS = MappingProxyType({
    provider.source.name: provider for provider in (
        OLRCProvider(), GovInfoCFRProvider(), CourtListenerProvider(), VirginiaCodeProvider(),
    )
})
