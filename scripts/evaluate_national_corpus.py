"""Run labeled retrieval checks against the documented bounded live corpus."""

import json
from datetime import date
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.national_corpus import CorpusQuery
from app.national_corpus_store import SQLiteNormalizedCorpus


POSITIVES = (
    ("olrc_title_one", CorpusQuery("US", "statute", citation="1 USC 1"), "1 U.S.C. § 1"),
    ("historical_cfr", CorpusQuery("US", "regulation", citation="1 CFR 1.1", currentness="historical"), "1 CFR 1.1"),
    ("federal_reporter", CorpusQuery("US", "opinion", citation="347 U.S. 483"), "347 U.S. 483"),
    ("virginia_landlord", CorpusQuery("US-VA", "statute", citation="Va. Code § 55.1-1220"), "Va. Code § 55.1-1220"),
    ("virginia_common_law", CorpusQuery("US-VA", "statute", text="common law england"), "Va. Code § 1-200"),
    ("maryland_repairs", CorpusQuery("US-MD", "statute", citation="Md. Code, Real Prop. § 8-211"), "Md. Code, Real Prop. § 8-211"),
    ("maryland_constitution", CorpusQuery("US-MD", "constitution", citation="Md. Decl. of Rts. art. 24"), "Md. Decl. of Rts. art. 24"),
    ("florida_maintenance", CorpusQuery("US-FL", "statute", citation="Fla. Stat. § 83.51"), "Fla. Stat. § 83.51"),
    ("florida_constitution", CorpusQuery("US-FL", "constitution", citation="Fla. Const. art. I, § 2"), "Fla. Const. art. I, § 2"),
    ("new_york_habitability", CorpusQuery("US-NY", "statute", citation="N.Y. Real Prop. Law § 235-b"), "N.Y. Real Prop. Law § 235-b"),
    ("new_york_constitution", CorpusQuery("US-NY", "constitution", citation="N.Y. Const. art. I, § 6"), "N.Y. Const. art. I, § 6"),
    ("california_current", CorpusQuery("US-CA", "statute", citation="Cal. Civ. Code § 1941.1", currentness="current",
                                      as_of=date(2026, 11, 9)), "Cal. Civ. Code § 1941.1"),
    ("california_rule", CorpusQuery("US-CA", "court_rule", citation="Cal. Rules of Court, rule 8.1115"), "Cal. Rules of Court, rule 8.1115"),
    ("repeal_marker", CorpusQuery("US", "statute", citation="44 U.S.C. § 1337", currentness="repealed"), "44 U.S.C. § 1337"),
    ("register_final", CorpusQuery("US", "register_document", citation="FR Doc. 2026-01868"), "FR Doc. 2026-01868"),
    ("register_notice", CorpusQuery("US", "register_document", citation="FR Doc. 2026-01841"), "FR Doc. 2026-01841"),
    ("register_proposed", CorpusQuery("US", "register_document", citation="FR Doc. 2026-01844", currentness="proposed"),
     "FR Doc. 2026-01844"),
)
NEGATIVES = (
    ("wrong_state", CorpusQuery("US-MD", "statute", citation="Va. Code § 55.1-1220")),
    ("federal_only", CorpusQuery("US", "statute", citation="Va. Code § 1-200")),
    ("wrong_type", CorpusQuery("US", "statute", citation="1 CFR 1.1", currentness="historical")),
    ("historical_as_current", CorpusQuery("US", "regulation", citation="1 CFR 1.1", currentness="current")),
    ("unresolved_as_current", CorpusQuery("US", "opinion", citation="347 U.S. 483", currentness="current")),
    ("combined_as_majority", CorpusQuery("US", "opinion", citation="347 U.S. 483", opinion_roles=("lead", "majority", "unanimous"))),
    ("fabricated_citation", CorpusQuery("US", "statute", citation="999 USC 99999")),
    ("repealed_as_current", CorpusQuery("US", "statute", citation="44 U.S.C. § 1337", currentness="current",
                                       as_of=date(2026, 11, 9))),
    ("register_as_regulation", CorpusQuery("US", "regulation", citation="FR Doc. 2026-01868")),
    ("proposal_as_regulation", CorpusQuery("US", "regulation", citation="FR Doc. 2026-01844", currentness="proposed")),
    ("california_unverified_date", CorpusQuery("US-CA", "statute", citation="Cal. Civ. Code § 1941.1",
                                              currentness="current", as_of=date(2026, 11, 12))),
    ("florida_constitution_as_statute", CorpusQuery("US-FL", "statute", citation="Fla. Const. art. I, § 2")),
    ("ny_text_in_maryland", CorpusQuery("US-MD", "statute", citation="N.Y. Real Prop. Law § 235-b")),
)


def evaluate(store):
    positives = []
    for name, query, expected in POSITIVES:
        hits = store.search(query)
        rank = next((i for i, hit in enumerate(hits, 1) if hit["citation"] == expected), None)
        precision = {str(k): len({hit["citation"] for hit in hits[:k] if hit["citation"] == expected}) / k for k in (1, 3)}
        positives.append({"label": name, "target_rank": rank, "precision_at": precision})
    negatives = [{"label": name, "results": len(store.search(query))} for name, query in NEGATIVES]
    return {
        "corpus": store.stats(), "positive_checks": positives, "negative_checks": negatives,
        "precision_at_1": sum(row["target_rank"] == 1 for row in positives) / len(positives),
        "precision_at_3": sum(row["precision_at"]["3"] for row in positives) / len(positives),
        "negative_leaks": sum(row["results"] for row in negatives),
    }


if __name__ == "__main__":
    database = Path(__file__).resolve().parents[1] / ".local" / "national-corpus" / "corpus.sqlite3"
    if not database.is_file():
        sys.exit("Build the documented live corpus before running this evaluation.")
    with SQLiteNormalizedCorpus(database) as store:
        result = evaluate(store)
    print(json.dumps(result, indent=2))
    sys.exit(int(result["precision_at_1"] < 1 or result["negative_leaks"] > 0))
