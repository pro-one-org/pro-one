"""External legal corpus, separate from canonical records and conversation data.

SQLite is the initial backend. Ingestion accepts normalized bundles so REST,
bulk snapshots and a future replication source share the same write boundary.
"""

from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import re
import sqlite3
from typing import Protocol

from app.courtlistener_models import CaseBundle, Court, Docket, Cluster, Opinion


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def encode(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


class LegalCorpusStore(Protocol):
    def ingest(self, bundle: CaseBundle): ...
    def search(self, query, *, state, sovereign, courts=(), date_from=None, date_to=None, limit=12): ...
    def case(self, cluster_identifier): ...
    def stats(self): ...


class SQLiteCorpusStore:
    def __init__(self, path=":memory:"):
        self.path = str(path)
        if self.path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path, timeout=5)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.executescript("""
        CREATE TABLE IF NOT EXISTS corpus_schema(version INTEGER PRIMARY KEY);
        INSERT OR IGNORE INTO corpus_schema VALUES(1);
        CREATE TABLE IF NOT EXISTS courts(id TEXT PRIMARY KEY,state TEXT,sovereign TEXT NOT NULL,hierarchy INTEGER NOT NULL,payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS dockets(id INTEGER PRIMARY KEY,court TEXT NOT NULL REFERENCES courts(id),payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS clusters(id INTEGER PRIMARY KEY,docket INTEGER NOT NULL REFERENCES dockets(id),name TEXT NOT NULL,decision_date TEXT,publication TEXT NOT NULL,origin TEXT NOT NULL,payload TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS cluster_date ON clusters(decision_date);
        CREATE TABLE IF NOT EXISTS opinions(id INTEGER PRIMARY KEY,cluster INTEGER NOT NULL REFERENCES clusters(id),role TEXT NOT NULL,text TEXT NOT NULL,content_hash TEXT NOT NULL,first_seen TEXT NOT NULL,last_fetched TEXT NOT NULL,last_checked TEXT NOT NULL,state TEXT NOT NULL,payload TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS opinion_cluster ON opinions(cluster);
        CREATE TABLE IF NOT EXISTS opinion_versions(opinion INTEGER NOT NULL,content_hash TEXT NOT NULL,text TEXT NOT NULL,payload TEXT NOT NULL,recorded_at TEXT NOT NULL,PRIMARY KEY(opinion,content_hash));
        CREATE TABLE IF NOT EXISTS entity_versions(kind TEXT NOT NULL,id TEXT NOT NULL,content_hash TEXT NOT NULL,payload TEXT NOT NULL,recorded_at TEXT NOT NULL,PRIMARY KEY(kind,id,content_hash));
        CREATE TABLE IF NOT EXISTS citations(cluster INTEGER NOT NULL REFERENCES clusters(id),citation TEXT NOT NULL,PRIMARY KEY(cluster,citation));
        CREATE INDEX IF NOT EXISTS citation_lookup ON citations(citation);
        CREATE TABLE IF NOT EXISTS citation_edges(citing INTEGER NOT NULL,cited INTEGER NOT NULL,depth INTEGER NOT NULL,PRIMARY KEY(citing,cited));
        CREATE INDEX IF NOT EXISTS incoming_edge ON citation_edges(cited);
        CREATE TABLE IF NOT EXISTS resource_cache(key TEXT PRIMARY KEY,payload TEXT NOT NULL,fetched_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS citation_verifications(citation TEXT PRIMARY KEY,cluster INTEGER NOT NULL,name TEXT NOT NULL,origin TEXT NOT NULL,verified_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS checkpoints(key TEXT PRIMARY KEY,payload TEXT NOT NULL,updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS docket_entries(id INTEGER PRIMARY KEY,docket INTEGER NOT NULL REFERENCES dockets(id),payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS recap_documents(id INTEGER PRIMARY KEY,docket_entry INTEGER NOT NULL REFERENCES docket_entries(id),docket INTEGER NOT NULL REFERENCES dockets(id),kind TEXT NOT NULL,text TEXT NOT NULL,content_hash TEXT NOT NULL,first_seen TEXT NOT NULL,last_fetched TEXT NOT NULL,payload TEXT NOT NULL);
        """)
        self._migrate_citation_edges()
        try:
            self.connection.executescript("""
            CREATE VIRTUAL TABLE IF NOT EXISTS opinion_fts USING fts5(text,content='opinions',content_rowid='id');
            CREATE TRIGGER IF NOT EXISTS opinion_insert AFTER INSERT ON opinions BEGIN INSERT INTO opinion_fts(rowid,text) VALUES(new.id,new.text); END;
            CREATE TRIGGER IF NOT EXISTS opinion_delete AFTER DELETE ON opinions BEGIN INSERT INTO opinion_fts(opinion_fts,rowid,text) VALUES('delete',old.id,old.text); END;
            CREATE TRIGGER IF NOT EXISTS opinion_update AFTER UPDATE OF text ON opinions BEGIN INSERT INTO opinion_fts(opinion_fts,rowid,text) VALUES('delete',old.id,old.text); INSERT INTO opinion_fts(rowid,text) VALUES(new.id,new.text); END;
            """)
            self.fts = True
        except sqlite3.OperationalError:
            self.fts = False

    def _migrate_citation_edges(self):
        if self.connection.execute("SELECT 1 FROM corpus_schema WHERE version=2").fetchone():
            return
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            if self.connection.execute("SELECT 1 FROM corpus_schema WHERE version=2").fetchone():
                return
            self.connection.execute("ALTER TABLE citation_edges ADD COLUMN from_graph INTEGER NOT NULL DEFAULT 0")
            # Legacy rows matching a depth-one opinion reference are ambiguous.
            # Preserve other rows as separately collected graph data.
            self.connection.execute("""
                UPDATE citation_edges AS edge SET from_graph=1
                WHERE depth != 1 OR NOT EXISTS (
                    SELECT 1 FROM opinions AS opinion, json_each(opinion.payload, '$.cited') AS reference
                    WHERE opinion.id=edge.citing AND reference.value=edge.cited
                )
            """)
            self.connection.execute("INSERT INTO corpus_schema VALUES(2)")

    def close(self):
        self.connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def ingest(self, bundle: CaseBundle):
        bundle.validate_relationships()
        now, changed, new = utcnow(), [], []
        with self.connection:
            court, docket, cluster = bundle.court, bundle.docket, bundle.cluster
            self.connection.execute("INSERT INTO courts VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET state=excluded.state,sovereign=excluded.sovereign,hierarchy=excluded.hierarchy,payload=excluded.payload",
                                    (court.id, court.state, court.sovereign, court.hierarchy, encode(court.model_dump())))
            self.connection.execute("INSERT INTO dockets VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET court=excluded.court,payload=excluded.payload",
                                    (docket.id, docket.court, encode(docket.model_dump())))
            self.connection.execute("INSERT INTO clusters VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET docket=excluded.docket,name=excluded.name,decision_date=excluded.decision_date,publication=excluded.publication,origin=excluded.origin,payload=excluded.payload",
                                    (cluster.id, cluster.docket, cluster.name, cluster.date, cluster.publication, bundle.origin, encode(cluster.model_dump())))
            self.connection.execute("DELETE FROM citations WHERE cluster=?", (cluster.id,))
            self.connection.executemany("INSERT INTO citations VALUES(?,?)", [(cluster.id, citation) for citation in set(cluster.citations)])
            if bundle.cluster.opinions:
                placeholders = ",".join("?" for _ in bundle.cluster.opinions)
                self.connection.execute("UPDATE opinions SET state='unavailable',last_checked=? WHERE cluster=? AND id NOT IN (" + placeholders + ")",
                                        (now, cluster.id, *bundle.cluster.opinions))
            for opinion in bundle.opinions:
                payload = encode(opinion.model_dump())
                old = self.connection.execute("SELECT content_hash,payload,state FROM opinions WHERE id=?", (opinion.id,)).fetchone()
                if old is None:
                    new.append(opinion.id)
                elif old["content_hash"] != opinion.content_hash or old["payload"] != payload:
                    changed.append(opinion.id)
                self.connection.execute("INSERT OR IGNORE INTO opinion_versions VALUES(?,?,?,?,?)",
                                        (opinion.id, opinion.content_hash, opinion.text, payload, now))
                self.connection.execute("INSERT INTO opinions VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET cluster=excluded.cluster,role=excluded.role,text=excluded.text,content_hash=excluded.content_hash,last_fetched=excluded.last_fetched,last_checked=excluded.last_checked,state=excluded.state,payload=excluded.payload",
                                        (opinion.id, cluster.id, opinion.role, opinion.text, opinion.content_hash, now, now, now, "changed_review_required" if opinion.id in changed or (old and old["state"] == "changed_review_required") else "available", payload))
                self.connection.execute("DELETE FROM citation_edges WHERE citing=? AND from_graph=0", (opinion.id,))
                self.connection.executemany("INSERT OR IGNORE INTO citation_edges(citing,cited,depth) VALUES(?,?,1)",
                                            [(opinion.id, cited) for cited in opinion.cited])
            from app.authority import digest
            for kind, entity in (("court", court), ("docket", docket), ("cluster", cluster), *(("opinion", op) for op in bundle.opinions)):
                value = encode(entity.model_dump())
                self.connection.execute("INSERT OR IGNORE INTO entity_versions VALUES(?,?,?,?,?)", (kind, str(entity.id), digest(value), value, now))
        return {"new": new, "changed": changed, "ingested": len(bundle.opinions)}

    def _treatment_signals(self, cited):
        # Read the current corpus so late-arriving opinions, edges and
        # corrections take effect without a global backfill.
        candidates = self.connection.execute("""
            SELECT later.id, later.payload, later.last_fetched, later_case.decision_date,
                   court.id AS court_id, target_case.id AS target_cluster
            FROM citation_edges edge
            JOIN opinions later ON later.id=edge.citing
            JOIN clusters later_case ON later_case.id=later.cluster
            JOIN dockets docket ON docket.id=later_case.docket
            JOIN courts court ON court.id=docket.court
            JOIN opinions target ON target.id=edge.cited
            JOIN clusters target_case ON target_case.id=target.cluster
            WHERE edge.cited=? AND later_case.decision_date>target_case.decision_date
                AND later.state!='unavailable' AND target.state!='unavailable'
            ORDER BY later_case.decision_date DESC, later.id
            LIMIT 21
        """, (cited,)).fetchall()
        if not candidates:
            return [], False
        citations = [r[0] for r in self.connection.execute(
            "SELECT citation FROM citations WHERE cluster=? ORDER BY citation", (candidates[0]["target_cluster"],)
        )]
        if not citations:
            return [], len(candidates) > 20
        citation_pattern = re.compile(r"(?<!\w)(?:" + "|".join(map(re.escape, citations)) + r")(?!\w)")
        treatment_pattern = re.compile(
            r"\b(overruled|abrogated|superseded|distinguished|limited|criticized|declined to follow)\b", re.I
        )
        signals = []
        for row in candidates[:20]:
            opinion = json.loads(row["payload"])
            for paragraph in opinion["paragraphs"]:
                text = paragraph["text"]
                citation_match = citation_pattern.search(text)
                treatment_match = treatment_pattern.search(text) if citation_match else None
                if not treatment_match:
                    continue
                start = min(citation_match.start(), treatment_match.start())
                end = max(citation_match.end(), treatment_match.end())
                if end - start > 1000:
                    continue
                signals.append({"citing": row["id"], "cited": cited, "signal": "potential_negative_treatment",
                                "passage": text[max(0, start - 150):end + 150], "role": opinion["role"],
                                "locator": paragraph["locator"],
                                "citation": citation_match.group(), "language": treatment_match.group(),
                                "citing_court": row["court_id"], "decision_date": row["decision_date"],
                                "source_fetched_at": row["last_fetched"], "review_status": "human_review_required"})
                break
        return signals, len(candidates) > 20

    def opinion(self, identifier):
        row = self.connection.execute("SELECT payload FROM opinions WHERE id=? AND state!='unavailable'", (identifier,)).fetchone()
        return Opinion.model_validate(json.loads(row[0])) if row else None

    def case(self, cluster_identifier):
        row = self.connection.execute("SELECT c.payload,c.origin,d.payload AS docket_payload,t.payload AS court_payload FROM clusters c JOIN dockets d ON c.docket=d.id JOIN courts t ON d.court=t.id WHERE c.id=?", (cluster_identifier,)).fetchone()
        if not row:
            return None
        opinions = [Opinion.model_validate(json.loads(o[0])) for o in self.connection.execute("SELECT payload FROM opinions WHERE cluster=? AND state!='unavailable' ORDER BY id", (cluster_identifier,))]
        return CaseBundle(court=Court.model_validate(json.loads(row["court_payload"])), docket=Docket.model_validate(json.loads(row["docket_payload"])),
                          cluster=Cluster.model_validate(json.loads(row["payload"])), opinions=opinions, origin=row["origin"])

    def search(self, query, *, state, sovereign="state", courts=(), date_from=None, date_to=None, limit=12):
        words = re.findall(r"[a-zA-Z0-9]+", query)[:24]
        if not words:
            return []
        clauses, args = ["t.state IS ?", "t.sovereign=?", "o.state!='unavailable'"], [state, sovereign]
        if courts:
            clauses.append("t.id IN (" + ",".join("?" for _ in courts) + ")")
            args.extend(courts)
        if date_from:
            clauses.append("c.decision_date>=?")
            args.append(date_from)
        if date_to:
            clauses.append("c.decision_date<=?")
            args.append(date_to)
        if self.fts:
            join, score = "JOIN opinion_fts f ON f.rowid=o.id", "bm25(opinion_fts)"
            clauses.append("opinion_fts MATCH ?")
            args.append(" OR ".join('"' + word + '"' for word in words))
        else:
            join, score = "", "0.0"
            clauses.append("(" + " OR ".join("o.text LIKE ? ESCAPE '\\'" for _ in words) + ")")
            args.extend("%" + word + "%" for word in words)
        args.append(max(1, min(int(limit), 100)))
        sql = f"SELECT o.id,c.id AS cluster,t.hierarchy,c.publication,c.decision_date,o.role,{score} AS score FROM opinions o JOIN clusters c ON o.cluster=c.id JOIN dockets d ON c.docket=d.id JOIN courts t ON d.court=t.id {join} WHERE " + " AND ".join(clauses) + " ORDER BY t.hierarchy,CASE c.publication WHEN 'Published' THEN 0 ELSE 1 END,CASE o.role WHEN 'lead' THEN 0 WHEN 'unanimous' THEN 0 ELSE 1 END,score,o.id LIMIT ?"
        return [dict(row) for row in self.connection.execute(sql, args)]

    def cached_resource(self, key, max_age_days=30):
        row = self.connection.execute("SELECT payload,fetched_at FROM resource_cache WHERE key=?", (key,)).fetchone()
        if row and datetime.fromisoformat(row["fetched_at"]) > datetime.now(timezone.utc) - timedelta(days=max_age_days):
            return json.loads(row["payload"])
        return None

    def cache_resource(self, key, payload):
        with self.connection:
            self.connection.execute("INSERT INTO resource_cache VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET payload=excluded.payload,fetched_at=excluded.fetched_at", (key, encode(payload), utcnow()))

    def save_verification(self, value):
        with self.connection:
            self.connection.execute("INSERT INTO citation_verifications VALUES(?,?,?,?,?) ON CONFLICT(citation) DO UPDATE SET cluster=excluded.cluster,name=excluded.name,origin=excluded.origin,verified_at=excluded.verified_at",
                                    (value["citation"], value["cluster"], value["name"], value["origin"], utcnow()))

    def verification(self, citation, max_age_days=30):
        row = self.connection.execute("SELECT * FROM citation_verifications WHERE citation=?", (citation,)).fetchone()
        if row and datetime.fromisoformat(row["verified_at"]) > datetime.now(timezone.utc) - timedelta(days=max_age_days):
            return dict(row)
        return None

    def bulk_citation_identity(self, citation):
        rows = self.connection.execute("SELECT c.id,c.name,c.origin FROM citations x JOIN clusters c ON x.cluster=c.id WHERE x.citation=?", (citation,)).fetchall()
        if len(rows) == 1 and rows[0]["origin"] == "courtlistener_bulk":
            return {"citation": citation, "cluster": rows[0]["id"], "name": rows[0]["name"], "origin": "courtlistener_bulk"}
        return None

    def add_edges(self, edges):
        with self.connection:
            self.connection.executemany("INSERT INTO citation_edges(citing,cited,depth,from_graph) VALUES(?,?,?,1) "
                "ON CONFLICT(citing,cited) DO UPDATE SET depth=excluded.depth,from_graph=1",
                [(e["citing"], e["cited"], e.get("depth", 1)) for e in edges])

    def checkpoint(self, key, value=None):
        if value is None:
            row = self.connection.execute("SELECT payload FROM checkpoints WHERE key=?", (key,)).fetchone()
            return json.loads(row[0]) if row else None
        with self.connection:
            self.connection.execute("INSERT INTO checkpoints VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET payload=excluded.payload,updated_at=excluded.updated_at", (key, encode(value), utcnow()))

    def mark_unavailable(self, opinion_identifier):
        with self.connection:
            self.connection.execute("UPDATE opinions SET state='unavailable',last_checked=? WHERE id=?", (utcnow(), opinion_identifier))

    def graph(self, opinion_identifier):
        outgoing = [r[0] for r in self.connection.execute("SELECT cited FROM citation_edges WHERE citing=?", (opinion_identifier,))]
        incoming = [r[0] for r in self.connection.execute("SELECT citing FROM citation_edges WHERE cited=?", (opinion_identifier,))]
        signals, treatment_scan_truncated = self._treatment_signals(opinion_identifier)
        return {"cited": outgoing, "citing": incoming, "incoming_count": len(incoming), "signals": signals,
                "treatment_scan_truncated": treatment_scan_truncated,
                "treatment": "human_review_required" if signals else "citation_graph_available" if outgoing or incoming else "unknown",
                "currentness": "unresolved"}

    def stats(self):
        counts = {table: self.connection.execute("SELECT count(*) FROM " + table).fetchone()[0]
                  for table in ("courts", "dockets", "clusters", "opinions", "citations", "citation_edges", "opinion_versions", "recap_documents")}
        return {**counts, "fts5": self.fts, "bytes": self.connection.execute("PRAGMA page_count").fetchone()[0] * self.connection.execute("PRAGMA page_size").fetchone()[0],
                "last_sync": self.connection.execute("SELECT max(last_fetched) FROM opinions").fetchone()[0],
                "jurisdictions": [dict(r) for r in self.connection.execute("SELECT t.state,t.sovereign,count(*) AS opinions FROM opinions o JOIN clusters c ON o.cluster=c.id JOIN dockets d ON c.docket=d.id JOIN courts t ON d.court=t.id GROUP BY t.state,t.sovereign")],
                "origins": [dict(r) for r in self.connection.execute("SELECT origin,count(*) AS clusters FROM clusters GROUP BY origin")]}
