"""Build proposed review artifacts; never update the canonical graph or commit."""

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.authority import AuthorityDocument, RepositoryAuthorityProvider, VirginiaOfficialProvider
from app.capabilities import ResearchMatter
from app.capability_compiler import CapabilityCompiler
from app.repository import RecordRepository


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jurisdiction", required=True)
    parser.add_argument("--country", default="US")
    parser.add_argument("--legal-area", required=True)
    parser.add_argument("--topic", required=True)
    parser.add_argument("--provider", choices=["repository", "virginia_official", "courtlistener_corpus"], default="repository")
    parser.add_argument("--corpus-path", type=Path, help="Existing local corpus; no network access")
    parser.add_argument("--collection", type=Path, help="Local authoritative source collection JSON; no URLs are fetched from it")
    parser.add_argument("--output", required=True, type=Path, help="New review directory outside canonical data")
    parser.add_argument("--previous", type=Path, help="Previous bundle.json for refresh comparison")
    parser.add_argument("--propose-knowledge", action="store_true",
                        help="Use the configured live model for unverified knowledge review candidates; may incur charges")
    args = parser.parse_args()
    target = args.output.resolve()
    if target.exists() or any(target == (ROOT / d).resolve() or (ROOT / d).resolve() in target.parents for d in ("data", "schemas", "app", ".git", "tests")):
        parser.error("output must be a new, separate review directory")
    repository = RecordRepository()
    matter = ResearchMatter(country=args.country, state=args.jurisdiction, legal_area=args.legal_area, topics=[args.topic])
    try:
        if args.collection:
            if args.collection.stat().st_size > 4 * 1024 * 1024:
                raise ValueError("collection_limit")
            raw = json.loads(args.collection.read_text(encoding="utf-8"))
            documents = [AuthorityDocument(d["source"], tuple(d.get("passages", [])), d["text"]) for d in raw]
        else:
            if args.provider == "courtlistener_corpus":
                from app.corpus_store import SQLiteCorpusStore
                from app.courtlistener_authority import LocalCorpusAuthorityProvider
                if not args.corpus_path or not args.corpus_path.is_file():
                    raise ValueError("existing_corpus_required")
                with SQLiteCorpusStore(args.corpus_path) as store:
                    provider = LocalCorpusAuthorityProvider(store)
                    documents = [provider.fetch(sid) for sid in provider.search(matter, limit=12)]
            else:
                provider = RepositoryAuthorityProvider(repository) if args.provider == "repository" else VirginiaOfficialProvider(repository)
                documents = [provider.fetch(sid) for sid in provider.search(matter)]
        previous = json.loads(args.previous.read_text(encoding="utf-8")) if args.previous else None
        bundle = CapabilityCompiler(repository).compile(matter, documents, previous=previous)
        if args.propose_knowledge:
            from app.config import Settings
            from app.knowledge_proposals import propose_knowledge
            from app.models.base import GenerationConfig
            settings = Settings.from_environment()
            if settings.provider not in {"openai", "anthropic"}:
                raise ValueError("explicit_live_model_required")
            config = GenerationConfig(provider=settings.provider, model=settings.model)
            bundle = propose_knowledge(bundle, settings.registry(), config)
            bundle["report"]["review_required"].append("Unverified model knowledge candidates and their evidence bindings")
    except Exception:
        print("Capability compilation failed safely. Check collection structure, authority access, source metadata and evidence links.", file=sys.stderr)
        return 1
    target.mkdir(parents=True)
    (target / "bundle.json").write_text(json.dumps(bundle, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    report = bundle["report"]
    (target / "REVIEW.md").write_text("# Proposed capability review\n\nStructural checks passed; no legal approval or currentness certification.\n\n" +
                                     "\n".join("- " + item for item in report["review_required"] + report["support_gaps"]) +
                                     ("\n\nKnowledge proposal: " + json.dumps(report["knowledge_proposal"])
                                      if args.propose_knowledge else "") +
                                     "\n\nRefresh: " + json.dumps(report["refresh"]) + "\n", encoding="utf-8")
    print(f"Wrote proposed review artifacts to {target}; {len(bundle['legal_rules'])} extractive candidate rules. No records promoted.")
    if args.propose_knowledge:
        status = report["knowledge_proposal"]["status"]
        print(f"Knowledge proposal status: {status}; semantic review pending.")
        return 0 if status == "proposed" else 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
