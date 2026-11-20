"""Replay dated publisher evidence against retained official publications."""
from datetime import date, datetime
from functools import lru_cache
import gzip
from hashlib import sha256
from html.parser import HTMLParser
from io import BytesIO
from itertools import takewhile
import json
import re
from urllib.parse import urlsplit

from app.jurisdictions import ROOT


CERTIFIED_TYPES = {"US-WI": "statute", "US-MI": "court_rule", "US-IN": "court_rule", "US-DE": "court_rule"}
INDIANA_RULES_ROOT = "https://rules.incourts.gov/Content/"
INDIANA_RULESETS = {"trial": "Indiana Rules of Trial Procedure", "small-claims": "Indiana Small Claims Rules"}
MICHIGAN_RULES_BOOK = (
    "https://www.courts.michigan.gov/siteassets/rules-instructions-administrative-orders/"
    "michigan-court-rules/michigan-court-rules-responsive-html5.zip/Michigan_Court_Rules/"
)
DELAWARE_COMMON_PLEAS_PATH = "/forms/download.aspx?id=176248"
DELAWARE_COMMON_PLEAS_DIGEST = "89f788cd80dae047959e9cc98e2a6fdf83c4ec7d51fc339198f9c2fd7f1fad7e"
DELAWARE_COMMON_PLEAS_RULES = {
    "3(a)": (0, "Rule 3. Commencement of action.", "(a) Complaint and praecipe.", "(b) Omitted."),
    "4(a)": (1, "Rule 4. Process.", "(a) Issuance of writs.", "(b)"),
    "6(a)": (8, "Rule 6. Time.", "(a) Computation.", "(b)"),
    "8(a)": (9, "Rule 8. General rules of pleading.", "(a) Claims for relief.", "(b)"),
    "8(b)": (9, "Rule 8. General rules of pleading.", "(b) Defense; form of denials.", "(c)"),
    "12(a)": (12, "Rule 12. Defenses and objections", "(a) Time.", "(b)"),
}
DELAWARE_PDF_SPACING = {
    " t herein": " therein", " especia lly": " especially", " w hich": " which",
    " th e Court": " the Court", " relief ,": " relief,", " third -party": " third-party",
    " deni ed": " denied", " th e averments": " the averments", " ord er": " order",
    " tri al": " trial", " cross -claim": " cross-claim", " a ffidavit": " affidavit",
}


@lru_cache(maxsize=16)
def retained_publication(digest):
    return retained_publisher_bytes(digest, "html").decode("utf-8-sig")


def retained_publisher_bytes(digest, extension):
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("invalid_certified_publication")
    raw = gzip.decompress((ROOT / "certified" / f"{digest}.{extension}.gz").read_bytes())
    if sha256(raw).hexdigest() != digest:
        raise ValueError("certified_publisher_hash_mismatch")
    return raw


class PublicationText(HTMLParser):
    def __init__(self, path):
        super().__init__()
        self.path = path
        self.blocks = 0
        self.active_tag = None
        self.depth = 0
        self.block = []
        self.page = []
        self.citations = []
        self.has_effective_date_note = False

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        element_path = attributes.get("data-path", "")
        note_parent = element_path.rpartition("/_")[0]
        if (note_parent and "qsnote_note" in (attributes.get("class") or "").split()
                and (self.path == note_parent or self.path.startswith(note_parent + "/"))
                and attributes.get("data-section")):
            self.has_effective_date_note = True
        if self.active_tag == tag:
            self.depth += 1
        if element_path == self.path:
            self.blocks += 1
            self.active_tag = tag
            self.depth = 1
            self.citations = json.loads(attributes.get("data-cites", "[]"))

    def handle_endtag(self, tag):
        if tag == self.active_tag:
            self.depth -= 1
            if self.depth == 0:
                self.active_tag = None

    def handle_data(self, data):
        self.page.append(data)
        if self.active_tag:
            self.block.append(data)


class CourtRuleParagraphs(HTMLParser):
    def __init__(self):
        super().__init__()
        self.active = None
        self.rows = []

    def handle_starttag(self, tag, attrs):
        if tag == "p":
            attributes = dict(attrs)
            self.active = (attributes.get("id"), attributes.get("class", "").split(), [])

    def handle_data(self, data):
        if self.active:
            self.active[2].append(data)

    def handle_endtag(self, tag):
        if tag == "p" and self.active:
            anchor, classes, parts = self.active
            text = " ".join("".join(parts).replace("\u200b", " ").split())
            self.rows.append((anchor, classes, text))
            self.active = None


@lru_cache(maxsize=4)
def michigan_civil_rules(digest):
    parser = CourtRuleParagraphs()
    parser.feed(retained_publication(digest))
    parser.close()
    return parser.rows


def michigan_basis(url, digest, anchor, citation, quote):
    matched = re.fullmatch(r"MCR (([24])\.\d{3})\(([A-Z])\)", citation)
    if not matched or not re.fullmatch(r"\d+", anchor):
        raise ValueError("invalid_certified_publication")
    rule, chapter, subsection = matched.groups()
    chapter_name = f"Court_Rules_Chapter_{chapter}"
    if url != f"{MICHIGAN_RULES_BOOK}{chapter_name}/{chapter_name}.htm":
        raise ValueError("invalid_certified_publication")
    rows = michigan_civil_rules(digest)
    dates = [text for _, classes, text in rows if "MainDate" in classes]
    headings = [index for index, (_, classes, text) in enumerate(rows)
                if "Rule_Heading" in classes and text.startswith(f"Rule {rule} ")]
    if len(dates) != 1 or len(headings) != 1:
        raise ValueError("certified_excerpt_or_date_mismatch")
    edition = "Chapter Updated with MSC Order(s) Effective on "
    if not dates[0].startswith(edition):
        raise ValueError("certified_excerpt_or_date_mismatch")
    day = datetime.strptime(dates[0].removeprefix(edition), "%B %d, %Y").date()
    rule_rows = list(takewhile(lambda row: "Rule_Heading" not in row[1], rows[headings[0] + 1:]))
    targets = [index for index, (node, classes, text) in enumerate(rule_rows)
               if node == anchor and any(kind.startswith("L1_") for kind in classes)
               and text.startswith(f"({subsection}) ")]
    if len(targets) != 1:
        raise ValueError("certified_excerpt_or_date_mismatch")
    target = targets[0]
    excerpt = [rule_rows[target]]
    excerpt.extend(takewhile(lambda row: not any(kind.startswith("L1_") for kind in row[1]),
                            rule_rows[target + 1:]))
    rule_text = " ".join(text for _, _, text in rule_rows)
    effective_dates = re.findall(r"\b(?:effective|takes effect)(?: on)? ([A-Z][a-z]+ \d{1,2}, \d{4})\b",
                                 rule_text, re.IGNORECASE)
    if (re.search(r"\b(?:future[- ]effective|proposed amendment)\b", rule_text, re.IGNORECASE)
            or any(datetime.strptime(label, "%B %d, %Y").date() > day for label in effective_dates)):
        raise ValueError("certified_version_requires_effective_date_review")
    if not quote or quote != " ".join(text for _, _, text in excerpt if text):
        raise ValueError("certified_excerpt_or_date_mismatch")
    return day, f"Michigan Supreme Court Rules Chapter {chapter}. " + dates[0]


class IndianaRulePublication(HTMLParser):
    """Read the version marker and paragraphs within the publisher's main content."""

    def __init__(self):
        super().__init__()
        self.main_depth = 0
        self.active = None
        self.rows = []
        self.current_marker = False
        self.current_rule_links = set()

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "div":
            if attrs.get("id") == "mc-main-content" or self.main_depth:
                self.main_depth += 1
        if not self.main_depth:
            return
        if tag in {"p", "h1", "h2"}:
            self.active = tag, (attrs.get("class") or "").split(), []
        if tag == "a" and re.fullmatch(r"rule[0-9-]+/current\.htm", attrs.get("href") or ""):
            self.current_rule_links.add(attrs["href"])
        if tag == "madcap:concept" and attrs.get("term") == "Current":
            self.current_marker = True

    def handle_endtag(self, tag):
        if self.active and self.active[0] == tag:
            name, classes, parts = self.active
            self.rows.append((name, classes, " ".join("".join(parts).split())))
            self.active = None
        if tag == "div" and self.main_depth:
            self.main_depth -= 1

    def handle_data(self, data):
        if self.active:
            self.active[2].append(data)


@lru_cache(maxsize=12)
def indiana_rule_publication(digest):
    page = IndianaRulePublication()
    page.feed(retained_publication(digest))
    page.close()
    return page


def indiana_basis(url, digest, path, citation, quote):
    match = re.fullmatch(r"Ind\. (Trial|Small Claims) (?:R\.|Rule) (\d+(?:\.\d+)?)(?:\(([A-Z])\))?", citation)
    if not match or not re.fullmatch(r"[0-9a-f]{64}", path):
        raise ValueError("invalid_certified_publication")
    kind, rule, subsection = match.groups()
    ruleset = "trial" if kind == "Trial" else "small-claims"
    relative = f"rule{rule.replace('.', '-')}/current.htm"
    if url != INDIANA_RULES_ROOT + ruleset + "/" + relative:
        raise ValueError("invalid_certified_publication")
    index = indiana_rule_publication(path)
    page = indiana_rule_publication(digest)
    heading = INDIANA_RULESETS[ruleset]
    dates = [m.group(1) for _, classes, text in index.rows if "rulenote" in classes
             for m in re.finditer(r"Updated, Effective ([A-Z][a-z]+ \d{1,2}, \d{4})", text)]
    rule_dates = [text.removeprefix("Effective ") for _, classes, text in page.rows
                  if "effective" in classes and text.startswith("Effective ")]
    titles = [text for tag, _, text in page.rows if tag == "h1" and text.startswith(f"Rule {rule}. ")]
    if (relative not in index.current_rule_links or not page.current_marker or len(titles) != 1
            or len(dates) != 1 or len(rule_dates) != 1
            or not any(tag == "h1" and text == heading for tag, _, text in index.rows)
            or not any("ruleset" in classes and text == heading for _, classes, text in page.rows)):
        raise ValueError("certified_excerpt_or_date_mismatch")
    day = datetime.strptime(dates[0], "%B %d, %Y").date()
    if datetime.strptime(rule_dates[0], "%B %d, %Y").date() > day:
        raise ValueError("certified_version_requires_effective_date_review")
    body_start = next(i for i, (_, classes, _) in enumerate(page.rows) if "effective" in classes)
    rows = list(takewhile(lambda row: row[2] != "Version History", page.rows[body_start + 1:]))
    headings = [i for i, (tag, _, text) in enumerate(rows) if tag == "h2" and text.startswith(f"({subsection}) ")]
    section_heading = ""
    if subsection and len(headings) == 1:
        start = headings[0]
        section_heading = rows[start][2] + " "
        rows = list(takewhile(lambda row: row[0] != "h2", rows[start + 1:]))
    elif subsection or any(tag == "h2" for tag, _, _ in rows):
        raise ValueError("certified_excerpt_or_date_mismatch")
    body = " ".join(text for _, _, text in rows if text)
    if not body or quote not in (body, section_heading + body):
        raise ValueError("certified_excerpt_or_date_mismatch")
    return day, f"{heading}. Updated, Effective {dates[0]}."


@lru_cache(maxsize=2)
def delaware_common_pleas_pages(digest):
    from pypdf import PdfReader

    if digest != DELAWARE_COMMON_PLEAS_DIGEST:
        raise ValueError("invalid_certified_publication")
    raw = retained_publisher_bytes(digest, "pdf")
    # The original has a complete PDF followed by an empty incremental xref
    # whose terminator is malformed. Parse the complete revision only.
    body, marker, tail = raw.rpartition(b"%%EOF")
    if not marker or not tail.startswith(b"\r\nxref\r\n0 0\r\ntrailer\r\n"):
        raise ValueError("certified_excerpt_or_date_mismatch")
    pages = PdfReader(BytesIO(body + marker), strict=True).pages
    if len(pages) != 68:
        raise ValueError("certified_excerpt_or_date_mismatch")
    text = {page: " ".join(pages[page].extract_text().split())
            for page, *_ in DELAWARE_COMMON_PLEAS_RULES.values()}
    if not text[0].startswith("Civil Rules Governing the Court of Common Pleas "):
        raise ValueError("certified_excerpt_or_date_mismatch")
    return text


def delaware_common_pleas_basis(url, digest, path, citation, quote):
    spec = DELAWARE_COMMON_PLEAS_RULES.get(citation.removeprefix("Del. Ct. Com. Pl. Civ. R. "))
    if (not citation.startswith("Del. Ct. Com. Pl. Civ. R. ") or not spec
            or url != "https://courts.delaware.gov" + DELAWARE_COMMON_PLEAS_PATH):
        raise ValueError("invalid_certified_publication")
    title = "Court of Common Pleas Civil Rules"
    edition = re.findall(
        rf'<h3>\s*<a href="{re.escape(DELAWARE_COMMON_PLEAS_PATH)}">{title}[^<]*'
        r'(?:<i[^>]*></i>)?</a>\*?\s*<span class="badge">Current as of (January 10, 2023)</span></h3>',
        retained_publication(path),
    )
    page, rule, first, following = spec
    text = delaware_common_pleas_pages(digest)[page]
    if len(edition) != 1 or text.count(rule) != 1:
        raise ValueError("certified_excerpt_or_date_mismatch")
    content = text.split(rule, 1)[1].partition(following)
    section = content[0].partition(first)
    expected = (section[1] + section[2]).strip()
    for split_word, printed_word in DELAWARE_PDF_SPACING.items():
        expected = expected.replace(split_word, printed_word)
    if not section[1] or not content[1] or quote != expected:
        raise ValueError("certified_excerpt_or_date_mismatch")
    return date(2023, 1, 10), f"{title}. Current as of {edition[0]}."


@lru_cache(maxsize=96)
def certified_basis(scope, url, digest, path, citation, quote):
    if scope == "US-MI":
        return michigan_basis(url, digest, path, citation, quote)
    if scope == "US-IN":
        return indiana_basis(url, digest, path, citation, quote)
    if scope == "US-DE":
        return delaware_common_pleas_basis(url, digest, path, citation, quote)
    endpoint = urlsplit(url)
    if (scope != "US-WI" or endpoint.scheme != "https" or endpoint.netloc != "docs.legis.wisconsin.gov"
            or not citation.startswith("Wis. Stat. § ") or not path.startswith(endpoint.path + "/")):
        raise ValueError("invalid_certified_publication")
    parser = PublicationText(path)
    parser.feed(retained_publication(digest))
    parser.close()
    if parser.has_effective_date_note:
        raise ValueError("certified_version_requires_effective_date_review")
    page = " ".join("".join(parser.page).split())
    certificate = re.search(
        r"2023-24 Wisconsin Statutes updated through 2025 Wis\. Act 247 and through all Supreme Court Orders "
        r"and Controlled Substances Board Orders filed before and in effect on November 4, 2026\. "
        r"Published and certified under s\. 35\.18\. Changes effective after November 4, 2026, "
        r"are designated by NOTES\. \(Published 11-4-26\)", page)
    expected = "statutes/" + citation.removeprefix("Wis. Stat. § ")
    if (parser.blocks != 1 or expected not in parser.citations or not quote
            or quote not in " ".join("".join(parser.block).split()) or not certificate):
        raise ValueError("certified_excerpt_or_date_mismatch")
    return date(2026, 11, 4), certificate.group()
