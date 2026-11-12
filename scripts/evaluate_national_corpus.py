"""Run labeled retrieval checks against the documented bounded live corpus."""

import json
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
)
NEGATIVES = (
    ("wrong_state", CorpusQuery("US-MD", "statute", citation="Va. Code § 55.1-1220")),
    ("federal_only", CorpusQuery("US", "statute", citation="Va. Code § 1-200")),
    ("wrong_type", CorpusQuery("US", "statute", citation="1 CFR 1.1", currentness="historical")),
    ("historical_as_current", CorpusQuery("US", "regulation", citation="1 CFR 1.1", currentness="current")),
    ("unresolved_as_current", CorpusQuery("US", "opinion", citation="347 U.S. 483", currentness="current")),
    ("combined_as_majority", CorpusQuery("US", "opinion", citation="347 U.S. 483", opinion_roles=("lead", "majority", "unanimous"))),
    ("fabricated_citation", CorpusQuery("US", "statute", citation="999 USC 99999")),
)


def evaluate(store):
    positives = []
    for name, query, expected in POSITIVES:
        hits = store.search(query)
        rank = next((i for i, hit in enumerate(hits, 1) if hit["citation"] == expected), None)
        positives.append({"label": name, "target_rank": rank})
    negatives = [{"label": name, "results": len(store.search(query))} for name, query in NEGATIVES]
    return {
        "corpus": store.stats(), "positive_checks": positives, "negative_checks": negatives,
        "precision_at_1": sum(row["target_rank"] == 1 for row in positives) / len(positives),
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
