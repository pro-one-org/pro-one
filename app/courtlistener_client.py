"""Fixed-host authenticated v4 client; no PACER purchase or arbitrary URLs.

Official contracts checked 2026-11-03; see docs/courtlistener.md. Private error
bodies, account objects and credentials never cross the normalized boundary.
"""

from dataclasses import dataclass
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
import http.client
import json
import re
import time
from urllib.parse import urlencode, urlsplit, parse_qs

from app.courtlistener_models import API_BASE, Court, Docket, Cluster, Opinion, CaseBundle, court_id, external_id


ENDPOINTS = frozenset({"search", "courts", "dockets", "clusters", "opinions", "citation-lookup", "api-usage", "opinions-cited", "docket-entries", "recap-documents"})


class CourtListenerError(ValueError):
    def __init__(self, code, retry_after=None):
        super().__init__(code)
        self.code, self.retry_after = code, retry_after


@dataclass
class RequestBudget:
    max_requests: int = 30
    max_pages: int = 2
    max_documents: int = 12
    max_bytes: int = 12000000
    max_seconds: int = 30
    requests: int = 0
    pages: int = 0
    documents: int = 0
    bytes: int = 0
    started: float = 0

    def __post_init__(self):
        self.started = time.monotonic()
        if not (1 <= self.max_requests <= 5000 and 1 <= self.max_pages <= 1000 and 1 <= self.max_documents <= 5000
                and 1 <= self.max_seconds <= 3600 and 1 <= self.max_bytes <= 500000000):
            raise ValueError("invalid_operation_budget")

    def remaining_time(self):
        remaining = self.max_seconds - (time.monotonic() - self.started)
        if remaining <= 0:
            raise CourtListenerError("runtime_budget_exhausted")
        return remaining

    def permit(self):
        self.remaining_time()
        if self.requests >= self.max_requests or self.bytes >= self.max_bytes:
            raise CourtListenerError("request_budget_exhausted")
        self.requests += 1

    def metrics(self):
        return {"requests": self.requests, "pages": self.pages, "documents": self.documents,
                "bytes": self.bytes, "elapsed_ms": round(1000 * (time.monotonic() - self.started), 2)}


class CourtListenerTransport:
    """TLS fixed host, identity encoding, wall deadline, bounded streaming reads."""
    def request(self, method, path, headers, body, timeout, max_bytes):
        connection = http.client.HTTPSConnection("www.courtlistener.com", timeout=min(timeout, 8))
        deadline = time.monotonic() + min(timeout, 8)
        try:
            connection.connect()
            sock = connection.sock
            sock.settimeout(max(.01, deadline - time.monotonic()))
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            if response.getheader("Content-Encoding", "identity") != "identity":
                raise CourtListenerError("response_encoding_invalid")
            chunks, size = [], 0
            while True:
                if response.isclosed():
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise CourtListenerError("timeout")
                sock.settimeout(remaining)
                chunk = response.read1(min(65536, max_bytes + 1 - size))
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    raise CourtListenerError("response_size_exceeded")
                chunks.append(chunk)
            return response.status, {"retry-after": response.getheader("Retry-After"),
                                     "content-type": response.getheader("Content-Type", "")}, b"".join(chunks)
        except CourtListenerError:
            raise
        except Exception:
            raise CourtListenerError("temporarily_unavailable") from None
        finally:
            connection.close()


def continuation_cursor(url, endpoint, original):
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname != "www.courtlistener.com" or parsed.netloc != "www.courtlistener.com"
            or parsed.path != "/api/rest/v4/" + endpoint + "/" or parsed.fragment or len(url) > 5000):
        raise CourtListenerError("pagination_url_rejected")
    values = parse_qs(parsed.query, keep_blank_values=True)
    cursor = values.pop("cursor", [])
    expected = {k: [str(v)] for k, v in original.items() if k != "cursor"}
    if (values != expected or len(cursor) != 1 or not re.fullmatch(r"[A-Za-z0-9_+/=-]{1,2048}", cursor[0])):
        raise CourtListenerError("pagination_scope_rejected")
    return cursor[0]


def retry_delay(value):
    if not value:
        return None
    try:
        if re.fullmatch(r"[0-9]{1,6}", str(value)):
            return min(int(value), 86400)
        timestamp = parsedate_to_datetime(value) if "," in value else datetime.fromisoformat(value)
        return min(86400, max(0, int((timestamp - datetime.now(timezone.utc)).total_seconds())))
    except (ValueError, TypeError, OverflowError):
        return None


class CourtListenerClient:
    def __init__(self, token=None, *, transport=None, budget=None, store=None, origin="courtlistener_v4"):
        self._token = token
        self.transport = transport or CourtListenerTransport()
        self.budget = budget or RequestBudget()
        self.store, self.origin = store, origin
        self.state = "available" if token else "unconfigured"
        self._cache = {}
        self.timings = {"search_ms": 0., "hydration_ms": 0., "citation_ms": 0.}

    def __repr__(self):
        return f"CourtListenerClient(state={self.state!r})"

    def status(self):
        return {"configured": bool(self._token), "state": self.state}

    def _request(self, endpoint, *, identifier=None, params=None, form=None):
        if not self._token:
            raise CourtListenerError("unconfigured")
        if endpoint not in ENDPOINTS or (form is not None and endpoint != "citation-lookup"):
            raise CourtListenerError("endpoint_not_allowed")
        if identifier is not None:
            identifier = court_id(identifier) if endpoint == "courts" else external_id(identifier, endpoint)
        params = params or {}
        if len(urlencode(params)) > 5000:
            raise CourtListenerError("query_size_exceeded")
        path = "/api/rest/v4/" + endpoint + "/" + (str(identifier) + "/" if identifier is not None else "")
        if params:
            path += "?" + urlencode(params)
        body = urlencode(form).encode() if form is not None else None
        if body and len(body) > 4000:
            raise CourtListenerError("lookup_size_exceeded")
        self.budget.permit()
        try:
            status, headers, content = self.transport.request("POST" if body is not None else "GET", path,
                {"Authorization": "Token " + self._token, "Accept": "application/json", "Accept-Encoding": "identity",
                 "Content-Type": "application/x-www-form-urlencoded", "User-Agent": "Pro-One-Research/0.3"},
                body, min(8, self.budget.remaining_time()), min(3000000, self.budget.max_bytes - self.budget.bytes))
            self.budget.bytes += len(content)
            self.budget.remaining_time()
            if self.budget.bytes > self.budget.max_bytes or len(content) > 3000000:
                raise CourtListenerError("response_size_exceeded")
            if status == 429:
                self.state = "throttled"
                delay = retry_delay(headers.get("retry-after"))
                if delay is None:
                    try:
                        raw = json.loads(content)
                        delay = retry_delay(raw.get("wait_until") or raw.get("wait_util"))
                    except Exception:
                        pass
                raise CourtListenerError("throttled", delay)
            if status in {401, 403}:
                self.state = "unavailable"
                raise CourtListenerError("authentication_or_access_denied")
            if status == 404:
                raise CourtListenerError("not_found")
            if status != 200:
                raise CourtListenerError("temporarily_unavailable")
            if not headers.get("content-type", "").lower().startswith("application/json"):
                raise CourtListenerError("invalid_response")
            value = json.loads(content)
            if not isinstance(value, (dict, list)):
                raise ValueError()
            self.state = "available"
            return value
        except CourtListenerError:
            raise
        except Exception:
            self.state = "temporarily_unavailable"
            raise CourtListenerError("invalid_response") from None

    def usage(self):
        raw = self._request("api-usage")
        try:
            rows = [{k: row[k] for k in ("scope", "remaining", "limit", "reset_at", "blocked")}
                    for row in raw["current_usage"] if row["scope"] in {"user", "citations", "api_usage"}]
            if not rows or not any(r["scope"] == "user" for r in rows) or any(type(r["remaining"]) is not int or type(r["limit"]) is not int or type(r["blocked"]) is not bool
                               or r["remaining"] < 0 or r["limit"] < 0 for r in rows):
                raise ValueError()
            return {"limits": rows, "available": not any(r["blocked"] or r["remaining"] == 0 for r in rows if r["scope"] == "user")}
        except Exception:
            raise CourtListenerError("usage_response_invalid") from None

    def iter_pages(self, endpoint, params, *, cursor=None):
        seen = set()
        for _ in range(self.budget.max_pages):
            if self.budget.pages >= self.budget.max_pages:
                raise CourtListenerError("page_budget_exhausted")
            if cursor:
                if not re.fullmatch(r"[A-Za-z0-9_+/=-]{1,2048}", cursor) or cursor in seen:
                    raise CourtListenerError("pagination_cursor_rejected")
                seen.add(cursor)
            raw = self._request(endpoint, params={**params, **({"cursor": cursor} if cursor else {})})
            self.budget.pages += 1
            if not isinstance(raw, dict) or not isinstance(raw.get("results"), list):
                raise CourtListenerError("pagination_response_invalid")
            next_cursor = continuation_cursor(raw["next"], endpoint, params) if raw.get("next") else None
            yield raw["results"], next_cursor
            if not next_cursor:
                break
            cursor = next_cursor

    def search_pages(self, query, courts, *, mode="keyword", date_from=None, date_to=None, cursor=None):
        if not query or len(query) > 300 or re.search(r"https?://|\b\d{3}-\d{2}-\d{4}\b", query):
            raise CourtListenerError("query_rejected")
        if mode not in {"keyword", "semantic"} or not courts or len(courts) > 12:
            raise CourtListenerError("search_scope_invalid")
        allowed = tuple(court_id(cid) for cid in courts)
        params = {"q": query, "type": "o", "court": " ".join(allowed), "order_by": "score desc"}
        if mode == "semantic":
            params["semantic"] = "true"
        for key, value in (("filed_after", date_from), ("filed_before", date_to)):
            if value:
                date.fromisoformat(value)
                params[key] = value
        started = time.perf_counter()
        try:
            for results, next_cursor in self.iter_pages("search", params, cursor=cursor):
                matches = []
                for raw in results[:100]:
                    if raw.get("court_id") not in allowed:
                        continue
                    # Discovery contains no snippet or authoritative text.
                    matches.append({"cluster": external_id(raw["cluster_id"], "clusters"), "court": raw["court_id"],
                                    "name": str(raw.get("caseName") or "")[:1000]})
                yield matches, next_cursor
        finally:
            self.timings["search_ms"] += 1000 * (time.perf_counter() - started)

    def resource(self, endpoint, identifier, *, refresh=False):
        key = endpoint + ":" + str(identifier)
        if not refresh:
            cached = self._cache.get(key)
            if cached is None and self.store:
                cached = self.store.cached_resource(key)
            if cached is not None:
                return cached
        try:
            value = self._request(endpoint, identifier=identifier)
        except CourtListenerError as error:
            if error.code == "not_found" and self.store and endpoint == "opinions":
                self.store.mark_unavailable(identifier)
            raise
        self._cache[key] = value
        if self.store:
            self.store.cache_resource(key, value)
        return value

    def hydrate(self, cluster_identifier, *, refresh=False):
        started = time.perf_counter()
        try:
            cluster = Cluster.normalize(self.resource("clusters", cluster_identifier, refresh=refresh))
            if cluster.id != external_id(cluster_identifier, "clusters"):
                raise CourtListenerError("case_identity_mismatch")
            docket = Docket.normalize(self.resource("dockets", cluster.docket, refresh=refresh))
            court = Court.normalize(self.resource("courts", docket.court, refresh=refresh))
            opinions = []
            for oid in cluster.opinions:
                if self.budget.documents >= self.budget.max_documents:
                    raise CourtListenerError("document_budget_exhausted")
                opinion = Opinion.normalize(self.resource("opinions", oid, refresh=refresh))
                if opinion.id != oid:
                    raise CourtListenerError("opinion_identity_mismatch")
                self.budget.documents += 1
                opinions.append(opinion)
            bundle = CaseBundle(court=court, docket=docket, cluster=cluster, opinions=opinions, origin=self.origin)
            bundle.validate_relationships()
            return bundle
        except CourtListenerError:
            raise
        except Exception:
            raise CourtListenerError("case_metadata_invalid") from None
        finally:
            self.timings["hydration_ms"] += 1000 * (time.perf_counter() - started)

    def lookup(self, citation):
        if not re.fullmatch(r"[0-9]{1,5} [A-Za-z.0-9 ]{1,35} [0-9]{1,6}", citation) or len(citation) > 100:
            raise CourtListenerError("citation_format_invalid")
        started = time.perf_counter()
        try:
            raw = self._request("citation-lookup", form={"text": citation})
            if not isinstance(raw, list) or len(raw) != 1:
                raise CourtListenerError("citation_unresolved")
            row = raw[0]
            if row.get("status") == 429:
                self.state = "throttled"
                raise CourtListenerError("throttled", retry_delay(row.get("wait_until") or row.get("wait_util")))
            if row.get("status") != 200 or len(row.get("clusters", [])) != 1:
                raise CourtListenerError("citation_unresolved")
            cluster = Cluster.normalize(row["clusters"][0])
            if citation not in cluster.citations or citation not in row.get("normalized_citations", [row.get("citation")]):
                raise CourtListenerError("citation_mismatch")
            return {"citation": citation, "cluster": cluster.id, "name": cluster.name, "origin": self.origin}
        finally:
            self.timings["citation_ms"] += 1000 * (time.perf_counter() - started)

    def citation_edges(self, opinion_identifier, *, incoming=False):
        field = "cited_opinion" if incoming else "citing_opinion"
        for rows, _ in self.iter_pages("opinions-cited", {field: str(external_id(opinion_identifier, "opinions")), "order_by": "id"}):
            for row in rows[:100]:
                yield {"citing": external_id(row["citing_opinion"], "opinions"),
                       "cited": external_id(row["cited_opinion"], "opinions"), "depth": max(1, min(int(row.get("depth", 1)), 10000))}
