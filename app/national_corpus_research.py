"""Project replay-verified corpus passages into the existing Research Core."""

from datetime import date
import re
import sqlite3

from app.authority import AuthorityDocument, AuthorityUnavailable, evidence_passage, normalized_source, proposed_review
from app.national_corpus import CorpusError, CorpusQuery, fingerprint
from app.national_corpus_providers import PROVIDERS
from app.national_corpus_store import SQLiteNormalizedCorpus
from app.research_planning import LegalResearchPlanner
from app.retrieval import tokens


STATE_CODES = {"Virginia": "VA", "Maryland": "MD", "Florida": "FL", "New York": "NY", "California": "CA"}
SOURCE_TYPES = {"statute": "statute", "regulation": "regulation", "opinion": "court_opinion",
                "court_rule": "court_rule", "constitution": "constitution", "register_document": "other"}
FAMILY_PRIORITY = ("statute", "regulation", "opinion", "constitution", "court_rule", "register_document")
CORPUS_ANCHORS = {"landlord_repairs": (
    "landlord repair", "warranty habitability", "dwelling untenantable", "fit habitable condition", "keep premises fit",
    "fit human habitation",
)}


class NormalizedAuthorityProvider:
    name = "normalized_corpus"

    def __init__(self, path):
        self.path = path
        self.documents = {}

    def search(self, matter, limit=6):
        if matter.country != "US":
            return []
        if matter.sovereign == "federal" and matter.state is None:
            scope = "US"
        elif matter.sovereign == "state" and matter.state in STATE_CODES:
            scope = "US-" + STATE_CODES[matter.state]
        else:
            return []
        try:
            plan = LegalResearchPlanner().plan(matter, require_courts=False)
            as_of = date.fromisoformat(matter.authority_as_of) if matter.authority_as_of else None
        except ValueError:
            return []
        self.documents.clear()
        try:
            with SQLiteNormalizedCorpus(self.path, read_only=True) as store:
                self._collect(store, matter, scope, plan, as_of, min(6, limit))
        except (sqlite3.Error, OSError, CorpusError):
            raise AuthorityUnavailable("normalized_corpus_unavailable") from None
        return list(self.documents)

    def _collect(self, store, matter, scope, plan, as_of, limit):
        queries = list(dict.fromkeys((*plan.queries, *(q for issue in plan.issues for q in CORPUS_ANCHORS.get(issue, ())))))
        families = tuple(dict.fromkeys(matter.authority_types)) or FAMILY_PRIORITY[:3]
        candidates = {}
        for family in families:
            for query in queries:
                for hit in store.search(CorpusQuery(scope, family, text=query, currentness=matter.authority_status,
                                                    as_of=as_of, court=matter.court or "",
                                                    agency=matter.agency or "", limit=3)):
                    if not hit["edition_conflict"]:
                        candidates.setdefault(family, {}).setdefault(hit["version_id"], hit)
        # Give every requested family one turn before filling additional slots.
        by_family = [list(candidates.get(family, {}).values())[:3] for family in families]
        for index in range(3):
            for hits in by_family:
                if index < len(hits):
                    hit = hits[index]
                    try:
                        document = self._verified_document(store, matter, plan, hit, queries)
                    except (ValueError, OSError):
                        document = None
                    if document:
                        self.documents[document.source["id"]] = document
                    if len(self.documents) >= limit:
                        return

    def fetch(self, source_id):
        if source_id not in self.documents:
            raise AuthorityUnavailable("normalized_authority_unavailable")
        return self.documents[source_id]

    def _verified_document(self, store, matter, plan, hit, queries):
        # Opinion claims need the existing CourtListener citation and role
        # path. A reporter granule can include syllabus and counsel's words.
        if hit["authority_type"] == "opinion":
            return None
        for observation in store.provenance(hit["version_id"]):
            provider = PROVIDERS.get(observation["provider"])
            if not provider or provider.source.parser_revision != observation["parser_revision"]:
                continue
            if observation["url"] != provider.source_url(observation["selector"]):
                continue
            raw = store.snapshot_bytes(observation["hash"])
            if raw is None or fingerprint(raw) != observation["hash"]:
                continue
            matches = [item for item in provider.normalize(observation["selector"], raw)
                       if item.native_id == observation["native_id"] and item.version.version_id == hit["version_id"]
                       and item.locator == observation["locator"] and item.original_citation == observation["original_citation"]]
            if len(matches) != 1:
                continue
            version = matches[0].version
            expected_jurisdiction = "US" if matter.sovereign == "federal" else "US-" + STATE_CODES[matter.state]
            if (version.jurisdiction != expected_jurisdiction or version.sovereign != matter.sovereign
                    or version.authority_type != hit["authority_type"] or version.currentness != matter.authority_status
                    or (version.currentness == "current" and version.current_as_of.isoformat() != matter.authority_as_of)):
                continue
            source = self._source(matter, plan, version, observation, provider.source)
            passages = self._passages(source, plan, version.text, queries, observation["locator"])
            if passages:
                return AuthorityDocument(source, passages, version.text)
        return None

    def _source(self, matter, plan, version, observation, metadata):
        today = date.today().isoformat()
        retrieved = observation["first_retrieved"][:10]
        dates = {key: value.isoformat() if value else None for key, value in {
            "published": version.published_on, "effective_from": version.effective_from,
            "effective_through": version.effective_until, "last_updated": version.amended_on,
        }.items()}
        dates["last_verified"] = today
        return {
            "id": "corpus-" + version.version_id, "schema_version": "1.0.0", "record_version": "0.1.0",
            "last_modified": today, "title": version.title, "status": "proposed",
            "source_type": SOURCE_TYPES[version.authority_type], "url": observation["url"],
            "jurisdiction": {"country": "US", "state": matter.state, "agency": version.agency},
            "legal_areas": [plan.legal_area], "review": proposed_review(),
            "authority": {"level": "official_primary" if metadata.official_publisher else "primary_reproduction",
                          "issuing_body": version.institution or version.legislature or metadata.attribution},
            "dates": dates,
            "provenance": {"source_content_version": version.edition, "content_hash": "sha256:" + version.normalized_hash,
                           "superseded_by_source_id": None},
            "corpus_provenance": {"provider": metadata.name, "native_identifier": observation["native_id"],
                                  "snapshot_key": observation["id"], "version_key": version.version_id,
                                  "artifact_hash": observation["hash"], "locator": observation["locator"],
                                  "currentness": version.currentness, "document_kind": version.document_kind,
                                  "current_as_of": version.current_as_of.isoformat() if version.current_as_of else None,
                                  "currentness_basis": version.currentness_basis},
            "access": {"is_free": True, "requires_login": metadata.authentication != "none", "format": "other"},
            "rights": {"reuse_status": "unknown", "rights_notes": metadata.rights},
            "workflow_fit": {"topics": list(plan.issues), "workflow_ids": [], "risk_level": "high"},
            "citation": {"preferred_citation": version.citation, "retrieved_at": retrieved},
        }

    def _passages(self, source, plan, text, queries, locator):
        normalized = normalized_source(text)
        anchors = [tokens(query) for query in queries]
        passages = []
        # Keep exact contiguous spans and include nearby qualifying language.
        for offset, segment in enumerate(re.split(r"(?<=[.;])\s+(?=[A-Z(])", normalized)):
            if not 35 <= len(segment) <= 900 or not any(anchor <= tokens(segment) for anchor in anchors if anchor):
                continue
            if re.search(r"\b(ignore|override|disregard)\b.{0,60}\b(instructions|policy|system)\b", segment, re.I):
                continue
            passage = evidence_passage(source, segment, f"{locator}, excerpt {offset + 1}",
                                       list(plan.issues), suffix=f"p{offset + 1}", method="provider_exact_text_check")
            passage["verification"]["retrieved_on"] = source["citation"]["retrieved_at"]
            status = source["corpus_provenance"]["currentness"]
            passage["limitations"].append(f"Corpus source edition: {source['provenance']['source_content_version']}; state: {status}.")
            if source["corpus_provenance"]["current_as_of"]:
                passage["limitations"].append("Publisher currentness is limited to " + source["corpus_provenance"]["current_as_of"] + ".")
            if source["corpus_provenance"]["document_kind"]:
                passage["limitations"].append("Federal Register publication context does not establish operative CFR text.")
            passages.append(passage)
            if len(passages) == 2:
                break
        return tuple(passages)
