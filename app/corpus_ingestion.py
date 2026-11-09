"""Resumable legal-data ingestion; external snapshots never approve canonical law."""

import bz2
import csv
import hashlib
import json
import time
from typing import Protocol

from app.courtlistener_client import CourtListenerError
from app.courtlistener_models import Court, Docket, Cluster, Opinion, CaseBundle
from app.corpus_store import encode


class CorpusIngestionSource(Protocol):
    """REST, bulk and future logical-replication sources emit this boundary."""
    def bundles(self): ...


class CourtListenerCorpusBuilder:
    def __init__(self, client, store):
        self.client, self.store = client, store

    def ingest(self, query, courts, *, jurisdiction, mode="keyword", date_from=None, date_to=None, max_results=20, resume=False):
        if not 1 <= max_results <= 5000 or (date_from and date_to and date_from > date_to):
            raise ValueError("ingestion_scope_invalid")
        specification = {"query": query, "courts": sorted(courts), "jurisdiction": jurisdiction,
                         "mode": mode, "date_from": date_from, "date_to": date_to}
        key = hashlib.sha256(encode(specification).encode()).hexdigest()
        state = self.store.checkpoint(key) if resume else None
        state = state or {"completed": [], "cursor": None, "done": False}
        report = {"status": "completed", "downloaded_clusters": 0, "downloaded_opinions": 0, "changed": 0,
                  "checkpoint": key, "errors": [], "retry_after_seconds": None, "origin": self.client.origin}
        if state["done"]:
            report.update(status="already_completed", metrics=self.client.budget.metrics())
            return report
        try:
            usage = self.client.usage()
            if not usage["available"]:
                raise CourtListenerError("throttled")
            remaining = min(r["remaining"] for r in usage["limits"] if r["scope"] == "user")
            self.client.budget.max_requests = min(self.client.budget.max_requests, self.client.budget.requests + remaining)
            for matches, next_cursor in self.client.search_pages(query, courts, mode=mode, date_from=date_from, date_to=date_to, cursor=state["cursor"]):
                page_limit_reached = False
                for hit in matches:
                    if hit["cluster"] in state["completed"]:
                        continue
                    if report["downloaded_clusters"] >= max_results:
                        report["status"] = "checkpointed"
                        page_limit_reached = True
                        break
                    bundle = self.client.hydrate(hit["cluster"])
                    if bundle.court.state != jurisdiction or bundle.court.id not in courts:
                        raise CourtListenerError("jurisdiction_mismatch")
                    result = self.store.ingest(bundle)
                    report["downloaded_clusters"] += 1
                    report["downloaded_opinions"] += len(bundle.opinions)
                    report["changed"] += len(result["changed"])
                    for citation in bundle.cluster.citations[:1]:
                        resolution = self.client.lookup(citation)
                        if resolution["cluster"] != bundle.cluster.id:
                            raise CourtListenerError("citation_mismatch")
                        self.store.save_verification(resolution)
                    state["completed"].append(bundle.cluster.id)
                    self.store.checkpoint(key, state)
                if page_limit_reached:
                    break
                state["cursor"], state["done"] = next_cursor, next_cursor is None
                self.store.checkpoint(key, state)
                if not state["done"]:
                    report["status"] = "checkpointed"
                if report["downloaded_clusters"] >= max_results:
                    break
            if state["done"]:
                report["status"] = "completed"
        except CourtListenerError as error:
            report.update(status="checkpointed", errors=[error.code], retry_after_seconds=error.retry_after)
        self.store.checkpoint(key, state)
        report["metrics"], report["timings"], report["corpus"] = self.client.budget.metrics(), self.client.timings, self.store.stats()
        return report


class CourtListenerBulkImporter:
    """Streaming table-wise FLP CSV/CSV.bz2 import, with bounded staging.

    Official table exports are not a perfectly consistent snapshot. Unresolved
    joins are reported and retained in staging, never invented or approved.
    """
    TABLES = {"courts", "dockets", "clusters", "opinions", "citations", "opinions_cited"}

    def __init__(self, store):
        self.store = store
        store.connection.execute("CREATE TABLE IF NOT EXISTS bulk_staging(kind TEXT NOT NULL,id TEXT NOT NULL,parent TEXT,payload TEXT NOT NULL,PRIMARY KEY(kind,id))")
        store.connection.execute("CREATE INDEX IF NOT EXISTS bulk_parent ON bulk_staging(kind,parent)")

    def load(self, table, path, *, max_rows=10000, max_bytes=100000000, max_seconds=120):
        if (table not in self.TABLES or not 1 <= max_rows <= 1000000
                or not 1 <= max_bytes <= 500000000 or not 1 <= max_seconds <= 3600):
            raise ValueError("bulk_table_or_budget_invalid")
        csv.field_size_limit(3000000)
        started, consumed, count = time.monotonic(), 0, 0
        opener = bz2.open if str(path).endswith(".bz2") else open
        with opener(path, "rt", encoding="utf-8", newline="") as stream:
            def bounded_lines():
                total = 0
                while True:
                    if time.monotonic() - started > max_seconds:
                        raise ValueError("bulk_runtime_limit")
                    line = stream.readline(min(3000001, max_bytes - total + 1))
                    if not line:
                        return
                    total += len(line.encode("utf-8"))
                    if total > max_bytes or len(line) > 3000000:
                        raise ValueError("bulk_input_limit")
                    yield line
            reader = csv.DictReader(bounded_lines(), escapechar="\\")
            for raw in reader:
                consumed += sum(len(str(value).encode()) for value in raw.values())
                if consumed > max_bytes or time.monotonic() - started > max_seconds or count >= max_rows:
                    break
                identifier = raw.get("id")
                raw = {k: None if value in {"\\N", "N"} else value for k, value in raw.items()}
                if not identifier or len(identifier) > 40:
                    raise ValueError("bulk_identifier_invalid")
                with self.store.connection:
                    parent = raw.get({"dockets": "court_id", "clusters": "docket_id", "opinions": "cluster_id", "citations": "cluster_id", "opinions_cited": "citing_opinion_id"}.get(table, ""))
                    self.store.connection.execute("INSERT INTO bulk_staging VALUES(?,?,?,?) ON CONFLICT(kind,id) DO UPDATE SET parent=excluded.parent,payload=excluded.payload", (table, identifier, parent, encode(raw)))
                count += 1
        return {"table": table, "staged": count, "bytes": consumed, "bounded": True}

    def _row(self, table, identifier):
        row = self.store.connection.execute("SELECT payload FROM bulk_staging WHERE kind=? AND id=?", (table, str(identifier))).fetchone()
        return json.loads(row[0]) if row else None

    def materialize(self, max_clusters=1000):
        if not 1 <= max_clusters <= 100000:
            raise ValueError("bulk_cluster_budget_invalid")
        completed, unresolved = 0, []
        for row in self.store.connection.execute("SELECT id,payload FROM bulk_staging WHERE kind='clusters' ORDER BY id LIMIT ?", (max_clusters,)).fetchall():
            raw_cluster = json.loads(row["payload"])
            try:
                docket_identifier = raw_cluster.get("docket_id") or raw_cluster.get("docket")
                raw_docket = self._row("dockets", docket_identifier)
                if not raw_docket:
                    raise ValueError()
                cid = raw_docket.get("court_id") or raw_docket.get("court")
                raw_court = self._row("courts", cid)
                if not raw_court:
                    raise ValueError()
                raw_docket.update(id=int(raw_docket["id"]), court=cid)
                opinions = []
                for op in self.store.connection.execute("SELECT payload FROM bulk_staging WHERE kind='opinions' AND parent=?", (row["id"],)):
                    value = json.loads(op[0])
                    if str(value.get("cluster_id") or value.get("cluster")) == row["id"]:
                        value.update(id=int(value["id"]), cluster=int(row["id"]), cluster_id=int(row["id"]), opinions_cited=[])
                        for edge_row in self.store.connection.execute("SELECT payload FROM bulk_staging WHERE kind='opinions_cited' AND parent=?", (str(value["id"]),)):
                            edge = json.loads(edge_row[0])
                            if str(edge.get("citing_opinion_id")) == str(value["id"]):
                                value["opinions_cited"].append(int(edge["cited_opinion_id"]))
                        opinions.append(Opinion.normalize(value))
                if not opinions:
                    raise ValueError()
                citations = [json.loads(r[0]) for r in self.store.connection.execute("SELECT payload FROM bulk_staging WHERE kind='citations' AND parent=?", (row["id"],))]
                raw_cluster.update(id=int(row["id"]), docket=int(docket_identifier), sub_opinions=[o.id for o in opinions], citations=citations)
                bundle = CaseBundle(court=Court.normalize(raw_court), docket=Docket.normalize(raw_docket), cluster=Cluster.normalize(raw_cluster),
                                    opinions=opinions, origin="courtlistener_bulk")
                self.store.ingest(bundle)
                edges = []
                for opinion in opinions:
                    for edge_row in self.store.connection.execute("SELECT payload FROM bulk_staging WHERE kind='opinions_cited' AND parent=?", (str(opinion.id),)):
                        edge = json.loads(edge_row[0])
                        edges.append({"citing": opinion.id, "cited": int(edge["cited_opinion_id"]), "depth": max(1, min(int(edge.get("depth") or 1), 10000))})
                self.store.add_edges(edges)
                completed += 1
            except (ValueError, KeyError, TypeError):
                unresolved.append(row["id"])
        return {"materialized_clusters": completed, "unresolved_cluster_ids": unresolved,
                "approval": "external_unreviewed", "corpus": self.store.stats()}
