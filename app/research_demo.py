"""Explicit offline contract demonstration; never masquerades as a live API/model.

Reconstructs API-shaped excerpt records from the repository's checked official
opinions. Cluster identities were checked on public CourtListener pages; docket
and individual-opinion identifiers below are SYNTHETIC. These are not downloaded
CourtListener records or complete opinions. Never persist them in a live corpus.
"""

from copy import deepcopy
from html import escape
import time
from app.capabilities import ResearchMatter
from app.corpus_store import SQLiteCorpusStore
from app.courtlistener_models import Court, Docket, Cluster, Opinion, CaseBundle
from app.courtlistener_authority import LocalCorpusAuthorityProvider
from app.generation import GenerationService
from app.legal_research import GeneralLegalResearchService
from app.models.base import GenerationConfig, ModelResponse
from app.models.registry import ProviderRegistry
from app.models.testing import valid_draft
from app.rendering import ResponseRenderingService
from app.research_synthesis import ResearchSynthesisService


DEMO_NOTICE = "Offline reconstructed CourtListener example. Synthetic docket/opinion IDs, excerpt-only records and deterministic model fixtures; no live API or AI verification. Human legal review and currentness checks remain pending."
DEMO_STATEMENTS = (
    "A wet floor alone does not establish a store's liability. The duty described here is ordinary care to keep premises reasonably safe for an invitee; the quoted warning rule concerns an unsafe condition known to the owner and unknown to the visitor, with an exception for an open and obvious danger. What the visitor could reasonably see and whether ordinary care was exercised remain factual questions.",
    "How a condition was created can matter to the notice analysis. In the cleaning-method example, the inference that the owner created the hazard depended on the jury accepting that theory. A dissent disputed the cleaning and notice inferences, and the procedural ruling did not decide liability after trial. For a wet-floor question, evidence about cleaning and what caused the fall may therefore matter; these excerpts do not establish who created this floor's condition, notice, causation, damages or an outcome.",
)


def demo_bundles(repository):
    for index, (sid, cluster, citation, day) in enumerate((
        ("va-fultz-delhaize", 1058333, "278 Va. 84", "2009-06-04"),
        ("va-austin-shoneys", 1060050, "254 Va. 134", "1997-06-06"),
    )):
        # Source IDs are canonical repository IDs, not external relationships.
        source = repository.get("sources", sid)
        if source is None:
            source = next(s for s in repository.records["sources"].values() if ("Fultz" if index == 0 else "Austin") in s["title"])
        texts = [p["text"] for p in repository.records["source_passages"].values() if p["source_id"] == source["id"]]
        docket, opinion = 990000001 + index, 990000101 + index
        raw_cluster = {"id": cluster, "docket": docket, "case_name": source["title"], "date_filed": day,
                       "precedential_status": "Published", "citations": [citation], "sub_opinions": [opinion],
                       "posture": "Excerpt-only reconstructed majority analysis; Austin reviewed a motion to strike, not liability after trial."}
        yield CaseBundle(court=Court.normalize({"id": "va", "full_name": "Supreme Court of Virginia"}),
            docket=Docket.normalize({"id": docket, "court": "va", "docket_number": "SYNTHETIC-FIXTURE", "case_name": source["title"]}),
            cluster=Cluster.normalize(raw_cluster),
            opinions=[Opinion.normalize({"id": opinion, "cluster": cluster, "type": "020lead",
                "html_with_citations": "".join(f'<p id="fixture-p{i+1}">{escape(text)}</p>' for i, text in enumerate(texts))})], origin="fixture")


class DemoSynthesisProvider:
    """Known fixed fixture proposer and separately called fixture verifier.

    This is integration proof, not evidence of an LLM's semantic accuracy. The
    verifier accepts only fixed statements against the exact fixture evidence
    snapshot captured before any provider call; arbitrary text is unsupported.
    """
    def __init__(self, package):
        self.expected = {p["id"]: p["text"] for p in package["grounding"]["passages"]}
        self.jurisdiction = deepcopy(package["user_context"]["jurisdiction_scope"])
        self.calls = []

    def generate(self, request):
        purpose = request.metadata.get("purpose")
        self.calls.append(purpose or "render")
        if purpose == "claim_proposal":
            support = [{"passage_id": pid, "relationship": "supports"} for pid in self.expected]
            output = {"claims": [{"statement": text, "issue": "premises_liability", "support": support,
                                  "jurisdiction": self.jurisdiction} for text in DEMO_STATEMENTS]}
        elif purpose == "claim_verification":
            data = request.grounded_package
            actual = {p["passage_id"]: p["text"] for p in data["cited_evidence"]}
            valid = (set(data) == {"candidate", "cited_evidence", "relevant_metadata"}
                     and data["candidate"]["statement"] in DEMO_STATEMENTS and actual == self.expected
                     and data["candidate"]["jurisdiction"] == self.jurisdiction)
            output = {"result": "entailed" if valid else "unsupported", "passage_ids": list(actual),
                      "missing_qualifications": [], "unsupported_fragments": [] if valid else ["unknown fixture proposition"]}
        else:
            output = valid_draft(request)
        return ModelResponse(request.provider, request.model, True, output=output)


def run_research_demo(repository):
    with SQLiteCorpusStore() as store:
        for bundle in demo_bundles(repository):
            store.ingest(bundle)
            store.save_verification({"citation": bundle.cluster.citations[0], "cluster": bundle.cluster.id,
                                     "name": bundle.cluster.name, "origin": "fixture"})
        service = GeneralLegalResearchService(repository, providers=[LocalCorpusAuthorityProvider(store)])
        assembled = service.assemble(ResearchMatter(country="US", state="Virginia", legal_area="torts", topics=["premises_liability"]), force_general=True)
        if not assembled["package"]:
            return {"status": assembled["status"], "response": None}
        package = assembled["package"]
        # These are previously checked canonical conflict notes, not fabricated
        # dissent text or an assertion about live provider role segmentation.
        conflicts = sorted({c for p in repository.records["source_passages"].values()
                            if "Austin" in p["title"] for c in p.get("conflicts", [])})
        for p in package["grounding"]["passages"]:
            if "Austin" in p["title"]:
                p["conflicts"] = conflicts
        package["response_plan"]["limitations"] = sorted(set(package["response_plan"]["limitations"] + conflicts))
        package["response_plan"]["required_disclosures"].append(DEMO_NOTICE)
        adapter = DemoSynthesisProvider(package)
        registry = ProviderRegistry()
        registry.register("fixture", adapter, {"offline-contract-demo"})
        config = GenerationConfig(provider="fixture", model="offline-contract-demo")
        package = ResearchSynthesisService(registry).prepare(package, config)
        started = time.perf_counter()
        generated = GenerationService(registry).generate(package, config)
        generation_ms = 1000 * (time.perf_counter() - started)
        started = time.perf_counter()
        response = ResponseRenderingService().render(generated, package, config)
        return {"status": "answered" if response else "rejected", "response": response,
                "synthesis": package.get("synthesis"), "corpus": store.stats(), "fixture_calls": adapter.calls,
                "validation": generated["validation"], "timings": {"generation_ms": generation_ms,
                    "render_validation_ms": 1000 * (time.perf_counter() - started)}}
