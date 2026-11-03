"""Compile authoritative collections into proposed, reviewable graph artifacts.

The compiler is extractive by design. A model's paraphrase cannot be proven
entailed deterministically; candidate statements must exactly match a linked
passage. Exceptions/conflicts are carried forward, never inferred away.
"""

from copy import deepcopy
from datetime import date
import re

from app.authority import AuthorityDocument, digest, evidence_passage, proposed_review
from app.capabilities import capability_errors, same_jurisdiction
from app.legal_research import evidence_errors


def proposed(record):
    value = deepcopy(record)
    value.update(status="proposed", review=proposed_review())
    value.pop("public_currentness", None)
    if "currentness" in value:
        value["currentness"] = {"status": "unresolved"}
    return value


def proposed_rule(repository, passage):
    rule = proposed(next(iter(repository.records["legal_rules"].values())))
    rule.update(id=passage["id"] + "-rule", title=passage["title"], record_version="0.1.0",
                last_modified=date.today().isoformat(), description="Extractive compiler candidate, pending human review.",
                rule_type="other", source_passage_ids=[passage["id"]], notes="Generated candidate only.")
    rule["jurisdiction"] = {**deepcopy(passage["jurisdiction"]), "jurisdiction_required": True,
                            "jurisdiction_notes": "Subject classification requires review."}
    rule["source_support"] = {"required_source_ids": [passage["source_id"]], "optional_source_ids": [],
                              "source_quotes_allowed": True, "source_review_required": True,
                              "source_notes": "Statement must exactly equal the referenced evidence."}
    rule["rule_statement"] = {"canonical_statement": passage["text"], "plain_language_statement": passage["text"],
                              "must_not_overstate": deepcopy(passage["limitations"]), "user_facing_allowed": False,
                              "rule_statement_notes": "Exact source context, not a verified legal holding."}
    rule["rule_scope"] = {"applies_to": ["Candidate legal research"], "does_not_apply_to": ["User-specific conclusions"],
                          "requires_user_facts": ["Jurisdiction"], "requires_source_check": True, "scope_notes": "Human review required."}
    rule["workflow_fit"] = {"supported_workflow_ids": [], "excluded_workflow_ids": [], "workflow_notes": "No workflow required."}
    rule["process_step_fit"] = {"supported_process_step_ids": [], "excluded_process_step_ids": [], "process_step_notes": "Not procedural advice."}
    rule["document_fit"] = {"supported_document_ids": [], "supported_document_types": [], "excluded_document_ids": [], "document_notes": "Not document approval."}
    rule["dates"] = {"effective_on": None, "last_updated": None, "last_checked": None, "expires_on": None,
                     "date_notes": "Retrieval does not certify effective dates."}
    rule["exceptions_and_variations"] = {"known_exceptions": [], "local_variations": [],
                                         "unresolved_questions": deepcopy(passage["limitations"]),
                                         "variation_notes": "Do not infer exceptions; review full source."}
    rule["user_support"] = {"allowed_support_modes": ["general_information"], "prohibited_support_modes": ["Outcome conclusions"],
                            "requires_plain_language": True, "requires_citation": True}
    rule["risk"] = {"risk_level": "high", "risk_triggers": ["Unreviewed extraction"], "unsafe_uses": ["Public legal reliance"],
                    "safe_continuation_notes": "Keep candidate artifacts separate until reviewed."}
    rule["evaluation"] = {"required_evaluation_fixture_ids": [], "required_tests": ["exact_evidence_link"],
                          "success_criteria": ["No proposition without evidence."], "known_failure_modes": ["Confusing a quotation with a holding."]}
    return rule


class CapabilityCompiler:
    def __init__(self, repository):
        self.repository = repository

    def compile(self, matter, documents: list[AuthorityDocument], candidate_propositions=None, previous=None):
        if not matter.country or not matter.state or not matter.legal_area or not matter.topics:
            raise ValueError("compiler_context_required")
        if len(documents) > 12:
            raise ValueError("compiler_collection_limit")
        sources, passages, rules, gaps, conflicts = {}, {}, {}, [], []
        for document in documents:
            source = proposed(document.source)
            # Classification is proposed developer input, never legal approval.
            source.setdefault("legal_areas", [matter.legal_area])
            self.repository.validate_record("sources", source)
            if source["id"] in sources:
                raise ValueError("duplicate_source")
            if not same_jurisdiction(source["jurisdiction"], matter.model_dump()):
                raise ValueError("compiler_jurisdiction_mismatch")
            if len(document.text) > 200000 or not document.text.strip():
                raise ValueError("compiler_source_size")
            source["provenance"]["content_hash"] = digest(document.text)
            source["provenance"]["source_content_version"] = digest(document.text)
            sources[source["id"]] = source
            if source.get("case_metadata", {}).get("opinion_role") in {"mixed", "unknown"}:
                gaps.append("Opinion-role classification requires human review; quoted context is not automatically a holding.")
            proposed_passages = list(document.passages)
            if not proposed_passages:
                # This proposes text to review; it does not decide which sentences
                # are holdings, exceptions, dissents or applicable propositions.
                for index, sentence in enumerate(re.split(r"(?<=[.!?])\s+", document.text)[:20]):
                    if 30 <= len(sentence) <= 1000:
                        proposed_passages.append(evidence_passage(source, sentence, f"Normalized source sentence {index + 1}",
                                                                 matter.topics, str(index + 1), "compiler_exact_text_check"))
                gaps.append("Automatically segmented excerpts require review for opinion role, exceptions, scope and context.")
            for original in proposed_passages[:20]:
                p = proposed(original)
                p.update(workflow_ids=[], legal_rule_ids=[], process_step_ids=[])
                p["verification"].update(source_version=digest(document.text), method="compiler_exact_text_check", verified_on=date.today().isoformat())
                self.repository.validate_record("source_passages", p)
                errors = evidence_errors(source, p, matter.model_dump())
                if " ".join(p["text"].split()) not in " ".join(document.text.split()):
                    errors.append("passage_not_in_source_text")
                if p["id"] in passages:
                    errors.append("duplicate_passage")
                if errors:
                    gaps.append("Rejected candidate evidence: " + ", ".join(sorted(set(errors))))
                    continue
                conflicts.extend(p.get("conflicts", []))
                passages[p["id"]] = p
        candidates = candidate_propositions if candidate_propositions is not None else [
            {"statement": p["text"], "source_passage_ids": [p["id"]]} for p in passages.values()]
        for candidate in candidates[:100]:
            ids = candidate.get("source_passage_ids", [])
            if len(ids) != 1 or ids[0] not in passages or candidate.get("statement") != passages[ids[0]]["text"]:
                gaps.append("Candidate proposition lacks exact supporting evidence; excluded from rules.")
                continue
            p = passages[ids[0]]
            rule = proposed_rule(self.repository, p)
            self.repository.validate_record("legal_rules", rule)
            rules[rule["id"]] = rule
            p["legal_rule_ids"] = [rule["id"]]
        capability_id = re.sub(r"[^a-z0-9]+", "-", f"{matter.country}-{matter.state}-{matter.legal_area}-{matter.topics[0]}".lower()).strip("-")
        today = date.today().isoformat()
        capability = {"id": capability_id, "title": f"{matter.state} {matter.topics[0].replace('_', ' ').title()}",
                      "schema_version": "1.0.0", "record_version": "0.1.0", "last_modified": today,
                      "status": "proposed", "review": proposed_review(), "jurisdiction": {"country": matter.country, "state": matter.state},
                      "sovereign": matter.sovereign, "legal_area": matter.legal_area, "topics": matter.topics,
                      "source_ids": sorted(sources), "source_passage_ids": sorted(passages), "legal_rule_ids": sorted(rules),
                      "process_step_ids": [], "risk_ids": [], "related_workflow_ids": [], "research_evaluation_ids": [],
                      "support_gaps": sorted(set(gaps + ["Human review of boundaries, authority, exceptions, conflicts and currentness is required."])),
                      "conflicts": sorted(set(conflicts)), "currentness": {"status": "unresolved"}}
        fixtures = []
        for check in ("grounded_answer", "missing_state", "wrong_state", "invented_case", "invented_statute", "unsupported_proposition", "currentness", "conflict", "no_workflow", "injection", "outcome", "deadline", "damages"):
            matter_data = matter.model_dump()
            expected = "rejected"
            if check in {"grounded_answer", "no_workflow", "injection"}:
                expected = "evidence_ready" if passages else "no_authoritative_support"
            elif check == "missing_state":
                matter_data["state"], expected = None, "missing_context"
            elif check == "wrong_state":
                matter_data["state"], expected = "Uncompiled State", "no_authoritative_support"
            fixture = {"id": capability_id + "-" + check, "title": f"Proposed {check} evaluation", "schema_version": "1.0.0",
                       "record_version": "0.1.0", "last_modified": today, "status": "proposed", "review": proposed_review(),
                       "capability_ids": [capability_id], "mode": "general_research" if check == "no_workflow" else "capability",
                       "scenario": f"Review {check} for {capability['title']}", "check": check, "matter": matter_data, "expected_status": expected}
            fixtures.append(fixture)
            capability["research_evaluation_ids"].append(fixture["id"])
            self.repository.validate_record("research_evaluations", fixture)
        graph = {"sources": sources, "source_passages": passages, "legal_rules": rules,
                 "research_evaluations": {f["id"]: f for f in fixtures}}
        self.repository.validate_record("legal_capabilities", capability)
        errors = capability_errors(capability, graph)
        if errors:
            raise ValueError("compiler_graph_invalid")
        old_sources = {s["id"]: s for s in (previous or {}).get("sources", [])}
        refresh = {"new": sorted(set(sources) - set(old_sources)), "removed": sorted(set(old_sources) - set(sources)),
                   "changed": sorted(sid for sid in sources.keys() & old_sources.keys() if
                                     any(sources[sid].get(key) != old_sources[sid].get(key) for key in
                                         ("provenance", "dates", "enactment_metadata", "case_metadata"))),
                   "conflicts_changed": bool(previous) and (previous.get("capabilities", [{}])[0].get("conflicts", []) != capability["conflicts"]),
                   "review_reset": True}
        return {"capabilities": [capability], "sources": list(sources.values()), "source_passages": list(passages.values()),
                "legal_rules": list(rules.values()), "research_evaluations": fixtures,
                "report": {"status": "proposed", "validation": "structural_and_exact_text_only", "support_gaps": capability["support_gaps"],
                           "conflicts": capability["conflicts"], "refresh": refresh, "public_execution": False,
                           "review_required": ["Capability boundaries", "Primary source set", "Propositions and exceptions", "Conflicts and opinion roles", "Currentness and subsequent treatment", "Risk policy", "Evaluation relevance"]}}
