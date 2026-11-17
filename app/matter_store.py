"""Transactional, append-only SQLite revisions for the local matter feature."""
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import sqlite3

from app.matter_models import Matter
from app.matter_state import MatterError, validate

MAX_REVISIONS = 200
MAX_SNAPSHOT_BYTES = 512 * 1024
LEDGER_RECORDS = ("messages", "evidence", "parties", "identities", "events", "assertions", "gaps",
                  "corrections", "disputes", "choices")


def now():
    return datetime.now(timezone.utc)


class RevisionConflict(MatterError):
    pass


class MatterNotFound(MatterError):
    pass


class MatterStore:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Restrict new files on POSIX. On Windows, use a user-private parent ACL.
        self.path.touch(mode=0o600, exist_ok=True)
        with closing(self.connect()) as connection, connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS matter_revisions (
                    matter_id TEXT NOT NULL, revision INTEGER NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY(matter_id, revision)
                ) WITHOUT ROWID
            """)

    def connect(self):
        return sqlite3.connect(self.path, timeout=5)

    @staticmethod
    def read(connection, matter_id, revision=None):
        query = "SELECT revision, payload FROM matter_revisions WHERE matter_id = ?"
        params = (str(matter_id),)
        if revision is None:
            query += " ORDER BY revision DESC LIMIT 1"
        else:
            query += " AND revision = ?"
            params += (revision,)
        row = connection.execute(query, params).fetchone()
        if row is None:
            raise MatterNotFound("matter_or_revision_not_found")
        matter = Matter.model_validate_json(row[1])
        if str(matter.id) != str(matter_id) or matter.revision != row[0]:
            raise MatterError("revision_identity_mismatch")
        return validate(matter)

    def get(self, matter_id, revision=None):
        with closing(self.connect()) as connection:
            return self.read(connection, matter_id, revision)

    @staticmethod
    def append(connection, matter):
        validate(matter)
        payload = matter.model_dump_json()
        if len(payload.encode("utf-8")) > MAX_SNAPSHOT_BYTES or matter.revision >= MAX_REVISIONS:
            raise MatterError("matter_limit_reached")
        connection.execute("INSERT INTO matter_revisions VALUES (?, ?, ?)",
                           (str(matter.id), matter.revision, payload))
        return matter

    def create(self, matter):
        if matter.revision != 0 or matter.created_at != matter.updated_at:
            raise MatterError("invalid_initial_revision")
        with closing(self.connect()) as connection, connection:
            return self.append(connection, matter)

    def update(self, base, proposed):
        if proposed == base:
            return self.get(base.id, base.revision)
        if (proposed.id != base.id or proposed.revision != base.revision + 1
                or proposed.created_at != base.created_at or proposed.updated_at < base.updated_at
                or any(getattr(proposed, name)[:len(getattr(base, name))] != getattr(base, name)
                       for name in LEDGER_RECORDS)):
            raise MatterError("invalid_revision")
        with closing(self.connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            if self.read(connection, base.id) != base:
                raise RevisionConflict("revision_conflict")
            return self.append(connection, proposed)
