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
    "written_contract_limitations": ("contracts", "written_contract_limitations"),
    "oral_contract_limitations": ("contracts", "oral_contract_limitations"),
    "fault": ("torts", "fault_allocation"),
    "deposit": ("landlord_tenant", "security_deposit"),
    "wageLaw": ("employment", "wage_payment"),
    "wage_enforcement": ("employment", "wage_enforcement"),
    "negligence_duty": ("torts", "negligence_duty"),
    "consumerLaw": ("consumer", "unfair_practices"),
    "consumer_private_action": ("consumer", "private_action"),
    "debtLaw": ("consumer_debt", "debt_collection"),
    "commencement": ("civil_procedure", "commencement"),
    "service": ("civil_procedure", "service_of_process"),
    "response": ("civil_procedure", "initial_response"),
    "contract_formation": ("contracts", "contract_formation"),
    "contract_damages": ("contracts", "accepted_goods_damages"),
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
