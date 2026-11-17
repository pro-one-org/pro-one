"""Resolve versioned claim definitions against Research Core evidence."""
from collections import defaultdict
from dataclasses import replace
import json

from pydantic import TypeAdapter

from app.authority import AuthorityDocument, AuthorityUnavailable, digest
from app.capabilities import ResearchMatter, same_jurisdiction
from app.claim_models import LegalTheory
from app.corpus import passage_relationship_errors
from app.legal_research import GeneralLegalResearchService, evidence_errors
from app.matter_models import Target
from app.matter_state import EVENT_FIELDS, OPTIONAL_EVENT_FIELDS, PARTY_FIELDS, MatterError, projection
from app.jurisdictions import registry


CATALOG = TypeAdapter(tuple[LegalTheory, ...])
INACTIVE = {"historical", "superseded", "repealed", "proposed", "review_required", "future_effective"}


def fingerprint(value):
    return digest(json.dumps(value, sort_keys=True, separators=(",", ":")))


class RetainedClaimAuthority:
    """Read the claim-specific, offline passage collection via Research Core."""
    name = "retained_claim_authority"

    def __init__(self, repository):
        payload = json.loads((repository.data_dir / "claim-authority.json").read_text(encoding="utf-8"))
        if (not isinstance(payload, dict) or set(payload) != {"sources", "passages"}
                or any(not isinstance(rows, list) for rows in payload.values())):
            raise ValueError("invalid_retained_claim_authority")
        sources = {}
        passages = defaultdict(list)
        seen = set()
        for source in payload["sources"]:
            repository.validate_record("sources", source)
            key = source["id"]
            if key in sources or key in repository.records["sources"]:
                raise ValueError("duplicate_retained_claim_source")
            sources[key] = source
        for passage in payload["passages"]:
            repository.validate_record("source_passages", passage)
            if (passage["id"] in seen or passage["id"] in repository.records["source_passages"]
                    or passage_relationship_errors(passage, sources=sources, workflows={}, legal_rules={}, process_steps={})):
                raise ValueError("invalid_retained_claim_passage")
            seen.add(passage["id"])
            passages[passage["source_id"]].append(passage)
        if set(sources) != set(passages):
            raise ValueError("retained_claim_source_without_passages")
        self.documents = {key: AuthorityDocument(source, tuple(passages[key]),
                                                 " ".join(p["text"] for p in passages[key]))
                          for key, source in sources.items()}

    def search(self, matter, limit=6):
        query = matter.model_dump()
        return [key for key, document in self.documents.items()
                if same_jurisdiction(document.source["jurisdiction"], query)
                and matter.legal_area in document.source["legal_areas"]
                and set(matter.topics) & set(document.source["workflow_fit"]["topics"])][:limit]

    def fetch(self, source_id):
        try:
            return self.documents[source_id]
        except KeyError:
            raise AuthorityUnavailable("source_unavailable") from None


def authority_binding(ref, passage, source, citation, query):
    if not passage or not source or not citation or evidence_errors(source, passage, query.model_dump()):
        return None
    if (passage["id"] != ref.passage_id or citation["passage_id"] != ref.passage_id
            or source["id"] != ref.source_id or source["source_type"] != ref.source_type
            or citation["source_id"] != source["id"]
            or passage["verification"]["source_version"] != ref.source_version
            or source["provenance"]["source_content_version"] != ref.source_version
            or passage["verification"]["excerpt_hash"] != ref.excerpt_hash
            or source["authority"]["level"] not in {"official_primary", "primary_reproduction"}):
        return None
    case = source.get("case_metadata") or {}
    corpus = source.get("corpus_provenance") or {}
    currentness = citation["source_currentness"]
    status = currentness["status"]
    if status != corpus.get("currentness", "unresolved") or (
        status == "current_as_of" and (
            not currentness.get("as_of") or currentness.get("as_of") != corpus.get("current_as_of")
            or not corpus.get("currentness_basis")
        )
    ):
        return None
    if ref.role == "supports":
        if ref.source_type == "court_opinion" and (
            case.get("opinion_role") not in {"lead", "unanimous", "majority"}
            or case.get("precedential_status") not in {"reported", "precedential", "binding"}
        ):
            return None
        if corpus.get("document_kind") or status in INACTIVE or (
            query.authority_as_of and (status != "current_as_of" or query.authority_as_of != currentness.get("as_of"))
        ):
            return None
        if query.authority_as_of:
            dates = currentness["dates"]
            if (dates.get("effective_from") and query.authority_as_of < dates["effective_from"]
                    or dates.get("effective_through") and query.authority_as_of > dates["effective_through"]):
                return None
    return {
        "relationship": ref.role, "passage_id": passage["id"], "source_id": source["id"],
        "source_version": ref.source_version, "excerpt_hash": ref.excerpt_hash,
        "citation": citation["preferred_citation"], "url": citation["official_url"],
        "jurisdiction": passage["jurisdiction"], "locator": passage["locator"], "quote": passage["text"],
        "source_type": source["source_type"], "issuing_body": source["authority"]["issuing_body"],
        "currentness": currentness, "opinion": case, "corpus": corpus,
        "limitations": citation["limitations"], "conflicts": passage.get("conflicts", []),
    }


class ClaimCatalog:
    def __init__(self, repository):
        self.repository = repository
        self.retained = RetainedClaimAuthority(repository)
        rows = CATALOG.validate_json((repository.data_dir / "claim-theories.json").read_bytes())
        versions = defaultdict(list)
        for theory in rows:
            versions[theory.id].append(theory)
        for group in versions.values():
            first = group[0]
            if (len({row.version for row in group}) != len(group)
                    or any((row.jurisdiction, row.kind, row.legal_area)
                           != (first.jurisdiction, first.kind, first.legal_area) for row in group)):
                raise ValueError("invalid_theory_version_identity")
            if first.jurisdiction not in registry():
                raise ValueError("invalid_theory_jurisdiction")
            for theory in group:
                related = versions.get(theory.related_theory, ())
                if theory.related_theory and (not related or theory.related_theory == theory.id
                        or related[-1].jurisdiction != theory.jurisdiction):
                    raise ValueError("invalid_related_theory")
                for element in theory.elements:
                    for link in element.fields:
                        expected = ("party" if link.field in PARTY_FIELDS else "event"
                                    if link.field in EVENT_FIELDS | OPTIONAL_EVENT_FIELDS else "matter")
                        if link.scope != expected:
                            raise ValueError("invalid_catalog_fact_scope")
        # Catalog order is explicit. Earlier versions remain available in the file.
        self.versions = tuple(rows)
        self.active = {key: group[-1] for key, group in versions.items()}

    def research(self, theory, settings=None, law_as_of=None, *, packages=None):
        owner = registry()[theory.jurisdiction]
        query = ResearchMatter(country="US", sovereign=owner.kind,
                               state=owner.name if owner.kind != "federal" else None, legal_area=theory.legal_area,
                               topics=list(theory.topics), authority_status="current" if law_as_of else "unresolved",
                               authority_as_of=law_as_of.isoformat() if law_as_of else None)
        packages = {} if packages is None else packages
        capability = theory.capability if not law_as_of else None
        key = (query.model_dump_json(), capability)
        if key not in packages:
            # Claims replay retained authority. Network refresh belongs to
            # Research Core and cannot replace pinned development definitions.
            local_settings = replace(settings, authority_network="", corpus_path="") if settings else None
            service = GeneralLegalResearchService(self.repository, local_settings)
            service.providers.append(self.retained)
            try:
                packages[key] = service.assemble(query, selected_capability_id=capability)["package"]
            finally:
                service.close()
        package = packages[key]
        if not package:
            if law_as_of:
                _, exact, limits = self.research(theory, settings, packages=packages)
                return {}, exact, limits
            return {}, (), ()
        sources = {row["id"]: row for row in package["grounding"]["sources"]}
        passages = {row["id"]: row for row in package["grounding"]["passages"]}
        citations = {row["passage_id"]: row for row in package["response_plan"]["citations"]}
        bindings = {}
        for element in theory.elements:
            found = []
            for ref in element.authority:
                if binding := authority_binding(ref, passages.get(ref.passage_id), sources.get(ref.source_id),
                                                citations.get(ref.passage_id), query):
                    found.append(binding)
            # Dropping even one qualification changes the catalog proposition.
            if len(found) == len(element.authority):
                bindings[element.id] = tuple(found)
        exact = tuple({"quote": passages[key]["text"], "citation": value,
                       "conflicts": passages[key].get("conflicts", [])} for key, value in citations.items())
        return bindings, exact, tuple(package["response_plan"]["limitations"])

    def validate(self):
        packages = {}
        for theory in self.versions:
            bindings, _, _ = self.research(theory, packages=packages)
            if set(bindings) != {element.id for element in theory.elements}:
                raise ValueError(f"unbound_catalog_authority:{theory.id}:{theory.version}")


def matter_scope(matter, request):
    facts = projection(matter)
    jurisdiction = facts.get(Target(field="jurisdiction"), {}).get("preferred")
    matter_type = facts.get(Target(field="matter_type"), {}).get("preferred")
    events = {row.id: row for row in matter.events}
    incidents = [row for row in events.values() if row.kind == "incident"]
    if request.event_id is not None and request.event_id not in events:
        raise MatterError("invalid_claim_event")
    event = events.get(request.event_id) if request.event_id else incidents[0] if len(incidents) == 1 else None
    if event and event.kind != "incident":
        raise MatterError("invalid_claim_event")
    parties = {row.id: row for row in matter.parties}
    if request.party_id and (request.party_id not in parties or not event or request.party_id not in event.participants):
        raise MatterError("invalid_claim_party")
    subject = request.party_id
    if not subject and event and len(event.participants) == 1:
        subject = event.participants[0]
    return jurisdiction.value if jurisdiction else None, matter_type.value if matter_type else None, event, subject, facts


def available(catalog, jurisdiction, matter_type):
    return tuple(row for row in catalog.active.values() if row.jurisdiction == jurisdiction
                 and matter_type in row.matter_types)
