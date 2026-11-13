"""SQLite persistence for normalized authorities and exact source snapshots."""

from dataclasses import asdict
import json
from pathlib import Path
import re
import sqlite3

from app.corpus_store import encode, utcnow
from app.national_corpus import CorpusError, fingerprint, identity


SCHEMA = """
CREATE TABLE IF NOT EXISTS corpus_artifacts(
    hash TEXT PRIMARY KEY, raw BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS corpus_snapshots(
    id TEXT PRIMARY KEY, provider TEXT NOT NULL, selector TEXT NOT NULL,
    hash TEXT NOT NULL REFERENCES corpus_artifacts(hash), url TEXT NOT NULL,
    parser_revision TEXT NOT NULL, first_retrieved TEXT NOT NULL, last_retrieved TEXT NOT NULL,
    source_metadata TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS corpus_versions(
    version_id TEXT PRIMARY KEY, authority_id TEXT NOT NULL, jurisdiction TEXT NOT NULL,
    authority_type TEXT NOT NULL, edition TEXT NOT NULL, currentness TEXT NOT NULL,
    opinion_role TEXT, normalized_hash TEXT NOT NULL, payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS corpus_scope ON corpus_versions(jurisdiction, authority_type, currentness, edition);
CREATE INDEX IF NOT EXISTS corpus_identity ON corpus_versions(authority_id, edition);
CREATE TABLE IF NOT EXISTS corpus_observations(
    snapshot_id TEXT NOT NULL REFERENCES corpus_snapshots(id),
    version_id TEXT NOT NULL REFERENCES corpus_versions(version_id),
    native_id TEXT NOT NULL, locator TEXT NOT NULL, original_citation TEXT NOT NULL,
    PRIMARY KEY(snapshot_id, native_id)
);
CREATE INDEX IF NOT EXISTS corpus_observation_version ON corpus_observations(version_id);
CREATE TABLE IF NOT EXISTS corpus_relationships(
    snapshot_id TEXT NOT NULL, native_id TEXT NOT NULL,
    kind TEXT NOT NULL, target_native_id TEXT NOT NULL,
    PRIMARY KEY(snapshot_id, native_id, kind, target_native_id),
    FOREIGN KEY(snapshot_id, native_id) REFERENCES corpus_observations(snapshot_id, native_id)
);
CREATE TABLE IF NOT EXISTS corpus_citations(
    citation TEXT NOT NULL, version_id TEXT NOT NULL REFERENCES corpus_versions(version_id),
    PRIMARY KEY(citation, version_id)
);
CREATE TABLE IF NOT EXISTS corpus_identity_checks(
    left_snapshot TEXT NOT NULL, left_native TEXT NOT NULL,
    right_snapshot TEXT NOT NULL, right_native TEXT NOT NULL,
    classification TEXT NOT NULL, basis TEXT NOT NULL, checked_at TEXT NOT NULL,
    PRIMARY KEY(left_snapshot,left_native,right_snapshot,right_native),
    FOREIGN KEY(left_snapshot,left_native) REFERENCES corpus_observations(snapshot_id,native_id),
    FOREIGN KEY(right_snapshot,right_native) REFERENCES corpus_observations(snapshot_id,native_id)
);
CREATE VIRTUAL TABLE IF NOT EXISTS corpus_fts USING fts5(title, body);
"""


def citation_key(citation):
    return " ".join(citation.casefold().split())


class SQLiteNormalizedCorpus:
    def __init__(self, path, *, storage_limit=1024 * 1024 * 1024, read_only=False):
        address = Path(path).resolve().as_uri() + "?mode=ro" if read_only else path
        self.connection = sqlite3.connect(address, timeout=5, uri=read_only)
        try:
            self.connection.row_factory = sqlite3.Row
            self.connection.execute("PRAGMA foreign_keys=ON")
            if read_only:
                self.connection.execute("PRAGMA query_only=ON")
                return
            page_size = self.connection.execute("PRAGMA page_size").fetchone()[0]
            if storage_limit < page_size or storage_limit % page_size:
                raise ValueError("invalid_corpus_storage_limit")
            pages = storage_limit // page_size
            allowed = self.connection.execute(f"PRAGMA max_page_count={pages:d}").fetchone()[0]
            if allowed != pages:
                raise CorpusError("corpus_storage_limit_exceeded")
            self.connection.executescript(SCHEMA)
        except BaseException:
            self.connection.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.connection.close()

    def ingest(self, provider, selector, raw):
        source = provider.source
        url = provider.source_url(selector)
        if not raw or len(raw) > source.max_bytes:
            raise CorpusError("source_size_out_of_bounds")
        raw_hash = fingerprint(raw)
        snapshot = identity(source.name, selector, raw_hash, source.parser_revision)
        timestamp = utcnow()
        db = self.connection
        with db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT 1 FROM corpus_snapshots WHERE id=?", (snapshot,),
            ).fetchone()
            if existing:
                db.execute("UPDATE corpus_snapshots SET last_retrieved=? WHERE id=?", (timestamp, snapshot))
                seen = db.execute(
                    "SELECT count(*) FROM corpus_observations WHERE snapshot_id=?", (snapshot,),
                ).fetchone()[0]
                return {"snapshot": snapshot, "source_hash": raw_hash, "records": seen, "new_versions": 0,
                        "changed_records": 0, "relationships_created": 0, "unchanged_snapshot": True}
            db.execute("INSERT OR IGNORE INTO corpus_artifacts VALUES(?,?)", (raw_hash, raw))
            db.execute("INSERT INTO corpus_snapshots VALUES(?,?,?,?,?,?,?,?,?)", (
                snapshot, source.name, selector, raw_hash, url, source.parser_revision, timestamp,
                timestamp, encode(asdict(source)),
            ))
            records = added = changed = edges = 0
            for observation in provider.normalize(selector, raw):
                version = observation.version
                if (version.authority_type != source.authority_type or version.jurisdiction not in source.jurisdictions
                        or not all(value.strip() for value in (
                            observation.native_id, observation.locator, observation.original_citation,
                        ))):
                    raise CorpusError("observation_scope_or_provenance_invalid")
                if records >= 50_000:
                    raise CorpusError("snapshot_record_limit")
                existed = db.execute(
                    "SELECT 1 FROM corpus_versions WHERE authority_id=? LIMIT 1", (version.authority_id,),
                ).fetchone()
                version_id, inserted = self._write_version(version)
                try:
                    db.execute("INSERT INTO corpus_observations VALUES(?,?,?,?,?)", (
                        snapshot, version_id, observation.native_id, observation.locator, observation.original_citation,
                    ))
                except sqlite3.IntegrityError as exc:
                    raise CorpusError("duplicate_source_native_identity") from exc
                relationship_rows = [
                    (snapshot, observation.native_id, edge.kind, edge.target_native_id)
                    for edge in observation.relationships
                ]
                db.executemany("INSERT INTO corpus_relationships VALUES(?,?,?,?)", relationship_rows)
                edges += len(relationship_rows)
                records += 1
                added += inserted
                changed += bool(existed and inserted)
            if not records:
                raise CorpusError("empty_source_snapshot")
        return {"snapshot": snapshot, "source_hash": raw_hash, "records": records, "new_versions": added,
                "changed_records": changed, "relationships_created": edges, "unchanged_snapshot": False}

    def _write_version(self, version):
        version_id = version.version_id
        result = self.connection.execute("INSERT OR IGNORE INTO corpus_versions VALUES(?,?,?,?,?,?,?,?,?)", (
            version_id, version.authority_id, version.jurisdiction, version.authority_type, version.edition,
            version.currentness, version.opinion_role, version.normalized_hash, version.model_dump_json(),
        ))
        if result.rowcount:
            self.connection.execute(
                "INSERT INTO corpus_fts(rowid,title,body) VALUES(?,?,?)",
                (result.lastrowid, version.title, version.text),
            )
            self.connection.executemany(
                "INSERT OR IGNORE INTO corpus_citations VALUES(?,?)",
                [(citation_key(citation), version_id) for citation in (version.citation, *version.alternate_citations)],
            )
        return version_id, result.rowcount

    def search(self, query):
        if (not query.jurisdiction or not query.authority_type or not 1 <= query.limit <= 100
                or len(query.text) > 500 or len(query.citation) > 200 or len(query.opinion_roles) > 15
                or (query.published_from and query.published_through and query.published_from > query.published_through)):
            raise CorpusError("invalid_corpus_query")
        # All eligibility predicates apply before ranking and limiting.
        joins = []
        filters = ["v.jurisdiction=?", "v.authority_type=?", "v.currentness=?"]
        params = [query.jurisdiction, query.authority_type, query.currentness]
        if query.currentness == "current":
            if not query.as_of:
                return []
            filters.append("json_extract(v.payload, '$.current_as_of')=?")
            params.append(query.as_of.isoformat())
        rank = "v.version_id"
        if query.citation:
            joins.append("JOIN corpus_citations c ON c.version_id=v.version_id")
            filters.append("c.citation=?")
            params.append(citation_key(query.citation))
        if query.text:
            terms = re.findall(r"[^\W_]+", query.text, flags=re.UNICODE)[:20]
            if not terms:
                return []
            joins.append("JOIN corpus_fts ON corpus_fts.rowid=v.rowid")
            filters.append("corpus_fts MATCH ?")
            params.append(" AND ".join(f'"{term}"' for term in terms))
            rank = "bm25(corpus_fts, 2.0, 1.0), v.version_id"
        if query.edition:
            filters.append("v.edition=?")
            params.append(query.edition)
        if query.opinion_roles:
            placeholders = ",".join("?" for _ in query.opinion_roles)
            filters.append(f"v.opinion_role IN ({placeholders})")
            params.extend(query.opinion_roles)
        for field in ("court", "agency", "legislature"):
            value = getattr(query, field)
            if value:
                filters.append(f"json_extract(v.payload, '$.{field}')=?")
                params.append(value)
        if query.published_from:
            filters.append("json_extract(v.payload, '$.published_on')>=?")
            params.append(query.published_from.isoformat())
        if query.published_through:
            filters.append("json_extract(v.payload, '$.published_on')<=?")
            params.append(query.published_through.isoformat())
        if query.provider:
            filters.append("""EXISTS (SELECT 1 FROM corpus_observations o
                JOIN corpus_snapshots s ON s.id=o.snapshot_id WHERE o.version_id=v.version_id AND s.provider=?)""")
            params.append(query.provider)
        rows = self.connection.execute(
            f"""SELECT v.*, EXISTS (
                    SELECT 1 FROM corpus_versions other WHERE other.authority_id=v.authority_id
                    AND other.edition=v.edition AND other.normalized_hash!=v.normalized_hash
                ) AS edition_conflict
                FROM corpus_versions v {' '.join(joins)} WHERE {' AND '.join(filters)} ORDER BY {rank} LIMIT ?""",
            (*params, query.limit),
        )
        return [self._result(row) for row in rows]

    def _result(self, row):
        return {
            **json.loads(row["payload"]), "authority_id": row["authority_id"], "version_id": row["version_id"],
            "normalized_hash": row["normalized_hash"], "edition_conflict": bool(row["edition_conflict"]),
        }

    def provenance(self, version_id):
        rows = self.connection.execute("""
            SELECT s.*, o.native_id, o.locator, o.original_citation FROM corpus_observations o
            JOIN corpus_snapshots s ON s.id=o.snapshot_id WHERE o.version_id=? ORDER BY s.id, o.native_id
            """, (version_id,))
        return [{**dict(row), "source_metadata": json.loads(row["source_metadata"])} for row in rows]

    def snapshot_bytes(self, content_hash):
        row = self.connection.execute("SELECT raw FROM corpus_artifacts WHERE hash=?", (content_hash,)).fetchone()
        return row["raw"] if row else None

    def relationships(self, version_id, *, limit=100):
        if not 1 <= limit <= 1000:
            raise CorpusError("invalid_relationship_limit")
        rows = self.connection.execute("""
            SELECT s.provider, r.snapshot_id, r.native_id, r.kind, r.target_native_id
            FROM corpus_observations o
            JOIN corpus_relationships r ON r.snapshot_id=o.snapshot_id AND r.native_id=o.native_id
            JOIN corpus_snapshots s ON s.id=o.snapshot_id
            WHERE o.version_id=? ORDER BY s.id, r.kind, r.target_native_id LIMIT ?
            """, (version_id, limit))
        return [dict(row) for row in rows]

    def check_identity(self, left_version, right_version):
        from app.national_corpus_identity import compare_identity

        pairs = []
        for version_id in (left_version, right_version):
            row = self.connection.execute("SELECT * FROM corpus_versions WHERE version_id=?", (version_id,)).fetchone()
            sources = self.provenance(version_id)
            if not row or not sources:
                raise CorpusError("identity_check_requires_observed_version")
            sources.sort(key=lambda source: (source["first_retrieved"], source["id"]), reverse=True)
            pairs.append((json.loads(row["payload"]) | {"authority_id": row["authority_id"],
                          "normalized_hash": row["normalized_hash"]}, sources[0]))
        (left, left_source), (right, right_source) = sorted(pairs, key=lambda pair: (pair[1]["id"], pair[1]["native_id"]))
        if (left_source["id"], left_source["native_id"]) == (right_source["id"], right_source["native_id"]):
            raise CorpusError("identity_check_requires_distinct_observations")
        classification, basis = compare_identity(left, right, left_source, right_source)
        values = (left_source["id"], left_source["native_id"], right_source["id"], right_source["native_id"])
        with self.connection:
            self.connection.execute("INSERT OR REPLACE INTO corpus_identity_checks VALUES(?,?,?,?,?,?,?)",
                                    (*values, classification, basis, utcnow()))
        return {"classification": classification, "basis": basis, "left_snapshot": values[0], "left_native": values[1],
                "right_snapshot": values[2], "right_native": values[3]}

    def identity_checks(self, left_version, right_version):
        rows = self.connection.execute("""
            SELECT DISTINCT c.classification FROM corpus_identity_checks c
            JOIN corpus_observations l ON l.snapshot_id=c.left_snapshot AND l.native_id=c.left_native
            JOIN corpus_observations r ON r.snapshot_id=c.right_snapshot AND r.native_id=c.right_native
            WHERE (l.version_id=? AND r.version_id=?) OR (l.version_id=? AND r.version_id=?)
            """, (left_version, right_version, right_version, left_version))
        return [row[0] for row in rows]

    def stats(self):
        return dict(self.connection.execute("""
            SELECT (SELECT count(DISTINCT authority_id) FROM corpus_versions) AS authorities,
                   (SELECT count(*) FROM corpus_versions) AS versions,
                   (SELECT count(*) FROM corpus_snapshots) AS snapshots,
                   (SELECT count(*) FROM corpus_observations) AS observations
            """).fetchone())
