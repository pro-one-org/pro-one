"""Matter-scoped, immutable development claim snapshots in the existing ledger."""
from contextlib import closing
from datetime import date
import json

from fastapi.encoders import jsonable_encoder

from app.claim_catalog import fingerprint
from app.matter_state import MatterError
from app.matter_store import MAX_SNAPSHOT_BYTES, MatterNotFound, RevisionConflict, now


MAX_ANALYSES = 400


class ClaimStore:
    def __init__(self, matter_store):
        self.store = matter_store
        with closing(self.store.connect()) as connection, connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS claim_analyses (
                    matter_id TEXT NOT NULL, revision INTEGER NOT NULL,
                    analysis_id TEXT NOT NULL, created_at TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY(matter_id, analysis_id)
                ) WITHOUT ROWID
            """)

    def save(self, matter, snapshot):
        if (snapshot["matter_id"], snapshot["matter_revision"]) != (matter.id, matter.revision):
            raise MatterError("invalid_analysis_identity")
        encoded = jsonable_encoder(snapshot)
        identity = fingerprint(encoded).split(":", 1)[1]
        payload = json.dumps(encoded, separators=(",", ":"))
        if len(payload.encode("utf-8")) > MAX_SNAPSHOT_BYTES:
            raise MatterError("claim_analysis_limit")
        with closing(self.store.connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            if self.store.read(connection, matter.id) != matter:
                raise RevisionConflict("revision_conflict")
            row = connection.execute("SELECT created_at FROM claim_analyses WHERE matter_id=? AND analysis_id=?",
                                     (str(matter.id), identity)).fetchone()
            if row:
                created = row[0]
            else:
                count = connection.execute("SELECT COUNT(*) FROM claim_analyses WHERE matter_id=?",
                                           (str(matter.id),)).fetchone()[0]
                if count >= MAX_ANALYSES:
                    raise MatterError("claim_analysis_limit")
                created = now().isoformat()
                connection.execute("INSERT INTO claim_analyses VALUES (?, ?, ?, ?, ?)",
                                   (str(matter.id), matter.revision, identity, created, payload))
        return encoded | {"analysis_id": identity, "created_at": created, "freshness": "latest_snapshot"}

    def get(self, matter_id, identity, service):
        with closing(self.store.connect()) as connection, connection:
            connection.execute("BEGIN")
            latest = self.store.read(connection, matter_id)
            row = connection.execute(
                "SELECT revision, created_at, payload FROM claim_analyses WHERE matter_id=? AND analysis_id=?",
                (str(matter_id), identity)).fetchone()
        if not row:
            raise MatterNotFound("claim_analysis_not_found")
        revision, created, payload = row
        data = json.loads(payload)
        if (data["matter_id"] != str(matter_id) or data["matter_revision"] != revision
                or fingerprint(data) != "sha256:" + identity):
            raise MatterError("invalid_analysis_identity")
        stale_reasons = []
        if latest.revision != revision:
            stale_reasons.append("matter_revision_changed")
        as_of = date.fromisoformat(data["law_as_of"]) if data["law_as_of"] else None
        if service.active_versions(data | {"law_as_of": as_of}) != data["authority_versions"]:
            stale_reasons.append("theory_or_authority_changed")
        return data | {"analysis_id": identity, "created_at": created, "latest_matter_revision": latest.revision,
                       "freshness": "stale" if stale_reasons else "latest_snapshot", "stale_reasons": stale_reasons}
