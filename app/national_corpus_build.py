"""Persist a bounded corpus build and checkpoint each atomic source commit."""

from dataclasses import dataclass
import json
import re
import sqlite3
from uuid import uuid4

from pydantic import ValidationError

from app.corpus_store import encode, utcnow
from app.national_corpus import AuthorityVersion, CorpusError, identity
from app.national_corpus_providers import PROVIDERS


CONFIG_VERSION = "corpus-build-v1"
HEX_ID = re.compile(r"[0-9a-f]{64}")
FIELDS = ("provider", "selector", "parser_revision", "jurisdictions", "authority_type", "pinned_snapshot")


@dataclass(frozen=True)
class BuildSelector:
    provider: str
    selector: str
    snapshot: str | None = None


class CorpusBuilds:
    def __init__(self, store):
        self.store = store
        self.db = store.connection

    def start(self, requested):
        if not 1 <= len(requested) <= 32:
            raise CorpusError("build_selector_count_out_of_bounds")
        if len({(item.provider, item.selector) for item in requested}) != len(requested):
            raise CorpusError("duplicate_build_selector")
        config = []
        for item in requested:
            provider = PROVIDERS.get(item.provider)
            if not provider or not 1 <= len(item.selector) <= 160:
                raise CorpusError("invalid_build_selector")
            provider.source_url(item.selector)
            source = provider.source
            if item.snapshot is None:
                if not source.refresh_supported:
                    raise CorpusError("build_source_requires_retained_snapshot")
            else:
                if not HEX_ID.fullmatch(item.snapshot):
                    raise CorpusError("invalid_build_snapshot")
                artifact = self.db.execute(
                    "SELECT provider,selector,parser_revision FROM corpus_snapshots WHERE id=?", (item.snapshot,),
                ).fetchone()
                if not artifact or tuple(artifact) != (item.provider, item.selector, source.parser_revision):
                    raise CorpusError("build_snapshot_selector_mismatch")
            config.append((source.name, item.selector, source.parser_revision, encode(source.jurisdictions),
                           source.authority_type, item.snapshot))
        build_id = uuid4().hex
        with self.db:
            self.db.execute("INSERT INTO corpus_builds VALUES(?,?,NULL,?,?)",
                            (build_id, utcnow(), CONFIG_VERSION, identity(CONFIG_VERSION, encode(config))))
            self.db.executemany("""INSERT INTO corpus_build_steps
                (build_id,ordinal,provider,selector,parser_revision,jurisdictions,authority_type,pinned_snapshot)
                VALUES(?,?,?,?,?,?,?,?)""",
                [(build_id, ordinal, *step) for ordinal, step in enumerate(config, 1)])
        return self.manifest(build_id)

    def _load(self, build_id):
        if not re.fullmatch(r"[0-9a-f]{32}", build_id):
            raise CorpusError("invalid_corpus_build_id")
        build = self.db.execute("SELECT * FROM corpus_builds WHERE id=?", (build_id,)).fetchone()
        rows = self.db.execute(
            "SELECT * FROM corpus_build_steps WHERE build_id=? ORDER BY ordinal", (build_id,),
        ).fetchall()
        if not build or not rows:
            raise CorpusError("corpus_build_not_found")
        config = [tuple(row[field] for field in FIELDS) for row in rows]
        if build["config_hash"] != identity(build["config_version"], encode(config)):
            raise CorpusError("corpus_build_config_mismatch")
        return build, rows

    def _proof(self, snapshot, *, verify_parse=False):
        name, selector, raw, _ = self.store.replay_artifact(snapshot)
        row = self.db.execute("SELECT hash,parser_revision,url FROM corpus_snapshots WHERE id=?", (snapshot,)).fetchone()
        if identity(name, selector, row["hash"], row["parser_revision"]) != snapshot:
            raise CorpusError("build_snapshot_identity_mismatch")
        observations = [tuple(item) for item in self.db.execute("""
            SELECT o.native_id,o.version_id,v.authority_id,o.locator,o.original_citation
            FROM corpus_observations o JOIN corpus_versions v USING(version_id)
            WHERE o.snapshot_id=? ORDER BY o.native_id""", (snapshot,))]
        edges = [tuple(item) for item in self.db.execute("""
            SELECT native_id,kind,target_native_id FROM corpus_relationships
            WHERE snapshot_id=? ORDER BY native_id,kind,target_native_id""", (snapshot,))]
        if verify_parse:
            provider = PROVIDERS.get(name)
            if (not provider or row["parser_revision"] != provider.source.parser_revision
                    or row["url"] != provider.source_url(selector)):
                raise CorpusError("build_provider_revision_changed")
            parsed = list(provider.normalize(selector, raw))
            expected_observations = sorted((item.native_id, item.version.version_id, item.version.authority_id,
                                            item.locator, item.original_citation) for item in parsed)
            expected_edges = sorted((item.native_id, edge.kind, edge.target_native_id)
                                    for item in parsed for edge in item.relationships)
            if observations != expected_observations or edges != expected_edges:
                raise CorpusError("corpus_build_replay_mismatch")
            for saved in self.db.execute("""
                SELECT v.version_id,v.authority_id,v.normalized_hash,v.payload
                FROM corpus_observations o JOIN corpus_versions v USING(version_id) WHERE o.snapshot_id=?
                """, (snapshot,)):
                version = AuthorityVersion.model_validate_json(saved["payload"])
                if (version.version_id, version.authority_id, version.normalized_hash) != (
                        saved["version_id"], saved["authority_id"], saved["normalized_hash"]):
                    raise CorpusError("corpus_build_version_mismatch")
        return {"artifact_hash": row["hash"], "observation_hash": identity(encode(observations)),
                "relationship_hash": identity(encode(edges)), "observations": len(observations),
                "relationships": len(edges)}

    def resume(self, build_id, *, max_steps=32):
        if not 1 <= max_steps <= 32:
            raise CorpusError("invalid_build_step_limit")
        build, rows = self._load(build_id)
        if build["config_version"] != CONFIG_VERSION:
            raise CorpusError("unsupported_build_config_version")
        for row in [item for item in rows if item["result_snapshot"] is None][:max_steps]:
            key = (build_id, row["ordinal"])
            provider = PROVIDERS.get(row["provider"])
            with self.db:
                attempt = self.db.execute("""UPDATE corpus_build_steps SET attempts=attempts+1
                    WHERE build_id=? AND ordinal=? AND result_snapshot IS NULL AND attempts=?""", (*key, row["attempts"]))
                if attempt.rowcount != 1:
                    raise CorpusError("corpus_build_checkpoint_changed")
            attempt_number = row["attempts"] + 1

            def checkpoint(result):
                proof = self._proof(result["snapshot"])
                outcome = {"records_discovered": result["records"], "records_ingested": 0 if result["unchanged_snapshot"] else result["records"],
                           "versions_added": result["new_versions"], "unchanged_records": result["records"] if result["unchanged_snapshot"] else result["records"] - result["new_versions"],
                           "rejected_records": 0, "relationships_added": result["relationships_created"], **proof}
                updated = self.db.execute("""UPDATE corpus_build_steps SET result_snapshot=?,result=?
                    WHERE build_id=? AND ordinal=? AND result_snapshot IS NULL AND attempts=?""",
                    (result["snapshot"], encode(outcome), *key, attempt_number))
                if updated.rowcount != 1:
                    raise CorpusError("corpus_build_checkpoint_changed")
                self.db.execute("""UPDATE corpus_builds SET completed_at=? WHERE id=? AND completed_at IS NULL
                    AND NOT EXISTS (SELECT 1 FROM corpus_build_steps WHERE build_id=? AND result_snapshot IS NULL)""",
                    (utcnow(), build_id, build_id))

            try:
                if not provider or provider.source.parser_revision != row["parser_revision"]:
                    raise CorpusError("build_provider_revision_changed")
                if row["pinned_snapshot"]:
                    _, _, raw, retrieved_at = self.store.replay_artifact(row["pinned_snapshot"])
                    self.store.ingest(provider, row["selector"], raw, retrieved_at=retrieved_at,
                                      replay=True, checkpoint=checkpoint)
                else:
                    fetched = provider.fetch(row["selector"])
                    self.store.ingest(provider, row["selector"], fetched.raw, checkpoint=checkpoint)
            except (CorpusError, ValidationError, sqlite3.Error, OSError) as exc:
                message = str(exc) if isinstance(exc, CorpusError) else ""
                if re.fullmatch(r"source_http_[1-5][0-9]{2}", message):
                    code = message
                elif isinstance(exc, sqlite3.Error):
                    code = "build_storage_failed"
                elif message == "build_provider_revision_changed":
                    code = message
                else:
                    code = "build_source_failed"
                with self.db:
                    self.db.execute("""UPDATE corpus_build_steps SET error=? WHERE build_id=? AND ordinal=?
                        AND result_snapshot IS NULL AND attempts=?""", (code, *key, attempt_number))
                break
        return self.manifest(build_id)

    def manifest(self, build_id, *, verify=False):
        build, rows = self._load(build_id)
        steps = []
        for row in rows:
            result = json.loads(row["result"]) if row["result"] else None
            snapshot = row["result_snapshot"]
            if verify and snapshot:
                proof = self._proof(snapshot, verify_parse=True)
                expected_snapshot = identity(row["provider"], row["selector"], proof["artifact_hash"], row["parser_revision"])
                if (expected_snapshot != snapshot or row["pinned_snapshot"] not in (None, snapshot)
                        or not result or any(result.get(key) != value for key, value in proof.items())):
                    raise CorpusError("corpus_build_proof_mismatch")
            steps.append({
                "ordinal": row["ordinal"], "provider": row["provider"], "selector": row["selector"],
                "parser_revision": row["parser_revision"], "jurisdictions": json.loads(row["jurisdictions"]),
                "authority_type": row["authority_type"], "pinned_snapshot": row["pinned_snapshot"],
                "snapshot": snapshot, "attempts": row["attempts"], "last_error": row["error"],
                "checkpoint": "complete" if snapshot else "failed" if row["error"] else "pending",
                "result": result,
            })
        completed = sum(step["checkpoint"] == "complete" for step in steps)
        if bool(build["completed_at"]) != (completed == len(steps)):
            raise CorpusError("corpus_build_checkpoint_inconsistent")
        failed = any(step["checkpoint"] == "failed" for step in steps)
        return {"build_id": build_id, "started_at": build["started_at"], "completed_at": build["completed_at"],
                "config_version": build["config_version"], "config_hash": build["config_hash"],
                "status": "complete" if build["completed_at"] else "failed" if failed else "partial",
                "checkpoint": {"completed": completed, "requested": len(steps)},
                "warnings": ["Failed selector ingestion is atomic. Rejected record counts are unavailable for failed artifacts."]
                if any(step["last_error"] for step in steps) else [],
                "selectors": steps}
