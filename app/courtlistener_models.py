"""Normalized external legal data. Provider metadata is never legal approval."""

from datetime import date
from html.parser import HTMLParser
import re
from pydantic import BaseModel, ConfigDict, Field

from app.authority import digest


API_BASE = "https://www.courtlistener.com/api/rest/v4/"
# Reviewed jurisdiction identities, not a model-controlled authority hierarchy.
COURT_POLICY = {
    "va": ("Virginia", "state", 0), "vactapp": ("Virginia", "state", 1),
    "md": ("Maryland", "state", 0), "mdctspecapp": ("Maryland", "state", 1),
    "ca4": (None, "federal", 1), "vawd": (None, "federal", 2),
    "vaed": (None, "federal", 2), "dcd": (None, "federal", 2),
    "scotus": (None, "federal", 0),
}
ROLES = {"010combined": "mixed", "015unamimous": "unanimous", "020lead": "lead",
         "025plurality": "plurality", "030concurrence": "concurrence", "035concurrenceinpart": "concurrence_in_part",
         "040dissent": "dissent", "050addendum": "addendum", "060remittitur": "remittitur",
         "070rehearing": "rehearing", "080onthemerits": "on_the_merits", "090onmotiontostrike": "motion",
         "100trialcourt": "trial_document"}


def external_id(value, endpoint):
    if type(value) is int and 0 < value < 10**13:
        return value
    if isinstance(value, str):
        match = re.fullmatch(re.escape(API_BASE + endpoint + "/") + r"([1-9][0-9]{0,12})/", value)
        if match:
            return int(match[1])
    raise ValueError("invalid_external_relationship")


def court_id(value):
    if isinstance(value, str):
        if re.fullmatch(r"[a-z][a-z0-9]{0,24}", value):
            return value
        match = re.fullmatch(re.escape(API_BASE + "courts/") + r"([a-z][a-z0-9]{0,24})/", value)
        if match:
            return match[1]
    raise ValueError("invalid_court_relationship")


class ExternalModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Court(ExternalModel):
    id: str
    name: str = Field(min_length=1, max_length=500)
    state: str | None
    sovereign: str
    hierarchy: int

    @classmethod
    def normalize(cls, raw):
        cid = court_id(raw["id"])
        state, sovereign, hierarchy = COURT_POLICY.get(cid, (None, "unknown", 99))
        return cls(id=cid, name=raw["full_name"], state=state, sovereign=sovereign, hierarchy=hierarchy)


class Docket(ExternalModel):
    id: int
    court: str
    number: str = Field(max_length=1000)
    name: str = Field(max_length=1000)
    modified: str | None = None

    @classmethod
    def normalize(cls, raw):
        return cls(id=external_id(raw["id"], "dockets"), court=court_id(raw.get("court_id") or raw["court"]),
                   number=raw.get("docket_number") or "", name=raw.get("case_name") or "",
                   modified=raw.get("date_modified"))


class Cluster(ExternalModel):
    id: int
    docket: int
    name: str = Field(min_length=1, max_length=1000)
    date: str | None
    publication: str
    citations: list[str] = Field(max_length=100)
    opinions: list[int] = Field(max_length=100)
    judges: str = Field(default="", max_length=10000)
    posture: str = Field(default="", max_length=10000)

    @classmethod
    def normalize(cls, raw):
        filed = raw.get("date_filed") or None
        if filed:
            date.fromisoformat(filed)
        citations = []
        for citation in raw.get("citations", []):
            if isinstance(citation, str):
                citations.append(citation)
            else:
                citations.append(f"{citation['volume']} {citation['reporter']} {citation['page']}")
        return cls(id=external_id(raw["id"], "clusters"), docket=external_id(raw["docket"], "dockets"),
                   name=raw.get("case_name") or raw.get("case_name_full"), date=filed,
                   publication=raw.get("precedential_status") or "Unknown", citations=citations,
                   opinions=[external_id(x, "opinions") for x in raw.get("sub_opinions", [])],
                   judges=raw.get("judges") or "", posture=raw.get("posture") or "")


class OpinionHTML(HTMLParser):
    """No HTML execution. Preserve paragraph/page anchors and bounded text."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skip, self.buffer, self.paragraphs, self.locator = 0, [], [], ""

    def flush(self):
        text = " ".join("".join(self.buffer).split())
        if text:
            self.paragraphs.append({"text": text, "locator": f"paragraph {len(self.paragraphs) + 1}" + (f" ({self.locator})" if self.locator else "")})
        self.buffer = []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "iframe", "svg", "object", "template"}:
            self.skip += 1
        if self.skip:
            return
        if tag in {"p", "div", "h1", "h2", "h3", "blockquote", "li", "br"}:
            self.flush()
            values = dict(attrs)
            anchor = values.get("id", "")
            self.locator = anchor if re.fullmatch(r"[a-zA-Z0-9_.-]{1,60}", anchor) else ""

    def handle_endtag(self, tag):
        if tag in {"script", "style", "iframe", "svg", "object", "template"} and self.skip:
            self.skip -= 1
        if not self.skip and tag in {"p", "div", "h1", "h2", "h3", "blockquote", "li"}:
            self.flush()

    def handle_data(self, data):
        if not self.skip:
            self.buffer.append(data)


class Opinion(ExternalModel):
    id: int
    cluster: int
    role: str
    text: str = Field(max_length=1500000)
    paragraphs: list[dict] = Field(max_length=20000)
    content_hash: str
    cited: list[int] = Field(max_length=10000)
    text_format: str
    modified: str | None = None

    @classmethod
    def normalize(cls, raw):
        html = raw.get("html_with_citations")
        if html:
            if len(html) > 2000000:
                raise ValueError("opinion_text_limit")
            parser = OpinionHTML()
            parser.feed(html)
            parser.flush()
            paragraphs, fmt = parser.paragraphs, "html_with_citations"
        else:
            plain = raw.get("plain_text") or ""
            if len(plain) > 1500000:
                raise ValueError("opinion_text_limit")
            paragraphs = [{"text": " ".join(p.split()), "locator": f"paragraph {i + 1}"}
                          for i, p in enumerate(re.split(r"\n\s*\n", plain)) if p.strip()]
            fmt = "plain_text"
        text = "\n\n".join(p["text"] for p in paragraphs)
        return cls(id=external_id(raw["id"], "opinions"), cluster=external_id(raw.get("cluster_id") or raw["cluster"], "clusters"),
                   role=ROLES.get(raw.get("type"), "unknown"), text=text, paragraphs=paragraphs, content_hash=digest(text),
                   cited=[external_id(x, "opinions") for x in raw.get("opinions_cited", [])], text_format=fmt,
                   modified=raw.get("date_modified"))


class CaseBundle(ExternalModel):
    court: Court
    docket: Docket
    cluster: Cluster
    opinions: list[Opinion]
    origin: str = "courtlistener_v4"

    def validate_relationships(self):
        policy = COURT_POLICY.get(court_id(self.court.id), (None, "unknown", 99))
        if (self.court.state, self.court.sovereign, self.court.hierarchy) != policy:
            raise ValueError("court_policy_mismatch")
        external_id(self.docket.id, "dockets")
        external_id(self.cluster.id, "clusters")
        if self.cluster.date:
            date.fromisoformat(self.cluster.date)
        if (self.docket.court != self.court.id or self.cluster.docket != self.docket.id
                or any(o.cluster != self.cluster.id or o.id not in self.cluster.opinions for o in self.opinions)):
            raise ValueError("case_relationship_mismatch")
        if len({o.id for o in self.opinions}) != len(self.opinions):
            raise ValueError("duplicate_opinion")
        if {o.id for o in self.opinions} != set(self.cluster.opinions):
            raise ValueError("incomplete_case_bundle")
        for opinion in self.opinions:
            external_id(opinion.id, "opinions")
            if opinion.content_hash != digest(opinion.text) or opinion.text != "\n\n".join(p["text"] for p in opinion.paragraphs):
                raise ValueError("opinion_content_mismatch")
