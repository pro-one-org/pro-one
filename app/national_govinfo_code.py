"""Pinned U.S. Code granules published by GPO, including the statutory field only."""
from functools import lru_cache
from html.parser import HTMLParser
import json
import re

from app.jurisdictions import ROOT
from app.national_corpus import AuthorityVersion, CorpusError, Observation, Source, fingerprint
from app.national_corpus_transport import PublicProvider


class StatuteField(HTMLParser):
    def __init__(self):
        super().__init__()
        self.active = False
        self.fields = 0
        self.parts = []

    def handle_comment(self, data):
        if data.strip() == "field-start:statute":
            self.fields += 1
            self.active = True
        elif data.strip() == "field-end:statute":
            self.active = False

    def handle_data(self, data):
        if self.active:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if self.active and tag in {"p", "h4", "h5"}:
            self.parts.append(" ")


@lru_cache(maxsize=1)
def federal_granules():
    return {row["selector"]: row for row in json.loads((ROOT / "govinfo/index.json").read_bytes())}


class GovInfoCode(PublicProvider):
    source = Source(
        name="govinfo_code", host="www.govinfo.gov", authority_type="statute", jurisdictions=("US",),
        official_publisher=True, rendition="GPO annual U.S. Code HTML granule", endpoint="/content/pkg/",
        format="HTML", update="reviewed edition and section", rights="U.S. federal statutory publication.",
        attribution="U.S. Government Publishing Office", currentness_method="Historical annual edition only.",
        parser_revision="1", max_bytes=512000,
    )

    def source_url(self, selector):
        if selector not in federal_granules():
            raise CorpusError("unsupported_authority")
        return federal_granules()[selector]["url"]

    def normalize(self, selector, raw):
        self.source_url(selector)
        row = federal_granules()[selector]
        if fingerprint(raw) != row["sha256"]:
            raise CorpusError("changed_source_requires_review")
        title, section = row["title_number"], row["section"]
        text = raw.decode("utf-8")
        if (f"documentid:{title}_{section} " not in text
                or f"United States Code, {row['edition']} Edition" not in text
                or not re.search(r'<h3 class="section-head">(?:&sect;|§)' + re.escape(section) + r'\.', text)):
            raise CorpusError("source_section_identity_mismatch")
        parser = StatuteField()
        parser.feed(text)
        parser.close()
        body = " ".join("".join(parser.parts).split())
        if parser.active or parser.fields != 1 or not body:
            raise CorpusError("source_statutory_text_unavailable")
        citation = f"{title} U.S.C. § {section}"
        yield Observation(AuthorityVersion(
            jurisdiction="US", sovereign="federal", authority_type="statute",
            identity_namespace="usc", identity_key=f"{title}/{section}", citation=citation,
            title=citation, edition=f"U.S. Code {row['edition']}", text=body, currentness="historical",
            institution="U.S. Government Publishing Office", legislature="U.S. Congress",
            limitations=("Annual edition. Temporal applicability requires separate evidence.",),
        ), f"{title}_{section}", "GovInfo documentid and field-start:statute", citation)
