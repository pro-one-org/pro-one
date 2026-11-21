"""Expose reviewed passage identities from the national corpus to ordinary research."""
from types import SimpleNamespace
from textwrap import wrap

from app.authority import AuthorityDocument, AuthorityUnavailable, evidence_passage
from app.jurisdictions import NAME_SCOPES, registry
from app.national_corpus import identity
from app.national_corpus_research import NormalizedAuthorityProvider
from app.national_coverage import manifest
from app.national_publications import LegislativeExcerpts

# These are research topics, not interchangeable propositions. A limitations
# section must never establish the elements of negligence or contract breach.
SUBJECTS = {
    "pi_limitations": ("torts", "limitations"),
    "wrongful_death_limitations": ("torts", "wrongful_death_limitations"),
    "wrongful_death": ("torts", "wrongful_death"),
    "accrual": ("torts", "accrual"),
    "tolling": ("torts", "tolling"),
    "written_contract_limitations": ("contracts", "written_contract_limitations"),
    "oral_contract_limitations": ("contracts", "oral_contract_limitations"),
    "general_contract_limitations": ("contracts", "contract_limitations"),
    "sales_contract_limitations": ("contracts", "sales_contract_limitations"),
    "contract_accrual": ("contracts", "contract_accrual"),
    "fault": ("torts", "fault_allocation"),
    "joint_several_liability": ("torts", "joint_several_liability"),
    "tortfeasor_contribution": ("torts", "tortfeasor_contribution"),
    "deposit": ("landlord_tenant", "security_deposit"),
    "rent_payment_fees": ("landlord_tenant", "rent_payment_fees"),
    "habitability": ("landlord_tenant", "habitability"),
    "tenant_remedies": ("landlord_tenant", "tenant_remedies"),
    "eviction": ("landlord_tenant", "eviction_procedure"),
    "eviction_summons": ("landlord_tenant", "eviction_summons"),
    "tenancy_notice": ("landlord_tenant", "tenancy_notice"),
    "wageLaw": ("employment", "wage_payment"),
    "labor_agency": ("employment", "wage_agency_claim"),
    "sales_commissions": ("employment", "sales_commissions"),
    "wage_separation": ("employment", "wage_separation"),
    "wage_enforcement": ("employment", "wage_enforcement"),
    "wage_limitations": ("employment", "wage_limitations"),
    "wage_preemption": ("employment", "wage_preemption"),
    "negligence_duty": ("torts", "negligence_duty"),
    "negligence_elements": ("torts", "negligence_elements"),
    "negligence_causation": ("torts", "negligence_causation"),
    "premises": ("torts", "premises_liability"),
    "tort_damages": ("torts", "tort_damages"),
    "consumerLaw": ("consumer", "unfair_practices"),
    "consumer_private_action": ("consumer", "private_action"),
    "consumer_remedies": ("consumer", "consumer_remedies"),
    "consumer_limitations": ("consumer", "consumer_limitations"),
    "debtLaw": ("consumer_debt", "debt_collection"),
    "debt_forum": ("consumer_debt", "debt_forum"),
    "debt_pleading": ("consumer_debt", "debt_pleading"),
    "debt_judgment_proof": ("consumer_debt", "debt_judgment_proof"),
    "debt_limitations": ("consumer_debt", "debt_limitations"),
    "debt_private_action": ("consumer_debt", "debt_private_action"),
    "debt_cure_notice": ("consumer_debt", "debt_cure_notice"),
    "debt_cure_prior_defaults": ("consumer_debt", "debt_cure_prior_defaults"),
    "debt_cure_exceptions": ("consumer_debt", "debt_cure_exceptions"),
    "debt_harassment": ("consumer_debt", "debt_harassment"),
    "commencement": ("civil_procedure", "commencement"),
    "limitations_commencement": ("civil_procedure", "limitations_commencement"),
    "refiling_after_dismissal": ("civil_procedure", "refiling_after_dismissal"),
    "venue": ("civil_procedure", "venue"),
    "small_claims": ("civil_procedure", "small_claims"),
    "service": ("civil_procedure", "service_of_process"),
    "service_time_limit": ("civil_procedure", "service_time_limit"),
    "summons_issuance": ("civil_procedure", "summons_issuance"),
    "service_business_entity": ("civil_procedure", "service_on_business_entities"),
    "service_proof": ("civil_procedure", "proof_of_service"),
    "response": ("civil_procedure", "initial_response"),
    "postmotion_response": ("civil_procedure", "postmotion_response"),
    "demurrer_timing": ("civil_procedure", "demurrer_timing"),
    "amended_pleading_response": ("civil_procedure", "amended_pleading_response"),
    "pleading_contents": ("civil_procedure", "pleading_contents"),
    "answer_contents": ("civil_procedure", "answer_contents"),
    "justice_court_response": ("civil_procedure", "justice_court_response"),
    "fees": ("civil_procedure", "filing_fees"),
    "filing_cost_waiver": ("civil_procedure", "filing_cost_waiver"),
    "e_filing": ("civil_procedure", "electronic_filing"),
    "calendar": ("civil_procedure", "time_computation"),
    "contract_formation": ("contracts", "contract_formation"),
    "automated_contract_formation": ("contracts", "automated_contract_formation"),
    "electronic_transaction_consent": ("contracts", "electronic_transaction_consent"),
    "electronic_contract_form": ("contracts", "electronic_contract_form"),
    "employment_contract_formation": ("contracts", "employment_contract_formation"),
    "contract_breach": ("contracts", "contract_breach"),
    "contract_damages": ("contracts", "accepted_goods_damages"),
    "general_contract_damages": ("contracts", "general_contract_damages"),
    "sale_price_recovery": ("contracts", "sale_price_recovery"),
}


class RetainedLegislativeResearch:
    name = "retained_legislative_authority"

    def __init__(self):
        self.documents = {}

    def search(self, matter, limit=6):
        self.documents.clear()
        scope = NAME_SCOPES.get((matter.state or "").casefold())
        status = "current_as_of" if matter.authority_status == "current" else matter.authority_status
        if (matter.country != "US" or not scope or registry()[scope].kind != matter.sovereign
                or status not in {"historical", "unresolved", "current_as_of"}
                or bool(matter.authority_as_of) != (status == "current_as_of")):
            return []
        record = manifest(scope)
        for selector, row in record.get("passages", {}).items():
            source_row = record["sources"][row["source_id"]]
            area, topic = SUBJECTS.get(source_row["category"], (None, None))
            kind = row["authority_type"]
            if (area != matter.legal_area or topic not in matter.topics or row["currentness"] != status
                    or row.get("current_as_of") != matter.authority_as_of
                    or matter.agency or (matter.court and matter.court != row.get("court"))
                    or matter.authority_types and kind not in matter.authority_types):
                continue
            provider = LegislativeExcerpts(scope, kind)
            observation, = provider.normalize(selector, row["text"].encode())
            v = observation.version
            snapshot = identity(provider.source.name, selector, row["text_sha256"], provider.source.parser_revision)
            provenance = {"id": snapshot, "url": source_row["url"], "native_id": selector,
                          "first_retrieved": row["retrieved_at"], "hash": row["text_sha256"],
                          "locator": observation.locator}
            source = NormalizedAuthorityProvider._source(
                matter, SimpleNamespace(legal_area=area, issues=[topic]), v, provenance, provider.source)
            if v.court:
                source["jurisdiction"]["court"] = v.court
            if kind == "opinion":
                source["authority"]["issuing_body"] = v.court
                source["case_metadata"] = {
                    "court": v.court, "decision_date": row["decision_date"], "publication_status": "unknown",
                    "precedential_status": v.precedential_status, "procedural_posture": v.procedural_posture,
                    "subsequent_treatment": "unknown", "opinion_role": v.opinion_role,
                }
            chunks = wrap(v.text, 1000, break_long_words=False, break_on_hyphens=False)
            passages = [evidence_passage(source, text, observation.locator, [topic], suffix=f"p{i}")
                        for i, text in enumerate(chunks, 1)]
            for passage in passages:
                passage["verification"]["retrieved_on"] = row["retrieved_at"][:10]
                passage["limitations"].extend(v.limitations)
                if v.current_as_of:
                    passage["limitations"].append("Publisher certification applies as of " + v.current_as_of.isoformat() + ".")
            self.documents[source["id"]] = AuthorityDocument(source, tuple(passages), v.text)
            if len(self.documents) >= limit:
                break
        return list(self.documents)

    def fetch(self, source_id):
        if source_id not in self.documents:
            raise AuthorityUnavailable("unsupported_authority")
        return self.documents[source_id]
