"""Reproducible offline acquisition, health and gap reports for the national catalog."""
from collections import Counter, defaultdict
from pathlib import Path

from app.jurisdictions import ROOT, registry
from app.national_coverage import coverage, manifest
from app.national_corpus_store import SQLiteNormalizedCorpus
from app.national_govinfo_code import GovInfoCode, federal_granules
from app.national_publications import LegislativeExcerpts


def retained_observations():
    federal = GovInfoCode()
    for selector, granule in federal_granules().items():
        yield federal, selector, (ROOT / "govinfo" / (selector + ".htm")).read_bytes(), granule["retrieved_on"]
    for scope in registry():
        for selector, row in manifest(scope).get("passages", {}).items():
            provider = LegislativeExcerpts(scope, row["authority_type"])
            yield provider, selector, row["text"].encode(), row["retrieved_at"]


def build(path):
    with SQLiteNormalizedCorpus(Path(path)) as store:
        for provider, selector, raw, timestamp in retained_observations():
            store.ingest(provider, selector, raw, retrieved_at=timestamp, replay=True)
        store.check_retained_versions()
        return store.stats(include_relationships=True)


def health(scope):
    rows = []
    for key, source in manifest(scope)["sources"].items():
        observation = source.get("observation", {})
        rows.append({"jurisdiction": scope, "source_id": key, "url": source["url"],
                     "status": observation.get("health", "manual_review_required"),
                     "as_of": observation.get("retrieved_at"), "snapshot": observation.get("sha256")})
    return rows


def gaps(scope):
    row = coverage(scope)
    return [{"jurisdiction": scope, "capability": key, "status": cell["status"]}
            for key, cell in row["cells"].items() if cell["status"] != "verified_supported"]


def state_baseline():
    """Count evidence versions and jurisdiction-level capabilities independently."""
    domains = {}
    for scope, owner in registry().items():
        if owner.kind not in {"state", "district"}:
            continue
        row = coverage(scope)
        for key, cell in row["cells"].items():
            report = domains.setdefault(key, {"passages": Counter(), "capability_statuses": Counter(), "coverage_depth": Counter(),
                                               "with_passages": [], "without_passages": [], "by_authority_category": {}})
            selectors = set(cell.get("passage_selectors", ()))
            by_category = defaultdict(Counter)
            for selector in selectors:
                passage = row["passages"][selector]
                currentness = passage["currentness"]
                category = row["sources"][passage["source_id"]]["category"]
                report["passages"][currentness] += 1
                by_category[category][currentness] += 1
            for category, counts in sorted(by_category.items()):
                category_report = report["by_authority_category"].setdefault(
                    category, {"passages": Counter(), "with_passages": []}
                )
                category_report["passages"].update(counts)
                category_report["with_passages"].append(scope)
            report["capability_statuses"][cell["status"]] += 1
            report["coverage_depth"][cell["coverage_depth"]] += 1
            report["with_passages" if selectors else "without_passages"].append(scope)
    return domains


def review_queue(scope):
    return [{"jurisdiction": scope, "citation": item["citation"], "source_id": item["source_id"],
             "currentness": item["currentness"], "captured_at": item["retrieved_at"],
             "current_as_of": item.get("current_as_of"),
             "reason": ("later_currentness_requires_review" if item["currentness"] == "current_as_of"
                        else "effective_period_and_subsequent_changes_require_review")}
            for item in manifest(scope).get("passages", {}).values()]


def source_distribution():
    result = {}
    for scope in registry():
        row = manifest(scope)
        result[scope] = {"source_entries": len(row["sources"]), "court_directory_entries": len(row["court_directory"]),
                         "retained_passages": len(row.get("passages", {})),
                         "health": dict(Counter(r["status"] for r in health(scope)))}
    return result
