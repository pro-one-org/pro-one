"""Workflow-independent evidence assembly using the shared generation contract.

Free legal prose cannot be deterministically proven entailed by a passage. The
initial research contract therefore permits only exact evidence excerpts and
source-linked, curated explanation variants. Models select/organize these claims;
they cannot add law by attaching a real citation to an invented sentence.
"""

from copy import deepcopy
from app.authority import AuthorityUnavailable, configured_authority_providers, digest, authority_rank
from app.capabilities import CapabilityResolutionService, ResearchMatter, same_jurisdiction
from app.models.base import GenerationConfig
from app.rendering import ResponseRenderingService
from app.retrieval import eligible_record, lexical_score, tokens


RESEARCH_DISCLOSURE = "This is a development draft for inspection, not an approved legal answer."
CURRENTNESS_LIMIT = "Retrieval and verification dates do not certify current law. Subsequent case treatment is unknown; no citator check has been performed."
FACT_LIMIT = "These sources do not establish that you have a valid claim, that any party was negligent, or that you will recover damages."


def evidence_errors(source, passage, jurisdiction):
    errors = []
    if not same_jurisdiction(source["jurisdiction"], jurisdiction) or not same_jurisdiction(passage["jurisdiction"], jurisdiction):
        errors.append("cross_jurisdiction_evidence")
    if jurisdiction.get("legal_area") not in source.get("legal_areas", []):
        errors.append("cross_domain_evidence")
    if passage["source_id"] != source["id"]:
        errors.append("passage_source_mismatch")
    if source["authority"]["level"] not in {"official_primary", "official_secondary"}:
        errors.append("unknown_source_authority")
    if not passage["locator"] or not source["citation"]["preferred_citation"] or not source["url"].startswith("https://"):
        errors.append("citation_metadata_missing")
    if not source["provenance"]["source_content_version"] or not passage["verification"]["source_version"]:
        errors.append("source_version_missing")
    if digest(passage["text"]) != passage["verification"]["excerpt_hash"]:
        errors.append("evidence_hash_mismatch")
    if (not eligible_record(source) or not eligible_record(passage) or source["provenance"]["superseded_by_source_id"]
            or source["review"]["status"] == "deprecated" or passage["review"]["status"] == "deprecated"):
        errors.append("ineligible_source")
    return errors


class GeneralLegalResearchService:
    def __init__(self, repository, settings=None, generation=None, providers=None):
        self.repository, self.settings, self.generation = repository, settings, generation
        self.providers = providers if providers is not None else configured_authority_providers(
            repository, getattr(settings, "authority_network", ""))

    def assemble(self, matter: ResearchMatter, *, force_general=False, selected_capability_id=None):
        resolution = CapabilityResolutionService(self.repository).resolve(matter)
        if resolution["missing_context"]:
            return {"status": "missing_context", "resolution": resolution, "package": None}
        if matter.sovereign != "state":
            return {"status": "unsupported", "resolution": resolution, "package": None}
        if selected_capability_id is not None and not any(c["capability_id"] == selected_capability_id for c in resolution["exact"]):
            return {"status": "capability_not_relevant", "resolution": resolution, "package": None}
        capability = None
        if resolution["exact"] and not force_general:
            candidates = [c["capability_id"] for c in resolution["exact"]]
            if selected_capability_id is not None and selected_capability_id not in candidates:
                return {"status": "capability_not_relevant", "resolution": resolution, "package": None}
            capability = self.repository.get("legal_capabilities", selected_capability_id or candidates[0])
        mode = "capability" if capability else "general_research"
        sources, passages, gaps = {}, {}, []
        if capability:
            self.repository.validate_capabilities()
            sources = {sid: deepcopy(self.repository.get("sources", sid)) for sid in capability["source_ids"]}
            passages = {pid: deepcopy(self.repository.get("source_passages", pid)) for pid in capability["source_passage_ids"]}
            gaps = deepcopy(capability["support_gaps"])
        else:
            # Query only legal concepts; names, documents and user facts never
            # leave the process for an authority search.
            query = matter.model_copy(update={"goal": "", "user_posture": None, "document_type": None})
            for provider in self.providers[:2]:
                try:
                    for sid in provider.search(query, limit=3)[:3]:
                        document = provider.fetch(sid)
                        self.repository.validate_record("sources", document.source)
                        sources[sid] = deepcopy(document.source)
                        # A new fetch replaces, rather than augments, the previous
                        # snapshot of that source. Changed text cannot retain stale
                        # passages under new provenance.
                        passages = {pid: p for pid, p in passages.items() if p["source_id"] != sid}
                        for p in document.passages[:12]:
                            self.repository.validate_record("source_passages", p)
                            # Provider evidence must be present in fetched text,
                            # not an unverified search hit or invented summary.
                            if " ".join(p["text"].split()) not in " ".join(document.text.split()):
                                raise AuthorityUnavailable("passage_not_in_fetched_text")
                            passages[p["id"]] = deepcopy(p)
                except AuthorityUnavailable:
                    gaps.append("An authority provider was unavailable or returned changed evidence; research may be incomplete.")
        if capability:
            conflicts = deepcopy(capability["conflicts"])
        else:
            conflicts = []
            gaps.append("Research is bounded to the configured authoritative collections; it is not an exhaustive legal search.")
        # Do not silently filter contaminated provider evidence into an answer.
        for passage in passages.values():
            source = sources.get(passage["source_id"])
            if not source or evidence_errors(source, passage, matter.model_dump()):
                return {"status": "evidence_rejected", "resolution": resolution, "package": None}
            if source.get("case_metadata", {}).get("subsequent_treatment"):
                gaps.append("Subsequent case treatment is unresolved; check later history before relying on an opinion.")
            conflicts.extend(passage.get("conflicts", []))
        order = {pid: index for index, pid in enumerate(capability["source_passage_ids"])} if capability else {}
        ranked = sorted(passages.values(), key=lambda p: (authority_rank(sources[p["source_id"]]),
                        order.get(p["id"], 0), -lexical_score(tokens(" ".join(matter.topics)), p), p["id"]))[:12]
        if not ranked:
            return {"status": "no_authoritative_support", "resolution": resolution, "package": None}
        claims, citations = [], []
        for passage in ranked:
            source = sources[passage["source_id"]]
            cid = "citation." + passage["id"]
            allowed_texts = [passage["text"]]
            # Only compiled packages can use curated explanations. Dynamic
            # research never manufactures a permanent or reviewed proposition.
            if capability:
                for rid in passage["legal_rule_ids"]:
                    rule = self.repository.get("legal_rules", rid)
                    if (rid in capability["legal_rule_ids"] and rule and eligible_record(rule)
                            and passage["id"] in rule.get("source_passage_ids", [])
                            and rule["rule_statement"]["canonical_statement"] == passage["text"]):
                        allowed_texts.append(rule["rule_statement"]["plain_language_statement"])
            limits = sorted(set(passage["limitations"] + [CURRENTNESS_LIMIT, FACT_LIMIT]))
            claims.append({"claim_id": "claim." + passage["id"], "workflow_id": None,
                           "topic": passage["propositions"][0], "proposition": passage["text"],
                           "supported_by_passage_ids": [passage["id"]], "source_ids": [source["id"]],
                           "citation_ids": [cid], "legal_rule_ids": [], "jurisdiction": deepcopy(passage["jurisdiction"]),
                           "support_state": "source_linked_development", "limitations": limits,
                           "conflicts": deepcopy(conflicts), "allowed_texts": allowed_texts, "quotation_allowed": True})
            citations.append({"citation_id": cid, "passage_id": passage["id"], "source_id": source["id"],
                              "source_title": source["title"], "official_url": source["url"], "locator": passage["locator"],
                              "preferred_citation": source["citation"]["preferred_citation"], "source_status": source["status"],
                              "source_type": source["source_type"], "source_currentness": {"status": "unresolved", "dates": source["dates"],
                                  "retrieved_at": source["citation"]["retrieved_at"], "provenance": source["provenance"]},
                              "passage_currentness": passage["verification"], "limitations": limits})
        limitations = sorted({CURRENTNESS_LIMIT, FACT_LIMIT, *gaps, *conflicts, *(v for c in claims for v in c["limitations"])})
        package = {"workflow_id": None, "evidence_mode": mode, "capability_id": capability["id"] if capability else None,
                   "development_package": {"available": True, "package_integrity": True},
                   "public_execution": {"allowed": False, "input_eligible": True, "reason": "research_release_review_required"},
                   "scope_resolution": {"state": "research_subject_identified"},
                   "routing": {"state": "continue_with_source_backed_information"},
                   "user_context": {"missing_information": [], "facts": {}, "jurisdiction_scope": {"country": matter.country, "state": matter.state}},
                   "risks": {"recognized": []},
                   "grounding": {"sources": list(sources.values()), "passages": ranked,
                                 "eligibility": {"development_grounding": {"available": True}}},
                   "response_plan": {"available": True, "claims": claims, "citations": citations,
                                     "support_gaps": [{"code": "research_limit", "message": s} for s in gaps],
                                     "required_disclosures": [RESEARCH_DISCLOSURE], "limitations": limitations,
                                     "allowed_sections": ["source_limit", "next_steps", "questions_to_answer"],
                                     "required_sections": ["source_limit", "next_steps"]}}
        return {"status": "evidence_ready", "resolution": resolution, "package": deepcopy(package)}

    def respond(self, matter, config: GenerationConfig):
        if self.settings and self.settings.mode == "production":
            return {"status": "unavailable", "response": None, "reason": "research_release_review_required"}
        prepared = self.assemble(matter)
        if prepared["package"] is None:
            return {"status": prepared["status"], "response": None}
        package = prepared["package"]
        generated = self.generation.generate(package, config)
        rendered = ResponseRenderingService().render(generated, package, config)
        return {"status": "answered" if rendered else generated["generation"]["status"], "response": rendered}
