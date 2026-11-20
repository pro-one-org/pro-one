"""Replay dated publisher evidence against retained official publications."""
from datetime import date, datetime
from functools import lru_cache
import gzip
from hashlib import sha256
from html.parser import HTMLParser
from itertools import takewhile
import json
import re
from urllib.parse import urlsplit

from app.jurisdictions import ROOT


CERTIFIED_TYPES = {"US-WI": "statute", "US-MI": "court_rule"}
MICHIGAN_RULES_BOOK = (
    "https://www.courts.michigan.gov/siteassets/rules-instructions-administrative-orders/"
    "michigan-court-rules/michigan-court-rules-responsive-html5.zip/Michigan_Court_Rules/"
)


@lru_cache(maxsize=16)
def retained_publication(digest):
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("invalid_certified_publication")
    raw = gzip.decompress((ROOT / "certified" / (digest + ".html.gz")).read_bytes())
    if sha256(raw).hexdigest() != digest:
        raise ValueError("certified_publisher_hash_mismatch")
    return raw.decode("utf-8-sig")


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


@lru_cache(maxsize=64)
def certified_basis(scope, url, digest, path, citation, quote):
    if scope == "US-MI":
        return michigan_basis(url, digest, path, citation, quote)
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
