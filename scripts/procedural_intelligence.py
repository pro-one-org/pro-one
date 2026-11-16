"""Validate, acquire and replay bounded procedural source snapshots."""

import argparse
import json
from pathlib import Path
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import Settings
from app.national_corpus import CorpusError, fingerprint
from app.national_corpus_store import SQLiteNormalizedCorpus
from app.generation import GenerationService
from app.procedural_authority import PUBLICATIONS, ProceduralPublicationProvider, load_catalog
from app.procedural_research import ProceduralRequest, ProceduralResearchService
from app.repository import RecordRepository


def snapshot_keys(catalog):
    return sorted({row.artifact for row in catalog.authorities.values()}
                  | {row.status_artifact for row in catalog.authorities.values() if row.status_artifact})


def read_snapshot(directory, key):
    with (directory / key).open("rb") as artifact:
        return artifact.read(PUBLICATIONS[key].max_bytes + 1)


def replay(catalog, directory, database):
    artifacts = {key: read_snapshot(directory, key) for key in snapshot_keys(catalog)}
    hashes = {key: fingerprint(raw) for key, raw in artifacts.items()}
    for row in catalog.authorities.values():
        if hashes[row.artifact] != row.artifact_hash or (row.status_artifact and hashes[row.status_artifact] != row.status_hash):
            raise CorpusError(f"procedural_publisher_bytes_changed:{row.native_id}")
    source_keys = sorted({row.artifact for row in catalog.authorities.values()})
    normalized = {}
    for key in source_keys:
        provider = ProceduralPublicationProvider(key, catalog)
        rows = list(provider.normalize(key, artifacts[key]))
        normalized[key] = (provider, len(rows))
    output = {}
    with SQLiteNormalizedCorpus(database) as store:
        for key, (provider, count) in normalized.items():
            # The bounded release has one capture per selector. Distinct editions
            # use distinct reviewed artifacts or are retained by corpus snapshot ID.
            captured = {row.captured_on for row in catalog.authorities.values() if row.artifact == key}
            if len(captured) != 1:
                raise CorpusError(f"procedural_capture_date_conflict:{key}")
            result = store.ingest(provider, key, artifacts[key], replay=True,
                                  retrieved_at=next(iter(captured)).isoformat() + "T00:00:00+00:00")
            if result["records"] != count:
                raise CorpusError(f"procedural_replay_count_mismatch:{key}")
            output[key] = result
        return {"results": output, "corpus": store.stats()}


def benchmark(iterations):
    settings = Settings()
    service = ProceduralResearchService(RecordRepository(), settings, GenerationService(settings.registry({})))
    first = ProceduralRequest(message="I slipped and fell at a restaurant in Virginia and want them to pay.")
    samples = []
    for _ in range(iterations):
        start = perf_counter()
        result = service.respond(first)
        selected = service.respond(first.model_copy(update={"choice_token": result["choice_token"],
                                                             "selected_path": "va_litigation"}))
        if selected["status"] != "procedure_explained":
            raise ValueError("procedural_benchmark_failed")
        samples.append((perf_counter() - start) * 1000)
    samples.sort()
    return {"iterations": iterations, "p50_ms": round(samples[(iterations - 1) // 2], 2),
            "p95_ms": round(samples[(95 * iterations + 99) // 100 - 1], 2)}


def main():
    catalog = load_catalog()
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("validate")
    capture = commands.add_parser("capture")
    capture.add_argument("publication", choices=snapshot_keys(catalog))
    capture.add_argument("directory", type=Path)
    replay_parser = commands.add_parser("replay")
    replay_parser.add_argument("directory", type=Path)
    replay_parser.add_argument("database", type=Path)
    bench = commands.add_parser("benchmark")
    bench.add_argument("--iterations", type=int, default=30, choices=range(1, 201), metavar="1..200")
    args = parser.parse_args()
    if args.command == "validate":
        output = {"authorities": len(catalog.authorities), "forums": len(catalog.forums),
                  "paths": len(catalog.paths), "requirements": len(catalog.requirements),
                  "jurisdictions": sorted({row.version.jurisdiction for row in catalog.authorities.values()})}
    elif args.command == "capture":
        key = args.publication
        provider = ProceduralPublicationProvider(key, catalog)
        capture = provider.fetch(key)
        found = fingerprint(capture.raw)
        pinned = {row.artifact_hash for row in catalog.authorities.values() if row.artifact == key}
        pinned.update(row.status_hash for row in catalog.authorities.values() if row.status_artifact == key)
        # Preserve changed publications as new local artifacts for comparison.
        args.directory.mkdir(parents=True, exist_ok=True)
        destination = args.directory / (key if found in pinned else f"{key}.{found}")
        if not destination.exists():
            try:
                with destination.open("xb") as artifact:
                    artifact.write(capture.raw)
            except FileExistsError:
                pass
        output = {"publication": key, "sha256": found, "reviewed_bytes": found in pinned, "requests": capture.requests}
    elif args.command == "replay":
        output = replay(catalog, args.directory, args.database)
    else:
        output = benchmark(args.iterations)
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
