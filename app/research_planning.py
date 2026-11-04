"""Legal concepts may be proposed; policy supplies every search boundary."""

from dataclasses import dataclass, asdict
import re
from app.courtlistener_models import COURT_POLICY


TOPIC_TERMS = {
    "premises_liability": ("premises liability business invitee", "actual constructive notice dangerous condition", "hazard created by premises owner", "open obvious contributory negligence"),
    "negligence": ("negligence duty breach causation ordinary care condition created",),
    "notice": ("actual constructive notice dangerous condition",),
    "contributory_negligence": ("contributory negligence ordinary care",),
    "limitations": ("personal injury limitations accrual tolling",),
    "civil_procedure": ("civil procedure summary judgment",),
}
LEGAL_VOCABULARY = set(" ".join(q for queries in TOPIC_TERMS.values() for q in queries).split()) | {"wet", "floor", "store", "reasonable", "care"}


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
        issues = tuple(t for t in matter.topics if t in TOPIC_TERMS)
        queries = list(dict.fromkeys(q for topic in issues for q in TOPIC_TERMS[topic]))[:4]
        for suggestion in suggestions[:4]:
            words = re.findall(r"[a-z]+", suggestion.casefold())
            if words and set(words).issubset(LEGAL_VOCABULARY) and len(suggestion) <= 200 and not re.search(r"[^a-zA-Z ]", suggestion):
                queries.append(" ".join(words))
        if not queries:
            raise ValueError("research_concepts_unconfigured")
        return ResearchPlan("US", matter.state, matter.sovereign, matter.legal_area, issues, tuple(dict.fromkeys(queries))[:4], courts)
