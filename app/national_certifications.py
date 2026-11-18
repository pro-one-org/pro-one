"""Replay Wisconsin's dated legislative certification against the retained publication."""
from datetime import date
from functools import lru_cache
import gzip
from hashlib import sha256
from html.parser import HTMLParser
import json
import re
from urllib.parse import urlsplit

from app.jurisdictions import ROOT


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

    def handle_starttag(self, tag, attrs):
        if self.active_tag == tag:
            self.depth += 1
        if dict(attrs).get("data-path") == self.path:
            self.blocks += 1
            self.active_tag = tag
            self.depth = 1
            self.citations = json.loads(dict(attrs).get("data-cites", "[]"))

    def handle_endtag(self, tag):
        if tag == self.active_tag:
            self.depth -= 1
            if self.depth == 0:
                self.active_tag = None

    def handle_data(self, data):
        self.page.append(data)
        if self.active_tag:
            self.block.append(data)


@lru_cache(maxsize=64)
def certified_basis(scope, url, digest, path, citation, quote):
    endpoint = urlsplit(url)
    if (scope != "US-WI" or endpoint.scheme != "https" or endpoint.netloc != "docs.legis.wisconsin.gov"
            or not citation.startswith("Wis. Stat. § ") or not path.startswith(endpoint.path + "/")
            or not re.fullmatch(r"[0-9a-f]{64}", digest)):
        raise ValueError("invalid_certified_publication")
    raw = gzip.decompress((ROOT / "certified" / (digest + ".html.gz")).read_bytes())
    if sha256(raw).hexdigest() != digest:
        raise ValueError("certified_publisher_hash_mismatch")
    parser = PublicationText(path)
    parser.feed(raw.decode("utf-8-sig"))
    parser.close()
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
