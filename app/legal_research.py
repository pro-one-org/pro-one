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
    if source["authority"]["level"] not in {"official_primary", "official_secondary", "primary_reproduction"}:
        errors.append("unknown_source_authority")
    external = source.get("external_identifiers")
    context = passage.get("external_context")
    if external and (external.get("citation_status") not in {"verified", "fixture_verified"} or not context
                     or any(external.get(k) != context.get(k) for k in ("cluster", "opinion"))
                     or external.get("opinion") is None or context.get("source_hash") != source["provenance"]["content_hash"]):
        errors.append("external_identity_mismatch")
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
            repository, getattr(settings, "authority_network", ""), getattr(settings, "corpus_path", ""))
        if (providers is None and getattr(settings, "mode", None) == "development"
                and getattr(settings, "normalized_corpus_path", "")):
            from app.national_corpus_research import NormalizedAuthorityProvider
            self.providers.append(NormalizedAuthorityProvider(settings.normalized_corpus_path))

    def close(self):
        for provider in self.providers:
            if hasattr(provider, "close"):
                provider.close()

    def assemble(self, matter: ResearchMatter, *, force_general=False, selected_capability_id=None):
        resolution = CapabilityResolutionService(self.repository).resolve(matter)
        if resolution["missing_context"]:
            return {"status": "missing_context", "resolution": resolution, "package": None}
        corpus_enabled = any(provider.name == "normalized_corpus" for provider in self.providers)
        if matter.sovereign != "state" and not (corpus_enabled and matter.sovereign == "federal" and matter.state is None):
            return {"status": "unsupported", "resolution": resolution, "package": None}
        requested_types = set()
        if matter.authority_types:
            from app.national_corpus_research import SOURCE_TYPES
            requested_types = {SOURCE_TYPES[kind] for kind in matter.authority_types}
        if selected_capability_id is not None and not any(c["capability_id"] == selected_capability_id for c in resolution["exact"]):
            return {"status": "capability_not_relevant", "resolution": resolution, "package": None}
        capability = None
        if resolution["exact"] and not force_general and not matter.authority_types and matter.authority_status == "unresolved":
            candidates = [c["capability_id"] for c in resolution["exact"]]
            if selected_capability_id is not None and selected_capability_id not in candidates:
                return {"status": "capability_not_relevant", "resolution": resolution, "package": None}
            capability = self.repository.get("legal_capabilities", selected_capability_id or candidates[0])
        mode = "capability" if capability else "general_research"
        sources, passages, gaps = {}, {}, []
        provider_gaps = ["CourtListener network access is not configured; only existing local/repository evidence can be used."
                         for p in self.providers if getattr(p, "network_requested_unconfigured", False)]
        if capability:
            self.repository.validate_capabilities()
            sources = {sid: deepcopy(self.repository.get("sources", sid)) for sid in capability["source_ids"]}
            passages = {pid: deepcopy(self.repository.get("source_passages", pid)) for pid in capability["source_passage_ids"]}
            gaps = deepcopy(capability["support_gaps"])
        gaps.extend(provider_gaps)
        # Query only legal concepts; names, documents and user facts never
        # leave the process for an authority search.
        query = matter.model_copy(update={"goal": "", "user_posture": None, "document_type": None})
        fetch_gap = "An authority provider was unavailable or returned changed evidence; research may be incomplete."
        for provider in self.providers[:4]:
            if matter.authority_status != "unresolved" and provider.name != "normalized_corpus":
                continue
            if matter.sovereign == "federal" and provider.name not in {"normalized_corpus", "courtlistener", "courtlistener_corpus"}:
                continue
            if capability and provider.name not in {"courtlistener", "courtlistener_corpus", "virginia_official"}:
                continue
            try:
                identifiers = provider.search(query, limit=6)[:6]
            except AuthorityUnavailable:
                gaps.append(fetch_gap)
                continue
            for sid in identifiers:
                if capability and provider.name == "virginia_official" and sid not in capability["source_ids"]:
                    continue
                try:
                    document = provider.fetch(sid)
                except AuthorityUnavailable:
                    gaps.append(fetch_gap)
                    continue
                if requested_types and document.source["source_type"] not in requested_types:
                    continue
                if document.source["source_type"] == "other" and not document.source.get("corpus_provenance", {}).get("document_kind"):
                    continue
                self.repository.validate_record("sources", document.source)
                candidate_passages = document.passages[:12]
                text = " ".join(document.text.split())
                if document.source["id"] != sid:
                    return {"status": "evidence_rejected", "resolution": resolution, "package": None}
                for passage in candidate_passages:
                    self.repository.validate_record("source_passages", passage)
                    if passage["source_id"] != sid or " ".join(passage["text"].split()) not in text:
                        return {"status": "evidence_rejected", "resolution": resolution, "package": None}
                if not candidate_passages:
                    gaps.append(fetch_gap)
                # Replace the entire source snapshot only after verifying every
                # selected passage against the fetched text.
                sources[sid] = deepcopy(document.source)
                passages = {pid: p for pid, p in passages.items() if p["source_id"] != sid}
                passages.update({p["id"]: deepcopy(p) for p in candidate_passages})
        if capability and selected_capability_id is None:
            topical_passages = {pid: p for pid, p in passages.items() if set(matter.topics) & set(p["propositions"])}
            if topical_passages:
                passages = topical_passages
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
            if source.get("external_identifiers", {}).get("origin") == "fixture":
                gaps.append("Offline reconstructed CourtListener fixture: no authenticated API download or live semantic verification occurred.")
            conflicts.extend(passage.get("conflicts", []))
        order = {pid: index for index, pid in enumerate(capability["source_passage_ids"])} if capability else {}
        # A combined opinion can duplicate the lead and dissent. Prefer
        # separately attributed text when selecting within the evidence cap.
        ranked = sorted(passages.values(), key=lambda p: (authority_rank(sources[p["source_id"]]),
                        (sources[p["source_id"]].get("case_metadata") or {}).get("opinion_role") in {"mixed", "unknown"},
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
            citations[-1]["external_identifiers"] = deepcopy(source.get("external_identifiers"))
            citations[-1]["case_metadata"] = deepcopy(source.get("case_metadata"))
            if source.get("corpus_provenance"):
                citations[-1]["corpus_provenance"] = deepcopy(source["corpus_provenance"])
                citations[-1]["source_currentness"]["status"] = source["corpus_provenance"]["currentness"]
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
            self.close()
            return {"status": "unavailable", "response": None, "reason": "research_release_review_required"}
        try:
            if self.generation and config.provider != "testing":
                from app.courtlistener_authority import LocalCorpusAuthorityProvider
                from app.research_planning import ModelResearchPlanner
                for provider in self.providers:
                    if isinstance(provider, LocalCorpusAuthorityProvider):
                        provider.planner = ModelResearchPlanner(self.generation.registry, config)
            prepared = self.assemble(matter)
        finally:
            self.close()
        if prepared["package"] is None:
            return {"status": prepared["status"], "response": None}
        package = prepared["package"]
        if self.generation and config.provider != "testing":
            from app.research_synthesis import ResearchSynthesisService
            package = ResearchSynthesisService(self.generation.registry).prepare(package, config)
        generated = self.generation.generate(package, config)
        rendered = ResponseRenderingService().render(generated, package, config)
        return {"status": "answered" if rendered else generated["generation"]["status"], "response": rendered,
                "synthesis": deepcopy(package.get("synthesis", {"status": "exact_text_fallback"}))}
