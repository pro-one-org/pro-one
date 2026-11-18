"""Observe one pinned public publisher URL, recording drift without mutating authority."""
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
import sqlite3

from app.jurisdictions import registry
from app.national_corpus import CorpusError, fingerprint
from app.national_corpus_transport import PublicProvider
from app.national_coverage import manifest
from app.national_govinfo_code import GovInfoCode, federal_granules
from app.national_publications import LegislativeExcerpts


class PinnedPublisher(PublicProvider):
    def __init__(self, provider, selector):
        self.url = provider.source_url(selector)
        self.selector = selector
        self.source = replace(provider.source, max_bytes=5_000_000)

    def source_url(self, selector):
        if selector != self.selector or not self.url.startswith("https://"):
            raise CorpusError("unsupported_authority")
        return self.url


def target(scope, selector):
    if scope == "US" and selector in federal_granules():
        return GovInfoCode(), federal_granules()[selector]["sha256"]
    if scope in registry():
        row = manifest(scope).get("passages", {}).get(selector)
        if row:
            return LegislativeExcerpts(scope, row["authority_type"]), row["publisher_sha256"]
    raise CorpusError("unsupported_authority")


def check(scope, selector, history, *, fetch=None):
    provider, expected = target(scope, selector)
    endpoint = PinnedPublisher(provider, selector)
    observed = None
    code = None
    try:
        if isinstance(provider, LegislativeExcerpts) and provider.publication(selector)[0].get("publisher_archive_etag"):
            raise CorpusError("archive_member_replay_required")
        raw = (fetch or endpoint.fetch)(selector).raw
        observed = fingerprint(raw)
        if observed != expected:
            status = "changed_content"
        elif isinstance(provider, GovInfoCode):
            list(provider.normalize(selector, raw))
            status = "healthy"
        else:
            status = "publisher_bytes_unchanged"
    except CorpusError as exc:
        code = str(exc)
        if code == "archive_member_replay_required":
            status = "archive_member_replay_required"
        elif code in {"source_http_301", "source_http_302", "source_http_303", "source_http_307", "source_http_308"}:
            status = "redirected"
        elif code in {"source_http_401", "source_http_403"}:
            status = "authentication_required" if code.endswith("401") else "access_denied"
        else:
            status = "parser_failed" if observed else "unreachable"
    record = dict(jurisdiction=scope, selector=selector, url=endpoint.url, expected_hash=expected,
                  observed_hash=observed, status=status, error=code, checked_at=datetime.now(timezone.utc).isoformat())
    connection = sqlite3.connect(Path(history))
    try:
        with connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS publisher_health(
                id INTEGER PRIMARY KEY, jurisdiction TEXT, selector TEXT, url TEXT, expected_hash TEXT,
                observed_hash TEXT, status TEXT, error TEXT, checked_at TEXT)""")
            connection.execute("""INSERT INTO publisher_health
                (jurisdiction,selector,url,expected_hash,observed_hash,status,error,checked_at)
                VALUES (:jurisdiction,:selector,:url,:expected_hash,:observed_hash,:status,:error,:checked_at)""", record)
    finally:
        connection.close()
    return record
