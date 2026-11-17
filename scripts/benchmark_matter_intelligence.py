"""Benchmark offline matter commands against small synthetic matters."""
import argparse
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.matter_service import MatterService
from app.matter_state import procedural_facts, projection, snapshot
from app.matter_store import MatterStore


def benchmark(iterations):
    samples = {key: [] for key in ("create", "update", "ingest_document", "detect_conflict",
                                   "snapshot", "retrieve_procedural_facts")}

    def measure(key, action):
        begin = perf_counter()
        result = action()
        samples[key].append((perf_counter() - begin) * 1000)
        return result

    with TemporaryDirectory() as directory:
        service = MatterService(MatterStore(Path(directory) / "bench.sqlite3"))
        for _ in range(iterations):
            matter, _ = measure("create", lambda: service.create(
                "Virginia. I slipped in a Wendy's bathroom and broke my wrist. I want them to pay."))
            matter, _ = measure("update", lambda: service.statement(
                matter, "Date: 2026-10-03\nIncident locality: Charlottesville"))
            matter, _ = measure("ingest_document", lambda: service.upload(
                matter, b"Incident date: 2026-10-04\nDiagnosis: wrist fracture", "text/plain", "incident_report"))
            fields = measure("detect_conflict", lambda: projection(matter))
            if [row["status"] for target, row in fields.items() if target.field == "date"] != ["conflicting"]:
                raise RuntimeError("benchmark conflict was not detected")
            measure("snapshot", lambda: snapshot(matter))
            _, facts = measure("retrieve_procedural_facts", lambda: procedural_facts(
                projection(service.store.get(matter.id)), matter.parties))
            if facts["incident_locality"]["value"] != "Charlottesville":
                raise RuntimeError("benchmark fact was not retained")

    results = {}
    for key, measurements in samples.items():
        measurements.sort()
        results[key] = {
            "p50_ms": round(measurements[(iterations - 1) // 2], 3),
            "p95_ms": round(measurements[(95 * iterations + 99) // 100 - 1], 3),
        }
    return {"iterations": iterations, "synthetic": True, "operations": results}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=30, choices=range(1, 201), metavar="1..200")
    args = parser.parse_args()
    print(json.dumps(benchmark(args.iterations), indent=2))
