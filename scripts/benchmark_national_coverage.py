"""Exercise the real corpus store across all registered scopes with labeled synthetic data."""
import json
from pathlib import Path
from statistics import median
import sys
from tempfile import TemporaryDirectory
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.jurisdictions import registry
from app.national_corpus import AuthorityVersion, CorpusQuery, Observation, Source, SourceRelationship
from app.national_corpus_store import SQLiteNormalizedCorpus


class SyntheticPublication:
    def __init__(self, owner, kind):
        self.owner = owner
        self.source = Source("benchmark_" + owner.id, "example.invalid", kind, (owner.id,), False,
                             "Synthetic fixture", "/", "JSON", "offline", "Synthetic", "Benchmark",
                             "Historical fixture", "1", refresh_supported=False)

    def source_url(self, selector):
        return "https://example.invalid/" + self.owner.id + "/" + selector

    def normalize(self, selector, raw):
        for number in json.loads(raw)["sections"]:
            version = AuthorityVersion(
                jurisdiction=self.owner.id, sovereign=self.owner.kind, authority_type=self.source.authority_type,
                identity_namespace="synthetic_benchmark", identity_key=str(number), citation=f"Fixture § {number}",
                title="Synthetic retrieval test", edition="fixture", text=f"Synthetic marker{number} in {self.owner.id}.",
                currentness="historical",
            )
            yield Observation(version, str(number), f"fixture/{number}", version.citation,
                              (SourceRelationship("part_of", selector),))


def measure(per_scope=400):
    with TemporaryDirectory() as folder:
        db = Path(folder) / "benchmark.sqlite3"
        raw = json.dumps({"sections": list(range(per_scope))}).encode()
        with SQLiteNormalizedCorpus(db) as store:
            start = perf_counter()
            providers = [SyntheticPublication(row, ("statute", "regulation", "court_rule")[i % 3])
                         for i, row in enumerate(registry().values())]
            for provider in providers:
                store.ingest(provider, "fixture", raw)
            elapsed = perf_counter() - start
            samples = []
            for provider in providers:
                for i in (0, per_scope // 2, per_scope - 1):
                    q = CorpusQuery(provider.owner.id, provider.source.authority_type, citation=f"Fixture § {i}",
                                    text=f"marker{i}", currentness="historical")
                    start = perf_counter()
                    hits = store.search(q)
                    samples.append((perf_counter() - start) * 1000)
                    if len(hits) != 1 or hits[0]["jurisdiction"] != provider.owner.id:
                        raise RuntimeError("synthetic_authority_scope_leakage")
            stats = store.stats(include_relationships=True)
            count = per_scope * len(providers)
            if stats["versions"] != count or stats["source_relationships"] != count:
                raise RuntimeError("synthetic_corpus_size_mismatch")
            distribution = dict(store.connection.execute(
                "SELECT authority_type,count(*) FROM corpus_versions GROUP BY authority_type"))
        samples.sort()
        return {"dataset": "synthetic", "jurisdictions": len(providers), "records": count,
                "edges": stats["source_relationships"], "authority_types": distribution,
                "records_per_second": round(count / elapsed), "database_bytes": db.stat().st_size,
                "retrieval_p50_ms": round(median(samples), 4),
                "retrieval_p95_ms": round(samples[(95 * len(samples) - 1) // 100], 4)}


if __name__ == "__main__":
    print(json.dumps(measure(), indent=2))
