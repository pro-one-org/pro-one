"""Read-only coverage inspection. Directory references cannot satisfy an authority requirement."""
from collections import Counter, defaultdict
from hashlib import sha256
import re
from functools import lru_cache
import json
from urllib.parse import urlsplit

from app.jurisdictions import ROOT, jurisdiction_id, registry
from app.national_govinfo_code import federal_granules
from app.national_certifications import certified_basis

# Each capability has its own discovery dependencies. A homepage alone is never
# evidence of a rule, a form revision, a monetary amount, or a filing deadline.
CAPABILITIES = {
    "research": {"statutes": ("statutes",), "constitution": ("constitution",),
                 "cases": ("opinions",), "regulations": ("regulations",), "rules": ("civil_rules", "court_rules")},
    "substantive": {"negligence": ("negligence",), "premises": ("premises",), "fault_allocation": ("fault",),
                    "contract": ("contract", "commercial_code"), "consumer": ("consumerLaw", "consumer_agency"),
                    "landlord_tenant": ("deposit", "eviction"), "debt": ("debtLaw",), "wage": ("wageLaw", "labor_agency")},
    "negligence": {"duty": ("negligence_duty", "negligence_elements"), "breach": ("negligence_breach", "negligence_elements"),
                   "causation": ("negligence_causation", "negligence_elements"), "injury": ("negligence_injury", "negligence_elements"),
                   "premises_relationship": ("premises",), "plaintiff_fault": ("fault",)},
    "contract": {"formation": ("contract_formation", "automated_contract_formation"), "breach": ("contract_breach",),
                 "damages": ("contract_damages",), "limitations": ("written_contract_limitations", "oral_contract_limitations", "general_contract_limitations")},
    "consumer": {"statute": ("consumerLaw",), "enforcement": ("consumer_agency",),
                 "private_action": ("consumer_private_action",), "remedies": ("consumer_remedies",)},
    "housing": {"deposit": ("deposit",), "habitability": ("habitability",), "possession": ("eviction",),
                "notice": ("tenancy_notice",)},
    "debt": {"collection_law": ("debtLaw",), "forum": ("debt_forum",), "response": ("debt_response",)},
    "wages": {"payment": ("wageLaw",), "agency": ("labor_agency",),
              "enforcement": ("wage_enforcement",), "limitations": ("wage_limitations",)},
    "procedure": {"court_structure": ("court_directory", "judiciary"), "commencement": ("commencement",),
                  "venue": ("venue",), "service": ("service",), "response": ("response",), "fees": ("fees",),
                  "e_filing": ("e_filing",), "small_claims": ("small_claims",), "calendar": ("calendar",)},
    "deadlines": {"pi_limitations": ("pi_limitations",), "wrongful_death_limitations": ("wrongful_death_limitations",),
                  "contract_limitations": ("written_contract_limitations", "oral_contract_limitations", "general_contract_limitations"),
                  "initial_response": ("response",), "service": ("service",)},
    "forms": {"forms_index": ("forms",), "complaint": ("complaint_form",), "answer": ("answer_form",),
              "summons": ("summons_form",), "cover_sheet": ("cover_sheet_form",), "small_claim": ("small_claim_form",)},
}
ACTION_REQUIREMENTS = {
    "complaint": ("commencement", "venue", "service", "fees", "e_filing"),
    "answer": ("response", "service", "fees", "e_filing"),
    "small_claim": ("small_claims", "venue", "service", "fees"),
    "demand": (),
}


@lru_cache(maxsize=1)
def directories():
    return json.loads((ROOT / "directories.json").read_bytes())


@lru_cache(maxsize=57)
def manifest(scope):
    owner = registry()[scope]
    record = json.loads((ROOT / owner.manifest).read_bytes())
    if record["jurisdiction"] != scope or not record["sources"]:
        raise ValueError("coverage_manifest_scope_mismatch")
    sources = record["sources"]
    for key, source in sources.items():
        if (not key.startswith(f"{scope}:{source['category']}:")
                or urlsplit(source["url"]).scheme not in {"https", "http"}
                or not urlsplit(source["url"]).hostname
                or (source["directory"] and source["directory"] not in directories())):
            raise ValueError("invalid_coverage_source")
    seen = set()
    for court in record["court_directory"]:
        if (not court["id"].startswith(scope + ":court:") or court["id"] in seen
                or court["source_id"] not in sources):
            raise ValueError("invalid_court_reference")
        seen.add(court["id"])
    for lead in record["citation_leads"]:
        if lead.get("source_id") and lead["source_id"] not in sources:
            raise ValueError("invalid_citation_lead")
    for key, form in record.get("forms", {}).items():
        if (not key.startswith(scope + ":form:") or form["source_id"] not in sources
                or form["index_source_id"] not in sources or form["automated_completion"] != "disabled"):
            raise ValueError("invalid_form_reference")
    for selector, passage in record.get("passages", {}).items():
        source = sources.get(passage["source_id"])
        capture = passage["publisher_sha256"]
        identity = scope + passage["citation"] + passage["text"] + capture
        if (not source or source["title"] != passage["citation"] or not re.fullmatch("[a-f0-9]{64}", capture)
                or sha256(identity.encode()).hexdigest()[:30] != selector
                or sha256(passage["text"].encode()).hexdigest() != passage["text_sha256"]
                or passage["currentness"] not in {"unresolved", "historical", "current_as_of"}):
            raise ValueError("invalid_passage_binding")
        if passage["authority_type"] == "opinion" and (
                not passage.get("court") or not passage.get("decision_date") or not passage.get("procedural_posture")
                or passage.get("opinion_role") not in {"majority", "unanimous"}
                or passage["currentness"] != "historical"):
            raise ValueError("invalid_retained_opinion")
        if passage["currentness"] == "current_as_of":
            day, _ = certified_basis(scope, source["url"], capture, passage["publisher_path"], passage["citation"], passage["text"])
            if passage["current_as_of"] != day.isoformat() or passage["authority_type"] != "statute":
                raise ValueError("invalid_publisher_certification")
    fault = record.get("fault_allocation")
    if fault:
        binding = record.get("passages", {}).get(fault["passage_selector"])
        if (not binding or binding["source_id"] != fault["source_id"]
                or sources[binding["source_id"]]["category"] != "fault"
                or fault["currentness"] != binding["currentness"]
                or fault["regime"] not in {"contributory", "pure_comparative", "modified_comparative_50",
                                          "modified_comparative_51", "other_state_specific"}):
            raise ValueError("invalid_fault_allocation_binding")
    return record


def action_shells(scope):
    if scope not in registry() or registry()[scope].kind not in {"state", "district"}:
        return []
    record = manifest(scope)
    by_category = defaultdict(list)
    for key, item in record["sources"].items():
        by_category[item["category"]].append(key)
    evidence = defaultdict(list)
    for selector, passage in record.get("passages", {}).items():
        category = record["sources"][passage["source_id"]]["category"]
        evidence[category].append({
            "passage_selector": selector, "source_id": passage["source_id"],
            "citation": passage["citation"], "court": passage.get("court"),
            "currentness": passage["currentness"], "current_as_of": passage.get("current_as_of"),
        })
    return [{
        "id": f"{scope[3:].lower()}_{kind}_reference", "jurisdiction": scope, "version": record["version"],
        "action_type": kind, "path": "pre_suit" if kind == "demand" else "civil_response" if kind == "answer" else "civil_initiation",
        "stage": "reference", "coverage_status": "reference_only" if kind == "demand" else "local_rule_required",
        "court_selection": "not_applicable" if kind == "demand" else "user_must_identify_court",
        "party_requirements": ["attributed_legal_identity", "party_role"],
        "matter_requirements": ["resolved_governing_jurisdiction", "attributed_material_facts", "user_selected_path"],
        "claim_analysis": "verified_applicable_basis_required",
        "procedure_dependencies": {k: by_category[k] for k in deps},
        "procedure_evidence": {k: evidence[k] for k in deps},
        "court_references": by_category["judiciary"], "rules_references": by_category["civil_rules"],
        "document_strategy": "reviewed_demand_basis_required" if kind == "demand" else "resolve_mandatory_form_and_local_requirements",
        "local_rules": "not_assessed" if kind == "demand" else "local_rule_required",
        "currentness": "currentness_unresolved", "readiness": "blocked", "execution": "disabled",
    } for kind, deps in ACTION_REQUIREMENTS.items()]


def coverage(value):
    scope = jurisdiction_id(value)
    if not scope:
        raise KeyError(value)
    record = manifest(scope)
    by_category = defaultdict(list)
    for key, source in record["sources"].items():
        by_category[source["category"]].append(key)
    passages = defaultdict(list)
    for key, passage in record.get("passages", {}).items():
        passages[passage["source_id"]].append(key)
    editions = {row["source_id"]: selector for selector, row in federal_granules().items()} if scope == "US" else {}
    cells = {}
    capabilities_by_area = dict(CAPABILITIES)
    if scope == "US":
        capabilities_by_area["federal_jurisdiction"] = {"federal_question": ("federal_question",), "diversity": ("diversity",)}
    for area, capabilities in capabilities_by_area.items():
        for capability, categories in capabilities.items():
            refs = [key for category in categories for key in by_category[category]]
            leads = [row for row in record["citation_leads"] if row["category"] in categories]
            bindings = [binding for ref in refs for binding in passages[ref]]
            historical = [editions[ref] for ref in refs if ref in editions]
            has_unresolved = any(record["passages"][key]["currentness"] == "unresolved" for key in bindings)
            certified = {key: record["passages"][key]["current_as_of"] for key in bindings
                         if record["passages"][key]["currentness"] == "current_as_of"}
            only_historical = (bindings or historical) and not (has_unresolved or certified)
            cells[area + "." + capability] = {
                "status": "currentness_unresolved" if has_unresolved else "dated_passage_available" if certified else "historical_only" if only_historical else "reference_only" if refs or leads else "not_yet_supported",
                "coverage_depth": "partial" if bindings or historical else "reference_only" if refs or leads else "unsupported",
                "certified_passages_as_of": certified,
                "historical_granules": historical,
                "passage_selectors": bindings,
                "source_ids": refs, "citation_leads": leads, "currentness": "historical" if only_historical else "current_as_of" if certified and not has_unresolved else "currentness_unresolved",
            }
    if "fault_allocation" in record:
        cells["substantive.fault_allocation"]["allocation"] = record["fault_allocation"]
    shells = action_shells(scope)
    for kind in ACTION_REQUIREMENTS:
        shell = next((s for s in shells if s["action_type"] == kind), None)
        cells["action." + kind] = {"status": shell["coverage_status"] if shell else "not_yet_supported",
                                  "coverage_depth": "reference_only" if shell else "unsupported",
                                  "definition_id": shell["id"] if shell else None, "currentness": "currentness_unresolved"}
    return {"jurisdiction": scope, "name": registry()[scope].name, "kind": registry()[scope].kind,
            "coverage_version": record["version"], "cells": cells, "sources": record["sources"],
            "court_directory": record["court_directory"], "action_shells": shells, "forms": record.get("forms", {}),
            "passages": record.get("passages", {}),
            "execution": "disabled", "legal_review": "legal_review_required",
            "governing_law": "matter_specific_review_required",
            "tribal_scope": "identify_the_specific_sovereign_if_applicable"}


def summary():
    counts = Counter()
    by_status = Counter()
    by_depth = Counter()
    endpoints = set()
    version_status = Counter(historical=len(federal_granules()))
    for scope, owner in registry().items():
        row = coverage(scope)
        counts[owner.kind] += 1
        counts["manifests"] += 1
        counts["source_entries"] += len(row["sources"])
        endpoints.update(source["url"] for source in row["sources"].values())
        counts["court_directory_entries"] += len(row["court_directory"])
        counts["action_shells"] += len(row["action_shells"])
        counts["form_records"] += len(row["forms"])
        counts["retained_state_and_territorial_passages"] += len(row["passages"])
        version_status.update(p["currentness"] for p in row["passages"].values())
        counts["small_claims_source_entries"] += sum(s["category"] == "small_claims" for s in row["sources"].values())
        counts["coverage_cells"] += len(row["cells"])
        by_status.update(v["status"] for v in row["cells"].values())
        by_depth.update(v["coverage_depth"] for v in row["cells"].values())
    return {"jurisdictions": len(registry()), **counts, "unique_directory_endpoints": len(endpoints),
            "retained_authority_evidence": {"total": sum(version_status.values()),
                                            "publisher_verified_as_of": version_status["current_as_of"],
                                            "historical": version_status["historical"],
                                            "currentness_unresolved": version_status["unresolved"]},
            "coverage_statuses": dict(by_status), "coverage_depth": dict(by_depth), "execution": "disabled"}
