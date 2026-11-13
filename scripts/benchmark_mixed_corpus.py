"""Scale test using replicated shapes from the verified local source corpus."""

from dataclasses import replace
import json
from pathlib import Path
import sqlite3
import sys
from tempfile import TemporaryDirectory
from time import perf_counter
import tracemalloc

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.national_corpus import AuthorityVersion, CorpusQuery, Observation, Source, SourceRelationship
from app.national_corpus_store import SQLiteNormalizedCorpus


class ReplicatedShapes:
    def __init__(self, family, seeds):
        self.seeds = seeds
        self.source = Source(
            f"benchmark_{family}", "benchmark.invalid", family, ("US", "US-VA", "US-MD", "US-FL", "US-NY", "US-CA"),
            False, "synthetic replication of real normalized record shapes", "/local", "fixture",
            "benchmark", "internal test", "source corpus", "preserves historical flag only", "1",
        )

    def source_url(self, selector):
        return f"https://benchmark.invalid/local/{selector}"

    def normalize(self, selector, raw):
        for index in range(int(raw)):
            seed = self.seeds[index % len(self.seeds)]
            key = f"{selector}-{index}"
            payload = seed.model_dump() | {
                "identity_namespace": self.source.name, "identity_key": key, "citation": f"Fixture {key}",
                "alternate_citations": (), "text": f"benchmarker{key.replace('-', 'x')} {seed.text[:3000]}",
                "currentness": "proposed" if seed.document_kind == "proposed_rule" else "unresolved",
                "current_as_of": None, "currentness_basis": None, "repealed_on": None,
            }
            yield Observation(AuthorityVersion(**payload), key, f"fixture row {index}", f"Fixture {key}",
                              (SourceRelationship("part_of", f"fixture:{selector}"),))


def benchmark(source_path, scale=30000):
    with SQLiteNormalizedCorpus(source_path, read_only=True) as store:
        shapes = {}
        for family in ("statute", "regulation", "opinion", "register_document", "constitution", "court_rule"):
            rows = store.connection.execute("SELECT payload FROM corpus_versions WHERE authority_type=? ORDER BY version_id LIMIT 25",
                                            (family,))
            shapes[family] = [AuthorityVersion.model_validate_json(row[0]) for row in rows]
            if not shapes[family]:
                raise ValueError(f"missing benchmark family: {family}")
    if scale < len(shapes) or scale > 50000:
        raise ValueError("benchmark scale must be between 6 and 50000")
    tracemalloc.start()
    with TemporaryDirectory(prefix="pro-one-mixed-") as directory:
        database = Path(directory) / "mixed.sqlite3"
        with SQLiteNormalizedCorpus(database) as store:
            started = perf_counter()
            edges = count = 0
            adapters = []
            for index, (family, seeds) in enumerate(shapes.items()):
                adapter = ReplicatedShapes(family, seeds)
                amount = scale // len(shapes) + int(index < scale % len(shapes))
                selector = str(index)
                raw = str(amount).encode()
                result = store.ingest(adapter, selector, raw)
                edges += result["relationships_created"]
                count += result["records"]
                adapters.append((adapter, selector, raw))
            ingest = perf_counter() - started
            refresh_start = perf_counter()
            for adapter, selector, raw in adapters:
                assert store.ingest(adapter, selector, raw)["unchanged_snapshot"]
            refresh = perf_counter() - refresh_start
            timings = []
            for adapter, selector, raw in adapters:
                for index in range(0, int(raw), max(1, int(raw) // 20)):
                    seed = adapter.seeds[index % len(adapter.seeds)]
                    query = CorpusQuery(seed.jurisdiction, adapter.source.authority_type,
                                        text=f"benchmarker{selector}x{index}",
                                        currentness="proposed" if seed.document_kind == "proposed_rule" else "unresolved")
                    start = perf_counter()
                    hits = store.search(query)
                    timings.append(perf_counter() - start)
                    assert [hit["citation"] for hit in hits] == [f"Fixture {selector}-{index}"]
                    assert not store.search(replace(query, jurisdiction="US-ZZ"))
            assert count == edges == scale
            _, peak = tracemalloc.get_traced_memory()
            page_count = store.connection.execute("PRAGMA page_count").fetchone()[0]
            page_size = store.connection.execute("PRAGMA page_size").fetchone()[0]
        tracemalloc.stop()
    return {
        "replicated_records": count, "authority_families": len(shapes), "relationships": edges,
        "ingest_and_index_seconds": round(ingest, 3), "records_per_second": round(count / ingest),
        "unchanged_refresh_ms": round(refresh * 1000, 2), "database_bytes": page_count * page_size,
        "python_traced_peak_bytes": peak, "queries": len(timings),
        "retrieval_p95_ms": round(sorted(timings)[(95 * len(timings) - 1) // 100] * 1000, 3),
    }


if __name__ == "__main__":
    path = Path(__file__).resolve().parents[1] / ".local/national-corpus/corpus.sqlite3"
    print(json.dumps(benchmark(path), indent=2))
