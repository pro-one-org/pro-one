"""Capture and replay bounded, public CourtListener v4 opinion hydration."""

from base64 import b64decode, b64encode
from datetime import date
import json
import os
import re

from app.corpus_store import encode
from app.courtlistener_authority import normalize_name
from app.courtlistener_client import CourtListenerClient, CourtListenerError, CourtListenerTransport, RequestBudget
from app.courtlistener_models import API_BASE, COURT_POLICY
from app.national_corpus import AuthorityVersion, CorpusError, FetchedSource, Observation, Source, SourceRelationship


class CapturingTransport(CourtListenerTransport):
    def __init__(self, transport):
        self.transport = transport
        self.responses = []

    def request(self, method, path, headers, body, timeout, max_bytes):
        status, response_headers, raw = self.transport.request(method, path, headers, body, timeout, max_bytes)
        if status == 200:
            self.responses.append({
                "method": method, "path": path, "response": b64encode(raw).decode("ascii"),
            })
        return status, response_headers, raw


class ReplayTransport:
    def __init__(self, responses):
        if not isinstance(responses, list):
            raise CorpusError("courtlistener_snapshot_invalid")
        self.responses = iter(responses)

    def request(self, method, path, headers, body, timeout, max_bytes):
        row = next(self.responses, {})
        if not isinstance(row, dict) or (row.get("method"), row.get("path")) != (method, path):
            raise CourtListenerError("courtlistener_snapshot_request_mismatch")
        raw = b64decode(row["response"], validate=True)
        if len(raw) > max_bytes:
            raise CourtListenerError("response_size_exceeded")
        return 200, {"content-type": "application/json"}, raw


class CourtListenerProvider:
    source = Source(
        name="courtlistener", host="www.courtlistener.com", authority_type="opinion", jurisdictions=("US",),
        official_publisher=False, rendition="Free Law Project reproduction of public opinions",
        endpoint="/api/rest/v4/citation-lookup/", format="archive of exact v4 JSON response bytes",
        update="explicit case-citation hydration", authentication="server-side token",
        rights="Judicial opinions are government edicts. Provider data and service terms apply.",
        attribution="Free Law Project / CourtListener and the issuing court",
        currentness_method="Provider citation lookup and court match. Later treatment and official text parity unresolved.",
        parser_revision="1", max_requests=12,
    )

    def __init__(self, transport=None):
        self.transport = transport

    def _selection(self, selector):
        court, _, citation = selector.partition("/")
        if (COURT_POLICY.get(court, (None, None))[1] != "federal" or len(citation) > 100
                or not re.fullmatch(r"[0-9]{1,5} [A-Za-z.0-9 ]{1,35} [0-9]{1,6}", citation)):
            raise CorpusError("invalid_courtlistener_selector")
        return court, citation

    def source_url(self, selector):
        self._selection(selector)
        return f"https://{self.source.host}{self.source.endpoint}"

    def _case(self, selector, transport, token):
        court, citation = self._selection(selector)
        budget = RequestBudget(max_requests=self.source.max_requests, max_bytes=5_500_000, max_documents=8)
        client = CourtListenerClient(token, transport=transport, budget=budget)
        try:
            resolution = client.lookup(citation)
            bundle = client.hydrate(resolution["cluster"])
        except CourtListenerError as exc:
            raise CorpusError(f"courtlistener_{exc.code}") from None
        if (bundle.court.sovereign != "federal" or bundle.court.id != court or citation not in bundle.cluster.citations
                or normalize_name(resolution["name"]) != normalize_name(bundle.cluster.name)):
            raise CorpusError("courtlistener_case_identity_mismatch")
        return bundle, budget.requests

    def fetch(self, selector):
        transport = CapturingTransport(self.transport or CourtListenerTransport())
        _, requests = self._case(selector, transport, os.environ.get("COURTLISTENER_API_TOKEN"))
        return FetchedSource(encode(transport.responses).encode(), requests)

    def normalize(self, selector, raw):
        try:
            replay = ReplayTransport(json.loads(raw))
        except (UnicodeError, ValueError):
            raise CorpusError("courtlistener_snapshot_invalid") from None
        bundle, _ = self._case(selector, replay, "offline-replay")
        if next(replay.responses, None) is not None:
            raise CorpusError("courtlistener_snapshot_has_extra_responses")
        citation = bundle.cluster.citations[0]
        cluster = f"clusters/{bundle.cluster.id}/"
        docket = f"dockets/{bundle.docket.id}/"
        published_on = date.fromisoformat(bundle.cluster.date) if bundle.cluster.date else None
        for opinion in bundle.opinions:
            if not opinion.text:
                raise CorpusError("courtlistener_opinion_text_missing")
            native = f"opinions/{opinion.id}/"
            version = AuthorityVersion(
                jurisdiction="US", sovereign="federal", authority_type="opinion",
                identity_namespace="courtlistener_opinion", identity_key=str(opinion.id),
                title=bundle.cluster.name, citation=citation, edition="provider opinion",
                alternate_citations=tuple(bundle.cluster.citations[1:]), text=opinion.text, published_on=published_on,
                court=bundle.court.name, hierarchy=(bundle.court.id, cluster), opinion_role=opinion.role,
                precedential_status=bundle.cluster.publication, procedural_posture=bundle.cluster.posture or None,
                limitations=("Publisher reproduction. Independent text parity and subsequent treatment unresolved.",
                             "Opinion role and publication metadata are supplied by CourtListener."),
            )
            relationships = (
                SourceRelationship("opinion_of", cluster), SourceRelationship("docket_of", docket),
                *(SourceRelationship("cites", f"opinions/{target}/") for target in dict.fromkeys(opinion.cited)),
            )
            yield Observation(version, native, API_BASE + native, citation, relationships)
