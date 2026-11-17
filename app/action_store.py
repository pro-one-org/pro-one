"""Immutable action artifacts in the same authorized SQLite matter ledger."""
from contextlib import closing
import json

from fastapi.encoders import jsonable_encoder

from app.claim_catalog import fingerprint
from app.matter_state import MatterError
from app.matter_store import MAX_SNAPSHOT_BYTES, MatterNotFound, RevisionConflict, now


LIMIT = 600
MAX_ARTIFACT_BYTES = MAX_SNAPSHOT_BYTES * 2


class ActionStore:
    def __init__(self, ledger):
        self.ledger = ledger
        with closing(ledger.connect()) as connection, connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS legal_action_artifacts (
                    matter_id TEXT NOT NULL, revision INTEGER NOT NULL,
                    kind TEXT NOT NULL, artifact_id TEXT NOT NULL, created_at TEXT NOT NULL,
                    payload TEXT NOT NULL, PRIMARY KEY(matter_id, artifact_id)
                ) WITHOUT ROWID
            """)
            connection.execute("""
                CREATE INDEX IF NOT EXISTS legal_action_artifacts_scope
                ON legal_action_artifacts (matter_id, revision, kind, created_at)
            """)

    @staticmethod
    def prepare(matter, kind, dependencies, payload, *, actor="deterministic_engine"):
        data = jsonable_encoder(payload | {
            "schema_version": "1.0.0", "matter_id": matter.id, "matter_revision": matter.revision, "kind": kind,
            "dependencies": dependencies, "actor": actor, "model_assistance": False,
        })
        return data | {"artifact_id": fingerprint(data).split(":", 1)[1]}

    def save(self, matter, *artifacts):
        results = []
        with closing(self.ledger.connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            if self.ledger.read(connection, matter.id) != matter:
                raise RevisionConflict("revision_conflict")
            count = connection.execute("SELECT COUNT(*) FROM legal_action_artifacts WHERE matter_id=?",
                                       (str(matter.id),)).fetchone()[0]
            for artifact in artifacts:
                identity = artifact["artifact_id"]
                data = {key: value for key, value in artifact.items() if key != "artifact_id"}
                if (data["matter_id"], data["matter_revision"]) != (str(matter.id), matter.revision):
                    raise MatterError("invalid_action_artifact_scope")
                if fingerprint(data) != "sha256:" + identity:
                    raise MatterError("invalid_action_artifact_identity")
                payload = json.dumps(data, separators=(",", ":"), ensure_ascii=True)
                if len(payload) > MAX_ARTIFACT_BYTES:
                    raise MatterError("action_artifact_size_limit")
                params = (str(matter.id), identity)
                row = connection.execute("SELECT created_at FROM legal_action_artifacts WHERE matter_id=? AND artifact_id=?",
                                         params).fetchone()
                if row:
                    created = row[0]
                else:
                    count += 1
                    if count > LIMIT:
                        raise MatterError("action_artifact_count_limit")
                    created = now().isoformat()
                    connection.execute("INSERT INTO legal_action_artifacts VALUES (?, ?, ?, ?, ?, ?)",
                                       (params[0], matter.revision, data["kind"], identity, created, payload))
                results.append(artifact | {"created_at": created})
        return results

    @staticmethod
    def decode(matter_id, row):
        revision, kind, identity, created, payload = row
        data = json.loads(payload)
        if (data["matter_id"], data["matter_revision"], data["kind"], fingerprint(data)) != (
            str(matter_id), revision, kind, "sha256:" + identity
        ):
            raise MatterError("invalid_action_artifact_identity")
        return data | {"artifact_id": identity, "created_at": created}

    def record(self, matter_id, kind, identity):
        with closing(self.ledger.connect()) as connection:
            row = connection.execute("""
                SELECT revision, kind, artifact_id, created_at, payload
                FROM legal_action_artifacts WHERE matter_id=? AND kind=? AND artifact_id=?
            """, (str(matter_id), kind, identity)).fetchone()
        if not row:
            raise MatterNotFound("action_artifact_not_found")
        return self.decode(matter_id, row)

    def current(self, matter, kinds):
        with closing(self.ledger.connect()) as connection:
            rows = connection.execute(f"""
                SELECT revision, kind, artifact_id, created_at, payload
                FROM legal_action_artifacts WHERE matter_id=? AND revision=? AND kind IN ({','.join('?' for _ in kinds)})
                ORDER BY created_at, artifact_id
            """, (str(matter.id), matter.revision, *kinds)).fetchall()
        return [self.decode(matter.id, row) for row in rows]
