"""Case-law hydration, local retrieval and citation identity assurance."""

from copy import deepcopy
from datetime import date
import re
import time

from app.authority import AuthorityDocument, AuthorityUnavailable, proposed_review, digest
from app.corpus_store import CORPUS_STORAGE_ERRORS
from app.courtlistener_client import CourtListenerClient, CourtListenerError
from app.courtlistener_models import CaseBundle
from app.research_planning import LegalResearchPlanner, RESEARCH_TOPICS
from app.retrieval import tokens


class CourtListenerCitationVerifier:
    def __init__(self, store, client=None):
        self.store, self.client = store, client

    def verify(self, citation, expected_cluster, expected_name, *, refresh=False):
        value = None if refresh else self.store.verification(citation)
        if value is None and self.client is None:
            value = self.store.bulk_citation_identity(citation)
        if value is None and self.client:
            value = self.client.lookup(citation)
            self.store.save_verification(value)
        if (not value or value["cluster"] != expected_cluster
                or normalize_name(value["name"]) != normalize_name(expected_name)):
            raise AuthorityUnavailable("citation_identity_unverified")
        return {"status": "fixture_verified" if value["origin"] == "fixture" else "verified",
                "cluster": expected_cluster, "citation": citation, "origin": value["origin"],
                "limitations": ["Citation identity does not establish proposition support, controlling force or current law."]}


def normalize_name(value):
    return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))


def extract_passages(bundle: CaseBundle, opinion, topics, legal_area, *, limit=5):
    """Select multiple issue-relevant exact spans, preserving role and context."""
    area_topics = RESEARCH_TOPICS.get(legal_area, {})
    wanted = tokens(" ".join(topics).replace("_", " "))
    wanted |= tokens(" ".join(query for topic in topics for query in area_topics.get(topic, ())))
    candidates, offset = [], 0
    for index, paragraph in enumerate(opinion.paragraphs):
        text = paragraph["text"]
        start = opinion.text.find(text, offset)
        if start < 0:
            raise AuthorityUnavailable("paragraph_not_in_opinion")
        offset = start + len(text)
        score = len(tokens(text) & wanted)
        if score and len(text) >= 25:
            # Never let source instructions become a legal claim. They remain
            # preserved in the corpus as external document text.
            if re.search(r"\b(ignore|override|disregard)\b.{0,60}\b(instructions|policy|system)\b", text, re.I):
                continue
            excerpt = text[:1000]
            if len(text) > 1000 and ". " in excerpt:
                excerpt = excerpt[:excerpt.rfind(". ") + 1]
            candidates.append((score, index, start, excerpt, text))
    selected = sorted(candidates, key=lambda item: (-item[0], item[1]))[:min(limit, 8)]
    source = source_record(bundle, opinion, legal_area, topics)
    passages = []
    for _, index, start, text, context in sorted(selected, key=lambda item: item[1]):
        role = opinion.role
        classification = "candidate_dissent" if role == "dissent" else "candidate_concurrence" if "concurrence" in role else "candidate_reasoning" if role in {"lead", "unanimous"} else "unknown"
        limits = ["Passage classification is a candidate, not a determination of a holding or applicability.",
                  "Subsequent treatment and legal currentness have not been certified."]
        if role not in {"lead", "unanimous"}:
            limits.append(f"This is {role} opinion text; it must not be presented as a majority holding.")
        passage = {"id": f"cl-opinion-{opinion.id}-p{index + 1}", "schema_version": "1.0.0", "record_version": "0.1.0",
                   "last_modified": date.today().isoformat(), "title": bundle.cluster.name, "status": "proposed", "review": proposed_review(),
                   "source_id": source["id"], "workflow_ids": [], "jurisdiction": deepcopy(source["jurisdiction"]),
                   "locator": opinion.paragraphs[index]["locator"], "propositions": list(dict.fromkeys(topics)) or ["legal_research"],
                   "text": text, "verification": {"retrieved_on": date.today().isoformat(), "verified_on": date.today().isoformat(),
                       "source_version": opinion.content_hash, "excerpt_hash": digest(text), "method": "provider_exact_text_check"},
                   "limitations": limits, "legal_rule_ids": [], "process_step_ids": [],
                   "external_context": {"provider": "courtlistener", "opinion": opinion.id, "cluster": bundle.cluster.id,
                       "opinion_role": role, "classification": classification, "source_hash": opinion.content_hash,
                       "start": start, "end": start + len(text), "context_window": context[:4000]}}
        if role not in {"lead", "unanimous"}:
            passage["conflicts"] = [f"{bundle.cluster.name}: selected {role} opinion requires separate comparison; do not merge its reasoning into a majority holding."]
        if opinion.text[start:start + len(text)] != text:
            raise AuthorityUnavailable("excerpt_not_in_opinion")
        passages.append(passage)
    return source, tuple(passages)


def source_record(bundle, opinion, legal_area, topics):
    today = date.today().isoformat()
    return {"id": f"cl-opinion-{opinion.id}", "schema_version": "1.0.0", "record_version": "0.1.0", "last_modified": today,
            "title": bundle.cluster.name, "status": "proposed", "source_type": "court_opinion",
            "url": f"https://www.courtlistener.com/opinion/{bundle.cluster.id}/", "jurisdiction": {"country": "US", "state": bundle.court.state,
                "court": bundle.court.name, "locality": None, "agency": None}, "legal_areas": [legal_area],
            "authority": {"level": "primary_reproduction", "issuing_body": bundle.court.name, "is_source_of_truth": False,
                          "authority_notes": "CourtListener reproduces judicial text; provider metadata is not approval, applicability or currentness."},
            "dates": {"published": bundle.cluster.date, "effective_from": None, "effective_through": None, "last_updated": None, "last_verified": today},
            "provenance": {"source_content_version": opinion.content_hash, "content_hash": opinion.content_hash, "superseded_by_source_id": None},
            "access": {"is_free": True, "requires_login": False, "format": "html" if opinion.text_format == "html_with_citations" else "text"},
            "rights": {"reuse_status": "public_domain", "rights_notes": "Judicial text is an edict of government; provider service terms still apply."},
            "review": proposed_review(), "workflow_fit": {"topics": topics, "workflow_ids": [], "risk_level": "high"},
            "citation": {"preferred_citation": bundle.cluster.citations[0] if bundle.cluster.citations else "Unverified citation", "retrieved_at": today},
            "case_metadata": {"court": bundle.court.name, "decision_date": bundle.cluster.date,
                              "publication_status": "published" if bundle.cluster.publication == "Published" else "unpublished" if bundle.cluster.publication == "Unpublished" else "unknown",
                              "precedential_status": "reported" if bundle.cluster.publication == "Published" else "nonprecedential" if bundle.cluster.publication == "Unpublished" else "unknown",
                              "procedural_posture": bundle.cluster.posture or None, "subsequent_treatment": "unknown", "opinion_role": opinion.role},
            "external_identifiers": {"provider": "courtlistener", "api_version": "v4", "court": bundle.court.id, "docket": bundle.docket.id,
                                     "cluster": bundle.cluster.id, "opinion": opinion.id, "origin": bundle.origin, "citation_status": "unverified"}}


class LocalCorpusAuthorityProvider:
    name = "courtlistener_corpus"
    search_modes = ("keyword",)

    def __init__(self, store, client=None):
        self.store, self.client = store, client
        self._documents = {}
        self.metrics = {"local_search_ms": 0., "extraction_ms": 0.}
        self.owned_store = False
        self.planner = LegalResearchPlanner()

    def close(self):
        if self.owned_store:
            self.store.close()

    def search(self, matter, limit=6):
        if self.store is None:
            raise AuthorityUnavailable("corpus_storage_unavailable")
        try:
            return self._search(matter, limit)
        except CORPUS_STORAGE_ERRORS:
            raise AuthorityUnavailable("corpus_storage_unavailable") from None

    def _search(self, matter, limit, plan=None):
        try:
            plan = plan or self.planner.plan(matter)
        except ValueError:
            return []
        started = time.perf_counter()
        hits = self.store.search(" ".join(plan.queries), state=matter.state, sovereign=matter.sovereign,
                                 courts=plan.courts, limit=min(limit, 12))
        self.metrics["local_search_ms"] += 1000 * (time.perf_counter() - started)
        identifiers = []
        for hit in hits:
            bundle = self.store.case(hit["cluster"])
            if bundle and {o.id for o in bundle.opinions} != set(bundle.cluster.opinions):
                # A missing dissent/other part cannot silently disappear from
                # a cluster represented as complete legal evidence.
                continue
            opinion = next((o for o in bundle.opinions if o.id == hit["id"]), None) if bundle else None
            if not opinion or not opinion.text or bundle.court.state != matter.state or bundle.court.sovereign != matter.sovereign:
                continue
            try:
                citation = bundle.cluster.citations[0]
                verified = CourtListenerCitationVerifier(self.store, self.client).verify(citation, bundle.cluster.id, bundle.cluster.name)
            except (AuthorityUnavailable, CourtListenerError, IndexError):
                continue
            started = time.perf_counter()
            source, passages = extract_passages(bundle, opinion, list(plan.issues), matter.legal_area)
            self.metrics["extraction_ms"] += 1000 * (time.perf_counter() - started)
            if not passages:
                continue
            source["external_identifiers"]["citation_status"] = verified["status"]
            graph = self.store.graph(opinion.id)
            source["external_identifiers"]["treatment_signal"] = graph["treatment"]
            source["case_metadata"]["subsequent_treatment"] = graph["treatment"]
            if graph["treatment_scan_truncated"]:
                for p in passages:
                    p["limitations"].append("Potential treatment screening examined only the 20 most recent eligible citing opinions in this corpus.")
            if graph["signals"]:
                for p in passages:
                    p.setdefault("conflicts", []).append("Potential negative-treatment language exists in a later citing document; human review is required.")
            self._documents[source["id"]] = AuthorityDocument(source, passages, opinion.text)
            identifiers.append(source["id"])
        return identifiers[:limit]

    def fetch(self, source_id):
        if source_id not in self._documents:
            raise AuthorityUnavailable("source_not_selected")
        return deepcopy(self._documents[source_id])


class CourtListenerAuthorityProvider(LocalCorpusAuthorityProvider):
    name = "courtlistener"
    search_modes = ("keyword", "semantic")

    def _search(self, matter, limit, plan=None):
        try:
            plan = plan or self.planner.plan(matter)
        except ValueError:
            return []
        try:
            local = super()._search(matter, limit, plan=plan)
            if len(local) >= min(limit, 3):
                return local
            usage = self.client.usage()
            if not usage["available"]:
                raise CourtListenerError("throttled")
            remaining = min(r["remaining"] for r in usage["limits"] if r["scope"] == "user")
            self.client.budget.max_requests = min(self.client.budget.max_requests, self.client.budget.requests + remaining)
            seen = set()
            for index, query in enumerate(plan.queries):
                mode = "keyword" if index % 2 == 0 else "semantic"
                for hits, _ in self.client.search_pages(query, plan.courts, mode=mode):
                    for hit in hits:
                        if hit["cluster"] in seen or len(seen) >= min(limit, plan.max_results):
                            continue
                        seen.add(hit["cluster"])
                        bundle = self.client.hydrate(hit["cluster"])
                        if bundle.court.state != matter.state or bundle.court.sovereign != matter.sovereign or bundle.court.id not in plan.courts:
                            raise AuthorityUnavailable("jurisdiction_contamination")
                        self.store.ingest(bundle)
                        if bundle.cluster.citations:
                            value = self.client.lookup(bundle.cluster.citations[0])
                            if value["cluster"] != bundle.cluster.id:
                                raise AuthorityUnavailable("citation_mismatch")
                            self.store.save_verification(value)
                    if len(seen) >= min(limit, plan.max_results):
                        break
                if len(seen) >= min(limit, plan.max_results):
                    break
            # One bounded graph expansion, after discovery, never arbitrary
            # recursive crawling. Graph edges remain signals, not legal rules.
            if seen and self.client.budget.pages < self.client.budget.max_pages:
                seed = self.store.case(next(iter(sorted(seen))))
                if seed and seed.opinions:
                    self.store.add_edges(list(self.client.citation_edges(seed.opinions[0].id, incoming=True)))
            return super()._search(matter, limit, plan=plan)
        except CourtListenerError:
            # Partial hydrated documents remain external corpus data; only
            # verified local identities can be selected after an external error.
            available = super()._search(matter, limit, plan=plan)
            if available:
                return available
            raise AuthorityUnavailable("courtlistener_unavailable") from None
