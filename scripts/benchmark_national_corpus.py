"""Exercise normalized CFR parsing, storage and scoped retrieval with synthetic text."""

import argparse
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.national_corpus import CorpusQuery
from app.national_corpus_providers import PROVIDERS
from app.national_corpus_store import SQLiteNormalizedCorpus


def measure(scale):
    sections = "".join(
        f"<SECTION><SECTNO>§ 1.{i}</SECTNO><SUBJECT>Synthetic section {i}</SUBJECT>"
        f"<P>Benchmark bulletin identifier{i} for synthetic retrieval.</P></SECTION>"
        for i in range(1, scale + 1)
    )
    raw = (f"<CFRDOC><FMTR><TITLEPG><TITLENUM>Title 1</TITLENUM><REVISED>Revised as of January 1, 2023</REVISED>"
           f"</TITLEPG></FMTR><TITLE><PART><EAR>Pt. 1</EAR>{sections}</PART></TITLE></CFRDOC>").encode()
    with TemporaryDirectory(prefix="pro-one-national-") as directory:
        database = Path(directory) / "benchmark.sqlite3"
        with SQLiteNormalizedCorpus(database) as store:
            start = perf_counter()
            report = store.ingest(PROVIDERS["govinfo_cfr"], "2023/1/1", raw)
            elapsed = perf_counter() - start
            if report["records"] != scale or report["new_versions"] != scale:
                raise RuntimeError("benchmark_ingest_count_mismatch")
            latencies = []
            for i in sorted({1, scale, *range(1, scale, max(1, scale // 100))}):
                start = perf_counter()
                hits = store.search(CorpusQuery("US", "regulation", text=f"bulletin identifier{i}", currentness="historical"))
                latencies.append(perf_counter() - start)
                if [hit["citation"] for hit in hits] != [f"1 CFR 1.{i}"]:
                    raise RuntimeError("benchmark_retrieval_mismatch")
            for negative in (
                CorpusQuery("US-VA", "regulation", text="bulletin", currentness="historical"),
                CorpusQuery("US", "statute", text="bulletin", currentness="historical"),
                CorpusQuery("US", "regulation", text="bulletin", currentness="current"),
            ):
                if store.search(negative):
                    raise RuntimeError("benchmark_scope_leak")
            return {
                "synthetic_records": scale, "input_bytes": len(raw), "database_bytes": database.stat().st_size,
                "ingest_seconds": round(elapsed, 3), "records_per_second": round(scale / elapsed),
                "positive_queries": len(latencies), "scope_negatives": 3,
                "query_p95_ms": round(sorted(latencies)[(95 * len(latencies) - 1) // 100] * 1000, 3),
                "api_requests": 0, "model_calls": 0, "model_tokens": 0, "estimated_model_cost": 0,
            }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scale", type=int, default=10000)
    args = parser.parse_args()
    if not 1 <= args.scale <= 40000:
        parser.error("scale must be in 1..40000")
    print(json.dumps(measure(args.scale), indent=2))
