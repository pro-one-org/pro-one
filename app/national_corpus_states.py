"""Bounded adapters for state legislature and judiciary publications."""

from dataclasses import dataclass, field
from datetime import date, datetime
from html.parser import HTMLParser
import re
from urllib.parse import urlencode

from app.national_corpus import AuthorityVersion, CorpusError, Observation, Source, SourceRelationship
from app.national_corpus_transport import PublicProvider


@dataclass
class Element:
    tag: str
    attrs: dict
    children: list = field(default_factory=list)

    def find(self, *, tag="", css="", **attrs):
        for item in self.children:
            if isinstance(item, Element):
                if ((not tag or tag == item.tag) and (not css or css in item.attrs.get("class", "").split())
                        and all(item.attrs.get(key) == value for key, value in attrs.items())):
                    yield item
                yield from item.find(tag=tag, css=css, **attrs)

    def one(self, **criteria):
        matches = list(self.find(**criteria))
        if len(matches) != 1:
            raise CorpusError("source_html_scope_mismatch")
        return matches[0]

    def fragments(self):
        if self.tag in {"script", "style", "template", "iframe", "button"}:
            return
        block = self.tag in {"br", "div", "p", "li", "tr", "td", "section", "h2", "h3", "h4"}
        if block:
            yield "\n"
        for item in self.children:
            if isinstance(item, Element):
                yield from item.fragments()
            else:
                yield item
        if block:
            yield "\n"

    def text(self):
        return " ".join("".join(self.fragments()).split())


class StateHTML(HTMLParser):
    void = frozenset("area base br col embed hr img input link meta param source track wbr".split())

    def __init__(self, raw):
        super().__init__(convert_charrefs=True)
        self.root = Element("", {})
        self.stack = [self.root]
        try:
            self.feed(raw.decode("utf-8-sig"))
            self.close()
        except UnicodeError:
            raise CorpusError("source_html_encoding_invalid") from None

    def handle_starttag(self, tag, attrs):
        if len(self.stack) > 128:
            raise CorpusError("source_html_depth_limit")
        if tag in {"option", "li", "p", "td", "tr"} and self.stack[-1].tag == tag:
            self.stack.pop()
        node = Element(tag, {key: value or "" for key, value in attrs})
        self.stack[-1].children.append(node)
        if tag not in self.void:
            self.stack.append(node)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.void:
            self.handle_endtag(tag)

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def selector_match(pattern, selector):
    match = re.fullmatch(pattern, selector)
    if not match:
        raise CorpusError("invalid_state_selector")
    return match.groups()


def official_source(name, host, jurisdiction, family, publisher, endpoint, edition, rights):
    return Source(
        name=name, host=host, jurisdictions=(jurisdiction,), authority_type=family,
        official_publisher=True, rendition=f"{publisher} public publication", endpoint=endpoint,
        format="scoped HTML", update=edition, rights=rights, attribution=publisher,
        currentness_method="Checks publisher identity and available edition markers. Operative currentness remains unresolved.",
        parser_revision="1", max_bytes=2 * 1024 * 1024,
    )


def state_observation(source, native, title, citation, original, edition, body, hierarchy, locator, **metadata):
    if not body or re.match(r"^\[?(repealed|reserved|expired)\b", body, re.I):
        raise CorpusError("source_operative_text_unavailable")
    version = AuthorityVersion(
        jurisdiction=source.jurisdictions[0], sovereign="state", authority_type=source.authority_type,
        identity_namespace=source.name, identity_key=native, title=title, citation=citation,
        edition=edition, text=body, hierarchy=hierarchy, institution=source.attribution,
        limitations=("Publisher text. Operative currentness requires additional evidence.",), **metadata,
    )
    edges = tuple(SourceRelationship("part_of", parent) for parent in hierarchy)
    return Observation(version, native, locator, original, edges)


class MarylandProvider(PublicProvider):
    articles = {"grp": "Real Property", "c0": "Declaration of Rights"}
    path = "/mgawebsite/Laws/StatuteText"

    def __init__(self, constitutional=False):
        self.constitutional = constitutional
        self.source = official_source(
            "maryland_constitution" if constitutional else "maryland_code",
            "mgaleg.maryland.gov", "US-MD", "constitution" if constitutional else "statute",
            "Maryland General Assembly", self.path, "January rendition (enactments=false)",
            "Publisher codification or constitutional text. Publisher notes retained in source artifact.",
        )

    def _selection(self, selector):
        return selector_match(r"(c0)/([1-9][0-9]{0,2})" if self.constitutional else
                              r"(grp)/([1-9][0-9]?-[0-9]{1,4}(?:\.[0-9]{1,3})?)", selector)

    def source_url(self, selector):
        article, section = self._selection(selector)
        query = urlencode({"article": article, "section": section, "enactments": "false"})
        return f"https://{self.source.host}{self.path}?{query}"

    def normalize(self, selector, raw):
        article, section = self._selection(selector)
        box = StateHTML(raw).root.one(id="StatuteText")
        lines = [" ".join(line.split()) for line in "".join(box.fragments()).splitlines() if line.strip()]
        if len(lines) < 3 or lines[0] != f"Article - {self.articles[article]}":
            raise CorpusError("source_article_identity_mismatch")
        if lines[1].replace("–", "-").replace(" ", "") != f"§{section}.":
            raise CorpusError("source_section_identity_mismatch")
        citation = f"Md. Decl. of Rts. art. {section}" if self.constitutional else f"Md. Code, Real Prop. § {section}"
        yield state_observation(self.source, selector, citation, citation, lines[1],
                                "January online rendition", "\n".join(lines[2:]),
                                (self.articles[article],), "#StatuteText",
                                legislature="Maryland General Assembly")


class NewYorkProvider(PublicProvider):
    def __init__(self, constitutional=False):
        self.constitutional = constitutional
        self.source = official_source(
            "new_york_constitution" if constitutional else "new_york_code",
            "www.nysenate.gov", "US-NY", "constitution" if constitutional else "statute",
            "New York State Senate", "/legislation/laws/{law}/{section}", "Publisher revision marker",
            "Senate Open Legislation publishes CC BY-NC-ND 3.0 terms for site content. Local capture of legal text only.",
        )

    def _selection(self, selector):
        return selector_match(r"(CNS)/(A1S[1-9][0-9]?)" if self.constitutional else
                              r"(RPP)/([1-9][0-9]{0,3}(?:-[A-Z]{1,2})?)", selector)

    def source_url(self, selector):
        law, section = self._selection(selector)
        return f"https://{self.source.host}/legislation/laws/{law}/{section}"

    def normalize(self, selector, raw):
        law, section = self._selection(selector)
        root = StateHTML(raw).root
        number = section.split("S")[1] if self.constitutional else section
        title = root.one(css="nys-openleg-result-title-short").text()
        heading = root.one(css="nys-openleg-result-title-headline").text()
        location = root.one(css="nys-openleg-result-title-location").text()
        body = root.one(css="nys-openleg-result-text").text()
        revision = root.one(css="nys-openleg-history-published").text()
        version = re.fullmatch(r"Viewing most recent revision \(from (\d{4}-\d{2}-\d{2})\)", revision)
        if (heading != f"SECTION {number}" or not re.match(rf"§\s*{re.escape(number)}\.", body, re.I)
                or f"({law})" not in location or not version):
            raise CorpusError("source_section_identity_mismatch")
        try:
            edition = date.fromisoformat(version[1]).isoformat()
        except ValueError:
            raise CorpusError("source_edition_identity_mismatch") from None
        if self.constitutional:
            if not location.endswith(", ARTICLE I"):
                raise CorpusError("source_article_identity_mismatch")
            citation = f"N.Y. Const. art. I, § {number}"
        else:
            citation = f"N.Y. Real Prop. Law § {section.lower()}"
        yield state_observation(self.source, selector, title, citation, heading, edition, body,
                                (location,), ".nys-openleg-result-text", legislature="New York State Legislature")


class FloridaProvider(PublicProvider):
    def __init__(self, constitutional=False):
        self.constitutional = constitutional
        self.source = official_source(
            "florida_constitution" if constitutional else "florida_code",
            "www.leg.state.fl.us", "US-FL", "constitution" if constitutional else "statute",
            "Florida Legislature", "/Statutes/index.cfm", "Online Sunshine publisher edition",
            "Florida statutory and constitutional text. Publisher artwork and notes remain in source artifact.",
        )

    def source_url(self, selector):
        if self.constitutional:
            if selector != "article-I":
                raise CorpusError("invalid_state_selector")
            return f"https://{self.source.host}/statutes/index.cfm?submenu=3"
        chapter, section = selector_match(r"([1-9][0-9]{0,3})\.([0-9]{2,4})", selector)
        bucket = int(chapter) // 100 * 100
        target = f"{bucket:04d}-{bucket + 99:04d}/{int(chapter):04d}/Sections/{int(chapter):04d}.{section}.html"
        return f"https://{self.source.host}/Statutes/index.cfm?App_mode=Display_Statute&URL={target}"

    def normalize(self, selector, raw):
        self.source_url(selector)
        root = StateHTML(raw).root
        if self.constitutional:
            constitution = root.one(css="Constitution")
            for section in constitution.find(css="Section"):
                number = section.one(css="SectionNumber")
                anchors = list(number.find(tag="a"))
                if len(anchors) != 1:
                    continue
                native = anchors[0].attrs.get("name", "")
                match = re.fullmatch(r"A1S([0-9]{2})", native)
                if not match:
                    continue
                original = number.text()
                if original != f"SECTION {int(match[1])}.":
                    raise CorpusError("source_section_identity_mismatch")
                citation = f"Fla. Const. art. I, § {int(match[1])}"
                yield state_observation(
                    self.source, native, section.one(css="CatchlineText").text(), citation, original,
                    "1968 constitution as amended, online", section.one(css="SectionBody").text(),
                    ("Article I",), f"a[name={native}] / .SectionBody",
                )
            return
        headings = [node.text() for node in root.find(tag="h2")]
        years = [match[1] for value in headings if (match := re.fullmatch(r"The (\d{4}) Florida Statutes", value))]
        if len(years) != 1:
            raise CorpusError("source_edition_identity_mismatch")
        section = root.one(id="statutes").one(css="Section")
        original = section.one(css="SectionNumber").text()
        if original != selector:
            raise CorpusError("source_section_identity_mismatch")
        yield state_observation(
            self.source, selector, section.one(css="CatchlineText").text(), f"Fla. Stat. § {selector}", original,
            years[0], section.one(css="SectionBody").text(), (f"Chapter {selector.split('.')[0]}",),
            "#statutes .SectionBody", legislature="Florida Legislature",
        )


class CaliforniaCourtRules(PublicProvider):
    source = official_source(
        "california_court_rules", "courts.ca.gov", "US-CA", "court_rule",
        "Judicial Branch of California", "/cms/rules/index/eight/rule8_{number}", "Publisher edition heading",
        "California Rules of Court. Advisory commentary is retained in the source artifact.",
    )

    def source_url(self, selector):
        (number,) = selector_match(r"8\.([1-9][0-9]{0,3})", selector)
        return f"https://{self.source.host}/cms/rules/index/eight/rule8_{number}"

    def normalize(self, selector, raw):
        self.source_url(selector)
        root = StateHTML(raw).root
        title = root.one(css="hangover__title").text()
        edition = root.one(css="brow__secondary").text()
        if not title.startswith(f"Rule {selector}. ") or not re.fullmatch(r"20[0-9]{2}", edition):
            raise CorpusError("source_rule_identity_mismatch")
        paragraphs = []
        amended = None
        for item in root.one(tag="article").find(tag="p"):
            classes = item.attrs.get("class", "").split()
            if "rulehist" in classes:
                history = re.match(rf"Rule {re.escape(selector)} amended effective ([A-Z][a-z]+ \d{{1,2}}, \d{{4}})", item.text())
                if history:
                    amended = datetime.strptime(history[1], "%B %d, %Y").date()
                break
            if set(classes) & {"subdivheading", "subdivtext", "paragraphlist", "paragraphnolist"}:
                paragraphs.append(item.text())
        yield state_observation(
            self.source, selector, title, f"Cal. Rules of Court, rule {selector}", title,
            edition, "\n".join(paragraphs), ("Title 8",), "article / operative rule paragraphs",
            effective_from=amended,
        )
