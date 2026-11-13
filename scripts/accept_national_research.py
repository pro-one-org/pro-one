"""Exercise source-backed Research Core packages against the bounded local corpus."""

from dataclasses import replace
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.capabilities import ResearchMatter
from app.config import Settings
from app.generation import GenerationService
from app.legal_research import GeneralLegalResearchService
from app.models.base import GenerationConfig
from app.models.registry import ProviderRegistry
from app.repository import RecordRepository
from scripts.accept_research_model import ObservedProvider


def run(normalized, courtlistener, *, live=False, federal=False):
    base = Settings.from_environment() if live else Settings()
    if base.mode != "development" or (live and base.provider == "testing"):
        raise ValueError("development_acceptance_model_required")
    settings = replace(base, authority_network="", corpus_path=str(courtlistener), normalized_corpus_path=str(normalized))
    config = GenerationConfig(provider=settings.provider, model=settings.model)
    observer = ObservedProvider(settings.registry().resolve(config.provider, config.model))
    registry = ProviderRegistry()
    registry.register(config.provider, observer, {config.model})
    repo = RecordRepository()
    areas = (
        ("virginia_mixed", "Virginia", {"statute", "court_opinion"}),
        ("maryland_statute", "Maryland", {"statute"}),
        ("florida_statute", "Florida", {"statute"}),
        ("new_york_statute", "New York", {"statute"}),
        ("california_as_of", "California", {"statute"}),
    )
    results = []
    scenarios = []
    for label, state, expected in areas[:1] if live else areas:
        fields = {"authority_status": "current", "authority_as_of": "2026-11-09"} if state == "California" else {}
        scenarios.append((label, ResearchMatter(country="US", state=state, legal_area="landlord_tenant",
                                                topics=["landlord_repairs"], authority_types=["statute", "opinion"],
                                                **fields), expected))
    if federal or not live:
        scenario = ("federal_statute_case", ResearchMatter(country="US", sovereign="federal",
                    legal_area="administrative_law", topics=["federal_register"], authority_types=["statute", "opinion"]),
                    {"statute", "court_opinion"})
        scenarios = [scenario] if live else [*scenarios, scenario]
    for label, matter, expected in scenarios:
        service = GeneralLegalResearchService(repo, settings, GenerationService(registry))
        try:
            package = service.assemble(matter)["package"]
            if not package:
                results.append({"label": label, "passed": False, "status": "no_package"})
                continue
            types = {source["source_type"] for source in package["grounding"]["sources"]}
            jurisdictions = {source["jurisdiction"]["state"] for source in package["grounding"]["sources"]}
            bindings = [c.get("corpus_provenance") for c in package["response_plan"]["citations"]]
            roles = {source.get("case_metadata", {}).get("opinion_role") for source in package["grounding"]["sources"]} - {None}
            rendered = service.respond(matter, config)
            accepted = rendered.get("response") or {}
            synthesis = rendered.get("synthesis", {})
            results.append({
                "label": label, "evidence_types": sorted(types), "jurisdictions": sorted(jurisdictions, key=str),
                "corpus_bindings": sum(bool(binding) for binding in bindings),
                "opinion_roles": sorted(roles),
                "status": rendered["status"], "synthesis_status": synthesis.get("status"),
                "verified_claims": sum(row.get("verification_status") == "independently_verified_development"
                                       for row in synthesis.get("ledger", [])),
                "passed": expected.issubset(types) and jurisdictions == {matter.state} and any(bindings)
                and (label != "federal_statute_case" or {"lead", "dissent"}.issubset(roles))
                and not package["public_execution"]["allowed"] and bool(accepted) and not accepted["publicly_approved"],
            })
        finally:
            service.close()
    if not live:
        comparison = [row for row in results if row["label"] in {"virginia_mixed", "florida_statute"}]
        results.append({"label": "virginia_florida_independent_scope", "status": "separate_scoped_responses",
                        "passed": len(comparison) == 2 and all(row["passed"] for row in comparison)
                        and {tuple(row["jurisdictions"]) for row in comparison} == {("Virginia",), ("Florida",)}})
        for label, family, topic, status, expected in (
            ("federal_statute", "statute", "federal_register", "unresolved", "evidence_ready"),
            ("federal_historical_regulation", "regulation", "federal_register", "historical", "evidence_ready"),
            ("federal_current_regulation_gap", "regulation", "federal_register", "current", "no_authoritative_support"),
            ("federal_register_proposal", "register_document", "port_of_entry", "proposed", "no_authoritative_support"),
            ("federal_register_final", "register_document", "port_of_entry", "unresolved", "evidence_ready"),
            ("uncovered_issue", "statute", "unmapped_topic", "unresolved", "no_authoritative_support"),
        ):
            matter = ResearchMatter(country="US", sovereign="federal", legal_area="administrative_law", topics=[topic],
                                    authority_types=[family], authority_status=status)
            service = GeneralLegalResearchService(repo, settings)
            try:
                outcome = service.assemble(matter)
                results.append({"label": label, "status": outcome["status"], "passed": outcome["status"] == expected})
            finally:
                service.close()
    return {"mode": "live" if live else "offline", "results": results, "calls": observer.calls,
            "passed": all(item["passed"] for item in results)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--federal", action="store_true", help="Use the federal mixed-source scenario in live mode")
    parser.add_argument("--normalized", type=Path, default=Path(".local/national-corpus/corpus.sqlite3"))
    parser.add_argument("--courtlistener", type=Path, required=True)
    args = parser.parse_args()
    if not args.normalized.is_file() or not args.courtlistener.is_file():
        parser.error("both source databases must already exist")
    result = run(args.normalized, args.courtlistener, live=args.live, federal=args.federal)
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["passed"] else 1)
