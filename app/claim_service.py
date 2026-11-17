"""Revision-bound claim analysis and neutral development rendering."""
from app.claim_catalog import ClaimCatalog, available, fingerprint, matter_scope
from app.claim_mapping import CONFLICT, evidence_for, fact_view, model_mappings, posture, relation, validate_mappings
from app.claim_models import AnalyzeClaim, ElementMatterMapping
from app.matter_models import Target
from app.matter_state import MatterError


BOUNDARY = ("This development analysis describes source passages and the evidence currently recorded. "
            "Decisions about claims, defendants, litigation, settlement and filing require separate judgment.")
AUTHORITY_LIMIT = "The available authority does not establish the governing rule for the requested date."
DATA_LIMIT = "Additional facts may be relevant. Evidence links identify what the records address."
POSTURE_LABELS = {
    "asserted_support": "The user reported a relevant fact.",
    "documented_support": "An uploaded document records a relevant fact.",
    "externally_verified_support": "An attributed external record supports a relevant fact.",
    "alleged_support": "A pleading alleges a relevant fact.",
    "conflicting_support": "The matter contains differing or disputed accounts.",
    "adverse_evidence_present": "The matter contains potentially adverse information.",
    "evidence_present": "The matter contains relevant context.",
    "inference_only": "The matter contains a model inference.",
    "unresolved": "This source link still needs clarification.",
    "unknown": "The matter has open factual questions.",
    "no_mapped_evidence": "This condition has no mapped evidence.",
}
INJURY_DOCUMENTS = {"medical_record", "incident_report", "court_filing"}


class ClaimService:
    def __init__(self, repository, settings=None, registry=None, verifier=("", "")):
        self.catalog = ClaimCatalog(repository)
        self.settings = settings
        self.registry = registry
        self.verifier = verifier

    def discover(self, matter, request, scope=None):
        jurisdiction, matter_type, _, _, _ = scope or matter_scope(matter, request)
        theories = available(self.catalog, jurisdiction, matter_type)
        if len(set(request.theory_ids)) != len(request.theory_ids) or not set(request.theory_ids) <= {
            row.id for row in theories
        }:
            raise MatterError("claim_theory_outside_matter_scope")
        selected = [row for row in theories if not request.theory_ids or row.id in request.theory_ids]
        packages = {}
        return [(row, *self.catalog.research(row, self.settings, request.law_as_of, packages=packages))
                for row in selected]

    def analyze(self, matter, request):
        if request.revision != matter.revision:
            raise MatterError("claim_revision_mismatch")
        evidence = {item.id: item for item in matter.evidence}
        relevant = tuple(row for row in matter.assertions if row.target.field != "injury"
                         or getattr(row.source, "evidence_id", None) is None
                         or evidence[row.source.evidence_id].kind in INJURY_DOCUMENTS)
        # Project only claim-eligible evidence, so an unrelated document
        # cannot suppress a question or create a competing injury account.
        claim_matter = matter.model_copy(update={"assertions": relevant})
        scope = matter_scope(claim_matter, request)
        jurisdiction, matter_type, event, party, facts = scope
        prepared = self.discover(claim_matter, request, scope)
        assertions = {row.id: row for row in relevant}
        candidates, contexts, authorities, questions, fallback = [], {}, {}, {}, {}
        theories = []
        for theory, bindings, exact, limits in prepared:
            for item in exact:
                fallback[item["citation"]["passage_id"]] = item
            elements = []
            for element in theory.elements:
                key = theory.id, element.id
                binding = bindings.get(element.id)
                if not binding or any(row["relationship"] == "conflicts" for row in binding):
                    elements.append({"id": element.id, "status": "authority_unresolved", "authority": binding or ()})
                    continue
                authorities[key] = binding
                gaps = []
                for link in element.fields:
                    target, rows, status = fact_view(claim_matter, facts, link, event, party)
                    relationships = [relation(link, row, status) for row in rows]
                    if link.field == "employee_notice" and event and len(event.participants) > 1:
                        relationships = ["context" if kind == "supporting" else kind for kind in relationships]
                    notice_unclear = link.field == "employee_notice" and bool(rows) and set(relationships) == {"context"}
                    if notice_unclear or status in CONFLICT | {"unknown", "unresolved", "inferred", "alleged"}:
                        reason = ("party_identity_unresolved" if link.scope == "party" and status == "unresolved"
                                  else "event_scope_unresolved" if target is None
                                  else "evidence_attribution_unresolved" if notice_unclear else status)
                        gaps.append({"field": link.field, "target": target, "reason": reason})
                        if target is not None:
                            prompt = (f"What can clarify the different accounts of {link.field.replace('_', ' ')}?"
                                      if status in CONFLICT else link.question)
                            question = questions.setdefault(target, {
                                "target": target, "question": prompt, "reason": reason, "dependencies": [],
                            })
                            question["dependencies"].append({
                                "theory_id": theory.id, "theory_version": theory.version, "element_id": element.id,
                                "authority_passages": [row["passage_id"] for row in binding],
                            })
                    for assertion, relationship in zip(rows, relationships, strict=True):
                        source_id = getattr(assertion.source, "evidence_id", None)
                        mapping = ElementMatterMapping(
                            matter_id=matter.id, matter_revision=matter.revision, theory_id=theory.id,
                            theory_version=theory.version, element_id=element.id, target=assertion.target,
                            assertion_id=assertion.id, evidence_id=source_id, relationship=relationship,
                        )
                        contexts[mapping] = status
                        candidates.append(mapping)
                status = "reference_analysis" if any(row["currentness"]["status"] != "current_as_of" for row in binding) else "dated_analysis"
                elements.append({
                    "id": element.id, "label": element.label, "description": element.description, "kind": element.kind,
                    "parent": element.parent, "burden": element.burden, "standard": element.standard,
                    "status": status, "authority": binding, "gaps": gaps, "evidence": [],
                })
            complete = bool(elements) and all(row["status"] != "authority_unresolved" for row in elements)
            theories.append({
                "id": theory.id, "version": theory.version, "jurisdiction": theory.jurisdiction,
                "legal_area": theory.legal_area, "label": theory.label if complete else None,
                "plain_language_label": theory.plain_language_label if complete else None,
                "kind": theory.kind, "review": theory.review, "related_theory": theory.related_theory if complete else None,
                "procedural_reference": theory.procedural_reference if complete else None,
                "status": ("authority_unresolved" if not complete else "reference_analysis"
                           if any(row["status"] == "reference_analysis" for row in elements) else "dated_analysis"),
                "logic": theory.logic if complete else None, "elements": elements,
                "limitations": list(theory.limitations) + list(limits),
            })
        if request.model_assistance:
            proposer = (getattr(self.settings, "provider", ""), getattr(self.settings, "model", ""))
            selected, lineage = model_mappings(candidates, assertions, authorities, self.registry, proposer, self.verifier)
        else:
            selected = validate_mappings(candidates, candidates)
            lineage = {"verification": "catalog_relevance"}
        elements_by_key = {(theory["id"], row["id"]): row for theory in theories for row in theory["elements"]}
        for mapping in selected:
            assertion = assertions[mapping.assertion_id]
            elements_by_key[(mapping.theory_id, mapping.element_id)]["evidence"].append({
                "mapping": mapping, "posture": posture(assertion, contexts[mapping], mapping),
                "assertion": assertion, "evidence": evidence_for(assertion, evidence),
            })
        for element in elements_by_key.values():
            if "evidence" in element:
                element["evidence_postures"] = sorted({row["posture"] for row in element["evidence"]}) or [
                    "unknown" if element["gaps"] else "no_mapped_evidence"
                ]
        revisions = [self.binding_version(theory, bindings) for theory, bindings, _, _ in prepared]
        needs_event = any(link.scope == "event" for theory, _, _, _ in prepared
                          for element in theory.elements for link in element.fields)
        status = ("matter_scope_requires_confirmation" if not jurisdiction else "outside_bounded_coverage" if not theories
                  else "authority_unresolved" if all(row["status"] == "authority_unresolved" for row in theories)
                  else "event_scope_requires_confirmation" if needs_event and not event else "analysis_available")
        outputs = {
            "evidence": None, "strategy": "The engine provides a neutral comparison of the available authority and evidence.",
            "probability": "The evidence and gaps below are available for review.",
            "readiness": "The evidence below can inform a separate review of any proposed action.",
            "valuation": "The available records describe injury and other recorded facts.",
            "draft": "This report provides research and evidence for review.",
            "action": "This development tool provides an analysis for review.",
        }
        # Preserve facts separately on model failure, including both sides of a conflict.
        unmapped = []
        mapped_ids = {mapping.assertion_id for mapping in selected}
        if request.model_assistance:
            for key in dict.fromkeys(row.assertion_id for row in candidates if row.assertion_id not in mapped_ids):
                row = assertions[key]
                unmapped.append({"assertion": row, "evidence": evidence_for(row, evidence)})
        active_path = next((choice for choice in reversed(matter.choices)
                            if choice.based_on_revision + 1 == matter.revision and choice.jurisdiction == jurisdiction), None)
        goal = facts.get(Target(field="goal"), {}).get("preferred")
        return {
            "matter_id": matter.id, "matter_revision": matter.revision, "jurisdiction": jurisdiction,
            "event_id": event.id if event else None, "party_id": party, "law_as_of": request.law_as_of,
            "matter_type": matter_type, "requested_theory_ids": request.theory_ids,
            "status": status, "authority_versions": revisions, "theories": theories,
            "exact_authority": tuple(fallback.values()), "questions": list(questions.values()),
            "unmapped_matter_evidence": unmapped, "lineage": lineage, "goal": goal, "path_context": active_path,
            "boundary": BOUNDARY,
            "request_boundary": {"status": "informational_scope" if request.requested_output == "evidence" else "outside_informational_scope",
                                 "message": outputs[request.requested_output]},
            "summary": self.render(theories, status),
        }

    @staticmethod
    def binding_version(theory, bindings):
        return {"theory_id": theory.id, "version": theory.version,
                "fingerprint": fingerprint({"definition": theory.model_dump(mode="json"), "authority": bindings})}

    def active_versions(self, snapshot):
        versions = []
        packages = {}
        theories = available(self.catalog, snapshot["jurisdiction"], snapshot["matter_type"])
        for theory in theories:
            if snapshot["requested_theory_ids"] and theory.id not in snapshot["requested_theory_ids"]:
                continue
            bindings, _, _ = self.catalog.research(theory, self.settings, snapshot["law_as_of"], packages=packages)
            versions.append(self.binding_version(theory, bindings))
        return versions

    @staticmethod
    def render(theories, status):
        summaries = []
        for theory in theories:
            if theory["status"] == "authority_unresolved":
                summaries.append({"theory_id": theory["id"], "version": theory["version"], "message": AUTHORITY_LIMIT})
                continue
            statements = []
            for element in theory["elements"]:
                if "description" in element:
                    statements.append({"explanation": element["description"], "sources": [
                        {"citation": ref["citation"], "url": ref["url"], "locator": ref["locator"]}
                        for ref in element["authority"]
                    ], "evidence_postures": [POSTURE_LABELS[posture] for posture in element["evidence_postures"]],
                        "open_fields": [gap["field"].replace("_", " ") for gap in element["gaps"]]})
            summaries.append({"theory_id": theory["id"], "version": theory["version"],
                              "theory": theory["plain_language_label"], "status": theory["status"],
                              "requirements_and_evidence": statements})
        return {"theories": summaries, "matter_status": status, "evidence_scope": DATA_LIMIT,
                "authority_scope": AUTHORITY_LIMIT if any(
                    item["status"] != "dated_analysis" for item in theories) else None}
