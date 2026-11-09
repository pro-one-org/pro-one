"""Legal concepts may be proposed; policy supplies every search boundary."""

from dataclasses import dataclass, asdict
import json
import re
from pydantic import BaseModel, ConfigDict, Field
from app.courtlistener_models import COURT_POLICY
from app.models.base import ModelRequest


RESEARCH_TOPICS = {
    "torts": {
        "premises_liability": ("premises liability business invitee", "actual constructive notice dangerous condition",
                               "hazard created by premises owner", "open obvious contributory negligence"),
        "negligence": ("negligence duty breach causation ordinary care condition created",),
        "notice": ("actual constructive notice dangerous condition",),
        "contributory_negligence": ("contributory negligence proximate cause jury", "contributory negligence ordinary care"),
        "limitations": ("personal injury limitations accrual tolling",),
    },
    "civil_procedure": {
        "civil_procedure": ("civil procedure summary judgment",),
        "summary_judgment": ("summary judgment material fact dispute motion",),
        "limitations": ("personal injury limitations accrual tolling",),
    },
    "contracts": {
        "contract_breach": ("contract breach enforceable obligation resulting damage",),
    },
    "landlord_tenant": {
        "landlord_repairs": ("landlord tenant negligent repair mold",),
    },
}


@dataclass(frozen=True)
class ResearchPlan:
    country: str
    state: str | None
    sovereign: str
    legal_area: str
    issues: tuple[str, ...]
    queries: tuple[str, ...]
    courts: tuple[str, ...]
    max_results: int = 6
    max_pages: int = 2
    graph_expansion: int = 1
    max_requests: int = 30
    max_bytes: int = 12000000
    max_seconds: int = 30
    date_from: str | None = None
    date_to: str | None = None

    def as_dict(self):
        return asdict(self)


class LegalResearchPlanner:
    def plan(self, matter, suggestions=()):
        if matter.country != "US" or not matter.legal_area:
            raise ValueError("research_jurisdiction_required")
        courts = tuple(cid for cid, (state, sovereign, _) in COURT_POLICY.items()
                       if sovereign == matter.sovereign and state == matter.state)
        if not courts:
            raise ValueError("research_courts_unconfigured")
        topic_terms = RESEARCH_TOPICS.get(matter.legal_area, {})
        issues = tuple(t for t in matter.topics if t in topic_terms)
        queries = list(dict.fromkeys(q for topic in issues for q in topic_terms[topic]))[:4]
        if not queries:
            raise ValueError("research_concepts_unconfigured")
        vocabulary = set(" ".join(queries).split())
        if matter.legal_area == "torts":
            vocabulary.update({"wet", "floor", "store", "reasonable", "care"})
        accepted = []
        for suggestion in suggestions[:4]:
            words = re.findall(r"[a-z]+", suggestion.casefold())
            if words and set(words).issubset(vocabulary) and len(suggestion) <= 200 and not re.search(r"[^a-zA-Z ]", suggestion):
                accepted.append(" ".join(words))
        queries = list(dict.fromkeys(accepted + queries))[:4]
        return ResearchPlan("US", matter.state, matter.sovereign, matter.legal_area, issues, tuple(queries), courts)


class QueryProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    queries: list[str] = Field(min_length=1, max_length=2)


class ModelResearchPlanner:
    def __init__(self, registry, config):
        self.registry, self.config = registry, config

    def plan(self, matter):
        baseline = LegalResearchPlanner().plan(matter)
        request = ModelRequest(
            self.config.provider, self.config.model, "legal_query_proposal_v1",
            "Propose at most two focused legal research queries using only the vocabulary in the provided "
            "baseline queries. Use plain words and spaces. Do not add names, facts, URLs, citations, "
            "jurisdiction, court selections or budget settings. Source policy is controlled by the server.",
            {"legal_area": baseline.legal_area, "issues": baseline.issues, "baseline_queries": baseline.queries},
            QueryProposal.model_json_schema(), {"max_output_tokens": 500}, {"purpose": "legal_query_proposal"},
        )
        try:
            response = self.registry.resolve(self.config.provider, self.config.model).generate(request)
            if not response.success or (response.provider, response.model) != (self.config.provider, self.config.model):
                return baseline
            raw = response.output
            if isinstance(raw, str):
                if len(raw) > 4000:
                    return baseline
                raw = json.loads(raw)
            proposal = QueryProposal.model_validate(raw)
            return LegalResearchPlanner().plan(matter, suggestions=proposal.queries)
        except Exception:
            return baseline
